"""RAG对话节点 - v2 重构（纯LLM驱动 + 静默表单填写）

架构变更：
1. 意图识别：纯LLM判断是否需要检索，不再依赖规则匹配
2. 表单填写：纯LLM提取字段+备注重写，统一JSON输出，静默执行
3. 多级检索：L1 Redis → L2 BM25+SQL → L3a 稀疏向量粗排序 → L3b bge精排序 → 兜底空
4. 回答生成：检索无结果时prompt指示忽略，不得提及"检索失败"

节点清单：
- intent_classification_node: 检索意图识别（纯LLM）
- form_filling_node: 表单信息提取（纯LLM，静默执行）
- retrieval_node: 多级检索（L1-L3）
- stream_response_node: 流式回答生成

v2 修订：
- 同步阻塞调用（Redis/BM25/Milvus/SentenceTransformer）全部包 asyncio.to_thread
- RAGRetriever 暴露公共方法 is_ready() / get_last_fine_results()，不再外部访问私有属性
- BM25 阈值改为归一化分数（top1 / top2 比值），避免分数无上界问题
- 查询改写仅历史非空时启用，减少简单问题的 LLM 调用次数
"""
import asyncio
import time
import re
import json
import os
from typing import Dict, Any, List, Optional

from backend.common.functions.rag.models.llm_client import llm_client
from backend.common.functions.rag.rag_config import RAGConfig
from backend.common.basics.utils.logger import logger
from backend.common.functions.info_collect.model import (
    STUDENT_FIELDS_META,
    validate_and_convert_field,
    get_field_schema_text,
)
from .state import ConversationState, NodeResult


# =============================================================================
# 辅助函数
# =============================================================================

def _build_history_summary(messages: List[Dict[str, str]], max_messages: int = 6) -> str:
    """构建对话历史摘要

    Args:
        messages: 完整对话历史
        max_messages: 最多取最近N条消息

    Returns:
        str: 历史摘要文本
    """
    if not messages:
        return "（无历史）"

    recent = messages[-max_messages:]
    parts = []
    for msg in recent:
        role = msg.get("role", "")
        content = (msg.get("content", "") or "")[:150]
        if role == "user":
            parts.append(f"学生: {content}")
        elif role == "assistant":
            parts.append(f"顾问: {content}")
    return "\n".join(parts) if parts else "（无历史）"


def _build_profile_summary(user_profile: Dict[str, Any]) -> str:
    """构建profile摘要文本（用于LLM prompt）"""
    if not user_profile:
        return "（暂无）"

    parts = []
    for field_name, field_value in user_profile.items():
        if field_name in STUDENT_FIELDS_META and field_value:
            label = STUDENT_FIELDS_META[field_name]["label"]
            parts.append(f"{label}: {field_value}")
    return ", ".join(parts) if parts else "（暂无）"


def _has_full_turn(messages: List[Dict[str, str]]) -> bool:
    """判断对话历史中是否包含至少一轮完整的 user+assistant 对话（M8）

    用于决定是否启用查询改写：
    - 至少 1 条 user 消息 + 1 条 assistant 消息 → 启用改写
    - 仅 0 或 1 条消息 → 跳过改写，减少不必要的 LLM 调用

    Args:
        messages: 对话历史列表

    Returns:
        bool: True 表示历史中有完整一轮对话
    """
    if not messages or len(messages) < 2:
        return False
    has_user = any(m.get("role") == "user" for m in messages)
    has_assistant = any(m.get("role") == "assistant" for m in messages)
    return has_user and has_assistant


# =============================================================================
# 分支A：检索意图识别节点（纯LLM）
# =============================================================================

