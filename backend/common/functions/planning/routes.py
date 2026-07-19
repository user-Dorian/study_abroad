"""留学规划路由 - AI辅助留学规划"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/planning", tags=["留学规划"])


class StudyPlan(BaseModel):
    """留学计划"""
    plan_id: str
    user_id: str
    title: str
    target_country: str
    target_level: str
    target_major: str
    timeline: List[dict]
    milestones: List[dict]
    status: str  # draft/active/completed
    created_at: datetime
    updated_at: Optional[datetime] = None


class CreatePlanRequest(BaseModel):
    """创建计划请求"""
    title: str
    target_country: str
    target_level: str
    target_major: str


class MilestoneRequest(BaseModel):
    """里程碑请求"""
    title: str
    description: Optional[str] = None
    due_date: datetime


# 模拟规划数据库
_plans_db = {}

# 规划模板
PLANNING_TEMPLATES = {
    "美国": {
        "timeline": [
            {"phase": "准备阶段", "duration": "6-12个月", "tasks": ["语言考试", "文书准备"]},
            {"phase": "申请阶段", "duration": "3-6个月", "tasks": ["提交申请", "面试准备"]},
            {"phase": "签证阶段", "duration": "1-2个月", "tasks": ["签证面试", "体检"]}
        ]
    },
    "英国": {
        "timeline": [
            {"phase": "准备阶段", "duration": "6-12个月", "tasks": ["语言考试", "推荐信"]},
            {"phase": "申请阶段", "duration": "2-4个月", "tasks": ["提交申请", "等待录取"]},
            {"phase": "签证阶段", "duration": "1个月", "tasks": ["签证申请"]}
        ]
    }
}


@router.post("/plans", response_model=StudyPlan)
async def create_plan(
    request: CreatePlanRequest,
    current_user: dict = Depends(require_user)
):
    """创建留学计划

    Args:
        request: 创建计划请求
        current_user: 当前用户

    Returns:
        StudyPlan: 留学计划
    """
    try:
        user_id = current_user["user_id"]

        # 获取模板
        template = PLANNING_TEMPLATES.get(request.target_country, PLANNING_TEMPLATES["美国"])

        # 创建计划
        plan_id = str(uuid.uuid4())
        plan = {
            "plan_id": plan_id,
            "user_id": user_id,
            "title": request.title,
            "target_country": request.target_country,
            "target_level": request.target_level,
            "target_major": request.target_major,
            "timeline": template["timeline"],
            "milestones": [],
            "status": "draft",
            "created_at": datetime.utcnow()
        }

        if user_id not in _plans_db:
            _plans_db[user_id] = {}
        _plans_db[user_id][plan_id] = plan

        logger.info(f"创建留学计划: user_id={user_id}, plan_id={plan_id}, country={request.target_country}")

        return StudyPlan(**plan)

    except Exception as e:
        logger.error(f"创建留学计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建留学计划失败: {str(e)}")


@router.get("/plans", response_model=List[StudyPlan])
async def get_plans(current_user: dict = Depends(require_user)):
    """获取留学计划列表

    Args:
        current_user: 当前用户

    Returns:
        List[StudyPlan]: 计划列表
    """
    try:
        user_id = current_user["user_id"]

        # 获取计划
        plans = list(_plans_db.get(user_id, {}).values())
        plans.sort(key=lambda x: x["created_at"], reverse=True)

        logger.info(f"获取留学计划列表: user_id={user_id}, count={len(plans)}")

        return [StudyPlan(**p) for p in plans]

    except Exception as e:
        logger.error(f"获取留学计划列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取留学计划列表失败: {str(e)}")


@router.get("/plans/{plan_id}", response_model=StudyPlan)
async def get_plan(
    plan_id: str,
    current_user: dict = Depends(require_user)
):
    """获取留学计划详情

    Args:
        plan_id: 计划ID
        current_user: 当前用户

    Returns:
        StudyPlan: 计划详情

    Raises:
        HTTPException: 404 - 计划不存在
    """
    try:
        user_id = current_user["user_id"]

        # 查找计划
        user_plans = _plans_db.get(user_id, {})
        plan = user_plans.get(plan_id)

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="计划不存在"
            )

        logger.info(f"获取留学计划: plan_id={plan_id}")

        return StudyPlan(**plan)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取留学计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取留学计划失败: {str(e)}")


@router.post("/plans/{plan_id}/milestones")
async def add_milestone(
    plan_id: str,
    request: MilestoneRequest,
    current_user: dict = Depends(require_user)
):
    """添加里程碑

    Args:
        plan_id: 计划ID
        request: 里程碑请求
        current_user: 当前用户

    Returns:
        dict: 添加结果
    """
    try:
        user_id = current_user["user_id"]

        # 查找计划
        user_plans = _plans_db.get(user_id, {})
        plan = user_plans.get(plan_id)

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="计划不存在"
            )

        # 添加里程碑
        milestone = {
            "milestone_id": str(uuid.uuid4()),
            "title": request.title,
            "description": request.description,
            "due_date": request.due_date.isoformat(),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat()
        }
        plan["milestones"].append(milestone)
        plan["updated_at"] = datetime.utcnow()

        logger.info(f"添加里程碑: plan_id={plan_id}, title={request.title}")

        return {
            "success": True,
            "milestone": milestone
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加里程碑失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"添加里程碑失败: {str(e)}")


@router.post("/plans/{plan_id}/activate")
async def activate_plan(
    plan_id: str,
    current_user: dict = Depends(require_user)
):
    """激活计划

    Args:
        plan_id: 计划ID
        current_user: 当前用户

    Returns:
        dict: 激活结果
    """
    try:
        user_id = current_user["user_id"]

        # 查找计划
        user_plans = _plans_db.get(user_id, {})
        plan = user_plans.get(plan_id)

        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="计划不存在"
            )

        # 激活计划
        plan["status"] = "active"
        plan["updated_at"] = datetime.utcnow()

        logger.info(f"激活留学计划: plan_id={plan_id}")

        return {
            "success": True,
            "message": "计划已激活"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"激活留学计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"激活留学计划失败: {str(e)}")
