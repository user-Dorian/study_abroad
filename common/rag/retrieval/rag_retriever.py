"""RAG核心检索器 - 整合意图识别、策略选择、向量检索、Reranker
支持步骤回调机制，供API流式推送执行过程到前端
"""
from typing import List, Dict, Optional, Callable, Any
import asyncio
import threading
import numpy as np
from common.rag.rag_config import RAGConfig
from common.rag.data_loader.chunk_and_embed import EmbeddingModel, MilvusManager
from common.rag.retrieval.reranker import Reranker, reranker
from common.rag.models.intent_classifier import intent_classifier, IntentClassifier
from common.rag.models.strategy_selector import strategy_selector, StrategySelector
from common.rag.models.llm_client import llm_client, LLMClient
from client.rag.prompts.prompt_template import prompt_manager
from common.utils.logger import logger

# 步骤回调函数签名: (step_number, step_name, status, detail, extra_data)
StepCallback = Callable[[int, str, str, str, Optional[dict]], None]


class RAGRetriever:
    """RAG检索器 - 完整的检索流程"""
    
    def __init__(self):
        self.embedding_model = None
        self.milvus_manager = None
        self.intent_classifier = intent_classifier
        self.strategy_selector = strategy_selector
        self.reranker = reranker
        self.llm_client = llm_client
        self._initialized = False
        self._init_lock = threading.Lock()
        self._step_callback: Optional[StepCallback] = None
        self._step_counter = 0
        self._last_update_check = 0.0
        self._history_messages: list = None
    
    def initialize(self):
        """初始化所有组件（仅实例化，不执行模型推理）"""
        if self._initialized:
            return

        with self._init_lock:
            if self._initialized:
                return

            logger.info("初始化RAG检索器...")
            self.embedding_model = EmbeddingModel()
            self.milvus_manager = MilvusManager()
            self._initialized = True
            logger.info("RAG检索器初始化完成")

    def warmup(self):
        """预热 EmbeddingModel 和 Reranker，触发底层模型加载"""
        self.initialize()
        logger.info("RAG检索器 warmup 开始...")
        self.embedding_model.warmup()
        self.reranker.warmup()
        logger.info("RAG检索器 warmup 完成")
    
    def set_step_callback(self, callback: StepCallback):
        """设置步骤回调函数，用于流式推送执行过程"""
        self._step_callback = callback
    
    def _reset_step_counter(self):
        """重置步骤计数器"""
        self._step_counter = 0
    
    def _next_step(self) -> int:
        """获取下一步骤编号"""
        self._step_counter += 1
        return self._step_counter
    
    def _emit_step(self, step: int, name: str, status: str, detail: str, extra: Optional[dict] = None):
        """触发步骤回调"""
        if self._step_callback:
            self._step_callback(step, name, status, detail, extra)
    
    def _check_data_updates(self):
        """检查数据文件夹是否有变更，必要时增量更新，每60秒最多检查一次"""
        import time
        now = time.time()
        if now - self._last_update_check < 60:
            return
        self._last_update_check = now

        try:
            from common.rag.data_loader.build_index import RAGDataBuilder
            builder = RAGDataBuilder()
            builder.incremental_update()
        except Exception as e:
            logger.warning(f"增量更新检查失败: {e}")

    def _build_messages_with_history(self, template_name: str, history_messages: list = None, **kwargs) -> list:
        """
        构建包含对话历史的LLM消息列表
        
        在 system 提示和当前用户问题之间插入对话历史，
        让 LLM 感知完整的对话上下文，实现多轮对话记忆。
        
        消息结构:
            [system_prompt, history_user_1, history_asst_1, ..., user_current_question]
        
        Args:
            template_name: prompt 模板名称
            history_messages: 对话历史（优先使用参数传递，避免并发覆盖）
            **kwargs: 模板变量
            
        Returns:
            list[dict]: 完整消息列表
        """
        messages = prompt_manager.build_messages(template_name, **kwargs)
        
        # 优先使用参数传递的history_messages，避免并发覆盖风险
        history = history_messages or getattr(self, '_history_messages', None)
        
        if not history:
            logger.debug(f"无对话历史，直接使用模板消息: template={template_name}")
            return messages
        
        # 详细日志：打印历史消息摘要
        history_summary = []
        for msg in history:
            role = msg.get("role", "unknown")
            content_preview = msg.get("content", "")[:30]
            history_summary.append(f"{role}:{content_preview}...")
        logger.info(f"注入对话历史到LLM: {len(history)}条消息, 模板={template_name}")
        logger.debug(f"历史消息摘要: {history_summary}")
        
        # messages 格式: [{"role": "system", ...}, {"role": "user", ...}]
        system_msg = messages[0] if messages and messages[0]["role"] == "system" else None
        user_msg = messages[-1] if messages else None
        
        new_messages = []
        if system_msg:
            new_messages.append(system_msg)
        
        # 在 system 和 user 之间插入对话历史
        for hist_msg in history:
            if hist_msg.get("role") in ["user", "assistant"]:
                new_messages.append({"role": hist_msg["role"], "content": hist_msg["content"]})
        
        if user_msg:
            new_messages.append(user_msg)
        
        logger.info(f"最终消息列表: {len(new_messages)}条 (system+{len(history)}history+user)")
        return new_messages

    # ==================== 非流式查询 (旧接口保持兼容) ====================

    def query(self, question: str) -> str:
        """
        完整的RAG查询流程
        
        Args:
            question: 用户问题
            
        Returns:
            回答文本
        """
        self.initialize()
        self._check_data_updates()
        self._reset_step_counter()
        
        # ====== 步骤1: 意图识别 ======
        step1 = self._next_step()
        self._emit_step(step1, "RAG意图识别", "running", f"正在识别问题意图: '{question}'")
        intent_result = self.intent_classifier.classify(question)
        
        intent_text = "通用问题" if intent_result["intent"] == "general" else "留学专业问题"
        self._emit_step(
            step1, "RAG意图识别", "success",
            f"识别结果: {intent_text} (置信度={intent_result['confidence']:.2f}, {intent_result['reason']})",
            {"intent": intent_result}
        )
        
        if intent_result["intent"] == "general":
            # 通用问题：直接调用LLM回答
            self._emit_step(step1 + 1, "LLM直接回答", "running", "通用问题，直接调用大模型回答")
            answer = self._answer_general_question(question)
            self._emit_step(step1 + 1, "LLM直接回答", "success", "回答生成完成")
            return answer
        
        # ====== 步骤2: 策略分析 ======
        step2 = self._next_step()
        self._emit_step(step2, "RAG策略分析", "running", "正在分析问题复杂度")
        strategy = self.strategy_selector.analyze(question)
        queries = self.strategy_selector.get_query_list(question, strategy)
        
        complexity_map = {"simple": "简单", "complex": "复杂", "abstract": "抽象"}
        complexity_text = complexity_map.get(strategy["complexity"], "未知")
        self._emit_step(
            step2, "RAG策略分析", "success",
            f"复杂度: {complexity_text} (置信度={strategy['confidence']:.2f})",
            {"strategy": strategy, "queries": queries}
        )
        
        if strategy["complexity"] == "simple":
            return self._simple_retrieve_and_answer(question)
        elif strategy["complexity"] == "complex":
            return self._complex_retrieve_and_answer(question, queries)
        else:
            return self._abstract_retrieve_and_answer(question, queries)
    
    def _answer_general_question(self, question: str, history_messages: list = None) -> str:
        """通用问题直接回答"""
        messages = self._build_messages_with_history("general_answer", history_messages=history_messages, question=question)
        return self.llm_client.chat(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME)
    
    def _simple_retrieve_and_answer(self, question: str, history_messages: list = None) -> str:
        """简单问题：直接检索后回答"""
        # 检索
        context = self._retrieve_context(question)
        
        if not context:
            return "抱歉，暂未找到相关信息。"
        
        # 生成回答
        step = self._next_step()
        self._emit_step(step, "LLM生成回答", "running", "正在基于检索上下文生成回答")
        messages = self._build_messages_with_history("rag_answer", history_messages=history_messages, context=context, question=question)
        answer = self.llm_client.chat(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME)
        self._emit_step(step, "LLM生成回答", "success", "回答生成完成")
        return answer
    
    def _complex_retrieve_and_answer(self, original_question: str, queries: List[str], history_messages: list = None) -> str:
        """复杂问题：多路检索后综合"""
        all_results = []
        total_queries = len(queries)

        # 批量编码所有子问题，避免每个子问题重复 encode
        step_vec = self._next_step()
        self._emit_step(step_vec, "bge-m3向量化", "running", f"正在批量编码 {total_queries} 个子问题...")
        dense_vecs, sparse_vecs = self.embedding_model.encode_texts(queries)
        if dense_vecs.size == 0:
            self._emit_step(step_vec, "bge-m3向量化", "error", "批量编码结果为空")
            logger.warning("批量编码结果为空")
            return "抱歉，暂未找到相关信息。"
        self._emit_step(step_vec, "bge-m3向量化", "success", f"批量编码 {total_queries} 个子问题完成, dense dim={dense_vecs.shape[1]}")

        for i, query in enumerate(queries):
            step = self._next_step()
            progress = f"{i+1}/{total_queries}"
            self._emit_step(step, f"子问题{i+1}检索", "running",
                f"检索: {query} ({progress})",
                {"progress": progress, "current": i+1, "total": total_queries}
            )
            context = self._retrieve_context_with_vectors(query, dense_vecs[i], sparse_vecs[i])
            if context:
                all_results.append({
                    "sub_question": query,
                    "context": context
                })
                self._emit_step(step, f"子问题{i+1}检索", "success",
                    f"检索到相关上下文 ({progress})",
                    {"progress": progress, "current": i+1, "total": total_queries}
                )
            else:
                self._emit_step(step, f"子问题{i+1}检索", "miss",
                    f"未检索到相关信息 ({progress})",
                    {"progress": progress, "current": i+1, "total": total_queries}
                )
        
        if not all_results:
            return "抱歉，暂未找到相关信息。"
        
        seen_contents = set()
        unique_results = []
        for result in all_results:
            content_hash = hash(result["context"][:100])
            if content_hash not in seen_contents:
                seen_contents.add(content_hash)
                unique_results.append(result)
        
        search_results_text = ""
        for idx, result in enumerate(unique_results):
            search_results_text += f"\n--- 关于「{result['sub_question']}」的检索结果 ---\n"
            search_results_text += result["context"]
        
        step = self._next_step()
        self._emit_step(step, "综合回答生成", "running", "正在综合多路检索结果生成回答")
        messages = self._build_messages_with_history(
            "synthesize_answer",
            history_messages=history_messages,
            original_question=original_question,
            search_results=search_results_text
        )
        answer = self.llm_client.chat(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME)
        self._emit_step(step, "综合回答生成", "success", f"综合 {len(all_results)} 路检索结果生成回答")
        
        return answer
    
    def _abstract_retrieve_and_answer(self, original_question: str, queries: List[str], history_messages: list = None) -> str:
        """抽象问题：转换后检索"""
        return self._complex_retrieve_and_answer(original_question, queries, history_messages)
    
    def _retrieve_context(self, query: str) -> str:
        """
        检索上下文（含父块去重）

        流程:
        1. query -> bge-m3 编码得到稠密+稀疏向量
        2. 混合检索(Milvus) -> top10
        3. Reranker精排序 -> top3
        4. 获取父分块文本（去重）

        Args:
            query: 查询问题

        Returns:
            上下文文本(拼接后的父分块)
        """
        # 1. 编码
        step = self._next_step()
        self._emit_step(step, "bge-m3向量化", "running", "正在对查询进行向量化编码...")
        dense_vecs, sparse_vecs = self.embedding_model.encode_texts([query])
        if dense_vecs.size == 0:
            self._emit_step(step, "bge-m3向量化", "error", "编码结果为空")
            logger.warning("编码结果为空")
            return ""
        self._emit_step(step, "bge-m3向量化", "success", f"编码完成, dense dim={dense_vecs.shape[1]}")

        return self._retrieve_context_with_vectors(query, dense_vecs[0], sparse_vecs[0])

    def _retrieve_context_with_vectors(self, query: str, query_dense: np.ndarray, query_sparse: dict) -> str:
        """
        使用预计算向量检索上下文（含父块去重）

        流程:
        1. 混合检索(Milvus) -> top10
        2. Reranker精排序 -> top3
        3. 获取父分块文本（去重）

        Args:
            query: 查询问题（仅用于 Reranker 和日志）
            query_dense: 预计算的稠密向量
            query_sparse: 预计算的稀疏向量

        Returns:
            上下文文本(拼接后的父分块)
        """
        # 1. 向量化步骤：使用预计算向量，标记为 skip
        step_vec = self._next_step()
        self._emit_step(step_vec, "bge-m3向量化", "skip", "使用预计算向量")

        # 2. 混合粗排
        step = self._next_step()
        self._emit_step(step, "Milvus混合粗排", "running",
            f"正在检索(dense_weight={RAGConfig.DENSE_VECTOR_WEIGHT}, sparse_weight={RAGConfig.SPARSE_VECTOR_WEIGHT})")
        coarse_results = self.milvus_manager.search_hybrid(
            query_dense=query_dense,
            query_sparse=query_sparse,
            top_k=RAGConfig.COARSE_TOP_K
        )

        if not coarse_results:
            self._emit_step(step, "Milvus混合粗排", "miss", "粗排无结果")
            logger.warning("粗排无结果")
            return ""

        self._emit_step(step, "Milvus混合粗排", "success", f"粗排返回 {len(coarse_results)} 条结果")

        # 3. Reranker精排
        step = self._next_step()
        self._emit_step(step, "bge-reranker精排", "running",
            f"正在精排序(top{RAGConfig.COARSE_TOP_K} -> top{RAGConfig.RERANK_TOP_K})")
        reranked = self.reranker.rerank(
            query=query,
            passages=coarse_results,
            top_k=RAGConfig.RERANK_TOP_K
        )
        self._emit_step(step, "bge-reranker精排", "success", f"精排完成, 保留 {len(reranked)} 条结果")

        # 4. 获取父分块文本并拼接（已按parent_id去重），取前3个
        parent_infos = self._get_parent_texts(reranked)
        parent_infos = parent_infos[:RAGConfig.FINAL_TOP_K]

        if not parent_infos:
            return ""

        # 拼接上下文，包含时间戳信息供 agent 判断时效性
        import datetime
        context_parts = []
        for info in parent_infos:
            parent_text = info["parent_text"]
            created_at = info["created_at"]
            age_days = info["age_days"]

            # 格式化具体日期字符串
            date_str = datetime.datetime.fromtimestamp(created_at).strftime("%Y-%m-%d")

            if age_days == 0:
                freshness = "今天"
            elif age_days < 30:
                freshness = f"{age_days}天前"
            elif age_days < 365:
                months = age_days // 30
                freshness = f"约{months}个月前"
            else:
                years = age_days // 365
                freshness = f"约{years}年前，请注意时效性"

            time_note = f"[信息时间：{date_str} ({freshness})]"

            context_parts.append(f"{time_note}\n{parent_text}")

        context = "\n\n---\n\n".join(context_parts)
        self._emit_step(self._next_step(), "获取父分块上下文", "success",
            f"去重后取前{len(parent_infos)}个父块作为最终上下文")

        return context
    
    def _get_parent_texts(self, results: List[dict]) -> List[dict]:
        """
        从检索结果中直接获取父分块文本和创建时间

        返回包含 parent_text、created_at 的字典列表
        """
        import time
        parent_infos = []
        seen_parent_ids = set()

        for result in results:
            parent_id = result.get("parent_id")
            if not parent_id or parent_id in seen_parent_ids:
                continue

            seen_parent_ids.add(parent_id)

            # 直接从结果中读取 parent_text 和 created_at
            parent_text = result.get("parent_text", "")
            created_at = result.get("created_at", 0)

            # 计算信息年龄（天）
            age_days = 0
            if created_at > 0:
                age_days = (int(time.time()) - created_at) // 86400

            if parent_text:
                parent_infos.append({
                    "parent_id": parent_id,
                    "parent_text": parent_text,
                    "created_at": created_at,
                    "age_days": age_days
                })

        return parent_infos

    # ==================== 流式查询（API使用） ====================

    def query_stream(
        self,
        question: str,
        stream_callback: Callable[[str], None] = None,
        step_callback: StepCallback = None,
        history_messages: list = None,
        return_context: bool = False
    ):
        """
        完整的RAG查询流程（流式输出）
        
        支持传入对话历史，实现多轮对话上下文记忆。
        
        Args:
            question: 用户问题
            stream_callback: 流式回调函数，每个token调用一次
            step_callback: 步骤回调函数，用于推送执行过程
            history_messages: 对话历史消息列表，格式 [{role, content}, ...]
            
        Returns:
            回答文本
        """
        # 保存对话历史作为备用（优先使用参数传递）
        self._history_messages = history_messages
        if history_messages:
            logger.info(f"RAG查询带对话历史: {len(history_messages)} 条历史消息")
        
        # 设置步骤回调
        if step_callback:
            self.set_step_callback(step_callback)

        self.initialize()
        self._check_data_updates()
        self._reset_step_counter()
        self._stream_callback = stream_callback

        # ====== 步骤0: 查询改写（上下文补全） ======
        # 当存在对话历史时，将追问改写为完整问题
        rewritten_question = question
        original_question = question
        if history_messages and len(history_messages) > 0:
            step0 = self._next_step()
            self._emit_step(step0, "查询改写", "running", "正在将追问改写为完整问题...")
            rewritten_question = self._rewrite_query_with_history(question, history_messages)
            self._emit_step(
                step0, "查询改写", "success",
                f"改写完成: '{question}' → '{rewritten_question}'",
                {"original": question, "rewritten": rewritten_question}
            )
            question = rewritten_question

        # ====== 快速路径：简单问题直接回答（规则判断，跳过LLM意图识别） ======
        # 对于明显的通用问题（问候、感谢、告别等），直接调用LLM回答，跳过意图识别和策略分析
        # 大幅减少简单问题的响应时间
        SIMPLE_GENERAL_PATTERNS = [
            "你好", "hello", "hi", "嗨", "哈喽", "早上好", "下午好", "晚上好", "在吗", "您好", "喂",
            "谢谢", "多谢", "thank you", "thanks", "感谢", "辛苦了", "好的", "收到", "知道了",
            "再见", "拜拜", "bye", "goodbye", "晚安", "明天见", "回头见",
            "嗯", "哦", "啊", "好", "行", "可以", "没问题", "是的", "对",
        ]
        
        is_simple_general = any(pattern in original_question.lower() for pattern in SIMPLE_GENERAL_PATTERNS)

        # 快速路径仅对明确问候/客套等通用短句生效；短问题若包含留学专业关键词仍需走检索
        if is_simple_general:
            step_fast = self._next_step()
            self._emit_step(step_fast, "快速路径", "running", f"检测到简单通用问题，直接调用LLM回答")
            answer = self._answer_general_question_stream(original_question, stream_callback, history_messages)
            self._emit_step(step_fast, "快速路径", "success", "快速回复完成")
            if return_context:
                return {"answer": answer, "context": None}
            return answer

        # ====== 步骤1: 意图识别 ======
        step1 = self._next_step()
        self._emit_step(step1, "RAG意图识别", "running", f"正在识别问题意图: '{question}'")
        intent_result = self.intent_classifier.classify(question)

        intent_text = "通用问题" if intent_result["intent"] == "general" else "留学专业问题"
        self._emit_step(
            step1, "RAG意图识别", "success",
            f"识别结果: {intent_text} (置信度={intent_result['confidence']:.2f}, {intent_result['reason']})",
            {"intent": intent_result}
        )

        if intent_result["intent"] == "general":
            # 通用问题：直接调用LLM回答（流式）
            # 注意：通用问题使用原始用户输入，不使用改写后的问题
            self._emit_step(step1 + 1, "LLM直接回答", "running", "通用问题，直接调用大模型回答")
            answer = self._answer_general_question_stream(original_question, stream_callback, history_messages)
            self._emit_step(step1 + 1, "LLM直接回答", "success", "回答生成完成")
            if return_context:
                return {"answer": answer, "context": None}
            return answer

        # ====== 步骤2: 策略分析 ======
        step2 = self._next_step()
        self._emit_step(step2, "RAG策略分析", "running", "正在分析问题复杂度")
        strategy = self.strategy_selector.analyze(question)
        queries = self.strategy_selector.get_query_list(question, strategy)

        complexity_map = {"simple": "简单", "complex": "复杂", "abstract": "抽象"}
        complexity_text = complexity_map.get(strategy["complexity"], "未知")
        self._emit_step(
            step2, "RAG策略分析", "success",
            f"复杂度: {complexity_text} (置信度={strategy['confidence']:.2f})",
            {"strategy": strategy, "queries": queries}
        )

        if strategy["complexity"] == "simple":
            return self._simple_retrieve_and_answer_stream(question, stream_callback, history_messages, return_context)
        elif strategy["complexity"] == "complex":
            return self._complex_retrieve_and_answer_stream(question, queries, stream_callback, history_messages, return_context)
        else:
            return self._abstract_retrieve_and_answer_stream(question, queries, stream_callback, history_messages, return_context)

    def _answer_general_question_stream(self, question: str, stream_callback: Callable[[str], None] = None, history_messages: list = None) -> str:
        """通用问题直接回答（流式）- 带对话历史"""
        messages = self._build_messages_with_history("general_answer", history_messages=history_messages, question=question)
        answer = ""
        first_chunk = True
        for chunk in self.llm_client.chat_stream(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME):
            if first_chunk and self._stream_callback:
                first_chunk = False
            answer += chunk
            if stream_callback:
                stream_callback(chunk)
        return answer

    def _simple_retrieve_and_answer_stream(self, question: str, stream_callback: Callable[[str], None] = None, history_messages: list = None, return_context: bool = False):
        """简单问题：直接检索后回答（流式）- 带对话历史"""
        # 检索
        context = self._retrieve_context(question)

        if not context:
            if return_context:
                return {"answer": "抱歉，暂未找到相关信息。", "context": None}
            return "抱歉，暂未找到相关信息。"

        # 生成回答（流式）
        step = self._next_step()
        self._emit_step(step, "LLM生成回答", "running", "正在基于检索上下文生成回答")
        messages = self._build_messages_with_history("rag_answer", history_messages=history_messages, context=context, question=question)
        answer = ""
        first_chunk = True
        for chunk in self.llm_client.chat_stream(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME):
            if first_chunk and self._stream_callback:
                first_chunk = False
            answer += chunk
            if stream_callback:
                stream_callback(chunk)
        self._emit_step(step, "LLM生成回答", "success", "回答生成完成")
        if return_context:
            return {"answer": answer, "context": context}
        return answer

    def _complex_retrieve_and_answer_stream(self, original_question: str, queries: List[str], stream_callback: Callable[[str], None] = None, history_messages: list = None, return_context: bool = False):
        """复杂问题：多路检索后综合（流式）- 带对话历史"""
        all_results = []
        total_queries = len(queries)

        # 批量编码所有子问题，避免每个子问题重复 encode
        step_vec = self._next_step()
        self._emit_step(step_vec, "bge-m3向量化", "running", f"正在批量编码 {total_queries} 个子问题...")
        dense_vecs, sparse_vecs = self.embedding_model.encode_texts(queries)
        if dense_vecs.size == 0:
            self._emit_step(step_vec, "bge-m3向量化", "error", "批量编码结果为空")
            logger.warning("批量编码结果为空")
            return "抱歉，暂未找到相关信息。"
        self._emit_step(step_vec, "bge-m3向量化", "success", f"批量编码 {total_queries} 个子问题完成, dense dim={dense_vecs.shape[1]}")

        for i, query in enumerate(queries):
            step = self._next_step()
            progress = f"{i+1}/{total_queries}"
            self._emit_step(step, f"子问题{i+1}检索", "running",
                f"检索: {query} ({progress})",
                {"progress": progress, "current": i+1, "total": total_queries}
            )
            context = self._retrieve_context_with_vectors(query, dense_vecs[i], sparse_vecs[i])
            if context:
                all_results.append({
                    "sub_question": query,
                    "context": context
                })
                self._emit_step(step, f"子问题{i+1}检索", "success",
                    f"检索到相关上下文 ({progress})",
                    {"progress": progress, "current": i+1, "total": total_queries}
                )
            else:
                self._emit_step(step, f"子问题{i+1}检索", "miss",
                    f"未检索到相关信息 ({progress})",
                    {"progress": progress, "current": i+1, "total": total_queries}
                )

        if not all_results:
            return "抱歉，暂未找到相关信息。"

        seen_contents = set()
        unique_results = []
        for result in all_results:
            content_hash = hash(result["context"][:100])
            if content_hash not in seen_contents:
                seen_contents.add(content_hash)
                unique_results.append(result)

        search_results_text = ""
        for idx, result in enumerate(unique_results):
            search_results_text += f"\n--- 关于「{result['sub_question']}」的检索结果 ---\n"
            search_results_text += result["context"]

        step = self._next_step()
        self._emit_step(step, "综合回答生成", "running", "正在综合多路检索结果生成回答")
        messages = self._build_messages_with_history(
            "synthesize_answer",
            history_messages=history_messages,
            original_question=original_question,
            search_results=search_results_text
        )
        answer = ""
        first_chunk = True
        for chunk in self.llm_client.chat_stream(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME):
            if first_chunk and self._stream_callback:
                first_chunk = False
            answer += chunk
            if stream_callback:
                stream_callback(chunk)
        self._emit_step(step, "综合回答生成", "success", f"综合 {len(all_results)} 路检索结果生成回答")

        return answer

    def _abstract_retrieve_and_answer_stream(self, original_question: str, queries: List[str], stream_callback: Callable[[str], None] = None, history_messages: list = None) -> str:
        """抽象问题：转换后检索（流式）"""
        return self._complex_retrieve_and_answer_stream(original_question, queries, stream_callback, history_messages)
    
    def _rewrite_query_with_history(self, question: str, history_messages: list) -> str:
        """
        查询改写：将对话中的追问改写为独立完整问题
        
        Args:
            question: 用户追问
            history_messages: 对话历史
            
        Returns:
            改写后的完整问题
        """
        # 构建历史摘要
        history_summary = ""
        for msg in history_messages[-6:]:  # 只取最近6条，避免过长
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:100]  # 截取前100字符
            history_summary += f"{role}: {content}\n"
        
        try:
            messages = prompt_manager.build_messages(
                "query_rewrite",
                history_summary=history_summary,
                question=question
            )
            
            rewritten = self.llm_client.chat(messages=messages, model=RAGConfig.GENERATION_MODEL_NAME)
            rewritten = rewritten.strip()
            
            # 如果改写结果为空或太短，返回原问题
            if not rewritten or len(rewritten) < len(question):
                logger.warning(f"查询改写结果异常，使用原问题: {rewritten}")
                return question
            
            logger.info(f"查询改写成功: '{question}' → '{rewritten}'")
            return rewritten
            
        except Exception as e:
            logger.error(f"查询改写失败: {e}")
            return question

    # ====== 阶段5异步化改造：异步版query和query_stream（保留同步方法不变） ======

    async def async_query(self, question: str, history_messages: list = None) -> str:
        """异步版非流式RAG查询（通过asyncio.to_thread包装）

        Args:
            question: 用户问题
            history_messages: 对话历史消息列表

        Returns:
            回答文本
        """
        return await asyncio.to_thread(self.query, question)

    async def async_query_stream(
        self,
        question: str,
        stream_callback=None,
        step_callback=None,
        history_messages: list = None,
        return_context: bool = False
    ):
        """
        异步版流式RAG查询

        使用 threading.Thread + asyncio.Queue 桥接同步线程和异步协程，
        让 RAG 检索在后台线程中运行，token 和步骤回调通过异步队列桥接到主协程。

        Args:
            question: 用户问题
            stream_callback: 流式token回调
            step_callback: 步骤回调
            history_messages: 对话历史消息列表
            return_context: 是否返回上下文

        Returns:
            回答文本（或包含上下文的字典）
        """
        stream_queue = asyncio.Queue()
        step_queue = asyncio.Queue()
        result_container = [None]
        error_container = [None]

        def sync_wrapper():
            """同步线程中运行query_stream"""
            try:
                result = self.query_stream(
                    question,
                    stream_callback=lambda token: asyncio.run_coroutine_threadsafe(
                        stream_queue.put({"type": "token", "content": token}),
                        asyncio.get_event_loop()
                    ),
                    step_callback=lambda step, name, status, detail, extra=None: asyncio.run_coroutine_threadsafe(
                        step_queue.put({"step": step, "name": name, "status": status, "detail": detail, "extra": extra}),
                        asyncio.get_event_loop()
                    ),
                    history_messages=history_messages,
                    return_context=return_context,
                )
                result_container[0] = result
            except Exception as e:
                error_container[0] = e
            finally:
                asyncio.run_coroutine_threadsafe(stream_queue.put(None), asyncio.get_event_loop())
                asyncio.run_coroutine_threadsafe(step_queue.put(None), asyncio.get_event_loop())

        thread = threading.Thread(target=sync_wrapper)
        thread.start()

        # 消费流式队列 - 通过stream_callback输出
        stream_done = False
        step_done = False

        while not (stream_done and step_done):
            # 处理步骤回调
            if not step_done:
                try:
                    step_info = await asyncio.wait_for(step_queue.get(), timeout=0.05)
                    if step_info is None:
                        step_done = True
                    elif step_callback:
                        step_callback(step_info["step"], step_info["name"], step_info["status"], step_info["detail"], step_info.get("extra"))
                except asyncio.TimeoutError:
                    pass

            # 处理流式token
            if not stream_done:
                try:
                    evt = await asyncio.wait_for(stream_queue.get(), timeout=0.05)
                    if evt is None:
                        stream_done = True
                    elif evt["type"] == "token" and stream_callback:
                        stream_callback(evt["content"])
                except asyncio.TimeoutError:
                    pass

        thread.join(timeout=5)

        if error_container[0]:
            raise error_container[0]

        return result_container[0]


rag_retriever = RAGRetriever()