async def intent_classification_node(state: ConversationState) -> NodeResult:
    """检索意图识别节点（v2: 纯LLM判断是否需要检索）

    流程：
    1. 构建历史摘要 + 用户消息
    2. 调用LLM判断是否需要检索知识库
    3. 输出 need_retrieval (bool)

    降级策略：
    - LLM调用失败 → 默认 need_retrieval=False

    Args:
        state: 当前对话状态

    Returns:
        NodeResult: 包含更新后的状态
    """
    state.add_node_to_path("intent_classification_node")
    user_msg = state.current_user_message
    start_time = time.time()

    logger.info(f"[意图识别] 开始 >>> 用户消息: {user_msg[:80]}")

    try:
        from .prompts import prompt_manager

        history_summary = _build_history_summary(state.messages)

        messages = prompt_manager.build_messages(
            "retrieval_intent",
            history_summary=history_summary,
            user_message=user_msg
        )

        result = await llm_client.async_chat_json(
            messages=messages,
            model=RAGConfig.INTENT_MODEL_NAME,
            temperature=0.0
        )

        need_retrieval = bool(result.get("need_retrieval", False))
        confidence = float(result.get("confidence", 0.5))
        reason = str(result.get("reason", ""))[:200]

        elapsed = time.time() - start_time
        logger.info(
            f"[意图识别] LLM判断完成 ({elapsed:.3f}s): "
            f"need_retrieval={need_retrieval}, confidence={confidence:.2f}, "
            f"reason={reason}"
        )

        # 更新状态
        state.intent_state.need_retrieval = need_retrieval
        state.intent_state.confidence = confidence
        state.intent_state.reason = reason
        state.intent_state.elapsed = elapsed

        # 同步检索状态
        state.retrieval_state.retrieval_needed = need_retrieval

        return NodeResult(
            success=True,
            state=state,
            message=f"意图识别完成: need_retrieval={need_retrieval}",
            should_continue=True
        )

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[意图识别] 失败 ({elapsed:.3f}s): {e}", exc_info=True)
        state.add_error(f"意图识别失败: {str(e)}")

        # 降级：默认不需要检索，直接走回答生成
        state.intent_state.need_retrieval = False
        state.intent_state.confidence = 0.5
        state.intent_state.reason = f"降级: {str(e)[:100]}"
        state.intent_state.elapsed = elapsed
        state.should_fallback = True
        state.retrieval_state.retrieval_needed = False

        return NodeResult(
            success=False,
            state=state,
            message=f"意图识别失败，使用降级策略: {str(e)}",
            should_continue=True
        )


# =============================================================================
# 分支B：表单信息提取节点（纯LLM，静默执行）
# =============================================================================

