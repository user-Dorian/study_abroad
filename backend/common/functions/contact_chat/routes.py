"""联系人聊天路由 - 管理联系人聊天历史"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/chat", tags=["联系人聊天"])


class ChatMessage(BaseModel):
    """聊天消息"""
    message_id: str
    from_user_id: str
    to_user_id: str
    content: str
    message_type: str = "text"  # text/image/file
    created_at: datetime
    read: bool = False


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    to_user_id: str
    content: str
    message_type: Optional[str] = "text"


class ChatHistoryResponse(BaseModel):
    """聊天历史响应"""
    messages: List[ChatMessage]
    total: int
    has_more: bool


# 模拟聊天消息数据库
_chat_messages_db = {}


@router.post("/send", response_model=ChatMessage)
async def send_message(
    request: SendMessageRequest,
    current_user: dict = Depends(require_user)
):
    """发送聊天消息（HTTP方式，WebSocket优先）

    Args:
        request: 发送消息请求
        current_user: 当前用户

    Returns:
        ChatMessage: 发送的消息

    Raises:
        HTTPException: 400 - 不能给自己发消息
    """
    try:
        user_id = current_user["user_id"]

        # 检查是否给自己发消息
        if user_id == request.to_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能给自己发消息"
            )

        # 创建消息
        message_id = str(uuid.uuid4())
        message = {
            "message_id": message_id,
            "from_user_id": user_id,
            "to_user_id": request.to_user_id,
            "content": request.content,
            "message_type": request.message_type,
            "created_at": datetime.utcnow(),
            "read": False
        }

        _chat_messages_db[message_id] = message

        logger.info(
            f"消息发送成功: from={user_id}, to={request.to_user_id}, "
            f"type={request.message_type}"
        )

        return ChatMessage(**message)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


@router.get("/history/{contact_id}", response_model=ChatHistoryResponse)
async def get_chat_history(
    contact_id: str,
    limit: int = 50,
    before: Optional[str] = None,
    current_user: dict = Depends(require_user)
):
    """获取与联系人的聊天历史

    Args:
        contact_id: 联系人ID
        limit: 返回消息数量限制
        before: 获取此消息ID之前的消息
        current_user: 当前用户

    Returns:
        ChatHistoryResponse: 聊天历史响应
    """
    try:
        user_id = current_user["user_id"]
        messages = []

        # 过滤与联系人的消息
        for msg in _chat_messages_db.values():
            # 双向消息
            if (msg["from_user_id"] == user_id and msg["to_user_id"] == contact_id) or \
               (msg["from_user_id"] == contact_id and msg["to_user_id"] == user_id):
                messages.append(msg)

        # 按时间排序
        messages.sort(key=lambda x: x["created_at"], reverse=True)

        # 分页
        total = len(messages)
        messages = messages[:limit]
        has_more = total > limit

        logger.info(
            f"获取聊天历史: user_id={user_id}, contact_id={contact_id}, "
            f"count={len(messages)}"
        )

        return ChatHistoryResponse(
            messages=[ChatMessage(**m) for m in messages],
            total=total,
            has_more=has_more
        )

    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取聊天历史失败: {str(e)}")


@router.post("/read/{contact_id}")
async def mark_messages_read(
    contact_id: str,
    current_user: dict = Depends(require_user)
):
    """标记消息为已读

    Args:
        contact_id: 联系人ID
        current_user: 当前用户

    Returns:
        dict: 标记结果
    """
    try:
        user_id = current_user["user_id"]
        updated_count = 0

        # 标记来自该联系人的所有未读消息为已读
        for msg in _chat_messages_db.values():
            if msg["from_user_id"] == contact_id and msg["to_user_id"] == user_id:
                if not msg["read"]:
                    msg["read"] = True
                    updated_count += 1

        logger.info(
            f"标记消息已读: user_id={user_id}, contact_id={contact_id}, "
            f"count={updated_count}"
        )

        return {
            "success": True,
            "updated_count": updated_count
        }

    except Exception as e:
        logger.error(f"标记消息已读失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"标记消息已读失败: {str(e)}")


@router.delete("/{message_id}")
async def delete_message(
    message_id: str,
    current_user: dict = Depends(require_user)
):
    """删除消息

    Args:
        message_id: 消息ID
        current_user: 当前用户

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 404 - 消息不存在/403 - 无权删除
    """
    try:
        # 检查消息是否存在
        message = _chat_messages_db.get(message_id)
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="消息不存在"
            )

        # 检查权限
        if message["from_user_id"] != current_user["user_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权删除此消息"
            )

        # 删除消息
        del _chat_messages_db[message_id]

        logger.info(f"删除消息成功: message_id={message_id}")

        return {
            "success": True,
            "message": "消息已删除"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除消息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除消息失败: {str(e)}")
