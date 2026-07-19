"""规划师端状态检查路由 - 提供系统状态检查功能

遵循客户端状态路由的实现风格，提供健康检查、系统信息等功能。
"""
from fastapi import APIRouter
from datetime import datetime
import time
import platform
import sys

from backend.common.basics.utils.logger import logger

router = APIRouter()

# 服务启动时间（全局常量）
START_TIME = time.time()


@router.get("/status")
async def get_status():
    """获取系统状态（基础健康检查）

    Returns:
        dict: 系统状态信息，包括运行时间、Python版本、平台信息等
    """
    uptime_seconds = round(time.time() - START_TIME, 2)
    uptime_hours = uptime_seconds / 3600

    return {
        "status": "ok",
        "service": "consultant",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "uptime_human": f"{int(uptime_hours)}h {int((uptime_hours % 1) * 60)}m",
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@router.get("/api/consultant/status")
async def get_consultant_status():
    """获取规划师端API状态（详细状态）

    Returns:
        dict: 规划师端API状态信息
    """
    uptime_seconds = round(time.time() - START_TIME, 2)
    uptime_hours = uptime_seconds / 3600

    return {
        "status": "ok",
        "service": "consultant",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "uptime_human": f"{int(uptime_hours)}h {int((uptime_hours % 1) * 60)}m",
        "python_version": sys.version,
        "platform": platform.platform(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "endpoints": {
            "auth": "/api/consultant/auth",
            "status": "/api/consultant/status",
            "health": "/api/consultant/health"
        }
    }


@router.get("/api/consultant/ping")
async def ping():
    """Ping端点 - 用于健康检查和负载均衡

    Returns:
        dict: 简单的pong响应
    """
    return {
        "ping": "pong",
        "service": "consultant",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }


@router.get("/api/consultant/health")
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
        from backend.consultant.config.redis_config import ConsultantRedisConfig
        if hasattr(ConsultantRedisConfig, 'validate') and ConsultantRedisConfig.validate():
            r = redis.Redis(
                host=ConsultantRedisConfig.HOST,
                port=ConsultantRedisConfig.PORT,
                password=ConsultantRedisConfig.PASSWORD,
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
        from backend.consultant.config.database import ConsultantDatabaseConfig
        if hasattr(ConsultantDatabaseConfig, 'validate') and ConsultantDatabaseConfig.validate():
            conn = psycopg2.connect(
                host=ConsultantDatabaseConfig.DB_HOST,
                port=ConsultantDatabaseConfig.DB_PORT,
                user=ConsultantDatabaseConfig.DB_USER,
                password=ConsultantDatabaseConfig.DB_PASSWORD,
                database=ConsultantDatabaseConfig.DB_NAME,
                connect_timeout=5
            )
            conn.close()
            components["database"] = {"status": "healthy", "message": "连接正常"}
        else:
            components["database"] = {"status": "disabled", "message": "数据库配置不完整"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "message": str(e)[:50]}

    # Milvus连接状态（企业数据集合）
    try:
        from backend.common.functions.rag.data_loader.chunk_and_embed import MilvusManager
        from backend.consultant.rag.rag_config import ConsultantRAGConfig

        milvus = MilvusManager(
            collection_name=ConsultantRAGConfig.MILVUS_COLLECTION_NAME,
            database_name=ConsultantRAGConfig.MILVUS_DATABASE_NAME,
        )
        count = milvus.get_count() if hasattr(milvus, 'get_count') else 0
        components["milvus"] = {"status": "healthy", "message": f"连接正常，向量数: {count}"}
    except Exception as e:
        components["milvus"] = {"status": "unhealthy", "message": str(e)[:50]}

    # 判断整体健康状态
    overall_status = "healthy"
    for component in components.values():
        if component["status"] == "unhealthy":
            overall_status = "degraded"
            break

    return {
        "status": overall_status,
        "service": "consultant",
        "version": "1.0.0",
        "uptime_seconds": uptime_seconds,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "components": components
    }


@router.get("/api/consultant/info")
async def get_info():
    """获取系统信息

    Returns:
        dict: 系统详细信息，包括环境、配置等
    """
    return {
        "service": "企业留学通 - 规划师端",
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
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "features": {
            "authentication": "JWT",
            "role": "consultant",
            "rag_enabled": True,
            "enterprise_data": True
        }
    }