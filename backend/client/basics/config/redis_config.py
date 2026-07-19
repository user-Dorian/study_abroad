"""Redis配置类 - 客户端Redis连接配置"""
import os
from typing import Dict, Any


class ClientRedisConfig:
    """Redis配置类 - 面向对象管理Redis连接
    
    Redis端口: 6379
    Redis密码: 1234
    """
    
    # Redis连接配置
    HOST: str = os.getenv('REDIS_HOST', '127.0.0.1')
    PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    PASSWORD: str = os.getenv('REDIS_PASSWORD', '1234')
    DB: int = int(os.getenv('REDIS_DB', '0'))
    
    # Redis连接池配置
    MAX_CONNECTIONS: int = int(os.getenv('REDIS_MAX_CONNECTIONS', '10'))
    SOCKET_TIMEOUT: int = int(os.getenv('REDIS_SOCKET_TIMEOUT', '5'))
    SOCKET_CONNECT_TIMEOUT: int = int(os.getenv('REDIS_SOCKET_CONNECT_TIMEOUT', '5'))
    
    # 缓存配置
    TTL: int = int(os.getenv('REDIS_TTL', '3600'))  # 默认1小时
    KEY_PREFIX: str = os.getenv('REDIS_KEY_PREFIX', 'qa:')
    
    @classmethod
    def get_connection_params(cls) -> Dict[str, Any]:
        """获取Redis连接参数
        
        Returns:
            Dict: Redis连接参数字典
        """
        return {
            'host': cls.HOST,
            'port': cls.PORT,
            'password': cls.PASSWORD,
            'db': cls.DB,
            'decode_responses': True,
            'socket_timeout': cls.SOCKET_TIMEOUT,
            'socket_connect_timeout': cls.SOCKET_CONNECT_TIMEOUT,
            'max_connections': cls.MAX_CONNECTIONS
        }
    
    @classmethod
    def get_url(cls) -> str:
        """获取Redis连接URL
        
        Returns:
            str: Redis连接URL
        """
        if cls.PASSWORD:
            return f"redis://:{cls.PASSWORD}@{cls.HOST}:{cls.PORT}/{cls.DB}"
        return f"redis://{cls.HOST}:{cls.PORT}/{cls.DB}"
    
    @classmethod
    def validate(cls) -> bool:
        """验证Redis配置是否完整
        
        Returns:
            bool: 配置完整返回True
        """
        return bool(cls.HOST and cls.PORT)
    
    @classmethod
    def build_key(cls, *parts: str) -> str:
        """构建Redis键名
        
        Args:
            *parts: 键名的各个部分
            
        Returns:
            str: 完整的键名
        """
        return cls.KEY_PREFIX + ':'.join(str(p) for p in parts)
    
    @classmethod
    def log_config(cls):
        """打印当前配置（调试用）"""
        print(f"\n{'='*50}")
        print(f"  Redis配置信息")
        print(f"{'='*50}")
        print(f"  地址: {cls.HOST}:{cls.PORT}")
        print(f"  数据库: {cls.DB}")
        print(f"  键前缀: {cls.KEY_PREFIX}")
        print(f"  默认TTL: {cls.TTL}秒")
        print(f"{'='*50}\n")
