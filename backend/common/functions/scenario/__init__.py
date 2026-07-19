"""情景对话功能模块

导出：
    - ScenarioWorkflow: 情景对话工作流类（供外部直接调用）
    - router: FastAPI 路由对象（已在 server.py 中挂载）
"""
from .graph import ScenarioWorkflow
from .routes import router

__all__ = ["ScenarioWorkflow", "router"]
