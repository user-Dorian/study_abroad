"""信息收集仓储层 - 学生信息数据库操作（asyncpg实现）"""
from typing import Dict, Any, Optional, List
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.functions.rag.rag_config import RAGConfig

# 延迟导入asyncpg
try:
    import asyncpg
except ImportError:
    asyncpg = None
    logger.warning("asyncpg未安装，数据库功能将不可用")


# 全局异步仓储实例
_async_repo: Optional[Any] = None


class StudentProfileRepository:
    """学生信息仓储层 - 异步操作（asyncpg实现）

    特性：
    - 异步数据库操作
    - 连接池管理
    - Upsert操作
    - 完善的错误处理
    """

    _pool: Optional[asyncpg.Pool] = None

    async def _ensure_pool(self):
        """确保连接池已初始化"""
        if self._pool is not None:
            return

        if asyncpg is None:
            logger.warning("asyncpg未安装，无法初始化数据库连接池")
            return

        try:
            self._pool = await asyncpg.create_pool(
                host=RAGConfig.DB_HOST,
                port=RAGConfig.DB_PORT,
                user=RAGConfig.DB_USER,
                password=RAGConfig.DB_PASSWORD,
                database=RAGConfig.DB_NAME,
                min_size=1,
                max_size=RAGConfig.DB_POOL_SIZE,
            )
            logger.info("学生信息仓储层连接池初始化成功 (asyncpg)")
        except Exception as e:
            logger.error(f"连接池初始化失败: {e}", exc_info=True)
            raise

    async def get_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取学生profile

        Args:
            user_id: 用户ID

        Returns:
            Dict: 学生profile
        """
        if asyncpg is None:
            logger.warning("asyncpg未安装，无法获取profile")
            return None

        try:
            await self._ensure_pool()
            if self._pool is None:
                return None

            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM student_profiles WHERE user_id = $1",
                    user_id
                )

                if not row:
                    logger.info(f"学生资料不存在: user_id={user_id}")
                    return None

                return dict(row)

        except Exception as e:
            logger.error(f"获取学生profile失败: {e}", exc_info=True)
            return None

    async def upsert_fields(
        self,
        user_id: str,
        fields: Dict[str, Any]
    ) -> bool:
        """更新或插入字段（UPSERT）

        Args:
            user_id: 用户ID
            fields: 字段字典

        Returns:
            bool: 是否成功
        """
        if asyncpg is None:
            logger.warning("asyncpg未安装，无法更新字段")
            return False

        try:
            await self._ensure_pool()
            if self._pool is None:
                return False

            async with self._pool.acquire() as conn:
                # 检查是否存在
                exists = await conn.fetchval(
                    "SELECT 1 FROM student_profiles WHERE user_id = $1",
                    user_id
                )

                fields = dict(fields)  # 复制避免污染

                if exists:
                    # 更新已有记录
                    set_parts = []
                    values = []
                    for key, value in fields.items():
                        set_parts.append(f"{key} = ${len(values) + 1}")
                        values.append(value)

                    values.append(datetime.utcnow())  # updated_at
                    values.append(user_id)  # WHERE条件

                    set_clause = ", ".join(set_parts)
                    await conn.execute(
                        f"UPDATE student_profiles "
                        f"SET {set_clause}, updated_at = ${len(set_parts) + 1} "
                        f"WHERE user_id = ${len(set_parts) + 2}",
                        *values
                    )
                else:
                    # 插入新记录
                    fields['user_id'] = user_id
                    fields['created_at'] = datetime.utcnow()
                    fields['updated_at'] = datetime.utcnow()

                    columns = list(fields.keys())
                    placeholders = [f"${i+1}" for i in range(len(columns))]
                    values = list(fields.values())

                    await conn.execute(
                        f"INSERT INTO student_profiles ({', '.join(columns)}) "
                        f"VALUES ({', '.join(placeholders)})",
                        *values
                    )

                logger.info(
                    f"UPSERT成功: user_id={user_id}, "
                    f"fields={list(fields.keys())}, existed={bool(exists)}"
                )
                return True

        except Exception as e:
            logger.error(f"UPSERT字段失败: {e}", exc_info=True)
            return False


def get_async_student_profile_repo() -> StudentProfileRepository:
    """获取异步仓储实例"""
    global _async_repo
    if _async_repo is None:
        _async_repo = StudentProfileRepository()
    return _async_repo