async def form_filling_node(state: ConversationState) -> NodeResult:
    """表单信息提取节点（v2: 纯LLM + 统一JSON输出 + 静默执行）

    流程：
    1. 构建prompt：字段schema + 当前profile + 当前备注 + 历史 + 用户消息
    2. 调用LLM输出结构化JSON: { "updates": {...}|null, "notes": "..."|null }
    3. 验证字段值并写入数据库
    4. 备注有更新则写入数据库
    5. 始终刷新profile快照供回答生成使用

    静默特性：
    - 不向用户输出任何反馈（"已记录您的姓名XXX"等）
    - 用户感知不到表单填写过程

    Args:
        state: 当前对话状态

    Returns:
        NodeResult: 包含更新后的状态和最新profile快照
    """
    state.add_node_to_path("form_filling_node")
    start_time = time.time()

    logger.info(f"[表单填写] 开始 >>> 用户消息: {state.current_user_message[:50]}")

    try:
        from .prompts import prompt_manager

        field_schema = get_field_schema_text()
        current_profile_text = _build_profile_summary(state.user_profile)
        current_notes = state.current_notes or "（空）"
        history_summary = _build_history_summary(state.messages)

        messages = prompt_manager.build_messages(
            "form_extraction",
            field_schema=field_schema,
            current_profile=current_profile_text,
            current_notes=current_notes,
            history_summary=history_summary,
            user_message=state.current_user_message
        )

        result = await llm_client.async_chat_json(
            messages=messages,
            model=RAGConfig.INTENT_MODEL_NAME,
            temperature=0.0
        )

        # 解析LLM输出（统一JSON格式）
        raw_updates = result.get("updates")
        raw_notes = result.get("notes")

        # ====== 检测清空表单指令 ======
        if raw_updates and isinstance(raw_updates, dict) and raw_updates.get("clear_all") is True:
            logger.info(f"[表单填写] 检测到清空表单指令: user_id={state.user_info.user_id}")
            try:
                from backend.common.functions.info_collect.repository import get_async_student_profile_repo
                repo = get_async_student_profile_repo()
                clear_success = await repo.clear_profile(state.user_info.user_id)
                if clear_success:
                    # 清空state中的user_profile
                    state.user_profile = {}
                    state.current_notes = ""
                    state.form_state.profile_snapshot = {}
                    state.form_state.extracted_updates = {}
                    state.form_state.extracted_notes = None
                    state.form_state.db_write_success = True
                    state.form_state.updated_field_names = []
                    state.form_state.notes_updated = False
                    state.form_state.elapsed = time.time() - start_time
                    logger.info(f"[表单填写] 清空表单成功: user_id={state.user_info.user_id}")
                else:
                    logger.warning(f"[表单填写] 清空表单失败: user_id={state.user_info.user_id}")
                    state.add_error("清空表单失败")
            except Exception as e:
                logger.error(f"[表单填写] 清空表单异常: {e}", exc_info=True)
                state.add_error(f"清空表单异常: {str(e)}")

            state.add_node_to_path("form_filling_node")
            return state

        # 标准化：updates 为空字典/空列表/None 都视为无字段更新
        updates_dict = {}
        if raw_updates and isinstance(raw_updates, dict):
            updates_dict = {k: v for k, v in raw_updates.items() if v is not None}

        notes_text = None
        if raw_notes and isinstance(raw_notes, str) and raw_notes.strip():
            notes_text = raw_notes.strip()

        # 保存LLM原始输出
        state.form_state.raw_llm_output = {
            "updates": updates_dict,
            "notes": notes_text
        }

        logger.info(
            f"[表单填写] LLM输出: updates字段={list(updates_dict.keys())}, "
            f"notes={'有重写' if notes_text else '无'}"
        )

        # 验证并写入字段
        validated_updates = {}
        for field_name, field_value in updates_dict.items():
            if field_name not in STUDENT_FIELDS_META:
                logger.warning(f"[表单填写] 未知字段: {field_name}")
                continue

            converted_value, error = validate_and_convert_field(field_name, field_value)
            if error:
                logger.warning(f"[表单填写] 字段验证失败: {field_name}={field_value} - {error}")
                continue

            # 跳过与现有值相同的字段
            existing = state.user_profile.get(field_name)
            if existing is not None and str(existing).strip() == str(converted_value).strip():
                logger.debug(f"[表单填写] 字段值未变化，跳过: {field_name}")
                continue

            validated_updates[field_name] = converted_value

        # 写入数据库
        db_write_success = False
        updated_field_names = []
        notes_updated = False

        if validated_updates or notes_text:
            try:
                from backend.common.functions.info_collect.repository import get_async_student_profile_repo

                repo = get_async_student_profile_repo()
                user_id = state.user_info.user_id

                # 合并要写入的字段
                write_data = {}
                if validated_updates:
                    write_data.update(validated_updates)
                if notes_text:
                    write_data["notes"] = notes_text

                if write_data:
                    upsert_result = await repo.upsert_fields(user_id, write_data)
                    db_write_success = bool(upsert_result)
                    logger.info(
                        f"[表单填写] DB写入: success={db_write_success}, "
                        f"fields={list(write_data.keys())}"
                    )

                # 更新state中的user_profile
                for field_name, field_value in validated_updates.items():
                    state.update_profile(field_name, field_value)
                    updated_field_names.append(field_name)

                if notes_text:
                    state.current_notes = notes_text
                    state.update_profile("notes", notes_text)
                    notes_updated = True

            except Exception as db_error:
                logger.error(f"[表单填写] DB写入异常: {db_error}", exc_info=True)
                state.add_error(f"DB写入失败: {str(db_error)}")

        # 刷新profile快照（始终执行，确保回答生成节点信息对齐）
        try:
            from backend.common.functions.info_collect.repository import get_async_student_profile_repo
            repo = get_async_student_profile_repo()
            latest_profile = await repo.get_profile(state.user_info.user_id)
            if latest_profile:
                state.form_state.profile_snapshot = latest_profile
                # 同步更新 state.user_profile（用DB最新值覆盖）
                for k, v in latest_profile.items():
                    if v is not None:
                        state.user_profile[k] = v
            else:
                state.form_state.profile_snapshot = dict(state.user_profile)
        except Exception as e:
            logger.warning(f"[表单填写] 刷新profile快照失败: {e}")
            state.form_state.profile_snapshot = dict(state.user_profile)

        # 更新state
        state.form_state.extracted_updates = validated_updates
        state.form_state.extracted_notes = notes_text
        state.form_state.db_write_success = db_write_success
        state.form_state.updated_field_names = updated_field_names
        state.form_state.notes_updated = notes_updated
        state.form_state.elapsed = time.time() - start_time

        elapsed = state.form_state.elapsed
        logger.info(
            f"[表单填写] 完成 ({elapsed:.3f}s): "
            f"updated_fields={updated_field_names}, "
            f"notes_updated={notes_updated}, "
            f"snapshot_fields={len(state.form_state.profile_snapshot)}"
        )

        return NodeResult(
            success=True,
            state=state,
            message=f"表单填写完成: {updated_field_names}",
            should_continue=True
        )

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[表单填写] 失败 ({elapsed:.3f}s): {e}", exc_info=True)
        state.add_error(f"表单填写失败: {str(e)}")

        # 静默降级：profile快照使用现有值
        state.form_state.profile_snapshot = dict(state.user_profile)
        state.form_state.elapsed = elapsed

        return NodeResult(
            success=False,
            state=state,
            message=f"表单填写失败: {str(e)}",
            should_continue=True
        )


