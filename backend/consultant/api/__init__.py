"""规划师端API路由模块

导出所有规划师端API路由，供server.py统一注册使用。
"""
from backend.consultant.api.auth_routes import router as auth_router
from backend.consultant.api.status_routes import router as status_router

__all__ = ["auth_router", "status_router"]