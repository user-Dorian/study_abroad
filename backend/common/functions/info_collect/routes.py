"""信息收集路由 - AI驱动的信息收集功能
AI主动发起对话，全程引导用户填写表单，自动提取并持久化数据
"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user
from backend.common.functions.info_collect.repository import get_async_student_profile_repo
from backend.common.functions.info_collect.model import (
    STUDENT_FIELDS_META,
    get_missing_fields,
)
from backend.common.functions.info_collect.llm_service import (
    generate_response,
    get_welcome_message,
)

router = APIRouter(prefix="/api/info-collect", tags=["信息收集"])


class ChatRequest(BaseModel):
    """聊天请求"""
    message: Optional[str] = None  # 首次可空（AI主动问候）
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应"""
    session_id: str
    assistant_message: str
    collected_data: Dict[str, Any]
    completion_rate: float
    missing_fields: List[str]
    is_complete: bool


class ChatMessage(BaseModel):
    """聊天消息"""
    role: str
    content: str
    timestamp: datetime


class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    user_id: str
    collected_data: Dict[str, Any]
    completion_rate: float
    missing_fields: List[str]
    is_complete: bool


# 内存会话管理（会话元数据，对话历史存内存，字段数据持久化到DB）
_sessions: Dict[str, Dict[str, Any]] = {}
_history: Dict[str, List[Dict[str, str]]] = {}


def _get_total_fields() -> int:
    """获取总字段数"""
    return len(STUDENT_FIELDS_META)


def _calc_completion(profile: Dict[str, Any]) -> float:
    """计算完成率"""
    if not profile:
        return 0.0
    total = _get_total_fields()
    if total == 0:
        return 100.0
    filled = sum(1 for fn in STUDENT_FIELDS_META
                 if profile.get(fn) is not None and str(profile.get(fn, "")).strip() != "")
    return round(filled / total * 100, 1)


def _get_missing_field_names(profile: Dict[str, Any]) -> List[str]:
    """获取缺失字段名列表"""
    if not profile:
        return list(STUDENT_FIELDS_META.keys())
    missing = []
    for fn, meta in STUDENT_FIELDS_META.items():
        val = profile.get(fn)
        if val is None or str(val).strip() == "":
            missing.append(fn)
    return missing


@router.post("/chat", response_model=ChatResponse)
async def chat_collect(
    request: ChatRequest,
    current_user: dict = Depends(require_user),
):
    """对话式信息收集 - AI主动引导，自动提取字段并持久化

    - 首次调用（message=None）：AI主动问候，开始对话
    - 后续调用：AI根据用户回答提取信息，自然引导
    """
    try:
        user_id = current_user["user_id"]
        repo = get_async_student_profile_repo()

        # ---------- 1. 会话管理 ----------
        if request.session_id and request.session_id in _sessions:
            session = _sessions[request.session_id]
        else:
            # 新会话
            import uuid
            session_id = request.session_id or str(uuid.uuid4())
            session = {
                "session_id": session_id,
                "user_id": user_id,
                "created_at": datetime.utcnow(),
            }
            _sessions[session_id] = session
            _history[session_id] = []

        session_id = session["session_id"]

        # ---------- 2. 从DB加载当前profile ----------
        profile = await repo.get_profile(user_id) or {}

        # ---------- 3. 构造对话历史 ----------
        conv_history = _history.get(session_id, [])

        # ---------- 4. 调用LLM ----------
        ai_message, extracted_fields = await generate_response(
            profile=profile,
            conversation_history=conv_history,
            user_message=request.message,
        )

        # ---------- 5. 保存提取的字段到DB ----------
        if extracted_fields:
            # 合并到profile
            profile.update(extracted_fields)
            # 持久化到DB
            success = await repo.upsert_fields(user_id, extracted_fields)
            if success:
                logger.info(f"字段已持久化: user_id={user_id}, fields={list(extracted_fields.keys())}")
            else:
                logger.warning(f"字段持久化失败: {extracted_fields}")

        # ---------- 6. 保存对话历史 ----------
        if request.message:
            conv_history.append({"role": "user", "content": request.message})
        conv_history.append({"role": "assistant", "content": ai_message})
        _history[session_id] = conv_history

        # ---------- 7. 计算状态 ----------
        completion = _calc_completion(profile)
        missing = _get_missing_field_names(profile)
        is_complete = completion >= 80.0

        logger.info(
            f"信息收集对话: session_id={session_id}, "
            f"completion={completion}%, fields={len(profile)}/"
            f"{_get_total_fields()}, extracted={list(extracted_fields.keys())}"
        )

        return ChatResponse(
            session_id=session_id,
            assistant_message=ai_message,
            collected_data=profile,
            completion_rate=completion,
            missing_fields=missing,
            is_complete=is_complete,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"信息收集对话失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"信息收集对话失败: {str(e)}",
        )


@router.get("/sessions/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取会话信息"""
    try:
        user_id = current_user["user_id"]

        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail="会话不存在")

        repo = get_async_student_profile_repo()
        profile = await repo.get_profile(user_id) or {}

        completion = _calc_completion(profile)
        missing = _get_missing_field_names(profile)

        return SessionInfo(
            session_id=session_id,
            user_id=user_id,
            collected_data=profile,
            completion_rate=completion,
            missing_fields=missing,
            is_complete=completion >= 80.0,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")


@router.get("/sessions/{session_id}/history", response_model=List[ChatMessage])
async def get_chat_history(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取聊天历史"""
    try:
        if session_id not in _sessions:
            raise HTTPException(status_code=404, detail="会话不存在")

        history = _history.get(session_id, [])
        return [
            ChatMessage(role=msg["role"], content=msg["content"], timestamp=datetime.utcnow())
            for msg in history
        ]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取聊天历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取聊天历史失败: {str(e)}")