# =============================================================================
# 多级检索节点（L1 Redis → L2 BM25+SQL → L3a 稀疏粗排序 → L3b 稠密精排序）
# =============================================================================

async def retrieval_node(state: ConversationState) -> NodeResult:
    """多级检索节点（v2: 细化L1-L3链路）

    链路：
    1. L1 Redis 精确匹配 → 命中即返回
    2. L2 BM25 + SQL（prob ≥ 0.7） → 命中即返回
    3. L3a BM25 稀疏向量粗排序 → 取 top 50
    4. L3b bge-m3 + bge-reranker-v2-m3 稠密精排序 → 取 top 10 (高于阈值)
    5. 兜底：无结果时返回空上下文，由回答生成LLM凭自身知识回答

    Args:
        state: 当前对话状态

    Returns:
        NodeResult: 包含更新后的状态和检索上下文
    """
    state.add_node_to_path("retrieval_node")
    start_time = time.time()

    if not state.retrieval_state.retrieval_needed:
        logger.info("[检索节点] 无需检索，跳过")
        return NodeResult(
            success=True,
            state=state,
            message="无需检索",
            should_continue=True
        )

    query = state.current_user_message
    logger.info(f"[检索节点] 开始 >>> 查询: {query[:60]}")

    try:
        # 查询改写（M8: 仅当历史中存在至少一轮完整 user+assistant 对话时启用）
        # 这样可以避免对首问或仅有 1 条历史的简单问题做无谓的 LLM 调用
        if _has_full_turn(state.messages):
            rewritten = await _rewrite_query(query, state.messages)
            if rewritten and rewritten != query:
                logger.info(f"[检索节点] 查询改写: '{query[:30]}' → '{rewritten[:30]}'")
                query = rewritten
        else:
            logger.debug("[检索节点] 历史不足一轮对话，跳过查询改写")

        context = None
        retrieval_source = "empty"

        # ====== L1: Redis 精确匹配 ======
        if not context:
            logger.info("[检索节点] L1: Redis 精确匹配...")
            redis_result = await _redis_retrieval(query)
            if redis_result:
                context = redis_result
                retrieval_source = "redis"
                state.retrieval_state.redis_hit = True
                logger.info(f"[检索节点] ✓ L1 Redis命中: {context[:60]}...")

        # ====== L2: BM25 + SQL ======
        if not context:
            logger.info("[检索节点] L2: BM25 + SQL...")
            bm25_results = await _bm25_retrieval(query)
            if bm25_results:
                normalized = _normalize_bm25_results(bm25_results)
                top_score = normalized[0].get("score", 0) if normalized else 0

                if top_score >= 0.7:
                    context = _format_bm25_results(normalized[:3])
                    retrieval_source = "bm25"
                    state.retrieval_state.bm25_hit = True
                    logger.info(f"[检索节点] ✓ L2 BM25命中 (score={top_score:.3f})")
                else:
                    logger.info(f"[检索节点] L2 BM25分数过低({top_score:.3f})，进入L3")
                    state.retrieval_state.coarse_candidates = normalized[:50]
            else:
                logger.info("[检索节点] L2 BM25无结果，进入L3")

        # ====== L3a + L3b: 稀疏粗排序 → 稠密精排序 ======
        if not context:
            logger.info("[检索节点] L3: 向量检索链路...")
            rag_context = await _rag_retrieval(query, state.retrieval_state)

            if rag_context:
                context = rag_context
                retrieval_source = "rag"
                state.retrieval_state.rag_hit = True
                logger.info(f"[检索节点] ✓ L3 RAG命中: {context[:60]}...")
            else:
                logger.info("[检索节点] ✗ L3 无结果，走兜底")

        # ====== 更新检索状态 ======
        state.retrieval_state.final_context = context
        state.retrieval_state.retrieval_source = retrieval_source
        state.retrieval_state.retrieval_time = time.time() - start_time

        elapsed = state.retrieval_state.retrieval_time
        logger.info(
            f"[检索节点] 完成 ({elapsed:.3f}s): "
            f"source={retrieval_source}, "
            f"has_context={context is not None}, "
            f"context_len={len(context) if context else 0}"
        )

        return NodeResult(
            success=True,
            state=state,
            message=f"检索完成: source={retrieval_source}",
            should_continue=True
        )

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[检索节点] 失败 ({elapsed:.3f}s): {e}", exc_info=True)
        state.add_error(f"检索失败: {str(e)}")
        state.retrieval_state.retrieval_time = elapsed
        state.retrieval_state.retrieval_source = "empty"
        state.retrieval_state.final_context = None

        return NodeResult(
            success=False,
            state=state,
            message=f"检索失败: {str(e)}",
            should_continue=True
        )


