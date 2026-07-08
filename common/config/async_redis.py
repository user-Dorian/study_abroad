"""阶段3异步改造：异步Redis连接池管理

使用 redis.asyncio（redis==5.3.1 自带模块）替代同步 redis.Redis，
供 FastAPI 异步路由使用，避免阻塞事件循环。

设计要点：
- 单例模式，全局共享一个异步Redis客户端
- asyncio.Lock 延迟初始化，避免模块加载时创建事件循环（模块可能在无事件循环的环境下被导入）
- 连接失败时抛出异常，由调用方决定降级策略
"""
import redis.asyncio as aioredis
from typing import Optional
from common.config.base_redis import RedisConfig
from common.utils.logger import logger


class AsyncRedisPool:
    """异步Redis连接池单例，供FastAPI异步路由使用"""

    _client: Optional[aioredis.Redis] = None
    _lock = None  # 延迟初始化，避免在模块加载时创建事件循环

    @classmethod
    def _get_lock(cls):
        """延迟获取asyncio.Lock，避免模块加载时创建事件循环"""
        import asyncio
        if cls._lock is None:
            cls._lock = asyncio.Lock()
        return cls._lock

    @classmethod
    async def get_client(cls) -> aioredis.Redis:
        """
        获取异步Redis客户端（单例，延迟初始化）

        Returns:
            redis.asyncio.Redis 实例

        Raises:
            Exception: Redis连接初始化失败时抛出
        """
        if cls._client is None:
            async with cls._get_lock():
                if cls._client is None:
                    try:
                        cls._client = aioredis.Redis(**RedisConfig.get_async_connection_params())
                        await cls._client.ping()
                        logger.info("异步Redis连接池初始化成功")
                    except Exception as e:
                        logger.error(f"异步Redis初始化失败: {e}")
                        cls._client = None
                        raise
        return cls._client

    @classmethod
    async def close(cls):
        """关闭异步Redis连接池（在应用 shutdown 时调用）"""
        if cls._client is not None:
            try:
                await cls._client.aclose()
                logger.info("异步Redis连接池已关闭")
            except Exception as e:
                logger.error(f"关闭异步Redis连接池异常: {e}")
            finally:
                cls._client = None
