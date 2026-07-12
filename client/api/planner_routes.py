"""我的规划师 API 路由"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from common.utils.auth import require_user
from common.utils.logger import logger
from common.utils.online_status import is_online, get_pending_notifications
from common.consultant.repository import get_consultant_relation_repo
from common.conversation.repository import AsyncMessageRepository
from common.config.async_database import AsyncDatabasePool

router = APIRouter(prefix="/api/planner", tags=["planner"])


# ====== Pydantic 请求/响应模型 ======

class SendMessageRequest(BaseModel):
    """发送消息请求"""
    content: str = Field(..., min_length=1, max_length=10000, description="消息内容")


class PlannerInfo(BaseModel):
    """规划师信息"""
    id: str
    name: Optional[str] = None
    username: Optional[str] = None
    created_at: str


class PlannerResponse(BaseModel):
    """获取规划师响应"""
    planner: Optional[PlannerInfo] = None


class ConversationMessage(BaseModel):
    """对话消息"""
    id: str
    conversation_id: str
    role: str
    content: str
    sender_type: Optional[str] = None
    created_at: str


class MessagesResponse(BaseModel):
    """消息列表响应"""
    messages: List[ConversationMessage]


class UpdatePhoneRequest(BaseModel):
    """更新手机号请求"""
    phone: str = Field(..., description="手机号")


# ====== 路由实现 ======

@router.get("/my-planner", response_model=PlannerResponse)
async def get_my_planner(current_user: dict = Depends(require_user)):
    """
    获取当前用户绑定的规划师信息

    返回当前用户活跃的规划师绑定关系，
    如果未绑定规划师则返回 planner=null。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_consultant_relation_repo()

        relation = await repo.get_active_relation_by_user(user_id)
        if relation is None:
            logger.info(f"用户未绑定规划师: user_id={user_id}")
            return PlannerResponse(planner=None)

        planner = PlannerInfo(
            id=relation["consultant_id"],
            name=relation.get("consultant_name"),
            username=relation.get("consultant_username"),
            created_at=relation["created_at"],
        )
        logger.info(f"获取规划师信息成功: user_id={user_id}, planner_id={planner.id}")
        return PlannerResponse(planner=planner)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取规划师信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取规划师信息失败: {str(e)}")


@router.get("/conversation")
async def get_planner_conversation(current_user: dict = Depends(require_user)):
    """
    获取与规划师的对话

    查找当前用户与规划师之间的联系人对话（dialogue_type='contact_chat'）。
    如果对话不存在则自动创建一个。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_consultant_relation_repo()

        # 先获取用户的规划师关系
        relation = await repo.get_active_relation_by_user(user_id)
        if relation is None:
            raise HTTPException(status_code=404, detail="您尚未绑定规划师")

        consultant_id = relation["consultant_id"]

        # 查找已有的联系人对话
        conversation = await repo.find_contact_conversation(user_id, consultant_id)
        if conversation is not None:
            logger.info(f"找到已有规划师对话: conv_id={conversation['id']}")
            return {"conversation": conversation}

        # 不存在则创建新的联系人对话
        consultant_name = relation.get("consultant_name") or relation.get("consultant_username") or "规划师"
        title = f"与{consultant_name}的对话"
        conversation = await repo.create_contact_conversation(user_id, consultant_id, title=title)
        logger.info(f"创建规划师对话成功: conv_id={conversation['id']}")
        return {"conversation": conversation}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取规划师对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取规划师对话失败: {str(e)}")


@router.post("/conversations/{conversation_id}/messages")
async def send_message_to_planner(
    conversation_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(require_user),
):
    """
    发送消息给规划师

    sender_type 固定为 'user'，表示当前用户发送消息。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_consultant_relation_repo()

        # 验证规划师关系存在
        relation = await repo.get_active_relation_by_user(user_id)
        if relation is None:
            raise HTTPException(status_code=404, detail="您尚未绑定规划师")

        # 验证对话归属（确保对话属于当前用户与规划师之间）
        conversation = await repo.find_contact_conversation(user_id, relation["consultant_id"])
        if conversation is None or conversation["id"] != conversation_id:
            raise HTTPException(status_code=403, detail="无权向此对话发送消息")

        # 保存消息
        message = await repo.save_contact_message(
            conversation_id=conversation_id,
            sender_id=user_id,
            sender_type="user",
            content=request.content,
        )
        logger.info(f"发送消息给规划师成功: conv_id={conversation_id}, user_id={user_id}")
        return {"message": message}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送消息给规划师失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送消息失败: {str(e)}")


