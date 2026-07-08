"""ConsultantQueryHandler - 规划师端查询处理器，提供Redis缓存、BM25匹配、数据库查询、RAG检索等底层能力"""
import redis
import psycopg2
import psycopg2.extras
import psycopg2.pool
import threading
import numpy as np
from typing import Optional, Tuple
from common.retrieval.bm25_retriever import BM25Retriever
from common.retrieval.bm25_index_builder import BM25IndexBuilder
from consultant.config.redis_config import ConsultantRedisConfig
from consultant.config.database import ConsultantDatabaseConfig
from common.rag.models.llm_client import llm_client, LLMClient
from consultant.rag.prompts.prompt_template import consultant_prompt_manager
from common.utils.logger import logger


class ConsultantQueryHandler:
    """规划师端查询处理器，提供多级检索的底层能力"""

    # 全局数据库连接池（类级别，所有实例共享）
    _db_pool_instance = None
    _pool_lock = threading.Lock()

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        bm25_retriever: Optional[BM25Retriever] = None,
        db_available: Optional[bool] = None,
    ):
        """
        初始化ConsultantQueryHandler，建立Redis、BM25、数据库连接

        Args:
            redis_client: 已初始化的Redis客户端，传入则复用，不传则自行创建
            bm25_retriever: 已加载的BM25Retriever实例，传入则复用，不传则自行加载
            db_available: 数据库是否可用（已由外部验证），传入则复用，不传则自行验证
        """
        self.redis_client: Optional[redis.Redis] = None
        self.bm25_retriever: Optional[BM25Retriever] = None
        self.db_pool = None

        # 优先复用外部传入的组件
        if redis_client is not None:
            self.redis_client = redis_client
            logger.info("ConsultantQueryHandler复用外部Redis连接")
        else:
            self._init_redis()

        if bm25_retriever is not None:
            self.bm25_retriever = bm25_retriever
            logger.info("ConsultantQueryHandler复用外部BM25检索器")
        else:
            self._init_bm25()

        if db_available is not None:
            self.db_pool = db_available
            logger.info(f"ConsultantQueryHandler复用外部数据库状态: {'可用' if db_available else '不可用'}")
        else:
            self._init_db_pool()

    def _init_redis(self):
        """初始化Redis连接"""
        try:
            if not ConsultantRedisConfig.validate():
                logger.warning("Redis配置不完整，Redis功能将不可用")
                return

            self.redis_client = redis.Redis(**ConsultantRedisConfig.get_connection_params())
            self.redis_client.ping()
            logger.info("Redis连接成功")
        except redis.ConnectionError as e:
            logger.warning(f"Redis连接失败，将降级到其他检索方式: {e}")
            self.redis_client = None
        except Exception as e:
            logger.error(f"Redis初始化异常: {e}")
            self.redis_client = None

    def _init_bm25(self):
        """初始化BM25检索器，优先从缓存加载，缓存不存在则重建"""
        try:
            self.bm25_retriever = BM25Retriever()
            # 优先从缓存文件加载
            if self.bm25_retriever.load_index():
                logger.info(f"BM25检索器从缓存加载成功，索引 {len(self.bm25_retriever.questions)} 个问题")
            else:
                # 缓存不存在则重建
                logger.info("BM25缓存文件不存在，开始重建索引...")
                builder = BM25IndexBuilder()
                self.bm25_retriever = builder.initialize()
                if self.bm25_retriever and self.bm25_retriever.is_loaded:
                    logger.info(f"BM25检索器重建成功，索引 {len(self.bm25_retriever.questions)} 个问题")
                else:
                    logger.warning("BM25检索器重建失败")
        except Exception as e:
            logger.error(f"BM25检索器初始化异常: {e}")
            self.bm25_retriever = None

    def _init_db_pool(self):
        """创建数据库连接池"""
        try:
            if not ConsultantDatabaseConfig.validate():
                logger.warning("数据库配置不完整")
                return

            if ConsultantQueryHandler._db_pool_instance is None:
                with ConsultantQueryHandler._pool_lock:
                    if ConsultantQueryHandler._db_pool_instance is None:
                        conn_params = ConsultantDatabaseConfig.get_connection_params()
                        ConsultantQueryHandler._db_pool_instance = psycopg2.pool.SimpleConnectionPool(
                            minconn=1,
                            maxconn=5,
                            **conn_params
                        )
                        logger.info("数据库连接池创建成功 (min=1, max=5)")

            self.db_pool = ConsultantQueryHandler._db_pool_instance is not None
            if self.db_pool:
                logger.info("数据库连接池可用")
        except Exception as e:
            logger.error(f"数据库连接池创建异常: {e}")
            self.db_pool = False

    def redis_exact_match(self, question: str) -> Optional[str]:
        """
        Redis检索结果精确匹配（只缓存检索结果，不缓存LLM回答）
        
        Args:
            question: 用户输入的问题

        Returns:
            匹配到的检索结果（来自SQL/RAG的原始数据），未命中返回None
        """
        if not self.redis_client:
            logger.debug("Redis客户端不可用，跳过检索结果匹配")
            return None

        try:
            key = f"{ConsultantRedisConfig.KEY_PREFIX_RETRIEVAL}{question}"
            result = self.redis_client.get(key)

            if result:
                self.redis_client.expire(key, ConsultantRedisConfig.TTL)
                logger.info(f"Redis检索结果命中: {question}")
                return result
            else:
                logger.debug(f"Redis检索结果未命中: {question}")
                return None
        except Exception as e:
            logger.error(f"Redis检索结果匹配异常: {e}")
            return None

    def bm25_match_with_softmax(
        self,
        question: str,
        top_k: int = 3,
        threshold: float = 0.7,
        min_results: int = 2,
        min_score: float = 3.0,
        temperature: float = 1.0,
    ) -> Tuple[Optional[str], float]:
        """
        BM25检索 + Softmax概率分布判断

        Args:
            question: 用户输入的问题
            top_k: BM25返回的top-k结果数量
            threshold: Softmax概率阈值，达到此值认为匹配成功
            min_results: 最少需要的结果数量，防止单结果时softmax为1.0的误判
            min_score: 最低BM25绝对得分阈值，低于此值认为语义无关
            temperature: Softmax温度参数，控制概率分布的平滑度

        Returns:
            (匹配的问题文本, 最高概率值)。未匹配时问题文本为None
        """
        if not self.bm25_retriever or not self.bm25_retriever.is_loaded:
            logger.warning("BM25检索器不可用")
            return None, 0.0

        try:
            # BM25检索
            results = self.bm25_retriever.search(question, top_k=top_k)
            if not results:
                logger.debug(f"BM25检索无结果: {question}")
                return None, 0.0

            # 过滤绝对得分过低的结果（防止停用词残留导致的误匹配）
            results = [r for r in results if r[1] >= min_score]
            if not results:
                logger.debug(
                    f"BM25所有结果得分低于阈值({min_score}): {question}"
                )
                return None, 0.0

            # 结果数量不足时拒绝（防止单结果softmax=1.0的误判）
            if len(results) < min_results:
                logger.debug(
                    f"BM25结果数量不足({len(results)}<{min_results}): {question}"
                )
                return None, 0.0

            # 提取分数
            scores = [r[1] for r in results]

            # 计算Softmax概率分布
            scores_array = np.array(scores) / temperature
            exp_scores = np.exp(scores_array - np.max(scores_array))
            probs = exp_scores / exp_scores.sum()

            top_prob = float(probs[0])
            matched_question = results[0][2] if results else None

            if top_prob >= threshold:
                logger.info(
                    f"BM25匹配成功(概率={top_prob:.4f} >= {threshold}): "
                    f"查询='{question}' -> 匹配='{matched_question}'"
                )
                return matched_question, top_prob
            else:
                logger.debug(
                    f"BM25匹配失败(概率={top_prob:.4f} < {threshold}): "
                    f"查询='{question}'"
                )
                return None, top_prob
        except Exception as e:
            logger.error(f"BM25匹配异常: {e}")
            return None, 0.0

    def query_database(self, question: str) -> Optional[str]:
        """
        从数据库查询问答对

        Args:
            question: 要查询的问题

        Returns:
            匹配到的答案，未找到返回None
        """
        if not self.db_pool:
            logger.warning("数据库不可用")
            return None

        pool = ConsultantQueryHandler._db_pool_instance
        if pool is None:
            logger.warning("数据库连接池未初始化")
            return None

        conn = None
        try:
            conn = pool.getconn()
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                sql = "SELECT answer FROM qa_pairs WHERE question = %s"
                cursor.execute(sql, (question,))
                result = cursor.fetchone()

                if result:
                    logger.info(f"数据库查询命中: {question}")
                    return result["answer"]
                else:
                    logger.debug(f"数据库查询未命中: {question}")
                    return None
        except Exception as e:
            logger.error(f"数据库查询异常: {e}")
            return None
        finally:
            if conn is not None:
                pool.putconn(conn)

    def cache_retrieval(self, question: str, context: str) -> bool:
        """
        将检索结果写入Redis缓存（只缓存检索结果，不缓存LLM回答）
        
        Args:
            question: 问题
            context: 检索结果（来自SQL/RAG的原始数据）

        Returns:
            写入是否成功
        """
        if not self.redis_client:
            logger.debug("Redis客户端不可用，跳过检索结果缓存")
            return False

        try:
            key = f"{ConsultantRedisConfig.KEY_PREFIX_RETRIEVAL}{question}"
            self.redis_client.setex(key, ConsultantRedisConfig.TTL, context)
            logger.info(f"检索结果已缓存到Redis: {question} (TTL={ConsultantRedisConfig.TTL}s)")
            return True
        except Exception as e:
            logger.error(f"检索结果缓存写入异常: {e}")
            return False

    def rag_retrieve(self, question: str, step_callback=None) -> Optional[str]:
        """
        RAG检索 - 基于向量数据库的智能检索
        
        返回检索到的上下文，不调用LLM生成回答。

        Args:
            question: 用户输入的问题
            step_callback: 可选的步骤回调函数 (step, name, status, detail, extra)

        Returns:
            RAG检索返回的上下文文本，检索失败返回None
        """
        try:
            from common.rag.retrieval.rag_retriever import rag_retriever
            logger.info(f"进入RAG检索模块: {question}")
            
            if step_callback:
                rag_retriever.set_step_callback(step_callback)
            
            context = rag_retriever.query(question)
            return context
        except Exception as e:
            logger.error(f"RAG检索异常: {e}")
            raise

    def fallback_to_llm(self, question: str, history_messages: list = None) -> Optional[str]:
        """
        兜底策略 - 当所有检索方式都失败时，调用大模型直接回答
        
        说明:
        - 作为最后兜底手段，确保服务始终有返回
        - 返回的是大模型基于自身知识的回答，未经检索验证
        - 支持传入对话历史，实现上下文记忆
        - 不写入Redis缓存（LLM回答不缓存）

        Args:
            question: 用户输入的问题
            history_messages: 对话历史消息列表

        Returns:
            大模型返回的回答，调用失败返回None
        """
        try:
            logger.info(f"触发兜底策略，调用大模型直接回答: {question}")
            logger.info(f"对话历史: {len(history_messages or [])} 条消息")
            
            # 构建系统提示
            system_messages = consultant_prompt_manager.build_messages("fallback_answer", question=question)
            
            # 构建完整的消息列表（包含历史）
            messages = []
            if system_messages:
                messages.extend(system_messages)
            
            # 添加对话历史
            if history_messages:
                for msg in history_messages:
                    if msg.get("role") in ["user", "assistant"]:
                        messages.append({"role": msg["role"], "content": msg["content"]})
            
            # 添加当前问题（如果历史中没有包含）
            if not history_messages:
                messages.append({"role": "user", "content": question})
            
            # 调用 LLM
            answer = llm_client.chat(messages=messages)
            
            if answer:
                logger.info(f"兜底大模型回答成功: {question}")
                return answer
            else:
                logger.warning(f"兜底大模型返回空回答: {question}")
                return None
        except Exception as e:
            logger.error(f"兜底大模型调用异常: {e}")
            return None
