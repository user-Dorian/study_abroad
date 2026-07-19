"""RAG检索器 - 多级检索系统（v2: 本地模型路径 + 两阶段排序）

v2 关键变更：
1. 优先使用 .env 中配置的本地模型路径（bge-m3 + bge-reranker-v2-m3）
2. 两阶段排序：
   - L3a 粗排序：bge-m3 向量检索 Milvus，取 top 50
   - L3b 精排序：bge-reranker-v2-m3 重排序，按 RERANK_SCORE_THRESHOLD 过滤，取 top 10
3. 失败冷却：避免每次请求都尝试连接 HuggingFace 导致卡顿
4. 线程锁：防止并发重复加载模型
5. 保存精排序结果到 _last_fine_results 供 state 使用
"""
import os
import time
import threading
from typing import List, Dict, Any, Optional

from backend.common.basics.utils.logger import logger
from ..rag_config import RAGConfig
from ..data_loader.chunk_and_embed import get_milvus_manager


# 初始化失败冷却时间（秒）：失败后5分钟内不再重试
_INIT_FAILURE_COOLDOWN = 300


class RAGRetriever:
    """RAG检索器 - 多级检索策略（v2）

    特性：
    - 本地模型路径优先加载（bge-m3 / bge-reranker-v2-m3）
    - 两阶段排序：L3a 向量粗排 → L3b reranker 精排
    - 模型预热
    - 线程锁防止并发重复加载
    - 失败冷却机制
    """

    def __init__(self):
        """初始化RAG检索器"""
        self._embedding_model = None  # type: Optional[Any]
        self._reranker = None  # type: Optional[Any]
        self._initialized = False
        self._init_failed = False
        self._init_failure_time = 0.0
        self._lock = threading.Lock()
        # 保存最近一次精排序结果，供 retrieval_state.fine_results 使用
        self._last_fine_results: List[Dict[str, Any]] = []

    def initialize(self):
        """初始化模型和连接（线程安全）

        失败时不抛异常，仅记录日志并标记 _init_failed，
        让 query() 走降级路径返回 None。
        """
        with self._lock:
            if self._initialized:
                return

            # 冷却期内直接返回
            if self._init_failed and (time.time() - self._init_failure_time) < _INIT_FAILURE_COOLDOWN:
                return

            try:
                # 延迟导入
                try:
                    from sentence_transformers import SentenceTransformer, CrossEncoder
                except ImportError:
                    logger.warning("sentence-transformers未安装，RAG检索器将降级")
                    self._initialized = True
                    return

                # 加载 Embedding 模型（bge-m3）
                emb_model = RAGConfig.EMBEDDING_MODEL_NAME
                emb_local = RAGConfig.EMBEDDING_IS_LOCAL_PATH
                logger.info(
                    f"加载Embedding模型: {emb_model} "
                    f"({'本地路径' if emb_local else 'HF模型名'})"
                )
                self._embedding_model = SentenceTransformer(
                    emb_model,
                    cache_folder=os.getenv('TRANSFORMERS_CACHE', None),
                    local_files_only=emb_local  # 本地路径时强制只读本地
                )
                logger.info(
                    f"Embedding模型加载成功: "
                    f"dim={self._embedding_model.get_sentence_embedding_dimension()}"
                )

                # 加载 Reranker 模型（bge-reranker-v2-m3）
                reranker_model = RAGConfig.RERANKER_MODEL_NAME
                reranker_local = RAGConfig.RERANKER_IS_LOCAL_PATH
                logger.info(
                    f"加载Reranker模型: {reranker_model} "
                    f"({'本地路径' if reranker_local else 'HF模型名'})"
                )
                self._reranker = CrossEncoder(
                    reranker_model,
                    cache_folder=os.getenv('TRANSFORMERS_CACHE', None),
                    local_files_only=reranker_local,
                    max_length=512
                )
                logger.info("Reranker模型加载成功")

                self._initialized = True
                self._init_failed = False

            except Exception as e:
                logger.error(f"RAG检索器初始化失败（5分钟内不再重试）: {e}", exc_info=True)
                self._init_failed = True
                self._init_failure_time = time.time()

    def warmup(self):
        """预热模型（避免首次请求卡顿）"""
        if not self._initialized:
            self.initialize()

        try:
            logger.info("开始预热Embedding模型...")
            test_text = "留学申请条件"
            embedding = self._embedding_model.encode([test_text])
            logger.info(f"Embedding模型预热完成: shape={embedding.shape}")

            if self._reranker:
                logger.info("开始预热Reranker模型...")
                scores = self._reranker.predict([("GPA要求", "美国研究生GPA一般要求3.0以上")])
                logger.info(f"Reranker模型预热完成: score={float(scores[0]):.4f}")

        except Exception as e:
            logger.warning(f"模型预热失败: {e}")

    def encode(self, texts: List[str]) -> List[List[float]]:
        """将文本编码为向量

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: 向量列表
        """
        if not self._initialized:
            self.initialize()

        if self._embedding_model is None:
            logger.warning("Embedding模型未加载，返回空向量")
            return [[0.0] * RAGConfig.EMBEDDING_DIMENSION for _ in texts]

        try:
            embeddings = self._embedding_model.encode(
                texts,
                batch_size=RAGConfig.EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True  # bge-m3 推荐 L2 归一化
            )
            return embeddings.tolist()

        except Exception as e:
            logger.error(f"文本编码失败: {e}", exc_info=True)
            raise

    def query(self, question: str, top_k: int = None) -> Optional[str]:
        """执行向量检索 + 两阶段排序

        v2 流程：
            L3a: bge-m3 编码 → Milvus 向量检索 top 50（粗排序）
            L3b: bge-reranker-v2-m3 重排序 → 阈值过滤 → top 10（精排序）
            返回拼接后的上下文文本

        Args:
            question: 用户问题
            top_k: 最终返回的结果数（默认 RAGConfig.RERANK_TOP_K）

        Returns:
            Optional[str]: 检索结果文本（拼接），无结果时返回 None
        """
        final_k = top_k or RAGConfig.RERANK_TOP_K
        self._last_fine_results = []  # 清空上一次结果

        try:
            if not self._initialized:
                self.initialize()

            if self._embedding_model is None:
                logger.warning("Embedding模型未加载，无法执行向量检索")
                return None

            # ====== L3a: 粗排序 - bge-m3 向量检索 Milvus（取 COARSE_TOP_K） ======
            coarse_k = RAGConfig.COARSE_TOP_K
            logger.info(f"[RAG检索] L3a 粗排序: 向量检索 top {coarse_k}")

            query_embedding = self.encode([question])[0]

            milvus = get_milvus_manager()
            coarse_results = milvus.search(query_embedding, coarse_k)

            if not coarse_results:
                logger.info("[RAG检索] L3a 粗排序无结果")
                return None

            logger.info(f"[RAG检索] L3a 粗排序命中 {len(coarse_results)} 条")

            # ====== L3b: 精排序 - bge-reranker 重排序 ======
            if not self._reranker:
                logger.warning("[RAG检索] Reranker未加载，使用粗排序结果（截断到 top_k）")
                fine_results = coarse_results[:final_k]
            else:
                fine_results = self._rerank(question, coarse_results, final_k)

            if not fine_results:
                logger.info("[RAG检索] L3b 精排序后无结果（阈值过滤）")
                return None

            # 保存精排序结果（供 state 使用）
            self._last_fine_results = fine_results

            # 拼接上下文
            context_parts = []
            for i, result in enumerate(fine_results, 1):
                q = result.get("question", "") or ""
                a = result.get("answer", "") or ""
                rerank_score = result.get("rerank_score")
                score_str = f" (score={rerank_score:.3f})" if rerank_score is not None else ""
                context_parts.append(f"【参考{i}】{score_str}\n问题：{q}\n答案：{a}")

            context = "\n\n".join(context_parts)
            logger.info(
                f"[RAG检索] 完成: 返回 {len(fine_results)} 条, "
                f"context_len={len(context)}"
            )

            return context

        except Exception as e:
            logger.error(f"[RAG检索] 检索失败: {e}", exc_info=True)
            return None

    def _rerank(
        self,
        question: str,
        coarse_results: List[Dict[str, Any]],
        final_k: int
    ) -> List[Dict[str, Any]]:
        """L3b: 使用 bge-reranker 精排序

        Args:
            question: 查询文本
            coarse_results: L3a 粗排序结果
            final_k: 最终返回数量

        Returns:
            List[Dict]: 精排序 + 阈值过滤后的结果
        """
        try:
            # 构建 query-document 对
            # bge-reranker-v2-m3 输入为 (query, document)
            pairs = []
            for r in coarse_results:
                # 拼接 question + answer 作为 document
                q = r.get("question", "") or ""
                a = r.get("answer", "") or ""
                document = f"{q}\n{a}" if q and a else (q or a)
                pairs.append((question, document))

            # 批量计算相关性分数
            scores = self._reranker.predict(pairs, show_progress_bar=False)

            # 附加分数
            scored_results = []
            for r, score in zip(coarse_results, scores):
                scored_results.append({
                    **r,
                    "rerank_score": float(score)
                })

            # 按分数降序排序
            scored_results.sort(key=lambda x: x["rerank_score"], reverse=True)

            # 阈值过滤
            threshold = RAGConfig.RERANK_SCORE_THRESHOLD
            filtered = [
                r for r in scored_results
                if r["rerank_score"] >= threshold
            ]

            # 如果阈值过滤后为空，但原结果不为空，则保留 top_k（避免完全空结果）
            if not filtered and scored_results:
                logger.warning(
                    f"[RAG检索] 所有结果分数低于阈值({threshold})，保留top{final_k}"
                )
                filtered = scored_results[:final_k]

            top_results = filtered[:final_k]

            if top_results:
                logger.info(
                    f"[RAG检索] L3b 精排序: "
                    f"top1_score={top_results[0]['rerank_score']:.4f}, "
                    f"top{final_k}_score={top_results[-1]['rerank_score']:.4f}, "
                    f"返回{len(top_results)}条"
                )

            return top_results

        except Exception as e:
            logger.warning(f"[RAG检索] Rerank失败，使用粗排序结果: {e}")
            return coarse_results[:final_k]

    # ==================================================================
    # 公共访问方法（供外部异步节点使用，避免直接访问私有属性）
    # ==================================================================

    def is_ready(self) -> bool:
        """检查 Embedding 模型是否已加载就绪

        Returns:
            bool: True 表示模型可用，可执行向量检索；False 表示需走兜底
        """
        return self._initialized and self._embedding_model is not None

    def get_last_fine_results(self) -> List[Dict[str, Any]]:
        """获取最近一次 query() 的精排序结果

        供 retrieval_state.fine_results 使用，方便上层 state 追踪检索细节。

        Returns:
            List[Dict[str, Any]]: 精排序结果列表（可能为空）
        """
        return list(self._last_fine_results) if self._last_fine_results else []


# 全局单例
rag_retriever = RAGRetriever()
