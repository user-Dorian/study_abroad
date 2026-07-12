"""客户端配置"""
from common.config.base_settings import BaseConfig, DevelopmentConfig, ProductionConfig


class ClientConfig(BaseConfig):
    """客户端配置"""
    APP_NAME = "留学通"
    PORT = 8002


class ClientDevelopmentConfig(ClientConfig, DevelopmentConfig):
    pass


class ClientProductionConfig(ClientConfig, ProductionConfig):
    pass


ENV = __import__('os').getenv("ENV", "development")
config_map = {"development": ClientDevelopmentConfig, "production": ClientProductionConfig}
Config = config_map.get(ENV, ClientDevelopmentConfig)
