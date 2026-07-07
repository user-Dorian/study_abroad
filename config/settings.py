"""应用核心配置 - 采用面向对象管理"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class BaseConfig:
    """基础配置类"""
    
    # 项目根目录
    BASE_DIR = Path(__file__).resolve().parent.parent
    
    # 应用配置
    APP_NAME = os.getenv("APP_NAME", "RAG系统")
    DEBUG = os.getenv("DEBUG", "False").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    
    # 服务器配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    
    # AI API配置
    DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    
    @classmethod
    def validate(cls):
        """验证必要配置是否存在"""
        missing = []
        if not cls.DASHSCOPE_API_KEY:
            missing.append("DASHSCOPE_API_KEY")
        if not cls.DEEPSEEK_API_KEY:
            missing.append("DEEPSEEK_API_KEY")
        
        if missing:
            from utils.logger import logger
            logger.warning(f"以下环境变量未配置: {', '.join(missing)}")
            logger.warning("请检查 .env 文件配置")
        
        return len(missing) == 0
    
    @classmethod
    def get_config_summary(cls) -> dict:
        """获取配置摘要(隐藏敏感信息)"""
        return {
            "APP_NAME": cls.APP_NAME,
            "DEBUG": cls.DEBUG,
            "HOST": cls.HOST,
            "PORT": cls.PORT,
            "DASHSCOPE_API_KEY": "已配置" if cls.DASHSCOPE_API_KEY else "未配置",
            "DEEPSEEK_API_KEY": "已配置" if cls.DEEPSEEK_API_KEY else "未配置",
        }


class DevelopmentConfig(BaseConfig):
    """开发环境配置"""
    DEBUG = True


class ProductionConfig(BaseConfig):
    """生产环境配置"""
    DEBUG = False


# 根据环境变量选择配置
ENV = os.getenv("ENV", "development")
config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
}

Config = config_map.get(ENV, DevelopmentConfig)
