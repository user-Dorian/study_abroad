"""联系人对话 API 路由 - 确保/获取联系人对话及消息"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from common.utils.auth import require_user
from common.utils.logger import logger
from common.config.async_database import AsyncDatabasePool
from common.conversation.repository import AsyncMessageRepository
from common.friendship.repository import get_friendship_repo

router = APIRouter(prefix="/api/contact-chat", tags=["contact-chat"])


class EnsureConversationRequest(BaseModel):
    target_user_id: str


class SendMessageRequest(BaseModel):
    content: str


@router.post("/ensure")
async def ensure_contact_conversation(
    request: EnsureConversationRequest,
    current_user: dict = Depends(require_user),
):
    """确保与指定用户存在联系人对话"""
    user_id = current_user["user_id"]
    target_id = request.target_user_id
    current_role = current_user.get("role", "client")

    if user_id == target_id:
        raise HTTPException(status_code=400, detail="不能和自己对话")

    target_row = await AsyncDatabasePool.execute_one(
        "SELECT id, role, username, display_name FROM users WHERE id = $1",
        target_id,
    )
    if not target_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    target_role = target_row["role"]

    # 同端 client↔client 需要好友验证
    if current_role == "client" and target_role == "client":
        friend_repo = get_friendship_repo()
        is_friend = await friend_repo.check_friendship(user_id, target_id)
        if not is_friend:
            raise HTTPException(status_code=403, detail="对方不是您的好友，请先发送好友请求")

    # 查找已有联系人对话
    uid1, uid2 = sorted([user_id, target_id])
    conv_row = await AsyncDatabasePool.execute_one(
        """SELECT id, user_id, other_user_id, title, created_at, updated_at
           FROM conversations
           WHERE dialogue_type = 'contact_chat'
             AND ((user_id = $1 AND other_user_id = $2) OR (user_id = $2 AND other_user_id = $1))
           LIMIT 1""",
        uid1, uid2,
    )

    if conv_row:
        return {"conversation": dict(conv_row), "created": False}

    title = f"与{target_row.get('display_name') or target_row['username']}的对话"
    new_conv = await AsyncDatabasePool.execute_one(
        """INSERT INTO conversations (user_id, other_user_id, title, dialogue_type)
           VALUES ($1, $2, $3, 'contact_chat')
           RETURNING id, user_id, other_user_id, title, created_at, updated_at""",
        uid1, uid2, title,
    )

    logger.info(f"创建联系人对话成功: user_id={uid1}, other={uid2}")
    return {"conversation": dict(new_conv), "created": True}


@router.get("/list")
async def list_contact_conversations(current_user: dict = Depends(require_user)):
    """获取当前用户的所有联系人对话列表"""
    user_id = current_user["user_id"]

    rows = await AsyncDatabasePool.execute_query(
        """SELECT c.id, c.title, c.user_id, c.other_user_id,
                  c.dialogue_type, c.created_at, c.updated_at,
                  u.id AS other_id, u.username AS other_username,
                  u.display_name AS other_display_name, u.role AS other_role,
                  um.unread_count, um.last_read_at
           FROM conversations c
           LEFT JOIN users u ON u.id = CASE
               WHEN c.user_id = $1 THEN c.other_user_id ELSE c.user_id
           END
           LEFT JOIN unread_messages um ON um.user_id = $1 AND um.conversation_id = c.id
           WHERE c.dialogue_type = 'contact_chat'
             AND (c.user_id = $1 OR c.other_user_id = $1)
           ORDER BY c.updated_at DESC""",
        user_id,
    )

    other_ids = []
    for row in rows:
        other_id = str(row["other_id"]) if row["other_id"] else None
        if other_id:
            other_ids.append(other_id)

    # 诊断日志：打印查询到的对方用户ID
    logger.info(f"[在线状态诊断] 当前用户={user_id}, 查询联系人ID列表={other_ids}")

    online_status = {}
    if other_ids:
        try:
            from common.utils.online_status import batch_check_online
            online_status = await batch_check_online(other_ids)
            # 诊断日志：打印在线状态结果
            logger.info(f"[在线状态诊断] batch_check_online结果={online_status}")
        except Exception as e:
            # 移除静默吞掉异常，改为记录日志
            logger.error(f"[在线状态诊断] batch_check_online失败: {e}")

    conversations = []
    for row in rows:
        other_id = str(row["other_id"]) if row["other_id"] else None
        last_msg = await AsyncDatabasePool.execute_one(
            "SELECT content, created_at FROM messages WHERE conversation_id = $1 ORDER BY created_at DESC LIMIT 1",
            str(row["id"]),
        )
        conversations.append({
            "id": str(row["id"]),
            "title": row["title"],
            "other_user": {
                "user_id": other_id,
                "username": row["other_username"],
                "display_name": row["other_display_name"],
                "role": row["other_role"],
                "online": online_status.get(other_id, False) if other_id else False,
            },
            "last_message": last_msg["content"][:80] + "..." if last_msg and len(last_msg["content"]) > 80 else (last_msg["content"] if last_msg else None),
            "last_message_time": str(last_msg["created_at"]) if last_msg else None,
            "updated_at": str(row["updated_at"]),
            "unread_count": row["unread_count"] or 0,  # 新增：未读消息数
        })

    return {"conversations": conversations}


@router.get("/{conversation_id}/messages")
async def get_contact_messages(
    conversation_id: str,
    limit: int = 50,
    current_user: dict = Depends(require_user),
):
    """获取联系人对话的消息列表"""
    user_id = current_user["user_id"]

    conv = await AsyncDatabasePool.execute_one(
        "SELECT id FROM conversations WHERE id = $1 AND (user_id = $2 OR other_user_id = $2)",
        conversation_id, user_id,
    )
    if not conv:
        raise HTTPException(status_code=403, detail="无权访问此对话")

    msg_repo = AsyncMessageRepository()
    messages = await msg_repo.get_messages(conversation_id, limit=limit)
    return {"messages": messages}


@router.post("/{conversation_id}/messages")
async def send_contact_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(require_user),
):
    """发送消息到联系人对话"""
    user_id = current_user["user_id"]
    current_role = current_user.get("role", "client")

    conv = await AsyncDatabasePool.execute_one(
        "SELECT id, user_id, other_user_id FROM conversations WHERE id = $1 AND (user_id = $2 OR other_user_id = $2)",
        conversation_id, user_id,
    )
    if not conv:
        raise HTTPException(status_code=403, detail="无权向此对话发送消息")

    target_user_id = str(conv["other_user_id"]) if str(conv["user_id"]) == user_id else str(conv["user_id"])

    # 同端 client↔client 需要验证好友关系
    if current_role == "client":
        target_role_row = await AsyncDatabasePool.execute_one(
            "SELECT role FROM users WHERE id = $1", target_user_id,
        )
        if target_role_row and target_role_row["role"] == "client":
            friend_repo = get_friendship_repo()
            is_friend = await friend_repo.check_friendship(user_id, target_user_id)
            if not is_friend:
                raise HTTPException(status_code=403, detail="对方不是您的好友")

    sender_type = "consultant" if current_role == "consultant" else "user"
    message = await AsyncDatabasePool.execute_one(
        """INSERT INTO messages (conversation_id, role, content, sender_type, sender_id)
           VALUES ($1, 'user', $2, $3, $4)
           RETURNING id, conversation_id, role, content, sender_type, sender_id, created_at""",
        conversation_id, request.content, sender_type, user_id,
    )

    await AsyncDatabasePool.execute_command(
        "UPDATE conversations SET updated_at = NOW() WHERE id = $1",
        conversation_id,
    )

    # 增加接收者的未读计数
    await AsyncDatabasePool.execute_command(
        """INSERT INTO unread_messages (user_id, conversation_id, unread_count, updated_at)
           VALUES ($1, $2, 1, NOW())
           ON CONFLICT (user_id, conversation_id)
           DO UPDATE SET
               unread_count = unread_messages.unread_count + 1,
               updated_at = NOW()""",
        target_user_id, conversation_id,
    )

    # 推送通知（包含完整消息对象，便于前端直接渲染）
    try:
        from common.utils.online_status import add_pending_notification, publish_notification
        sender_name = current_user.get("display_name") or current_user.get("username", "用户")
        notification = {
            "type": "new_message",
            "conversation_id": conversation_id,
            "from_id": user_id,
            "from_name": sender_name,
            "message": {
                "id": str(message["id"]),
                "conversation_id": conversation_id,
                "role": message["role"],
                "content": request.content,
                "sender_type": sender_type,
                "sender_id": user_id,
                "created_at": str(message["created_at"]),
            },
        }
        await add_pending_notification(target_user_id, notification)
        await publish_notification(target_user_id, notification)
    except Exception as e:
        logger.warning(f"发送通知失败: {e}")

    logger.info(f"联系人消息发送成功: conv={conversation_id}, from={user_id}, to={target_user_id}")
    return {"message": dict(message)}
