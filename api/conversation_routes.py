"""会话管理 API 路由"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import asyncio

from common.utils.sse import sse_event
from conversation.manager import ConversationManager
from conversation.graph import ConversationGraph
from conversation.config import ConversationConfig
from api.routes import get_query_handler
from utils.logger import logger
from utils.auth import get_current_user, require_user
from user_profile.message_helper import load_user_context_text
# 阶段2数据库异步化：导入 asyncpg 异步仓库类
from common.conversation.repository import AsyncConversationRepository, AsyncMessageRepository

router = APIRouter()

_conversation_manager: ConversationManager = None
_conversation_graph: ConversationGraph = None

# 阶段2数据库异步化：全局异步仓库单例（无状态，全局复用）
_async_conv_repo = AsyncConversationRepository()
_async_msg_repo = AsyncMessageRepository()


def init_conversation_module():
    """初始化会话管理模块"""
    global _conversation_manager, _conversation_graph
    if _conversation_manager is None:
        _conversation_manager = ConversationManager()
        _conversation_graph = ConversationGraph(_conversation_manager)
        logger.info("会话管理模块初始化完成")


def get_conversation_manager() -> ConversationManager:
    """获取全局会话管理器实例"""
    if _conversation_manager is None:
        init_conversation_module()
    return _conversation_manager


def get_conversation_graph() -> ConversationGraph:
    """获取全局对话图实例"""
    if _conversation_graph is None:
        init_conversation_module()
    return _conversation_graph


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


@router.post("/api/conversations")
async def create_conversation(
    request: CreateConversationRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """创建新会话"""
    try:
        title = request.title if request else None
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        # title 为 None 时使用默认标题（与 ConversationManager.create_conversation 行为一致）
        if title is None:
            title = ConversationConfig.DEFAULT_TITLE
        conv = await _async_conv_repo.create_conversation(title, user_id=user_id)
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

        # 查找已有的空对话（阶段2数据库异步化：调用 asyncpg 异步仓库）
        existing = await _async_conv_repo.find_empty_conversation(user_id=user_id) if user_id else None
        if existing:
            logger.info(f"复用已有空对话: id={existing['id']}")
            return existing

        # 没有空对话，新建一个（阶段2数据库异步化：调用 asyncpg 异步仓库，使用默认标题）
        conv = await _async_conv_repo.create_conversation(ConversationConfig.DEFAULT_TITLE, user_id=user_id)
        logger.info(f"新建空对话: id={conv['id']}")
        return conv
    except Exception as e:
        logger.error(f"确保空对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"确保空对话失败: {str(e)}")


@router.get("/api/conversations")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    """获取所有会话列表"""
    try:
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        convs = await _async_conv_repo.list_conversations(user_id=user_id)
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
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        conv = await _async_conv_repo.get_conversation(conversation_id, user_id=user_id)
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
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        conv = await _async_conv_repo.get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        success = await _async_conv_repo.update_title(conversation_id, request.title)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        conv = await _async_conv_repo.get_conversation(conversation_id, user_id=user_id)
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
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        success = await _async_conv_repo.delete_conversation(conversation_id, user_id=user_id)
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
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        conv = await _async_conv_repo.get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = await _async_msg_repo.get_messages(conversation_id, limit)
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
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：会话验证改为 asyncpg 异步仓库
        conv = await _async_conv_repo.get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        # 阶段2数据库异步化：DB 部分（save_message + update_timestamp）用 asyncpg 异步仓库，
        # 不再用 asyncio.to_thread 包装同步仓库；自动标题生成涉及 LLM 调用，保留同步线程包装
        msg = await _async_msg_repo.save_message(
            conversation_id=conversation_id,
            role=request.role,
            content=request.content,
            metadata=request.metadata,
        )
        await _async_conv_repo.update_timestamp(conversation_id)
        # 自动标题生成（涉及 LLM 调用，保持同步线程包装；失败不影响主流程）
        if request.role == "user":
            await asyncio.to_thread(
                get_conversation_manager()._auto_generate_title,
                conversation_id,
                request.content,
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
    
    新流程：
    1. 加载对话历史
    2. 意图识别：判断是否需要检索
    3. 不需要检索 → 直接【历史 + 问题】→ LLM回答（不写Redis）
    4. 需要检索 → 检索链获取上下文（Redis→SQL→RAG）
         → 检索结果来自SQL则写入Redis（只缓存检索结果）
         → 【历史 + 检索上下文 + 问题】→ LLM回答（不写Redis）
    """
    try:
        user_id = current_user.get("user_id") if current_user else None
        # 阶段2数据库异步化：会话验证改为 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        conv = await _async_conv_repo.get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")

    handler = get_query_handler()

    async def generate_events():
        # 阶段6改造说明：
        # 流式输出已移除 threading.Thread + queue.Queue，改用原生 async for chunk in llm_client.async_chat_stream(...)。
        # 已移除所有不必要的 await asyncio.sleep(0) 调用。
        execution_path = []
        final_answer = ""

        # ====== 步骤0: 加载对话历史 ======
        step_loading = {"step": 0, "name": "加载对话历史", "status": "running", "detail": "正在加载对话历史..."}
        yield f"data: {json.dumps(step_loading, ensure_ascii=False)}\n\n"

        try:
            history = get_conversation_manager().get_history_for_llm(conversation_id)
            history_tokens = sum(len(m.get("content", "")) for m in history)
            logger.info(f"对话历史加载完成: conversation_id={conversation_id}, 消息数={len(history)}, token={history_tokens}")
            
            step_loading["status"] = "success"
            step_loading["detail"] = f"已加载 {len(history)} 条历史消息"
            yield f"data: {json.dumps(step_loading, ensure_ascii=False)}\n\n"
            execution_path.append(step_loading)

            question = request.question
            original_question = question  # 保留原问题用于LLM组装
            logger.info(f"对话查询: conversation_id={conversation_id}, question={question[:50]}")

            from rag.models.llm_client import llm_client
            from rag.prompts.prompt_template import prompt_manager

            # ====== 步骤1: 查询改写（结合上下文补全问题） ======
            if history and len(history) > 0:
                step_rewrite = {"step": 1, "name": "查询改写", "status": "running", "detail": "正在结合对话历史改写问题..."}
                yield f"data: {json.dumps(step_rewrite, ensure_ascii=False)}\n\n"

                try:
                    # 构建历史摘要
                    history_summary = ""
                    for msg in history[-6:]:
                        role = "用户" if msg["role"] == "user" else "助手"
                        content = msg["content"][:100]
                        history_summary += f"{role}: {content}\n"

                    rewrite_messages = prompt_manager.build_messages(
                        "query_rewrite",
                        history_summary=history_summary,
                        question=question
                    )
                    # 阶段4异步改造：查询改写的 LLM 调用改为异步版本，避免阻塞事件循环
                    # 该调用位于 async 生成器 generate_events 内部（非 threading.Thread），可安全 await
                    rewritten = await llm_client.async_chat(messages=rewrite_messages)
                    rewritten = rewritten.strip()

                    if rewritten and len(rewritten) >= len(question):
                        logger.info(f"查询改写成功: '{question}' → '{rewritten}'")
                        step_rewrite["status"] = "success"
                        step_rewrite["detail"] = f"改写完成: '{question[:20]}' → '{rewritten[:40]}'"
                        question = rewritten  # 改写后的问题用于后续检索
                    else:
                        step_rewrite["status"] = "skip"
                        step_rewrite["detail"] = f"改写结果无效，继续使用原问题: '{question}'"
                except Exception as e:
                    logger.warning(f"查询改写失败: {e}")
                    step_rewrite["status"] = "skip"
                    step_rewrite["detail"] = f"改写异常({str(e)[:30]})，使用原问题"
                
                yield f"data: {json.dumps(step_rewrite, ensure_ascii=False)}\n\n"
                execution_path.append(step_rewrite)
            else:
                # 无历史时跳过改写
                step_rewrite_skip = {"step": 1, "name": "查询改写", "status": "skip", "detail": "首轮对话，无需改写"}
                yield f"data: {json.dumps(step_rewrite_skip, ensure_ascii=False)}\n\n"
                execution_path.append(step_rewrite_skip)

            # ====== 步骤2: 意图识别（判断是否需要检索） ======
            from rag.models.intent_classifier import intent_classifier
            step_intent = {"step": 2, "name": "意图识别", "status": "running", "detail": "正在判断是否需要检索..."}
            yield f"data: {json.dumps(step_intent, ensure_ascii=False)}\n\n"

            # 阶段4异步改造：意图识别改为异步版本，避免阻塞事件循环
            # 该调用位于 async 生成器 generate_events 内部（非 threading.Thread），可安全 await
            intent_result = await intent_classifier.async_classify(question)
            needs_retrieval = intent_result.get("intent") == "study_abroad"
            intent_text = "需要检索（留学专业问题）" if needs_retrieval else "无需检索（通用问题）"

            step_intent["status"] = "success"
            step_intent["detail"] = f"意图: {intent_text} (置信度={intent_result['confidence']:.2f})"
            yield f"data: {json.dumps(step_intent, ensure_ascii=False)}\n\n"
            execution_path.append(step_intent)

            # ====== 分支A: 不需要检索 ======
            if not needs_retrieval:
                logger.info(f"无需检索，直接LLM回答: {question}")
                step_direct = {"step": 3, "name": "LLM直接回答", "status": "running", "detail": "通用问题，直接调用大模型回答..."}
                yield f"data: {json.dumps(step_direct, ensure_ascii=False)}\n\n"

                # 构建带历史的消息（使用原问题）
                # 加载用户资料与简历文档，拼入system message（通用问题也需要用户上下文）
                user_profile_text, user_docs_text = load_user_context_text(user_id)
                general_msgs = prompt_manager.build_messages("general_answer", question=original_question)
                system_content = general_msgs[0]["content"]
                user_content = general_msgs[1]["content"]
                user_context_parts = []
                if user_profile_text:
                    user_context_parts.append(f"用户背景信息：\n{user_profile_text}")
                if user_docs_text:
                    user_context_parts.append(f"用户上传的文档内容：\n{user_docs_text}")
                if user_context_parts:
                    system_content = system_content + "\n\n" + "\n\n".join(user_context_parts)
                messages = []
                if history:
                    messages.extend([{"role": m["role"], "content": m["content"]} for m in history[-6:]])
                messages.append({"role": "system", "content": system_content})
                messages.append({"role": "user", "content": user_content})

                # 阶段6改造：移除 threading.Thread + queue.Queue，直接使用原生 async for 流式输出
                yield sse_event({"type": "answer_start", "detail": "开始生成回答"})
                answer = ""
                try:
                    async for chunk in llm_client.async_chat_stream(messages=messages):
                        answer += chunk
                        yield sse_event({"type": "answer_chunk", "content": chunk})
                except Exception as e:
                    logger.error(f"LLM流式回答异常: {e}")
                    yield sse_event({"type": "answer_error", "detail": str(e)})

                yield sse_event({"type": "answer_done", "detail": "回答生成完成"})

                step_direct["status"] = "success"
                step_direct["detail"] = "LLM直接回答完成（未使用检索，未写入Redis）"
                yield f"data: {json.dumps(step_direct, ensure_ascii=False)}\n\n"
                execution_path.append(step_direct)

                final_answer = answer
                result = {"type": "result", "answer": final_answer, "execution_path": execution_path}
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

                get_conversation_manager().add_message(conversation_id, "user", original_question)
                get_conversation_manager().add_message(conversation_id, "assistant", answer, {"source": "llm_direct"})
                return

            # ====== 分支B: 需要检索 ======
            # 步骤2: Redis检索结果缓存
            step_redis = {"step": 3, "name": "Redis检索缓存", "status": "running", "detail": f"正在查询Redis: retrieval:{question[:30]}..."}
            yield f"data: {json.dumps(step_redis, ensure_ascii=False)}\n\n"

            # 阶段3异步改造：替换为真正的异步 Redis 调用，避免阻塞事件循环
            context = await handler.async_redis_exact_match(question)
            if context is not None:
                step_redis["status"] = "success"
                step_redis["detail"] = f"检索缓存命中！key=retrieval:{question[:30]}, 长度={len(context)}字符"
                yield f"data: {json.dumps(step_redis, ensure_ascii=False)}\n\n"
                execution_path.append(step_redis)
                logger.info(f"Redis检索结果命中: {question}")
            else:
                step_redis["status"] = "miss"
                step_redis["detail"] = f"检索缓存未命中: key=retrieval:{question[:30]} 不存在，继续下一级检索"
                yield f"data: {json.dumps(step_redis, ensure_ascii=False)}\n\n"
                execution_path.append(step_redis)

                # 步骤3: BM25 + SQL检索（只有Redis未命中才执行）
                step_bm25 = {"step": 4, "name": "BM25相似度匹配", "status": "running", "detail": "正在进行分词和BM25相似度计算..."}
                yield f"data: {json.dumps(step_bm25, ensure_ascii=False)}\n\n"

                matched_question, prob = handler.bm25_match_with_softmax(question)
                db_context = None
                if prob >= 0.7 and matched_question is not None:
                    step_bm25["status"] = "running"
                    step_bm25["name"] = "SQL数据库查询"
                    step_bm25["detail"] = f"BM25匹配到(概率={prob:.2f})，正在查询数据库: {matched_question[:40]}"
                    yield f"data: {json.dumps(step_bm25, ensure_ascii=False)}\n\n"
                    
                    db_context = handler.query_database(matched_question)

                if db_context is not None:
                    context = db_context
                    # 关键：将检索结果写入Redis缓存（不是LLM回答）
                    # 阶段3异步改造：替换为真正的异步 Redis 写入调用
                    await handler.async_cache_retrieval(question, context)
                    step_bm25["status"] = "success"
                    step_bm25["name"] = "SQL数据库查询"
                    step_bm25["detail"] = f"✅ 数据库命中！问题='{matched_question[:40]}'，检索结果已缓存到Redis"
                    logger.info(f"数据库查询命中，已缓存检索结果到Redis: {question}")
                elif prob >= 0.7 and matched_question is not None:
                    step_bm25["status"] = "miss"
                    step_bm25["name"] = "SQL数据库查询"
                    step_bm25["detail"] = f"BM25匹配到(概率={prob:.2f})但数据库无对应答案，进入RAG检索"
                else:
                    step_bm25["status"] = "miss"
                    step_bm25["detail"] = f"BM25匹配度不足(最高概率={prob:.4f}，阈值0.7)，进入RAG向量检索"
                    logger.info(f"数据库未命中，准备RAG检索: {question}")
                yield f"data: {json.dumps(step_bm25, ensure_ascii=False)}\n\n"
                execution_path.append(step_bm25)

                # 步骤4: RAG向量检索（只有SQL/REDIS未命中才执行）
                if context is None:
                    step_rag = {"step": 5, "name": "RAG向量检索", "status": "running", "detail": "正在Milvus向量库中检索相似文档..."}
                    yield f"data: {json.dumps(step_rag, ensure_ascii=False)}\n\n"
                    
                    try:
                        from rag.retrieval.rag_retriever import rag_retriever
                        rag_context = await asyncio.to_thread(rag_retriever.query, question)
                        if rag_context:
                            context = rag_context
                            # 将RAG检索结果缓存到Redis（下次直接走Redis，不用再RAG）
                            # 阶段3异步改造：替换为真正的异步 Redis 写入调用
                            await handler.async_cache_retrieval(question, context)
                            step_rag["status"] = "success"
                            step_rag["detail"] = f"✅ RAG检索成功！已缓存到Redis(下次命中)，上下文长度={len(context)}字符"
                            logger.info(f"RAG检索成功，已缓存到Redis: {question}")
                        else:
                            step_rag["status"] = "miss"
                            step_rag["detail"] = "RAG向量检索无相关结果"
                    except Exception as e:
                        step_rag["status"] = "error"
                        step_rag["detail"] = f"RAG检索异常: {str(e)}"
                        logger.error(f"RAG检索异常: {e}")
                    yield f"data: {json.dumps(step_rag, ensure_ascii=False)}\n\n"
                    execution_path.append(step_rag)

            # 步骤5: 用检索结果 + 对话历史 → LLM生成回答
            if context:
                step_llm = {"step": 6, "name": "LLM生成回答", "status": "running", "detail": "基于检索结果和对话历史生成回答..."}
            else:
                step_llm = {"step": 6, "name": "LLM直接回答（兜底）", "status": "running", "detail": "未能检索到结果，调用大模型直接回答..."}
            yield f"data: {json.dumps(step_llm, ensure_ascii=False)}\n\n"

            # ====== 加载用户资料与简历文档内容（拼入system message） ======
            user_profile_text, user_docs_text = load_user_context_text(user_id)

            # 构建消息：历史 + 上下文 + 用户资料 + 当前问题
            messages = []
            if history:
                messages.extend([{"role": m["role"], "content": m["content"]} for m in history[-6:]])
            
            system_parts = []
            if context:
                system_parts.append(f"请基于以下检索到的信息回答用户的问题。\n\n检索到的相关信息：\n{context}")
            if user_profile_text:
                system_parts.append(f"用户背景信息：\n{user_profile_text}")
            if user_docs_text:
                system_parts.append(f"用户上传的文档内容：\n{user_docs_text}")
            
            if system_parts:
                system_prompt = "\n\n".join(system_parts)
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": original_question})

            # 阶段6改造：移除 threading.Thread + queue.Queue，直接使用原生 async for 流式输出
            yield sse_event({"type": "answer_start", "detail": "开始生成回答"})
            answer = ""
            try:
                async for chunk in llm_client.async_chat_stream(messages=messages):
                    answer += chunk
                    yield sse_event({"type": "answer_chunk", "content": chunk})
            except Exception as e:
                logger.error(f"LLM流式回答异常: {e}")
                yield sse_event({"type": "answer_error", "detail": str(e)})

            yield sse_event({"type": "answer_done", "detail": "回答生成完成"})

            if context:
                step_llm["detail"] = "基于检索结果生成回答完成（LLM回答未写入Redis）"
            else:
                step_llm["detail"] = "兜底回答完成（未使用检索，未写入Redis）"
            step_llm["status"] = "success"
            yield f"data: {json.dumps(step_llm, ensure_ascii=False)}\n\n"
            execution_path.append(step_llm)

            final_answer = answer
            result = {"type": "result", "answer": final_answer, "execution_path": execution_path}
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

            source = "retrieval_llm" if context else "fallback_llm"
            get_conversation_manager().add_message(conversation_id, "user", original_question)
            get_conversation_manager().add_message(conversation_id, "assistant", answer, {"source": source})

        except Exception as e:
            error_step = {"step": -1, "name": "系统错误", "status": "error", "detail": str(e)}
            yield f"data: {json.dumps(error_step, ensure_ascii=False)}\n\n"
            logger.error(f"对话查询异常: {e}", exc_info=True)

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    )