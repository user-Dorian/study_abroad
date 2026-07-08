"""规划师端Redis配置 - 使用独立前缀避免与客户端冲突"""
from common.config.base_redis import RedisConfig as BaseRedisConfig


class ConsultantRedisConfig(BaseRedisConfig):
    """规划师端Redis配置类"""

    DB = 1  # 使用不同DB
    KEY_PREFIX_RETRIEVAL = "consultant_retrieval:"
