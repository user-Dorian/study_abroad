"""数据库配置 - 采用面向对象管理"""
import os


class DatabaseConfig:
    """PostgreSQL数据库配置类"""

    # 数据库连接配置
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5433"))
    DB_USER = os.getenv("DB_USER", "eduagent_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "123456")
    DB_NAME = os.getenv("DB_NAME", "eduagent")

    # 连接池配置
    POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
    MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))  # 30分钟

    @classmethod
    def get_connection_url(cls) -> str:
        """获取数据库连接URL"""
        return (
            f"postgresql+psycopg2://{cls.DB_USER}:{cls.DB_PASSWORD}"
            f"@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
        )

    @classmethod
    def get_connection_params(cls) -> dict:
        """获取数据库连接参数字典"""
        return {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "user": cls.DB_USER,
            "password": cls.DB_PASSWORD,
            "database": cls.DB_NAME,
        }

    @classmethod
    def get_connection_info(cls) -> dict:
        """获取数据库连接信息字典(隐藏密码)"""
        return {
            "host": cls.DB_HOST,
            "port": cls.DB_PORT,
            "user": cls.DB_USER,
            "database": cls.DB_NAME,
            "pool_size": cls.POOL_SIZE,
            "max_overflow": cls.MAX_OVERFLOW,
        }

    @classmethod
    def validate(cls) -> bool:
        """验证数据库配置是否完整"""
        if not cls.DB_HOST or not cls.DB_USER or not cls.DB_NAME:
            from utils.logger import logger
            logger.error("数据库配置不完整，请检查环境变量")
            return False
        return True