@router.get("/conversations/{conversation_id}/messages", response_model=MessagesResponse)
async def get_planner_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200, description="返回消息条数上限"),
    current_user: dict = Depends(require_user),
):
    """
    获取与规划师的对话消息

    返回指定对话中的消息列表，按创建时间升序排列。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_consultant_relation_repo()

        # 验证规划师关系存在
        relation = await repo.get_active_relation_by_user(user_id)
        if relation is None:
            raise HTTPException(status_code=404, detail="您尚未绑定规划师")

        # 验证对话归属
        conversation = await repo.find_contact_conversation(user_id, relation["consultant_id"])
        if conversation is None or conversation["id"] != conversation_id:
            raise HTTPException(status_code=403, detail="无权访问此对话")

        # 获取消息
        msg_repo = AsyncMessageRepository()
        messages = await msg_repo.get_messages(conversation_id, limit=limit)
        logger.info(f"获取规划师对话消息成功: conv_id={conversation_id}, count={len(messages)}")
        return MessagesResponse(messages=messages)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取规划师对话消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取消息失败: {str(e)}")


def _mask_phone(phone: str) -> str:
    """脱敏手机号，显示前3位和后4位"""
    if phone and len(phone) == 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone


# ====== 手机号相关 API ======


@router.put("/profile/phone")
async def update_phone(request: UpdatePhoneRequest, current_user: dict = Depends(require_user)):
    """
    更新当前用户的手机号

    验证手机号格式（11位数字），更新 users 表的 phone 字段。
    """
    try:
        phone = request.phone.strip()
        if not phone.isdigit() or len(phone) != 11:
            raise HTTPException(status_code=400, detail="手机号格式不正确，请输入11位数字")

        user_id = current_user["user_id"]
        await AsyncDatabasePool.execute_command(
            "UPDATE users SET phone = $1 WHERE id = $2",
            phone, user_id,
        )
        logger.info(f"手机号更新成功: user_id={user_id}, phone={_mask_phone(phone)}")
        return {"success": True, "phone": _mask_phone(phone)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手机号更新失败: user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"手机号更新失败: {str(e)}")


@router.get("/planner-online")
async def get_planner_online(current_user: dict = Depends(require_user)):
    """
    获取当前用户的规划师是否在线
    """
    try:
        user_id = current_user["user_id"]
        repo = get_consultant_relation_repo()
        relation = await repo.get_active_relation_by_user(user_id)

        if relation is None:
            logger.info(f"用户未绑定规划师: user_id={user_id}")
            return {"online": False, "error": "未绑定规划师"}

        consultant_id = relation["consultant_id"]
        online = await is_online(consultant_id)
        logger.info(f"查询规划师在线状态: consultant_id={consultant_id}, online={online}")
        return {"online": online}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询规划师在线状态失败: user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"查询规划师在线状态失败: {str(e)}")


@router.get("/search-planners")
async def search_planners(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    current_user: dict = Depends(require_user),
):
    """
    搜索可添加的规划师（用户端）
    只返回 role='consultant' 且未与当前用户绑定的规划师
    """
    try:
        user_id = current_user["user_id"]
        sql = """
            SELECT u.id, u.username, u.display_name, u.phone
            FROM users u
            WHERE u.role = 'consultant'
              AND u.id != $1
              AND (u.username ILIKE $2 OR u.phone ILIKE $2 OR u.display_name ILIKE $2)
              AND u.id NOT IN (
                SELECT cr.consultant_id FROM consultant_relations cr
                WHERE cr.user_id = $1 AND cr.status = 'active'
              )
              AND u.id NOT IN (
                SELECT cr.user_id FROM consultant_relations cr
                WHERE cr.consultant_id = $1 AND cr.status = 'active'
              )
            LIMIT 20
        """
        pattern = f"%{keyword}%"
        rows = await AsyncDatabasePool.execute_query(sql, user_id, pattern)
        planners = []
        for row in rows:
            planners.append({
                "id": str(row["id"]),
                "username": row["username"],
                "display_name": row["display_name"],
                "phone": row["phone"],
            })
        logger.info(f"用户搜索规划师: keyword={keyword}, 结果数={len(planners)}")
        return {"planners": planners}
    except Exception as e:
        logger.error(f"搜索规划师失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.get("/notifications")
async def get_notifications(current_user: dict = Depends(require_user)):
    """
    轮询当前用户的待处理通知

    从 Redis 中取出所有待处理通知并返回。
    """
    try:
        user_id = current_user["user_id"]
        notifications = await get_pending_notifications(user_id)
        logger.info(f"获取待处理通知: user_id={user_id}, count={len(notifications)}")
        return {"notifications": notifications}

    except Exception as e:
        logger.error(f"获取待处理通知失败: user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"获取通知失败: {str(e)}")
