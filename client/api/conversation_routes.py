"""会话管理 API 路由"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import asyncio
import queue
import threading

from common.conversation.manager import ConversationManager
from common.conversation.graph import ConversationGraph
from client.api.routes import get_query_handler
from common.utils.logger import logger
from common.utils.auth import get_current_user, require_user

router = APIRouter()

_conversation_manager: ConversationManager = None
_conversation_graph: ConversationGraph = None


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
        conv = get_conversation_manager().get_conversation(conversation_id, user_id=user_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="会话不存在")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")

    handler = get_query_handler()

    async def generate_events():
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

            from common.rag.models.llm_client import llm_client
            from client.rag.prompts.prompt_template import prompt_manager

            # ====== 步骤1: 查询改写（结合上下文补全问题） ======
            if history and len(history) > 0:
                step_rewrite = {"step": 1, "name": "查询改写", "status": "running", "detail": "正在结合对话历史改写问题..."}
                yield f"data: {json.dumps(step_rewrite, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)

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
                    rewritten = llm_client.chat(messages=rewrite_messages)
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
                await asyncio.sleep(0.005)
                execution_path.append(step_rewrite)
            else:
                # 无历史时跳过改写
                step_rewrite_skip = {"step": 1, "name": "查询改写", "status": "skip", "detail": "首轮对话，无需改写"}
                yield f"data: {json.dumps(step_rewrite_skip, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)
                execution_path.append(step_rewrite_skip)

            # ====== 步骤2: 意图识别（判断是否需要检索） ======
            from common.rag.models.intent_classifier import intent_classifier
            step_intent = {"step": 2, "name": "意图识别", "status": "running", "detail": "正在判断是否需要检索..."}
            yield f"data: {json.dumps(step_intent, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.005)

            intent_result = intent_classifier.classify(question)
            needs_retrieval = intent_result.get("intent") == "study_abroad"
            intent_text = "需要检索（留学专业问题）" if needs_retrieval else "无需检索（通用问题）"

            step_intent["status"] = "success"
            step_intent["detail"] = f"意图: {intent_text} (置信度={intent_result['confidence']:.2f})"
            yield f"data: {json.dumps(step_intent, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.005)
            execution_path.append(step_intent)

            # ====== 分支A: 不需要检索 ======
            if not needs_retrieval:
                logger.info(f"无需检索，直接LLM回答: {question}")
                step_direct = {"step": 3, "name": "LLM直接回答", "status": "running", "detail": "通用问题，直接调用大模型回答..."}
                yield f"data: {json.dumps(step_direct, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)

                # 构建带历史的消息（使用原问题）
                messages = prompt_manager.build_messages("general_answer", question=original_question)
                if history:
                    hist_messages = [{"role": m["role"], "content": m["content"]} for m in history[-6:]]
                    messages = hist_messages + messages

                yield f"data: {json.dumps({'type': 'answer_start', 'detail': '开始生成回答'}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)
                
                # 使用线程+队列实现真正的流式输出（避免阻塞asyncio事件循环）
                stream_queue = queue.Queue()
                answer_result = [""]
                
                def llm_worker():
                    try:
                        for chunk in llm_client.chat_stream(messages=messages):
                            answer_result[0] += chunk
                            stream_queue.put(chunk)
                    except Exception as e:
                        stream_queue.put(("error", str(e)))
                    finally:
                        stream_queue.put(None)  # 结束标记
                
                worker_thread = threading.Thread(target=llm_worker)
                worker_thread.start()
                
                # 从队列中读取并yield（非阻塞，每次只处理一个chunk确保真正流式）
                while True:
                    try:
                        chunk = stream_queue.get(timeout=0.05)
                        if chunk is None:
                            break
                        if isinstance(chunk, tuple) and chunk[0] == "error":
                            logger.error(f"LLM流式生成错误: {chunk[1]}")
                            break
                        yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                        # 强制让事件循环有机会将数据flush到客户端
                        await asyncio.sleep(0.02)
                        continue  # 继续处理下一个，不批量处理
                    except queue.Empty:
                        if not worker_thread.is_alive():
                            # 等待队列中可能剩余的数据
                            while True:
                                try:
                                    chunk = stream_queue.get_nowait()
                                    if chunk is None:
                                        break
                                    if isinstance(chunk, tuple) and chunk[0] == "error":
                                        continue
                                    yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                                    await asyncio.sleep(0.02)
                                except queue.Empty:
                                    break
                            break
                        # 等待更多数据，但不阻塞太久
                        await asyncio.sleep(0.01)
                
                worker_thread.join(timeout=5)
                answer = answer_result[0]
                yield f"data: {json.dumps({'type': 'answer_done', 'detail': '回答生成完成'}, ensure_ascii=False)}\n\n"

                step_direct["status"] = "success"
                step_direct["detail"] = "LLM直接回答完成（未使用检索，未写入Redis）"
                yield f"data: {json.dumps(step_direct, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)
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
            await asyncio.sleep(0.005)

            context = handler.redis_exact_match(question)
            if context is not None:
                step_redis["status"] = "success"
                step_redis["detail"] = f"检索缓存命中！key=retrieval:{question[:30]}, 长度={len(context)}字符"
                yield f"data: {json.dumps(step_redis, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)
                execution_path.append(step_redis)
                logger.info(f"Redis检索结果命中: {question}")
            else:
                step_redis["status"] = "miss"
                step_redis["detail"] = f"检索缓存未命中: key=retrieval:{question[:30]} 不存在，继续下一级检索"
                yield f"data: {json.dumps(step_redis, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)
                execution_path.append(step_redis)

                # 步骤3: BM25 + SQL检索（只有Redis未命中才执行）
                step_bm25 = {"step": 4, "name": "BM25相似度匹配", "status": "running", "detail": "正在进行分词和BM25相似度计算..."}
                yield f"data: {json.dumps(step_bm25, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.005)

                matched_question, prob = handler.bm25_match_with_softmax(question)
                db_context = None
                if prob >= 0.7 and matched_question is not None:
                    step_bm25["status"] = "running"
                    step_bm25["name"] = "SQL数据库查询"
                    step_bm25["detail"] = f"BM25匹配到(概率={prob:.2f})，正在查询数据库: {matched_question[:40]}"
                    yield f"data: {json.dumps(step_bm25, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.005)
                    
                    db_context = handler.query_database(matched_question)

                if db_context is not None:
                    context = db_context
                    # 关键：将检索结果写入Redis缓存（不是LLM回答）
                    handler.cache_retrieval(question, context)
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
                await asyncio.sleep(0.005)
                execution_path.append(step_bm25)

                # 步骤4: RAG向量检索（只有SQL/REDIS未命中才执行）
                if context is None:
                    step_rag = {"step": 5, "name": "RAG向量检索", "status": "running", "detail": "正在Milvus向量库中检索相似文档..."}
                    yield f"data: {json.dumps(step_rag, ensure_ascii=False)}\n\n"
                    await asyncio.sleep(0.005)
                    
                    try:
                        from common.rag.retrieval.rag_retriever import rag_retriever
                        rag_context = rag_retriever.query(question)
                        if rag_context:
                            context = rag_context
                            # 将RAG检索结果缓存到Redis（下次直接走Redis，不用再RAG）
                            handler.cache_retrieval(question, context)
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
                    await asyncio.sleep(0.005)
                    execution_path.append(step_rag)

            # 步骤5: 用检索结果 + 对话历史 → LLM生成回答
            if context:
                step_llm = {"step": 6, "name": "LLM生成回答", "status": "running", "detail": "基于检索结果和对话历史生成回答..."}
            else:
                step_llm = {"step": 6, "name": "LLM直接回答（兜底）", "status": "running", "detail": "未能检索到结果，调用大模型直接回答..."}
            yield f"data: {json.dumps(step_llm, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.005)

            # ====== 加载用户资料与简历文档内容（拼入system message） ======
            user_profile_text = ""
            user_docs_text = ""
            try:
                if user_id:
                    from common.user_profile.repository import get_user_profile_repo, get_user_document_repo
                    profile = get_user_profile_repo().get_profile(user_id)
                    if profile:
                        parts = []
                        if profile.get("nickname"): parts.append(f"姓名：{profile['nickname']}")
                        if profile.get("occupation"): parts.append(f"职业：{profile['occupation']}")
                        if profile.get("industry"): parts.append(f"行业：{profile['industry']}")
                        if profile.get("experience_years"): parts.append(f"工作年限：{profile['experience_years']}")
                        if profile.get("skills") and len(profile["skills"]) > 0:
                            parts.append(f"技能：{', '.join(profile['skills'])}")
                        if profile.get("bio"): parts.append(f"个人简介：{profile['bio']}")
                        user_profile_text = "\n".join(parts)

                    # 加载简历文档内容
                    docs = get_user_document_repo().get_user_parsed_texts(user_id)
                    if docs:
                        doc_parts = []
                        for i, text in enumerate(docs, 1):
                            # 截取前1000字，避免token过长
                            truncated = text[:1000] + ("...(已截断)" if len(text) > 1000 else "")
                            doc_parts.append(f"[简历文档{i}]\n{truncated}")
                        user_docs_text = "\n\n".join(doc_parts)

                    if user_profile_text or user_docs_text:
                        logger.info(f"用户资料已加载: user_id={user_id}")
            except Exception as e:
                logger.warning(f"加载用户资料失败（不影响主流程）: {e}")

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

            yield f"data: {json.dumps({'type': 'answer_start', 'detail': '开始生成回答'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.005)
            
            # 使用线程+队列实现真正的流式输出（避免阻塞asyncio事件循环）
            stream_queue = queue.Queue()
            answer_result = [""]
            
            def llm_worker():
                try:
                    for chunk in llm_client.chat_stream(messages=messages):
                        answer_result[0] += chunk
                        stream_queue.put(chunk)
                except Exception as e:
                    stream_queue.put(("error", str(e)))
                finally:
                    stream_queue.put(None)  # 结束标记
            
            worker_thread = threading.Thread(target=llm_worker)
            worker_thread.start()
            
            # 从队列中读取并yield（非阻塞，每次只处理一个chunk确保真正流式）
            while True:
                try:
                    chunk = stream_queue.get(timeout=0.05)
                    if chunk is None:
                        break
                    if isinstance(chunk, tuple) and chunk[0] == "error":
                        logger.error(f"LLM流式生成错误: {chunk[1]}")
                        break
                    yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                    # 强制让事件循环有机会将数据flush到客户端
                    await asyncio.sleep(0.02)
                    continue  # 继续处理下一个，不批量处理
                except queue.Empty:
                    if not worker_thread.is_alive():
                        # 等待队列中可能剩余的数据
                        while True:
                            try:
                                chunk = stream_queue.get_nowait()
                                if chunk is None:
                                    break
                                if isinstance(chunk, tuple) and chunk[0] == "error":
                                    continue
                                yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                                await asyncio.sleep(0.02)
                            except queue.Empty:
                                break
                        break
                    # 等待更多数据，但不阻塞太久
                    await asyncio.sleep(0.01)
            
            worker_thread.join(timeout=5)
            answer = answer_result[0]
            yield f"data: {json.dumps({'type': 'answer_done', 'detail': '回答生成完成'}, ensure_ascii=False)}\n\n"

            if context:
                step_llm["detail"] = "基于检索结果生成回答完成（LLM回答未写入Redis）"
            else:
                step_llm["detail"] = "兜底回答完成（未使用检索，未写入Redis）"
            step_llm["status"] = "success"
            yield f"data: {json.dumps(step_llm, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.005)
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
