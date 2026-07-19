"""状态检查路由 - 提供系统状态检查功能"""
from fastapi import APIRouter
from datetime import datetime
import time
import platform
import sys

from backend.common.basics.utils.logger import logger

router = APIRouter()

# 服务启动时间（全局常量，被server.py引用）
START_TIME = time.time()


@router.get("/api/status")
async def get_status():
    """获取系统状态

    Returns:
        dict: 系统状态信息，包括运行时间、Python版本、平台信息等
    """
    uptime_seconds = round(time.time() - START_TIME, 2)
    uptime_hours = uptime_seconds / 3600

    return {
        "status": "ok",
        "service": "client",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "uptime_human": f"{int(uptime_hours)}h {int((uptime_hours % 1) * 60)}m",
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@router.get("/api/ping")
async def ping():
    """Ping端点 - 用于健康检查和负载均衡

    Returns:
        dict: 简单的pong响应
    """
    return {
        "ping": "pong",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@router.get("/api/health")
async def health_check():
    """健康检查端点 - 详细健康状态

    Returns:
        dict: 系统健康状态，包括各个组件的状态
    """
    uptime_seconds = round(time.time() - START_TIME, 2)

    # 检查各个组件状态
    components = {}

    # Redis连接状态
    try:
        import redis
        from backend.client.basics.config.redis_config import ClientRedisConfig
        if hasattr(ClientRedisConfig, 'validate') and ClientRedisConfig.validate():
            r = redis.Redis(
                host=ClientRedisConfig.HOST,
                port=ClientRedisConfig.PORT,
                password=ClientRedisConfig.PASSWORD,
                decode_responses=True
            )
            r.ping()
            components["redis"] = {"status": "healthy", "message": "连接正常"}
        else:
            components["redis"] = {"status": "disabled", "message": "Redis配置不完整"}
    except Exception as e:
        components["redis"] = {"status": "unhealthy", "message": str(e)[:50]}

    # 数据库连接状态
    try:
        import psycopg2
        from backend.client.basics.config.database import ClientDatabaseConfig
        if hasattr(ClientDatabaseConfig, 'validate') and ClientDatabaseConfig.validate():
            conn = psycopg2.connect(
                host=ClientDatabaseConfig.DB_HOST,
                port=ClientDatabaseConfig.DB_PORT,
                user=ClientDatabaseConfig.DB_USER,
                password=ClientDatabaseConfig.DB_PASSWORD,
                database=ClientDatabaseConfig.DB_NAME,
                connect_timeout=5
            )
            conn.close()
            components["database"] = {"status": "healthy", "message": "连接正常"}
        else:
            components["database"] = {"status": "disabled", "message": "数据库配置不完整"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "message": str(e)[:50]}

    # 判断整体健康状态
    overall_status = "healthy"
    for component in components.values():
        if component["status"] == "unhealthy":
            overall_status = "degraded"
            break

    return {
        "status": overall_status,
        "service": "client",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "components": components
    }


@router.get("/api/info")
async def get_info():
    """获取系统信息

    Returns:
        dict: 系统详细信息，包括环境、配置等
    """
    return {
        "service": "RAG智能检索系统-客户端",
        "version": "1.0.0",
        "python_version": sys.version,
        "platform": {
            "system": platform.system(),
            "node": platform.node(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor()
        },
        "environment": {
            "python_path": sys.executable,
            "working_directory": "."
        },
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
