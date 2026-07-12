"""规划师端联系人管理 API 路由 - 联系人搜索、绑定、对话等"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional

from consultant.api.auth_routes import _get_current_user_from_header
from common.consultant.repository import get_consultant_relation_repo
from common.friendship.repository import get_friendship_repo
from common.conversation.repository import AsyncMessageRepository
from common.config.async_database import AsyncDatabasePool
from common.config.async_redis import AsyncRedisPool
from common.utils.logger import logger
from common.utils.online_status import (
    batch_check_online, add_pending_notification, 
    get_pending_notifications, publish_notification,
)
from common.utils.binding_verification import verify_planner_user_binding

router = APIRouter()

# 异步消息仓库单例
_message_repo = None


def _get_message_repo() -> AsyncMessageRepository:
    global _message_repo
    if _message_repo is None:
        _message_repo = AsyncMessageRepository()
    return _message_repo


def _ensure_utc_iso(dt) -> str:
    """确保 datetime 转为带 UTC 时区标识的 ISO 字符串"""
    if hasattr(dt, 'isoformat'):
        if dt.tzinfo is None:
            return dt.isoformat() + "+00:00"
        return dt.isoformat()
    return str(dt)


class SearchUserRequest(BaseModel):
    """搜索用户请求"""
    keyword: str
    find_mode: bool = False  # False=添加模式（默认）, True=查找模式


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content: str


# ============================================================
# 0. 获取通讯录联系人（带筛选功能）
# ============================================================
@router.get("/api/consultant/contacts")
async def get_contacts(
    filter_type: str = Query(
        default="all",
        description="筛选类型: all=全部联系人, bound=已绑定用户, unbound=未绑定用户"
    ),
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取规划师的通讯录联系人列表，支持按绑定状态筛选

    功能说明：
    - filter_type=all：返回全部好友联系人
    - filter_type=bound：返回已绑定用户（在consultant_relations表中）
    - filter_type=unbound：返回未绑定用户（好友但未绑定）

    篮选参数无效时自动降级为返回全部联系人（增强系统健壮性）

    返回数据格式：
    {
      "contacts": [
        {
          "user_id": "xxx",
          "username": "张三",
          "display_name": "张三",
          "avatar_url": "...",
          "is_bound": true,
          "bound_at": "2024-01-01"
        }
      ]
    }
    """
    friendship_repo = get_friendship_repo()
    consultant_id = current_user["user_id"]

    # 调用筛选方法获取联系人列表
    contacts = await friendship_repo.get_contacts_with_binding_status(
        consultant_id=consultant_id,
        filter_type=filter_type
    )

    logger.info(
        f"[规划师端通讯录] consultant_id={consultant_id}, "
        f"filter_type={filter_type}, 结果数={len(contacts)}"
    )

    return {"contacts": contacts}


