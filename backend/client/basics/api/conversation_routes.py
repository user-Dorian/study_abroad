"""会话管理 API 路由

v2 重构：原 `_extract_and_update_student_info` / `_run_rag_node` / `_assemble_summary_context`
/ `_stream_chat_response` / `get_conversation_graph` 等同步支路函数已废弃，
相关逻辑统一由 `backend.client.functions.rag.graph.stream_conversation` 异步图执行。
本文件仅保留 HTTP 路由与会话持久化职责。
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import uuid

from backend.common.functions.conversation.manager import ConversationManager
from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import get_current_user, require_user
from backend.common.functions.info_collect.model import (
    STUDENT_FIELDS_META,
    get_missing_fields,
)

router = APIRouter()

_conversation_manager: ConversationManager = None


# ========== P0-E 修复：UUID 校验辅助函数 ==========
def validate_conversation_id(conv_id: str) -> str:
    """校验对话ID是否为有效UUID格式

    P0-E：无效的本地降级ID（如 _local_xxx / 短ID / 非UUID格式）应当返回 400，
    而不是触发后端 UUID 解析异常导致 500 错误。

    Returns:
        str: 校验通过后的 conv_id

    Raises:
        HTTPException: 400 - 无效的对话ID
    """
    if not conv_id or not isinstance(conv_id, str):
        raise HTTPException(status_code=400, detail="无效的对话ID")

    # 排除本地降级ID（_local_ 前缀 或 长度过短）
    if conv_id.startswith("_local_") or len(conv_id) < 32:
        raise HTTPException(
            status_code=400,
            detail="本地对话ID无效，请刷新页面",
        )

    try:
        uuid.UUID(conv_id)
        return conv_id
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=400, detail="无效的对话ID格式")


def init_conversation_module():
    """初始化会话管理模块"""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
        logger.info("会话管理模块初始化完成")


def get_conversation_manager() -> ConversationManager:
    """获取全局会话管理器实例"""
    if _conversation_manager is None:
        init_conversation_module()
    return _conversation_manager


class CreateConversationRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = None


class RenameConversationRequest(BaseModel):
    """重命名会话请求"""
    title: str


class QueryRequest(BaseModel):
    """查询请求"""
    question: str


class SaveMessageRequest(BaseModel):
    """保存消息请求"""
    role: str
    content: str
    metadata: Optional[dict] = None


class UpdateTitleRequest(BaseModel):
    """修改会话标题请求"""
    title: str


@router.post("/api/conversations")
async def create_conversation(
    request: CreateConversationRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """创建新会话"""
    try:
        title = request.title if request else None
        user_id = current_user.get("user_id") if current_user else None
        conv = get_conversation_manager().create_conversation(title, user_id=user_id)
        return conv
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建会话失败: {str(e)}")


@router.post("/api/conversations/ensure-empty")
async def ensure_empty_conversation(
    current_user: dict = Depends(get_current_user),
):
    """
    确保用户有一个空对话：
    - 已有空对话 → 返回已有的
    - 无空对话 → 新建一个并返回
    每个账号最多只有一个空对话ID
    """
    try:
        user_id = current_user.get("user_id") if current_user else None
        mgr = get_conversation_manager()

        # 查找已有的空对话
        existing = mgr.find_empty_conversation(user_id=user_id) if user_id else None
        if existing:
            logger.info(f"复用已有空对话: id={existing['id']}")
            return existing

        # 没有空对话，新建一个
        conv = mgr.create_conversation(user_id=user_id)
        logger.info(f"新建空对话: id={conv['id']}")
        return conv
    except Exception as e:
        logger.error(f"确保空对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"确保空对话失败: {str(e)}")


@router.get("/api/conversations")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    """获取所有会话列表

    【修复历史问题】chat/AI 对话分离：
    - 旧实现不按 dialogue_type 过滤，导致 contact_chat 联系人对话混入 AI 对话列表。
    - 新实现仅返回 dialogue_type='ai_chat' 的对话（兼容历史 NULL 数据），
      contact_chat 类型由 /api/contact-chat/list 端点独立提供。
    """
    try:
        user_id = current_user.get("user_id") if current_user else None
        # AI 对话列表：仅返回 ai_chat（兼容 NULL），排除 contact_chat
        convs = get_conversation_manager().list_conversations(
            user_id=user_id,
            dialogue_type="ai_chat",
        )
        return convs
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话列表失败: {str(e)}")


@router.get("/api/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单个会话信息"""
    try:
        # P0-E: 校验对话ID为有效UUID
        conversation_id = validate_conversation_id(conversation_id)
        user_id = current_user.get("user_id") if current_user else None
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return conv
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")


