"""申请时间线路由 - 管理留学申请时间节点"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/timeline", tags=["申请时间线"])


class TimelineEvent(BaseModel):
    """时间线事件"""
    event_id: str
    user_id: str
    event_type: str  # application/visa/test/document/payment/other
    title: str
    description: Optional[str] = None
    event_date: datetime
    status: str  # pending/completed/overdue
    priority: int = 0  # 0-低, 1-中, 2-高
    reminder_enabled: bool = True
    reminder_days: Optional[int] = 7
    created_at: datetime
    updated_at: Optional[datetime] = None


class CreateEventRequest(BaseModel):
    """创建事件请求"""
    event_type: str
    title: str
    description: Optional[str] = None
    event_date: datetime
    priority: Optional[int] = 0
    reminder_enabled: Optional[bool] = True
    reminder_days: Optional[int] = 7


class UpdateEventRequest(BaseModel):
    """更新事件请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    event_date: Optional[datetime] = None
    status: Optional[str] = None
    priority: Optional[int] = None
    reminder_enabled: Optional[bool] = None
    reminder_days: Optional[int] = None


class TimelineResponse(BaseModel):
    """时间线响应"""
    events: List[TimelineEvent]
    total: int
    upcoming_count: int
    overdue_count: int


# 模拟时间线数据库
_timeline_events_db = {}


@router.post("", response_model=TimelineEvent)
async def create_event(
    request: CreateEventRequest,
    current_user: dict = Depends(require_user)
):
    """创建时间线事件

    Args:
        request: 创建事件请求
        current_user: 当前用户

    Returns:
        TimelineEvent: 创建的事件
    """
    try:
        user_id = current_user["user_id"]

        # 创建事件
        event_id = str(uuid.uuid4())
        event = {
            "event_id": event_id,
            "user_id": user_id,
            "event_type": request.event_type,
            "title": request.title,
            "description": request.description,
            "event_date": request.event_date,
            "status": "pending",
            "priority": request.priority or 0,
            "reminder_enabled": request.reminder_enabled or True,
            "reminder_days": request.reminder_days or 7,
            "created_at": datetime.utcnow()
        }

        if user_id not in _timeline_events_db:
            _timeline_events_db[user_id] = {}
        _timeline_events_db[user_id][event_id] = event

        logger.info(f"创建时间线事件: user_id={user_id}, event_id={event_id}, type={request.event_type}")

        return TimelineEvent(**event)

    except Exception as e:
        logger.error(f"创建时间线事件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建时间线事件失败: {str(e)}")


@router.get("", response_model=TimelineResponse)
async def get_timeline(
    event_type: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(require_user)
):
    """获取时间线

    Args:
        event_type: 事件类型过滤
        status: 状态过滤
        current_user: 当前用户

    Returns:
        TimelineResponse: 时间线响应
    """
    try:
        user_id = current_user["user_id"]

        # 获取事件
        events = []
        user_events = _timeline_events_db.get(user_id, {})

        for event in user_events.values():
            if event_type and event["event_type"] != event_type:
                continue
            if status and event["status"] != status:
                continue
            events.append(event)

        # 按日期排序
        events.sort(key=lambda x: x["event_date"])

        # 统计
        now = datetime.utcnow()
        upcoming = len([e for e in events if e["status"] == "pending" and e["event_date"] > now])
        overdue = len([e for e in events if e["status"] == "pending" and e["event_date"] < now])

        logger.info(f"获取时间线: user_id={user_id}, count={len(events)}")

        return TimelineResponse(
            events=[TimelineEvent(**e) for e in events],
            total=len(events),
            upcoming_count=upcoming,
            overdue_count=overdue
        )

    except Exception as e:
        logger.error(f"获取时间线失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取时间线失败: {str(e)}")


@router.get("/{event_id}", response_model=TimelineEvent)
async def get_event(
    event_id: str,
    current_user: dict = Depends(require_user)
):
    """获取单个事件

    Args:
        event_id: 事件ID
        current_user: 当前用户

    Returns:
        TimelineEvent: 事件详情

    Raises:
        HTTPException: 404 - 事件不存在
    """
    try:
        user_id = current_user["user_id"]

        # 查找事件
        user_events = _timeline_events_db.get(user_id, {})
        event = user_events.get(event_id)

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="事件不存在"
            )

        logger.info(f"获取时间线事件: event_id={event_id}")

        return TimelineEvent(**event)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取时间线事件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取时间线事件失败: {str(e)}")


@router.put("/{event_id}", response_model=TimelineEvent)
async def update_event(
    event_id: str,
    request: UpdateEventRequest,
    current_user: dict = Depends(require_user)
):
    """更新事件

    Args:
        event_id: 事件ID
        request: 更新事件请求
        current_user: 当前用户

    Returns:
        TimelineEvent: 更新后的事件

    Raises:
        HTTPException: 404 - 事件不存在
    """
    try:
        user_id = current_user["user_id"]

        # 查找事件
        user_events = _timeline_events_db.get(user_id, {})
        event = user_events.get(event_id)

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="事件不存在"
            )

        # 更新事件
        update_data = request.dict(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                event[key] = value

        event["updated_at"] = datetime.utcnow()

        logger.info(f"更新时间线事件: event_id={event_id}")

        return TimelineEvent(**event)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新时间线事件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新时间线事件失败: {str(e)}")


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    current_user: dict = Depends(require_user)
):
    """删除事件

    Args:
        event_id: 事件ID
        current_user: 当前用户

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 404 - 事件不存在
    """
    try:
        user_id = current_user["user_id"]

        # 查找并删除事件
        user_events = _timeline_events_db.get(user_id, {})

        if event_id not in user_events:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="事件不存在"
            )

        del user_events[event_id]

        logger.info(f"删除时间线事件: event_id={event_id}")

        return {
            "success": True,
            "message": "事件已删除"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除时间线事件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除时间线事件失败: {str(e)}")


@router.post("/{event_id}/complete")
async def complete_event(
    event_id: str,
    current_user: dict = Depends(require_user)
):
    """标记事件为已完成

    Args:
        event_id: 事件ID
        current_user: 当前用户

    Returns:
        dict: 标记结果
    """
    try:
        user_id = current_user["user_id"]

        # 查找事件
        user_events = _timeline_events_db.get(user_id, {})
        event = user_events.get(event_id)

        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="事件不存在"
            )

        # 更新状态
        event["status"] = "completed"
        event["updated_at"] = datetime.utcnow()
        event["completed_at"] = datetime.utcnow()

        logger.info(f"标记时间线事件为已完成: event_id={event_id}")

        return {
            "success": True,
            "message": "事件已标记为已完成"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"标记时间线事件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"标记时间线事件失败: {str(e)}")
