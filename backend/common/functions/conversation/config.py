"""会话配置类"""
import os


class ConversationConfig:
    """会话配置类 - 管理会话相关配置
    
    硬约束配置：
    - PostgreSQL: 端口5433
    - Redis: 端口6379，密码1234
    """
    
    # ====== 会话配置 ======
    MAX_HISTORY_TURNS: int = int(os.getenv('CONVERSATION_MAX_HISTORY_TURNS', '10'))
    AUTO_TITLE_ENABLED: bool = os.getenv('CONVERSATION_AUTO_TITLE_ENABLED', 'true').lower() == 'true'
    TITLE_MAX_LENGTH: int = int(os.getenv('CONVERSATION_TITLE_MAX_LENGTH', '20'))
    DEFAULT_TITLE: str = os.getenv('CONVERSATION_DEFAULT_TITLE', '新对话')
    MESSAGES_PAGE_SIZE: int = int(os.getenv('CONVERSATION_MESSAGES_PAGE_SIZE', '50'))
    
    # ====== 数据库配置 ======
    DB_HOST: str = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT: int = int(os.getenv('DB_PORT', '5433'))  # Docker映射端口5433->容器5432
    DB_USER: str = os.getenv('DB_USER', 'eduagent_user')
    DB_PASSWORD: str = os.getenv('DB_PASSWORD', '123456')
    DB_NAME: str = os.getenv('DB_NAME', 'studyabroad')
    
    # ====== 连接池配置 ======
    DB_POOL_SIZE: int = int(os.getenv('DB_POOL_SIZE', '5'))
    DB_MAX_OVERFLOW: int = int(os.getenv('DB_MAX_OVERFLOW', '10'))
    DB_POOL_TIMEOUT: int = int(os.getenv('DB_POOL_TIMEOUT', '30'))
    
    @classmethod
    def get_db_url(cls, async_driver: bool = False) -> str:
        """获取数据库连接URL
        
        Args:
            async_driver: 是否使用异步驱动
            
        Returns:
            str: 数据库连接URL
        """
        driver = 'postgresql+asyncpg' if async_driver else 'postgresql+psycopg2'
        return f"{driver}://{cls.DB_USER}:{cls.DB_PASSWORD}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
    
    @classmethod
    def log_config(cls):
        """打印当前配置（调试用）"""
        print(f"\n{'='*50}")
        print(f"  会话配置信息")
        print(f"{'='*50}")
        print(f"  数据库: {cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}")
        print(f"  最大历史轮数: {cls.MAX_HISTORY_TURNS}")
        print(f"  自动生成标题: {cls.AUTO_TITLE_ENABLED}")
        print(f"  消息分页大小: {cls.MESSAGES_PAGE_SIZE}")
        print(f"{'='*50}\n")
