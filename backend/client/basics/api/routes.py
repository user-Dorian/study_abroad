"""主查询路由 - 提供RAG查询处理功能"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import redis

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import get_current_user

router = APIRouter()


class QueryRequest(BaseModel):
    """查询请求"""
    question: str
    top_k: Optional[int] = 5


class QueryResponse(BaseModel):
    """查询响应"""
    question: str
    answer: str
    sources: List[str]
    confidence: float


class QueryHandler:
    """查询处理器 - 管理Redis、BM25和数据库连接"""

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        bm25_retriever=None,
        db_available: bool = False
    ):
        self.redis_client = redis_client
        self.bm25_retriever = bm25_retriever
        self.db_available = db_available
        self._initialized = False

    def initialize(
        self,
        redis_client: Optional[redis.Redis] = None,
        bm25_retriever=None,
        db_available: bool = False
    ):
        """初始化查询处理器"""
        self.redis_client = redis_client
        self.bm25_retriever = bm25_retriever
        self.db_available = db_available
        self._initialized = True
        logger.info(f"QueryHandler初始化完成: redis={redis_client is not None}, bm25={bm25_retriever is not None}, db={db_available}")

    def redis_exact_match(self, question: str) -> Optional[str]:
        """Redis精确匹配查询

        Args:
            question: 用户问题

        Returns:
            str | None: 匹配到的答案，未匹配返回None
        """
        if not self.redis_client:
            logger.warning("Redis客户端未初始化")
            return None

        try:
            # 尝试从Redis获取缓存的答案
            cached = self.redis_client.get(f"qa:{question}")
            if cached:
                logger.info(f"Redis精确匹配成功: {question[:50]}")
                return cached.decode('utf-8')
            return None
        except Exception as e:
            logger.error(f"Redis查询异常: {e}")
            return None

    def bm25_match_with_softmax(self, question: str) -> tuple[Optional[str], float]:
        """BM25匹配查询（带softmax概率）

        Args:
            question: 用户问题

        Returns:
            tuple: (匹配的问题, 概率)
        """
        if not self.bm25_retriever:
            logger.warning("BM25检索器未初始化")
            return None, 0.0

        try:
            # 调用BM25检索
            if hasattr(self.bm25_retriever, 'search'):
                results = self.bm25_retriever.search(question, top_k=1)
                if results and len(results) > 0:
                    matched_question = results[0].get('question', '')
                    score = results[0].get('score', 0.0)
                    # 简单的softmax转换（假设score已经是归一化的）
                    probability = min(score / 10.0, 1.0)  # 简化处理
                    logger.info(f"BM25匹配成功: {matched_question[:50]}, prob={probability:.2f}")
                    return matched_question, probability
            return None, 0.0
        except Exception as e:
            logger.error(f"BM25查询异常: {e}")
            return None, 0.0

    def query_database(self, matched_question: str) -> Optional[str]:
        """数据库查询

        Args:
            matched_question: 匹配的问题

        Returns:
            str | None: 查询到的答案
        """
        if not self.db_available:
            logger.warning("数据库未连接")
            return None

        try:
            # 这里应该连接数据库查询答案
            # 由于实际数据库实现可能不同，这里只返回占位符
            logger.info(f"数据库查询: {matched_question[:50]}")
            return f"数据库答案: {matched_question}"
        except Exception as e:
            logger.error(f"数据库查询异常: {e}")
            return None

    def cache_retrieval(self, question: str, answer: str):
        """缓存检索结果到Redis

        Args:
            question: 问题
            answer: 答案
        """
        if not self.redis_client:
            return

        try:
            self.redis_client.setex(
                f"qa:{question}",
                3600,  # 缓存1小时
                answer
            )
            logger.info(f"结果已缓存到Redis: {question[:50]}")
        except Exception as e:
            logger.warning(f"缓存失败: {e}")

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized


# 全局查询处理器实例
_query_handler: Optional[QueryHandler] = None


def init_query_handler(
    redis_client: Optional[redis.Redis] = None,
    bm25_retriever=None,
    db_available: bool = False
):
    """初始化全局查询处理器

    Args:
        redis_client: Redis客户端
        bm25_retriever: BM25检索器
        db_available: 数据库是否可用
    """
    global _query_handler
    if _query_handler is None:
        _query_handler = QueryHandler()
    _query_handler.initialize(redis_client, bm25_retriever, db_available)
    logger.info("全局查询处理器初始化完成")


def get_query_handler() -> QueryHandler:
    """获取全局查询处理器实例

    Returns:
        QueryHandler: 查询处理器实例

    Raises:
        HTTPException: 500 - 查询处理器未初始化
    """
    if _query_handler is None or not _query_handler.is_initialized():
        # 如果未初始化，返回一个默认实例（用于测试）
        logger.warning("查询处理器未初始化，返回默认实例")
        return QueryHandler()
    return _query_handler


@router.post("/api/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    current_user: Optional[dict] = Depends(get_current_user)
):
    """RAG查询接口

    Args:
        request: 查询请求
        current_user: 当前用户（可选）

    Returns:
        QueryResponse: 查询响应

    Raises:
        HTTPException: 500 - 查询处理失败
    """
    try:
        handler = get_query_handler()

        # 多级检索策略
        sources = []
        answer = ""

        # L1: Redis精确匹配
        redis_answer = handler.redis_exact_match(request.question)
        if redis_answer:
            answer = redis_answer
            sources.append("Redis")
        else:
            # L2: BM25 + 数据库
            matched_question, prob = handler.bm25_match_with_softmax(request.question)
            if prob >= 0.7 and matched_question:
                db_answer = handler.query_database(matched_question)
                if db_answer:
                    answer = db_answer
                    sources.append(f"Database(prob={prob:.2f})")
                    # 缓存结果
                    handler.cache_retrieval(request.question, db_answer)
            else:
                # L3: 默认响应（实际应该调用RAG向量检索）
                answer = "抱歉，没有找到相关答案。请稍后再试或联系客服。"
                sources.append("Fallback")

        logger.info(
            f"查询处理完成: question={request.question[:50]}, "
            f"user={current_user.get('user_id') if current_user else 'anonymous'}, "
            f"sources={sources}"
        )

        return QueryResponse(
            question=request.question,
            answer=answer,
            sources=sources,
            confidence=0.85 if sources else 0.0
        )

    except Exception as e:
        logger.error(f"查询处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询处理失败: {str(e)}")


@router.get("/api/query/status")
async def query_status():
    """查询处理器状态检查"""
    handler = get_query_handler()
    return {
        "initialized": handler.is_initialized(),
        "redis_connected": handler.redis_client is not None,
        "bm25_available": handler.bm25_retriever is not None,
        "database_available": handler.db_available
    }