# ============================================================
# 1. 搜索用户
# ============================================================
@router.post("/api/consultant/users/search")
async def search_users(
    request: SearchUserRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """搜索用户（按用户名、电话或显示名模糊匹配）

    根据 find_mode 参数区分两种搜索模式：
    - find_mode=False（默认，添加模式）: 搜索可绑定的用户
      只返回未绑定任何规划师的普通用户（role='client' 或 NULL）
    - find_mode=True（查找模式）: 搜索已绑定的用户
      只返回当前规划师已绑定的客户
    """
    repo = get_consultant_relation_repo()
    consultant_id = current_user["user_id"]
    users = await repo.search_users(
        request.keyword,
        consultant_id,
        find_mode=request.find_mode
    )

    mode_desc = "查找模式（已绑定用户）" if request.find_mode else "添加模式（可绑定用户）"
    logger.info(
        f"[规划师端] 搜索用户 [{mode_desc}]: keyword={request.keyword}, "
        f"consultant_id={consultant_id}, 结果数={len(users)}"
    )
    return {"users": users}


# ============================================================
# 2. 绑定用户（添加为联系人）
# ============================================================
@router.post("/api/consultant/users/{user_id}/bind")
async def bind_user(
    user_id: str,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """绑定用户为联系人，成功后自动创建联系人对话"""
    repo = get_consultant_relation_repo()
    consultant_id = current_user["user_id"]

    # 检查是否已绑定
    exists = await repo.check_relation_exists(consultant_id, user_id)
    if exists:
        raise HTTPException(status_code=409, detail="该用户已是您的联系人")

    # 创建绑定关系
    try:
        relation = await repo.create_relation(consultant_id, user_id)
    except Exception as e:
        error_msg = str(e)
        if "check_consultant_not_self" in error_msg:
            raise HTTPException(status_code=400, detail="不能绑定自己")
        if "unique_active_user_relation" in error_msg:
            raise HTTPException(status_code=409, detail="该用户已有活跃规划师")
        logger.error(f"[规划师端] 绑定用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"绑定失败: {str(e)}")

    # 自动创建联系人对话（规划师作为 user_id，客户作为 other_user_id）
    conversation = None
    try:
        conversation = await repo.create_contact_conversation(
            user_id=consultant_id,
            other_user_id=user_id,
            title=f"联系人-{user_id}",
        )
    except Exception as e:
        logger.warning(f"[规划师端] 绑定后创建联系人对话失败: {e}")

    # 发送绑定通知给用户（在线则实时推送，离线则存为待处理）
    try:
        consultant_name = current_user.get("username", "规划师")
        notification = {
            "type": "planner_bind",
            "planner_id": consultant_id,
            "planner_name": consultant_name,
            "message": f"规划师 {consultant_name} 已将您添加为联系人，可以开始咨询了！",
        }
        # 同时尝试实时通知和持久化通知
        await add_pending_notification(user_id, notification)
        await publish_notification(user_id, notification)
    except Exception as e:
        logger.warning(f"[规划师端] 发送绑定通知失败: {e}")

    logger.info(
        f"[规划师端] 绑定用户成功: consultant={consultant_id}, "
        f"user={user_id}"
    )
    return {"relation": relation, "conversation": conversation}


# ============================================================
# 3. 获取客户列表
# ============================================================
@router.get("/api/consultant/clients")
async def list_clients(
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取当前规划师的所有活跃客户列表（含在线状态）"""
    repo = get_consultant_relation_repo()
    consultant_id = current_user["user_id"]
    clients = await repo.list_clients_by_consultant(consultant_id)

    # 批量查询在线状态
    user_ids = [c["user_id"] for c in clients]
    online_status = await batch_check_online(user_ids) if user_ids else {}
    for client in clients:
        client["online"] = online_status.get(client["user_id"], False)

    logger.info(f"[规划师端] 获取客户列表: 共 {len(clients)} 条")
    return {"clients": clients}


# ============================================================
# 4. 解除绑定
# ============================================================
@router.post("/api/consultant/clients/{relation_id}/unbind")
async def unbind_client(
    relation_id: str,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """解除与指定客户的绑定关系（软删除，设置 status=inactive）"""
    repo = get_consultant_relation_repo()
    consultant_id = current_user["user_id"]
    success = await repo.unbind_relation(relation_id, consultant_id)
    if not success:
        raise HTTPException(status_code=404, detail="关系不存在或已解除")
    logger.info(f"[规划师端] 解除绑定成功: relation_id={relation_id}")
    return {"success": True}


# ============================================================
# 5. 获取与客户的联系人对话
# ============================================================
@router.get("/api/consultant/clients/{client_id}/conversation")
async def get_client_conversation(
    client_id: str,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取与指定客户的联系人对话，不存在则自动创建"""
    repo = get_consultant_relation_repo()
    consultant_id = current_user["user_id"]

    # 验证绑定关系
    exists = await repo.check_relation_exists(consultant_id, client_id)
    if not exists:
        raise HTTPException(status_code=404, detail="该用户不是您的联系人")

    # 查找已有对话
    conversation = await repo.find_contact_conversation(consultant_id, client_id)
    if conversation is None:
        # 不存在则创建
        conversation = await repo.create_contact_conversation(
            user_id=consultant_id,
            other_user_id=client_id,
            title=f"联系人-{client_id}",
        )
        logger.info(
            f"[规划师端] 为客户创建新联系人对话: "
            f"consultant={consultant_id}, client={client_id}"
        )

    return {"conversation": conversation}


# ============================================================
# 6. 发送消息给联系人
# ============================================================
@router.post("/api/consultant/conversations/{conversation_id}/messages")
async def send_contact_message(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """向联系人对话发送消息，sender_type 固定为 'consultant'
    
    通信限制：
    - 验证对话归属：确保对话属于当前规划师
    - 验证绑定关系：确保对话对方是已绑定用户
    """
    repo = get_consultant_relation_repo()
    consultant_id = current_user["user_id"]

    # 验证对话归属和绑定关系
    try:
        # 查询对话信息
        conv_sql = (
            "SELECT id, user_id, other_user_id, dialogue_type "
            "FROM conversations WHERE id = $1 LIMIT 1"
        )
        conv_row = await AsyncDatabasePool.execute_one(conv_sql, conversation_id)
        
        if not conv_row:
            raise HTTPException(status_code=404, detail="对话不存在")
        
        # 验证对话属于当前规划师
        conv_user_id = str(conv_row["user_id"])
        conv_other_user_id = str(conv_row["other_user_id"]) if conv_row["other_user_id"] else None
        
        if conv_user_id != consultant_id and conv_other_user_id != consultant_id:
            logger.warning(
                f"[通信限制] 规划师尝试访问非自己的对话: "
                f"consultant_id={consultant_id}, conversation_id={conversation_id}"
            )
            raise HTTPException(status_code=403, detail="无权向此对话发送消息")
        
        # 确定对方用户ID（绑定验证的目标）
        target_user_id = conv_other_user_id if conv_user_id == consultant_id else conv_user_id
        
        if not target_user_id:
            raise HTTPException(status_code=400, detail="对话对方用户不存在")
        
        # 验证规划师是否绑定了该用户
        await verify_planner_user_binding(consultant_id, target_user_id)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 验证对话归属失败: {e}")
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")

    # 保存消息
    try:
        message = await repo.save_contact_message(
            conversation_id=conversation_id,
            sender_id=consultant_id,
            sender_type="consultant",
            content=request.content,
        )
        logger.info(
            f"[规划师端] 发送消息成功: conversation_id={conversation_id}, "
            f"consultant_id={consultant_id}, target_user_id={target_user_id}"
        )
        
        # 发送消息通知给用户
        try:
            consultant_name = current_user.get("display_name") or current_user.get("username", "规划师")
            notification = {
                "type": "new_message",
                "conversation_id": conversation_id,
                "from_id": consultant_id,
                "from_name": consultant_name,
                "message": request.content[:50] + ("..." if len(request.content) > 50 else ""),
            }
            await add_pending_notification(target_user_id, notification)
            await publish_notification(target_user_id, notification)
            logger.info(f"[规划师端] 已发送消息通知给用户: user_id={target_user_id}")
        except Exception as notify_err:
            logger.warning(f"[规划师端] 发送消息通知失败: {notify_err}")
    except Exception as e:
        logger.error(f"[规划师端] 发送联系人消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")

    return {"message": message}


# ============================================================
# 7. 获取联系人对话消息列表
# ============================================================
@router.get("/api/consultant/conversations/{conversation_id}/messages")
async def get_contact_messages(
    conversation_id: str,
    limit: int = 50,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取联系人对话的消息列表，按时间升序排列"""
    msg_repo = _get_message_repo()
    try:
        messages = await msg_repo.get_messages(conversation_id, limit)
    except Exception as e:
        logger.error(f"[规划师端] 获取联系人消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取消息失败: {str(e)}")

    return {"messages": messages}


# ============================================================
# 8. 获取联系人对话列表（所有与客户的对话，附带对方信息）
# ============================================================
# ============================================================
# 9. 获取用户端待处理通知（用户端轮询用）
# ============================================================
@router.get("/api/consultant/notifications/pending")
async def get_user_pending_notifications(
    target_user_id: str,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取指定用户的待处理通知（用于用户端轮询）"""
    try:
        notifications = await get_pending_notifications(target_user_id)
        return {"notifications": notifications}
    except Exception as e:
        logger.error(f"[规划师端] 获取待处理通知失败: {e}")
        return {"notifications": []}


# ============================================================
# 10. 用户端轮询通知 API（无认证，通过 user_id + token 方式验证）
# ============================================================
@router.get("/api/notifications/poll")
async def poll_notifications(current_user: dict = Depends(_get_current_user_from_header)):
    """轮询当前用户的待处理通知（双端共用）"""
    try:
        user_id = current_user.get("user_id") or current_user.get("sub")
        if not user_id:
            return {"notifications": []}
        notifications = await get_pending_notifications(user_id)
        return {"notifications": notifications}
    except Exception as e:
        logger.error(f"轮询通知失败: {e}")
        return {"notifications": []}


@router.get("/api/consultant/contact-conversations")
async def list_contact_conversations(
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取所有联系人对话列表，每个对话附带对方用户信息

    从 conversations 表中查询当前规划师作为 user_id 或 other_user_id
    且 dialogue_type='contact_chat' 的对话，并通过 JOIN 获取对方用户名和显示名。

    【修复历史问题】移除 consultant_relations 子查询过滤：
    - 旧实现要求"对方必须是已绑定的客户"才能出现在列表中，
      导致客户端可以看到的联系人，企业端却看不到。
    - 新实现只要 consultant 是对话参与方（user_id 或 other_user_id 是他），
      就返回该 contact_chat 对话，与客户端的同源逻辑保持一致。
    - 实际"是否已绑定"的过滤由 /api/consultant/contacts 端点按 filter_type 控制，
      联系人对话列表本身不再卡 consultant_relations。
    """
    consultant_id = current_user["user_id"]

    try:
        sql = (
            "SELECT c.id, c.title, c.user_id, c.other_user_id, "
            "       c.dialogue_type, c.created_at, c.updated_at, "
            "       u.id AS other_id, u.username AS other_username, "
            "       u.display_name AS other_display_name "
            "FROM conversations c "
            "LEFT JOIN users u ON u.id = CASE "
            "  WHEN c.user_id = $1 THEN c.other_user_id "
            "  ELSE c.user_id "
            "END "
            "WHERE c.dialogue_type = 'contact_chat' "
            "  AND (c.user_id = $1 OR c.other_user_id = $1) "
            "ORDER BY c.updated_at DESC"
        )
        rows = await AsyncDatabasePool.execute_query(sql, consultant_id)
    except Exception as e:
        logger.error(f"[规划师端] 获取联系人对话列表失败: {e}")
        raise HTTPException(
            status_code=500, detail=f"获取对话列表失败: {str(e)}"
        )

    conversations = []
    other_ids = []
    for row in rows:
        if str(row["user_id"]) == consultant_id:
            other_id = str(row["other_user_id"]) if row["other_user_id"] else None
        else:
            other_id = str(row["user_id"])
        if other_id:
            other_ids.append(other_id)

    # 批量查询在线状态
    online_status = await batch_check_online(other_ids) if other_ids else {}

    for row in rows:
        if str(row["user_id"]) == consultant_id:
            other_id = str(row["other_user_id"]) if row["other_user_id"] else None
        else:
            other_id = str(row["user_id"])

        conversations.append({
            "id": str(row["id"]),
            "title": row["title"],
            "user_id": str(row["user_id"]),
            "other_user_id": (
                str(row["other_user_id"]) if row["other_user_id"] else None
            ),
            "dialogue_type": row["dialogue_type"],
            "created_at": _ensure_utc_iso(row["created_at"]),
            "updated_at": _ensure_utc_iso(row["updated_at"]),
            "other_user": {
                "user_id": other_id,
                "username": row.get("other_username"),
                "display_name": row.get("other_display_name"),
                "online": online_status.get(other_id, False) if other_id else False,
            },
        })

    return {"conversations": conversations}
