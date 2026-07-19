"""数据库配置类 - 客户端PostgreSQL数据库配置"""
import os
from typing import Dict, Any


class ClientDatabaseConfig:
    """数据库配置类 - 面向对象管理PostgreSQL连接
    
    PostgreSQL端口: 5433 (Docker映射)
    数据库: studyabroad
    用户: eduagent_user
    """
    
    # 数据库连接配置
    DB_HOST: str = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT: int = int(os.getenv('DB_PORT', '5433'))
    DB_USER: str = os.getenv('DB_USER', 'eduagent_user')
    DB_PASSWORD: str = os.getenv('DB_PASSWORD', '123456')
    DB_NAME: str = os.getenv('DB_NAME', 'studyabroad')
    
    # 连接池配置
    DB_POOL_SIZE: int = int(os.getenv('DB_POOL_SIZE', '5'))
    DB_MAX_OVERFLOW: int = int(os.getenv('DB_MAX_OVERFLOW', '10'))
    DB_POOL_TIMEOUT: int = int(os.getenv('DB_POOL_TIMEOUT', '30'))
    DB_POOL_RECYCLE: int = int(os.getenv('DB_POOL_RECYCLE', '1800'))
    
    @classmethod
    def get_connection_params(cls) -> Dict[str, Any]:
        """获取数据库连接参数
        
        Returns:
            Dict: 数据库连接参数字典
        """
        return {
            'host': cls.DB_HOST,
            'port': cls.DB_PORT,
            'user': cls.DB_USER,
            'password': cls.DB_PASSWORD,
            'database': cls.DB_NAME
        }
    
    @classmethod
    def get_url(cls, async_driver: bool = False) -> str:
        """获取数据库连接URL
        
        Args:
            async_driver: 是否使用异步驱动
            
        Returns:
            str: 数据库连接URL
        """
        driver = 'postgresql+asyncpg' if async_driver else 'postgresql+psycopg2'
        return f"{driver}://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
    
    @classmethod
    def get_sqlalchemy_url(cls, async_driver: bool = False) -> str:
        """获取SQLAlchemy格式的数据库URL（别名）
        
        Args:
            async_driver: 是否使用异步驱动
            
        Returns:
            str: 数据库连接URL
        """
        return cls.get_url(async_driver)
    
    @classmethod
    def validate(cls) -> bool:
        """验证数据库配置是否完整
        
        Returns:
            bool: 配置完整返回True
        """
        return all([cls.DB_HOST, cls.DB_PORT, cls.DB_USER, cls.DB_NAME])
    
    @classmethod
    def get_pool_config(cls) -> Dict[str, Any]:
        """获取连接池配置
        
        Returns:
            Dict: 连接池配置字典
        """
        return {
            'pool_size': cls.DB_POOL_SIZE,
            'max_overflow': cls.DB_MAX_OVERFLOW,
            'pool_timeout': cls.DB_POOL_TIMEOUT,
            'pool_recycle': cls.DB_POOL_RECYCLE
        }
    
    @classmethod
    def log_config(cls):
        """打印当前配置（调试用）"""
        print(f"\n{'='*50}")
        print(f"  数据库配置信息")
        print(f"{'='*50}")
        print(f"  地址: {cls.DB_HOST}:{cls.DB_PORT}")
        print(f"  数据库: {cls.DB_NAME}")
        print(f"  用户: {cls.DB_USER}")
        print(f"  连接池大小: {cls.DB_POOL_SIZE}")
        print(f"{'='*50}\n")
