"""未读消息路由 - 管理未读消息计数和通知"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/unread", tags=["未读消息"])


class UnreadCountResponse(BaseModel):
    """未读消息计数响应"""
    user_id: str
    total_unread: int
    chat_unread: int
    system_unread: int
    updated_at: datetime


class UnreadMessage(BaseModel):
    """未读消息"""
    message_id: str
    from_user_id: str
    from_username: Optional[str] = None
    content_preview: str
    message_type: str
    created_at: datetime


# 模拟未读消息数据库
_unread_counts_db = {}
_unread_messages_db = {}


@router.get("/count", response_model=UnreadCountResponse)
async def get_unread_count(current_user: dict = Depends(require_user)):
    """获取未读消息计数

    Args:
        current_user: 当前用户

    Returns:
        UnreadCountResponse: 未读消息计数
    """
    try:
        user_id = current_user["user_id"]

        # 获取或初始化未读计数
        if user_id not in _unread_counts_db:
            _unread_counts_db[user_id] = {
                "chat_unread": 0,
                "system_unread": 0,
                "updated_at": datetime.utcnow()
            }

        counts = _unread_counts_db[user_id]

        logger.info(f"获取未读消息计数: user_id={user_id}, total={counts['chat_unread'] + counts['system_unread']}")

        return UnreadCountResponse(
            user_id=user_id,
            total_unread=counts["chat_unread"] + counts["system_unread"],
            chat_unread=counts["chat_unread"],
            system_unread=counts["system_unread"],
            updated_at=counts["updated_at"]
        )

    except Exception as e:
        logger.error(f"获取未读消息计数失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取未读消息计数失败: {str(e)}")


@router.get("/list", response_model=List[UnreadMessage])
async def get_unread_messages(
    limit: int = 20,
    message_type: Optional[str] = None,
    current_user: dict = Depends(require_user)
):
    """获取未读消息列表

    Args:
        limit: 返回消息数量限制
        message_type: 消息类型过滤
        current_user: 当前用户

    Returns:
        List[UnreadMessage]: 未读消息列表
    """
    try:
        user_id = current_user["user_id"]

        # 获取未读消息
        messages = []
        if user_id in _unread_messages_db:
            for msg in _unread_messages_db[user_id]:
                if message_type is None or msg["message_type"] == message_type:
                    messages.append(msg)

        # 按时间排序并限制数量
        messages.sort(key=lambda x: x["created_at"], reverse=True)
        messages = messages[:limit]

        logger.info(f"获取未读消息列表: user_id={user_id}, count={len(messages)}")

        return [UnreadMessage(**m) for m in messages]

    except Exception as e:
        logger.error(f"获取未读消息列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取未读消息列表失败: {str(e)}")


@router.post("/clear")
async def clear_unread_messages(
    message_type: Optional[str] = None,
    current_user: dict = Depends(require_user)
):
    """清除未读消息

    Args:
        message_type: 清除指定类型的消息（可选）
        current_user: 当前用户

    Returns:
        dict: 清除结果
    """
    try:
        user_id = current_user["user_id"]

        # 清除未读计数
        if user_id in _unread_counts_db:
            if message_type == "chat":
                _unread_counts_db[user_id]["chat_unread"] = 0
            elif message_type == "system":
                _unread_counts_db[user_id]["system_unread"] = 0
            else:
                _unread_counts_db[user_id]["chat_unread"] = 0
                _unread_counts_db[user_id]["system_unread"] = 0
            _unread_counts_db[user_id]["updated_at"] = datetime.utcnow()

        # 清除未读消息列表
        if message_type:
            if user_id in _unread_messages_db:
                _unread_messages_db[user_id] = [
                    m for m in _unread_messages_db[user_id]
                    if m["message_type"] != message_type
                ]
        else:
            _unread_messages_db[user_id] = []

        logger.info(f"清除未读消息: user_id={user_id}, type={message_type}")

        return {
            "success": True,
            "message": "未读消息已清除"
        }

    except Exception as e:
        logger.error(f"清除未读消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除未读消息失败: {str(e)}")


@router.post("/increment")
async def increment_unread_count(
    user_id: str,
    message_type: str = "chat",
    message_preview: Optional[str] = None
):
    """增加未读消息计数（内部接口）

    Args:
        user_id: 用户ID
        message_type: 消息类型
        message_preview: 消息预览（可选）

    Returns:
        dict: 增加结果
    """
    try:
        # 初始化计数
        if user_id not in _unread_counts_db:
            _unread_counts_db[user_id] = {
                "chat_unread": 0,
                "system_unread": 0,
                "updated_at": datetime.utcnow()
            }

        # 增加计数
        if message_type == "chat":
            _unread_counts_db[user_id]["chat_unread"] += 1
        elif message_type == "system":
            _unread_counts_db[user_id]["system_unread"] += 1

        _unread_counts_db[user_id]["updated_at"] = datetime.utcnow()

        # 添加消息预览
        if message_preview:
            if user_id not in _unread_messages_db:
                _unread_messages_db[user_id] = []

            _unread_messages_db[user_id].append({
                "message_id": f"msg_{datetime.utcnow().timestamp()}",
                "from_user_id": "system",
                "from_username": "系统",
                "content_preview": message_preview,
                "message_type": message_type,
                "created_at": datetime.utcnow()
            })

        logger.info(f"增加未读消息计数: user_id={user_id}, type={message_type}")

        return {
            "success": True,
            "message": "未读消息计数已增加"
        }

    except Exception as e:
        logger.error(f"增加未读消息计数失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"增加未读消息计数失败: {str(e)}")
