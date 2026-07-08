"""阶段2数据库异步化：异步数据库连接池管理（asyncpg）

使用 asyncpg 替代 psycopg2 的同步连接池，供 FastAPI 异步路由使用，
从根本上消除数据库 I/O 对事件循环的阻塞。

设计要点（与 common/config/async_redis.py 保持一致）：
- 单例模式，全局共享一个 asyncpg.Pool
- asyncio.Lock 延迟初始化，避免模块加载时创建事件循环（模块可能在无事件循环的环境下被导入）
- 连接失败时抛出异常，由调用方决定降级策略
- 提供 execute_query / execute_one / execute_command 三个便捷方法，
  封装 fetch / fetchrow / execute，返回 dict / Optional[dict] / 状态字符串
"""
import asyncio
from typing import Optional

import asyncpg

from common.config.base_database import DatabaseConfig
from common.utils.logger import logger


class AsyncDatabasePool:
    """异步数据库连接池单例，供 FastAPI 异步路由使用"""

    _pool: Optional[asyncpg.Pool] = None
    _lock = None  # 延迟初始化，避免模块加载时创建事件循环

    @classmethod
    def _get_lock(cls):
        """延迟获取 asyncio.Lock，避免模块加载时创建事件循环"""
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        """获取异步数据库连接池（单例，延迟初始化）

        Returns:
            asyncpg.Pool 实例

        Raises:
            Exception: 连接池创建失败时抛出
        """
        if cls._pool is None:
            async with cls._get_lock():
                if cls._pool is None:
                    try:
                        cls._pool = await asyncpg.create_pool(
                            dsn=DatabaseConfig.get_async_dsn(),
                            min_size=DatabaseConfig.ASYNC_POOL_MIN_SIZE,
                            max_size=DatabaseConfig.ASYNC_POOL_MAX_SIZE,
                        )
                        logger.info(
                            f"异步数据库连接池创建成功: min={DatabaseConfig.ASYNC_POOL_MIN_SIZE}, "
                            f"max={DatabaseConfig.ASYNC_POOL_MAX_SIZE}"
                        )
                    except Exception as e:
                        logger.error(f"异步数据库连接池创建失败: {e}")
                        raise
        return cls._pool

    @classmethod
    async def close(cls):
        """关闭异步数据库连接池（在应用 shutdown 时调用）"""
        if cls._pool is not None:
            try:
                await cls._pool.close()
                logger.info("异步数据库连接池已关闭")
            except Exception as e:
                logger.error(f"关闭异步数据库连接池异常: {e}")
            finally:
                cls._pool = None

    @classmethod
    async def execute_query(cls, sql: str, *args) -> list:
        """执行查询，返回 dict 列表

        Args:
            sql: SQL 语句，使用 $1, $2, ... 占位符（asyncpg 风格）
            *args: 占位符参数，按顺序对应 $1, $2, ...

        Returns:
            list[dict]: 查询结果，每行转为 dict；无结果时返回空列表
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(row) for row in rows]

    @classmethod
    async def execute_one(cls, sql: str, *args) -> Optional[dict]:
        """查询单条，返回 dict 或 None

        Args:
            sql: SQL 语句，使用 $1, $2, ... 占位符
            *args: 占位符参数

        Returns:
            dict | None: 查询结果首行转为 dict；无结果时返回 None
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else None

    @classmethod
    async def execute_command(cls, sql: str, *args) -> str:
        """执行 INSERT/UPDATE/DELETE，返回状态字符串

        Args:
            sql: SQL 语句，使用 $1, $2, ... 占位符
            *args: 占位符参数

        Returns:
            str: asyncpg 返回的状态字符串，如 "INSERT 0 1" / "UPDATE 1" / "DELETE 0"
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            return await conn.execute(sql, *args)
