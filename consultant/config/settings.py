"""规划师端核心配置 - 面向对象管理"""
from common.config.base_settings import BaseConfig


class ConsultantConfig(BaseConfig):
    """规划师端基础配置类"""

    APP_NAME = "企业留学通"
    PORT = 8001
    JWT_SECRET_KEY = "consultant-jwt-secret-key-change-in-production"
    ENTERPRISE_DATA_DIR = BaseConfig.BASE_DIR / "data" / "study_abroad" / "enterprise"