@router.put("/api/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    request: RenameConversationRequest,
    current_user: dict = Depends(get_current_user),
):
    """重命名会话"""
    try:
        # P0-E: 校验对话ID为有效UUID
        conversation_id = validate_conversation_id(conversation_id)
        user_id = current_user.get("user_id") if current_user else None
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        success = get_conversation_manager().rename_conversation(conversation_id, request.title)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        return conv
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重命名会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"重命名会话失败: {str(e)}")


@router.delete("/api/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除会话及所有消息"""
    try:
        # P0-E: 校验对话ID为有效UUID
        conversation_id = validate_conversation_id(conversation_id)
        user_id = current_user.get("user_id") if current_user else None
        success = get_conversation_manager().delete_conversation(conversation_id, user_id=user_id)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"success": True, "message": "会话删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除会话失败: {str(e)}")


@router.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """获取会话的消息历史"""
    try:
        # P0-E: 校验对话ID为有效UUID
        conversation_id = validate_conversation_id(conversation_id)
        user_id = current_user.get("user_id") if current_user else None
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = get_conversation_manager().get_messages(conversation_id, limit)
        return messages
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取消息失败: {str(e)}")


@router.post("/api/conversations/{conversation_id}/messages")
async def add_conversation_message(
    conversation_id: str,
    request: SaveMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    """向会话添加一条消息"""
    try:
        # P0-E: 校验对话ID为有效UUID
        conversation_id = validate_conversation_id(conversation_id)
        user_id = current_user.get("user_id") if current_user else None
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        msg = get_conversation_manager().add_message(
            conversation_id=conversation_id,
            role=request.role,
            content=request.content,
            metadata=request.metadata,
        )
        return msg
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存消息失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存消息失败: {str(e)}")


@router.post("/api/conversations/{conversation_id}/query")
async def conversation_query(
    conversation_id: str,
    request: QueryRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    在指定会话中提问（带对话上下文），使用SSE流式返回

    v2 流程：调用 `backend.client.functions.rag.graph.stream_conversation` 异步图，
    内部并行执行意图识别 + 表单填写，并根据意图分支执行多级检索与流式回答生成。
    本端点职责：转发 SSE 事件、解析 answer_chunk 拼接 final_answer、
    记录 student_field_updated 到 metadata、流结束后持久化对话历史。
    """
    # P0-E: 校验对话ID为有效UUID（先校验再执行业务，避免 500）
    conversation_id = validate_conversation_id(conversation_id)
    try:
        user_id = current_user.get("user_id") if current_user else None
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")

    async def generate_events():
        final_answer = ""
        updated_fields = []  # 记录表单字段更新（用于 metadata）

        try:
            # ====== 加载对话历史 ======
            history = get_conversation_manager().get_history_for_llm(conversation_id)
            logger.info(
                f"对话历史加载完成: conversation_id={conversation_id}, "
                f"消息数={len(history)}"
            )

            question = request.question
            logger.info(f"对话查询: conversation_id={conversation_id}, question={question[:50]}")

            # ====== 加载用户 profile ======
            profile = {}
            try:
                if user_id is not None:
                    from backend.common.functions.info_collect.repository import get_async_student_profile_repo
                    repo = get_async_student_profile_repo()
                    profile = await repo.get_profile(str(user_id)) or {}
            except Exception as e:
                logger.warning(f"获取用户profile失败: {e}")
                profile = {}

            # ====== 调用 graph 流程，转发 SSE 事件 ======
            # stream_conversation 已经 yield SSE 格式字符串（"data: {...}\n\n"），直接转发即可
            from backend.client.functions.rag.graph import stream_conversation

            async for sse_chunk in stream_conversation(
                user_id=str(user_id) if user_id is not None else "",
                user_message=question,
                messages=history,
                user_profile=profile,
                session_id=conversation_id,
            ):
                yield sse_chunk

                # 解析 SSE 内容，提取 answer_chunk 和 student_field_updated 事件
                try:
                    if isinstance(sse_chunk, str) and sse_chunk.startswith("data: "):
                        payload_str = sse_chunk[6:].strip()
                        if payload_str:
                            parsed = json.loads(payload_str)
                            evt_type = parsed.get("type")
                            if evt_type == "answer_chunk":
                                final_answer += parsed.get("content", "")
                            elif evt_type == "student_field_updated":
                                field_name = parsed.get("field")
                                if field_name is not None:
                                    updated_fields.append({
                                        "field": field_name,
                                        "value": parsed.get("value"),
                                        "completion_rate": parsed.get("completion_rate"),
                                    })
                except Exception as parse_err:
                    # 解析失败不影响流式输出
                    logger.debug(f"SSE 解析失败（忽略）: {parse_err}")

            # ====== 持久化对话历史 ======
            try:
                get_conversation_manager().add_message(conversation_id, "user", question)
                metadata = {}
                if updated_fields:
                    metadata["updated_fields"] = updated_fields
                get_conversation_manager().add_message(
                    conversation_id, "assistant", final_answer, metadata
                )
            except Exception as e:
                logger.error(f"持久化对话历史失败: {e}")

        except Exception as e:
            logger.error(f"对话查询异常: {e}", exc_info=True)
            error_event = {
                "type": "error",
                "message": "抱歉，系统暂时遇到问题，请稍后重试",
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )


@router.post("/api/conversations/greeting")
async def conversation_greeting(current_user: dict = Depends(get_current_user)):
    """新建对话AI主动问候端点

    解决问题：新建对话后AI不主动问候，且必填字段不填写。

    流程：
    1. 查找已有空对话；若无则新建
    2. 异步加载用户profile
    3. 调用 generate_response(user_message=None) 生成问候语
    4. 若LLM从历史上下文提取到字段，持久化到DB
    5. 把问候语保存为新会话的首条 assistant 消息（metadata.type=greeting）
    6. 计算 completion_rate = filled_count / total_count * 100（保留1位小数）
    7. 返回 JSON 响应（字段名严格按契约）

    兜底：LLM调用失败时使用 get_welcome_message() 作为问候语。
    """
    try:
        user_id = current_user.get("user_id") if current_user else None
        mgr = get_conversation_manager()

        # 1. 查找已有空对话；若无则新建
        conv = mgr.find_empty_conversation(user_id=user_id) if user_id else None
        if not conv:
            conv = mgr.create_conversation(user_id=user_id)
        conv_id = conv["id"]
        logger.info(f"问候端点: 准备对话 conv_id={conv_id}, user_id={user_id}")

        # 检查该会话是否已有问候消息（检查 metadata.type === 'greeting'）
        existing_messages = mgr.get_messages(conv_id, limit=10)
        for msg in existing_messages:
            metadata = msg.get("metadata") or {}
            if metadata.get("type") == "greeting":
                logger.info(f"问候端点: 会话已有问候消息，跳过重复生成")
                # 直接返回现有会话信息（不重新生成问候）
                return {
                    "conversation_id": conv_id,
                    "greeting_message": "",  # 前端应检查此字段为空时不渲染新消息
                    "profile": profile,
                    "completion_rate": 0.0,
                    "missing_fields": [],
                }

        # 2. 异步加载用户 profile
        repo = None
        profile: dict = {}
        try:
            if user_id is not None:
                from backend.common.functions.info_collect.repository import (
                    get_async_student_profile_repo,
                )
                repo = get_async_student_profile_repo()
                loaded = await repo.get_profile(str(user_id))
                profile = loaded or {}
        except Exception as e:
            logger.warning(f"问候端点: 加载profile失败: {e}")
            profile = {}

        # 3. 调用LLM生成问候语（user_message=None 触发问候语生成）
        greeting_message: str = ""
        extracted_fields: dict = {}
        try:
            from backend.common.functions.info_collect.llm_service import generate_response
            greeting_message, extracted_fields = await generate_response(
                profile=profile,
                conversation_history=[],
                user_message=None,
            )
        except Exception as e:
            logger.error(f"问候端点: LLM生成问候语失败，使用兜底: {e}", exc_info=True)
            from backend.common.functions.info_collect.llm_service import get_welcome_message
            greeting_message = get_welcome_message()
            extracted_fields = {}

        # 4. 持久化提取到的字段（若有）
        if extracted_fields and repo is not None and user_id is not None:
            try:
                await repo.upsert_fields(str(user_id), extracted_fields)
                profile = {**profile, **extracted_fields}
                logger.info(
                    f"问候端点: 已持久化提取字段: {list(extracted_fields.keys())}"
                )
            except Exception as e:
                logger.warning(f"问候端点: 持久化字段失败: {e}")

        # 5. 把问候语保存为新会话的首条 assistant 消息
        try:
            mgr.add_message(
                conversation_id=conv_id,
                role="assistant",
                content=greeting_message,
                metadata={"type": "greeting"},
            )
        except Exception as e:
            logger.warning(f"问候端点: 保存问候语到对话失败: {e}")

        # 6. 计算 completion_rate
        try:
            total_count = len(STUDENT_FIELDS_META)
            filled_count = sum(
                1
                for k in STUDENT_FIELDS_META
                if profile.get(k) is not None and str(profile.get(k)).strip() != ""
            )
            completion_rate = (
                round(filled_count / total_count * 100, 1) if total_count else 0.0
            )
        except Exception as e:
            logger.warning(f"问候端点: 计算完整度失败: {e}")
            completion_rate = 0.0

        # 7. 返回JSON响应（字段名严格按契约）
        missing_fields = [item["field"] for item in get_missing_fields(profile)]

        return {
            "conversation_id": conv_id,
            "greeting_message": greeting_message,
            "profile": profile,
            "completion_rate": completion_rate,
            "missing_fields": missing_fields,
        }
    except Exception as e:
        logger.error(f"问候端点异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成问候失败: {str(e)}")


@router.post("/api/conversations/{conv_id}/generate-title")
async def generate_conversation_title(
    conv_id: str,
    current_user: dict = Depends(get_current_user),
):
    """根据对话内容智能生成会话标题

    触发时机：对话轮数达到2轮（即用户+AI各发言2次）
    """
    try:
        mgr = get_conversation_manager()
        conv_id = validate_conversation_id(conv_id)

        # 获取对话历史
        messages = mgr.get_messages(conv_id, limit=10)

        if not messages or len(messages) < 2:
            return {"conversation_id": conv_id, "title": "新对话", "generated": False}

        # 提取前几轮对话内容（用于生成标题）
        history_text = ""
        for msg in messages[:4]:  # 只取前4条（约2轮）
            role = msg.get("role", "user")
            content = msg.get("content", "")
            history_text += f"{role}: {content[:100]}\n"

        # 调用LLM生成标题
        try:
            from backend.common.functions.rag.models.llm_client import llm_client
            from backend.common.functions.rag.rag_config import RAGConfig

            prompt = f"""请根据以下对话内容，生成一个简洁的会话标题（10字以内）：

对话内容：
{history_text}

要求：
1. 标题简洁，突出对话主题（如"美国F1签证咨询"、"香港AI硕士申请"）
2. 长度控制在10字以内
3. 只输出标题，不要其他内容

标题："""

            result = await llm_client.async_chat(
                messages=[{"role": "user", "content": prompt}],
                model=RAGConfig.INTENT_MODEL_NAME,
                temperature=0.3,
                max_tokens=20,
            )

            title = result.strip().strip('"').strip("'")[:20]  # 截断过长标题

        except Exception as e:
            logger.warning(f"LLM生成标题失败: {e}，使用兜底标题")
            title = "留学咨询"

        # 更新数据库中的标题
        try:
            mgr.update_conversation_title(conv_id, title)
            logger.info(f"生成会话标题成功: conv_id={conv_id}, title={title}")
        except Exception as e:
            logger.warning(f"更新标题失败: {e}")

        return {"conversation_id": conv_id, "title": title, "generated": True}

    except Exception as e:
        logger.error(f"生成会话标题异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成标题失败: {str(e)}")


@router.patch("/api/conversations/{conv_id}/title")
async def update_conversation_title(
    conv_id: str,
    request: UpdateTitleRequest,
    current_user: dict = Depends(get_current_user),
):
    """手动修改会话标题"""
    try:
        mgr = get_conversation_manager()
        conv_id = validate_conversation_id(conv_id)

        title = request.title.strip()[:50]  # 限制长度
        if not title:
            raise HTTPException(status_code=400, detail="标题不能为空")

        mgr.update_conversation_title(conv_id, title)
        logger.info(f"修改会话标题成功: conv_id={conv_id}, title={title}")

        return {"conversation_id": conv_id, "title": title}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改会话标题异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修改标题失败: {str(e)}")
