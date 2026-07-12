"""未读消息 API 路由 - 获取未读统计、标记已读"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from common.utils.auth import require_user
from common.utils.logger import logger
from common.config.async_database import AsyncDatabasePool

router = APIRouter(prefix="/api/unread-messages", tags=["unread-messages"])


class MarkReadRequest(BaseModel):
    conversation_id: str


@router.get("/stats")
async def get_unread_stats(current_user: dict = Depends(require_user)):
    """获取当前用户的未读消息统计

    返回总未读数和各对话的未读详情
    """
    user_id = current_user["user_id"]

    # 查询该用户的所有未读记录
    rows = await AsyncDatabasePool.execute_query(
        """SELECT u.conversation_id, u.unread_count, u.last_read_at,
                  c.title, c.other_user_id,
                  ou.username AS other_username, ou.display_name AS other_display_name
           FROM unread_messages u
           JOIN conversations c ON c.id = u.conversation_id
           LEFT JOIN users ou ON ou.id = CASE 
               WHEN c.user_id = $1 THEN c.other_user_id ELSE c.user_id 
           END
           WHERE u.user_id = $1 AND u.unread_count > 0
           ORDER BY u.updated_at DESC""",
        user_id,
    )

    total_unread = 0
    unread_conversations = []

    for row in rows:
        unread_count = row["unread_count"] or 0
        total_unread += unread_count
        unread_conversations.append({
            "conversation_id": str(row["conversation_id"]),
            "unread_count": unread_count,
            "other_user": {
                "user_id": str(row["other_user_id"]) if row["other_user_id"] else None,
                "username": row["other_username"],
                "display_name": row["other_display_name"],
            },
        })

    return {
        "total_unread": total_unread,
        "unread_conversations": unread_conversations,
    }


@router.post("/mark-read")
async def mark_conversation_read(
    request: MarkReadRequest,
    current_user: dict = Depends(require_user),
):
    """标记对话为已读

    清除指定对话的未读计数，更新last_read_at时间戳
    """
    user_id = current_user["user_id"]
    conversation_id = request.conversation_id

    # 验证对话归属
    conv = await AsyncDatabasePool.execute_one(
        """SELECT id FROM conversations 
           WHERE id = $1 AND (user_id = $2 OR other_user_id = $2)""",
        conversation_id, user_id,
    )

    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在或无权访问")

    # 获取当前未读数
    unread_row = await AsyncDatabasePool.execute_one(
        """SELECT unread_count FROM unread_messages 
           WHERE user_id = $1 AND conversation_id = $2""",
        user_id, conversation_id,
    )

    cleared_count = unread_row["unread_count"] if unread_row else 0

    # 更新未读计数为0
    await AsyncDatabasePool.execute_command(
        """INSERT INTO unread_messages (user_id, conversation_id, unread_count, last_read_at, updated_at)
           VALUES ($1, $2, 0, NOW(), NOW())
           ON CONFLICT (user_id, conversation_id) 
           DO UPDATE SET 
               unread_count = 0, 
               last_read_at = NOW(),
               updated_at = NOW()""",
        user_id, conversation_id,
    )

    logger.info(f"[未读消息] 标记已读: user={user_id}, conv={conversation_id}, cleared={cleared_count}")

    return {
        "success": True,
        "conversation_id": conversation_id,
        "cleared_count": cleared_count,
    }