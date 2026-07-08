"""Redis配置 - 采用面向对象管理"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class RedisConfig:
    """Redis配置类"""

    # 连接配置
    HOST = os.getenv("REDIS_HOST", "localhost")
    PORT = int(os.getenv("REDIS_PORT", "6379"))
    PASSWORD = os.getenv("REDIS_PASSWORD", "")
    DB = int(os.getenv("REDIS_DB", "0"))

    # 缓存配置
    TTL = int(os.getenv("REDIS_TTL", "3600"))  # 默认1小时，单位秒
    KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "qa:")
    KEY_PREFIX_RETRIEVAL = os.getenv("REDIS_KEY_PREFIX_RETRIEVAL", "retrieval:")  # 检索结果缓存前缀（不缓存LLM回答）

    # 阶段3异步改造：异步Redis连接池最大连接数
    ASYNC_MAX_CONNECTIONS = int(os.getenv("ASYNC_REDIS_MAX_CONNECTIONS", "50"))

    @classmethod
    def get_connection_params(cls) -> dict:
        """获取Redis连接参数"""
        params = {
            "host": cls.HOST,
            "port": cls.PORT,
            "db": cls.DB,
            "decode_responses": True,
        }
        if cls.PASSWORD:
            params["password"] = cls.PASSWORD
        return params

    @classmethod
    def get_async_connection_params(cls) -> dict:
        """
        阶段3异步改造：获取异步Redis连接参数

        与 get_connection_params() 保持一致，并附加 max_connections 参数，
        供 redis.asyncio.Redis 连接池使用。
        """
        params = cls.get_connection_params()
        params["max_connections"] = cls.ASYNC_MAX_CONNECTIONS
        return params

    @classmethod
    def get_connection_info(cls) -> dict:
        """获取Redis连接信息(隐藏密码)"""
        return {
            "host": cls.HOST,
            "port": cls.PORT,
            "db": cls.DB,
            "ttl": cls.TTL,
            "key_prefix": cls.KEY_PREFIX,
            "password": "已配置" if cls.PASSWORD else "未配置",
        }

    @classmethod
    def validate(cls) -> bool:
        """验证Redis配置"""
        if not cls.HOST or not cls.PORT:
            from common.utils.logger import logger
            logger.error("Redis配置不完整")
            return False
        return True
