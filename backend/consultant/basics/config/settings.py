"""主配置类 - 规划师端服务配置"""
import os
from typing import Optional
from pathlib import Path


class Config:
    """应用配置类 - 面向对象管理配置

    规划师端服务运行在端口8001
    客户端服务运行在端口8002
    """

    # 环境配置
    ENV: str = os.getenv('ENV', 'development')
    DEBUG: bool = os.getenv('DEBUG', 'True').lower() == 'true'

    # 应用配置
    APP_NAME: str = os.getenv('APP_NAME', '留学规划师系统')
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')

    # 服务配置 - 规划师端默认端口8001（使用独立的环境变量）
    HOST: str = os.getenv('HOST', '0.0.0.0')
    PORT: int = int(os.getenv('CONSULTANT_PORT', os.getenv('PORT', '8001')))

    # API密钥
    DASHSCOPE_API_KEY: Optional[str] = os.getenv('DASHSCOPE_API_KEY')
    DEEPSEEK_API_KEY: Optional[str] = os.getenv('DEEPSEEK_API_KEY')

    # SSL配置
    SSL_VERIFY: bool = os.getenv('SSL_VERIFY', 'false').lower() == 'true'

    # 模型路径
    EMBEDDING_MODEL_PATH: Optional[str] = os.getenv('EMBEDDING_MODEL_PATH')
    RERANKER_MODEL_PATH: Optional[str] = os.getenv('RERANKER_MODEL_PATH')

    # 会话管理配置
    CONVERSATION_MAX_HISTORY_TURNS: int = int(os.getenv('CONVERSATION_MAX_HISTORY_TURNS', '10'))
    CONVERSATION_AUTO_TITLE_ENABLED: bool = os.getenv('CONVERSATION_AUTO_TITLE_ENABLED', 'true').lower() == 'true'
    CONVERSATION_TITLE_MAX_LENGTH: int = int(os.getenv('CONVERSATION_TITLE_MAX_LENGTH', '20'))
    CONVERSATION_DEFAULT_TITLE: str = os.getenv('CONVERSATION_DEFAULT_TITLE', '新对话')
    CONVERSATION_MESSAGES_PAGE_SIZE: int = int(os.getenv('CONVERSATION_MESSAGES_PAGE_SIZE', '50'))

    # Docker环境配置
    AUTO_START_DOCKER_ENV: bool = os.getenv('AUTO_START_DOCKER_ENV', 'true').lower() == 'true'

    # 项目根目录
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent

    @classmethod
    def is_production(cls) -> bool:
        """判断是否为生产环境"""
        return cls.ENV == 'production'

    @classmethod
    def is_development(cls) -> bool:
        """判断是否为开发环境"""
        return cls.ENV == 'development'

    @classmethod
    def get_log_level(cls) -> str:
        """获取日志级别"""
        return 'DEBUG' if cls.DEBUG else 'INFO'

    @classmethod
    def validate(cls) -> bool:
        """验证必要配置是否完整"""
        required_keys = ['DASHSCOPE_API_KEY', 'DEEPSEEK_API_KEY']
        missing = [k for k in required_keys if not getattr(cls, k)]
        if missing:
            import warnings
            warnings.warn(f"缺少必要的环境变量: {missing}")
            return False
        return True

    @classmethod
    def log_config(cls):
        """打印当前配置（调试用）"""
        print(f"\n{'='*50}")
        print(f"  {cls.APP_NAME} 配置信息")
        print(f"{'='*50}")
        print(f"  环境: {cls.ENV}")
        print(f"  地址: http://{cls.HOST}:{cls.PORT}")
        print(f"  调试模式: {cls.DEBUG}")
        print(f"  SSL验证: {cls.SSL_VERIFY}")
        print(f"{'='*50}\n")