async def _rewrite_query(query: str, history: List[Dict[str, str]]) -> str:
    """查询改写：将追问改写为完整问题

    Args:
        query: 原始查询
        history: 对话历史

    Returns:
        str: 改写后的查询（失败时返回原始查询）
    """
    try:
        from .prompts import prompt_manager

        history_summary = _build_history_summary(history, max_messages=4)
        messages = prompt_manager.build_messages(
            "query_rewrite",
            history_summary=history_summary,
            question=query
        )

        rewritten = await llm_client.async_chat(
            messages=messages,
            model=RAGConfig.INTENT_MODEL_NAME,
            temperature=0.0,
            fallback_response=query,
        )
        return rewritten.strip()

    except Exception as e:
        logger.warning(f"[检索节点] 查询改写失败: {e}，使用原始查询")
        return query


async def _redis_retrieval(query: str) -> Optional[str]:
    """L1: Redis 精确匹配（v2: 同步客户端包 asyncio.to_thread，避免阻塞事件循环）

    Args:
        query: 查询文本

    Returns:
        Optional[str]: 检索结果或None
    """
    try:
        # 将同步 redis 调用放到线程池中执行，避免阻塞事件循环
        return await asyncio.to_thread(_redis_retrieval_sync, query)
    except Exception as e:
        logger.warning(f"[Redis检索] 失败: {e}")
        return None


def _redis_retrieval_sync(query: str) -> Optional[str]:
    """Redis 同步检索实现（被 _redis_retrieval 包到线程池中执行）"""
    try:
        import redis

        r = redis.Redis(
            host=RAGConfig.REDIS_HOST,
            port=RAGConfig.REDIS_PORT,
            password=RAGConfig.REDIS_PASSWORD,
            db=RAGConfig.REDIS_DB,
            decode_responses=True,
            socket_timeout=2.0,
        )

        # 精确匹配
        cache_key = f"qa:{query.strip()}"
        cached = r.get(cache_key)
        if cached:
            return cached

        # 规范化匹配（去标点、小写）
        normalized = re.sub(r'[^\w\u4e00-\u9fff]', '', query).lower()
        cache_key_norm = f"qa:{normalized}"
        cached = r.get(cache_key_norm)
        if cached:
            return cached

        return None

    except redis.exceptions.ConnectionError:
        logger.warning("[Redis检索] 连接失败，Redis可能未启动")
        return None
    except Exception as e:
        logger.warning(f"[Redis检索] 同步执行失败: {e}")
        return None


