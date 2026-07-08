"""规划师端数据库配置 - 对接企业数据库（与客户端共用但可定制）"""
from common.config.base_database import DatabaseConfig as BaseDBConfig


class ConsultantDatabaseConfig(BaseDBConfig):
    """规划师端PostgreSQL数据库配置类"""
    pass