async def _bm25_retrieval(query: str) -> List[Dict]:
    """L2: BM25 + SQL 检索（v2: 包 asyncio.to_thread，避免阻塞事件循环）

    Args:
        query: 查询文本

    Returns:
        List[Dict]: BM25检索结果
    """
    try:
        return await asyncio.to_thread(_bm25_retrieval_sync, query)
    except Exception as e:
        logger.error(f"[BM25检索] 失败: {e}", exc_info=True)
        return []


def _bm25_retrieval_sync(query: str) -> List[Dict]:
    """BM25 同步检索实现"""
    try:
        try:
            from backend.common.functions.retrieval.bm25_index_builder import BM25IndexBuilder
            bm25 = BM25IndexBuilder()
            results = bm25.search(query, top_k=10)
            if results:
                logger.info(f"[BM25检索] 命中{len(results)}条")
                return results
        except Exception as e:
            logger.debug(f"[BM25检索] 真实索引不可用: {e}")

        # 降级：使用模拟数据
        return _mock_bm25_search(query)

    except Exception as e:
        logger.error(f"[BM25检索] 同步执行失败: {e}", exc_info=True)
        return []


def _mock_bm25_search(query: str) -> List[Dict]:
    """模拟BM25检索"""
    try:
        mock_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "backend", "common", "data", "bm25_mock_data.json"
        )
        if not os.path.exists(mock_file):
            mock_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "data", "bm25_mock_data.json"
            )

        if not os.path.exists(mock_file):
            return []

        with open(mock_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        documents = data.get("documents", [])
    except Exception:
        documents = []

    results = []
    query_words = set(query.lower().split())
    for doc in documents:
        doc_text = (doc.get("question", "") + " " + doc.get("answer", "")).lower()
        doc_words = set(doc_text.split())
        if query_words and doc_words:
            intersection = query_words & doc_words
            union = query_words | doc_words
            score = len(intersection) / len(union) if union else 0
            if score > 0:
                results.append({
                    "id": doc.get("id", 0),
                    "question": doc.get("question", ""),
                    "answer": doc.get("answer", ""),
                    "score": score
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


async def _rag_retrieval(query: str, retrieval_state) -> Optional[str]:
    """L3: RAG 向量检索（L3a 稀疏粗排序 + L3b 稠密精排序）

    v2 修订：
    - 同步 SentenceTransformer/Milvus/CrossEncoder 调用包 asyncio.to_thread
    - 通过公共方法 is_ready() / get_last_fine_results() 访问 RAGRetriever 状态

    Args:
        query: 查询文本
        retrieval_state: 检索状态（用于保存中间结果）

    Returns:
        Optional[str]: 检索上下文
    """
    try:
        from backend.common.functions.rag.retrieval.rag_retriever import rag_retriever

        # 模型初始化（首次调用可能耗时，放线程池避免阻塞事件循环）
        await asyncio.to_thread(rag_retriever.initialize)

        # 通过公共方法检查就绪状态
        if not rag_retriever.is_ready():
            logger.warning("[RAG检索] embedding模型未加载，跳过向量检索")
            return None

        # 执行向量检索（内部已包含L3a粗排序 + L3b精排序）
        # 同步调用包到线程池中
        context = await asyncio.to_thread(
            rag_retriever.query, query, RAGConfig.RETRIEVAL_TOP_K
        )

        # 通过公共方法获取精排序结果
        retrieval_state.fine_results = rag_retriever.get_last_fine_results()

        return context

    except Exception as e:
        logger.error(f"[RAG检索] 失败: {e}", exc_info=True)
        return None


def _normalize_bm25_results(results) -> List[Dict]:
    """规范化BM25结果为dict列表（C6: 加入 softmax 归一化）

    v2 修订（C6）：
    - 真实 BM25 分数无上界，0.7 阈值失效
    - 现对 scores 做 softmax 归一化，使 top1 概率 ∈ (0,1)
    - 当 top1 softmax 概率 ≥ 0.7 时表示其显著优于其他候选
    - mock 数据（Jaccard 相似度）同样适用 softmax，不改变排名
    """
    if not results:
        return []

    normalized = []
    for item in results:
        if isinstance(item, dict):
            normalized.append({
                "question": str(item.get("question", "")),
                "answer": str(item.get("answer", "")),
                "score": float(item.get("score", 0.0)),
            })
        elif isinstance(item, (tuple, list)):
            if len(item) >= 3:
                normalized.append({
                    "question": str(item[0]) if item[0] else "",
                    "answer": str(item[1]) if item[1] else "",
                    "score": float(item[2]) if item[2] else 0.0
                })
            elif len(item) == 2:
                normalized.append({
                    "question": str(item[0]) if item[0] else "",
                    "answer": "",
                    "score": float(item[1]) if item[1] else 0.0
                })
        else:
            normalized.append({"question": str(item), "answer": "", "score": 0.0})

    # ====== C6: softmax 归一化 ======
    # 过滤负无穷/NaN，避免数值问题
    scores = [r["score"] for r in normalized]
    if not scores:
        return normalized

    max_score = max(scores)
    # 全部相同分数时 softmax 概率均分，top1 概率=1/n，自然不会触发 0.7 阈值
    exps = []
    for s in scores:
        # 限制指数输入范围，防止 overflow
        clipped = max(min(s - max_score, 0.0), -50.0)
        exps.append(_math_exp(clipped))
    exp_sum = sum(exps)
    if exp_sum <= 0:
        # 退化情况：所有分数相等且非常小，均分概率
        uniform = 1.0 / len(normalized)
        for r in normalized:
            r["score"] = uniform
    else:
        for r, e in zip(normalized, exps):
            r["score"] = e / exp_sum

    # 重新按归一化分数排序（softmax 不改变原始排名，但保险起见再排一次）
    normalized.sort(key=lambda x: x["score"], reverse=True)
    return normalized


def _math_exp(x: float) -> float:
    """安全计算 e^x，避免 import math 散落各处"""
    import math
    try:
        return math.exp(x)
    except (OverflowError, ValueError):
        return 0.0


def _format_bm25_results(results: List[Dict]) -> str:
    """格式化BM25结果为上下文"""
    if not results:
        return ""
    parts = []
    for i, result in enumerate(results[:3], 1):
        question = result.get("question", "")
        answer = result.get("answer", "")
        parts.append(f"【参考{i}】\n问题：{question}\n答案：{answer}")
    return "\n\n".join(parts)


# =============================================================================
# 回答生成节点（v2: 流式输出，含检索无结果时的prompt约束）
# =============================================================================

async def stream_response_node(state: ConversationState):
    """流式回答生成节点（v2 重构）

    接收：
    - 检索上下文（可能为空）
    - 表单profile快照（始终有值）
    - 对话历史 + 用户消息

    输出：
    - 流式文本片段（yield）

    关键约束：
    - 检索无结果时prompt指示忽略，凭自身知识回答
    - 不得提及"检索失败"、"没有查到相关信息"等
    - 表单填写静默执行，回答中不体现表单过程

    Args:
        state: 对话状态

    Yields:
        str: 流式输出的文本片段
    """
    state.add_node_to_path("stream_response_node")

    try:
        from .prompts import prompt_manager

        # 准备上下文
        retrieval_context = state.retrieval_state.final_context or "（无）"
        user_profile_text = _build_profile_summary(state.user_profile)
        history_summary = _build_history_summary(state.messages)

        # 计算已填写字段列表（用于告诉AI不要重复追问）
        filled_fields = []
        from backend.common.functions.info_collect.model import STUDENT_FIELDS_META
        for field_name, meta in STUDENT_FIELDS_META.items():
            value = state.user_profile.get(field_name)
            if value is not None and str(value).strip() != "":
                label = meta.get("label", field_name)
                filled_fields.append(label)

        filled_fields_text = ", ".join(filled_fields) if filled_fields else "（无）"

        messages = prompt_manager.build_messages(
            "stream_generation",
            retrieval_context=retrieval_context,
            user_profile=user_profile_text,
            filled_fields=filled_fields_text,
            history_summary=history_summary,
            user_message=state.current_user_message
        )

        # 流式生成
        async for chunk in llm_client.async_chat_stream(
            messages=messages,
            model=RAGConfig.GENERATION_MODEL_NAME,
            temperature=RAGConfig.LLM_TEMPERATURE
        ):
            yield chunk

    except Exception as e:
        logger.error(f"[流式回答] 生成失败: {e}", exc_info=True)
        yield "抱歉，系统遇到了一些问题，请稍后再试。"
