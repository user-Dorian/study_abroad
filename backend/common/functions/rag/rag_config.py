"""RAG配置类 - 统一管理RAG相关配置（v2: 优先本地模型路径）

模型加载策略：
1. 优先使用 .env 中的 EMBEDDING_MODEL_PATH / RERANKER_MODEL_PATH（本地路径）
2. 本地路径不存在时降级到 HuggingFace 模型名（在线下载或缓存）
3. bge-m3 (1024维) + bge-reranker-v2-m3（两阶段排序）
"""
import os
from typing import Optional


def _resolve_model_path(env_path_key: str, env_name_key: str, default_name: str) -> str:
    """解析模型路径：优先本地路径，路径不存在则降级到模型名

    Args:
        env_path_key: .env中本地路径的key（如 EMBEDDING_MODEL_PATH）
        env_name_key: .env中模型名的key（如 EMBEDDING_MODEL_NAME）
        default_name: 默认HuggingFace模型名

    Returns:
        str: 本地路径（存在）或 模型名（不存在时降级）
    """
    # 1. 优先尝试本地路径
    local_path = os.getenv(env_path_key, '').strip()
    if local_path and os.path.exists(local_path):
        return local_path

    # 2. 本地路径不存在，使用模型名（在线下载或HF缓存）
    return os.getenv(env_name_key, default_name).strip()


def _detect_embedding_dimension(model_path_or_name: str) -> int:
    """根据模型路径/名称自动推断embedding维度

    Args:
        model_path_or_name: 模型路径或名称

    Returns:
        int: embedding维度
    """
    name_lower = model_path_or_name.lower()
    # bge-m3 系列：1024维
    if 'bge-m3' in name_lower:
        return 1024
    # bge-large 系列：1024维
    if 'bge-large' in name_lower:
        return 1024
    # bge-base 系列：768维
    if 'bge-base' in name_lower:
        return 768
    # paraphrase-multilingual-MiniLM-L12-v2：384维
    if 'minilm' in name_lower or 'mini-lm' in name_lower:
        return 384
    # 默认值
    return int(os.getenv('EMBEDDING_DIMENSION', '1024'))


# 解析后的模型路径/名称（运行时确定）
_RESOLVED_EMBEDDING = _resolve_model_path(
    'EMBEDDING_MODEL_PATH',
    'EMBEDDING_MODEL_NAME',
    'BAAI/bge-m3'
)
_RESOLVED_RERANKER = _resolve_model_path(
    'RERANKER_MODEL_PATH',
    'RERANKER_MODEL_NAME',
    'BAAI/bge-reranker-v2-m3'
)
_RESOLVED_EMBEDDING_DIM = _detect_embedding_dimension(_RESOLVED_EMBEDDING)


class RAGConfig:
    """RAG配置类 - 面向对象管理RAG系统配置

    硬约束配置：
    - Milvus collection: study_abroad_vectors
    - Milvus端口: 19530
    - Redis: 端口6379，密码1234
    - PostgreSQL: 端口5433
    - 模型：bge-m3 (embedding, 1024维) + bge-reranker-v2-m3 (reranker)
    """

    # ====== Milvus配置 ======
    MILVUS_HOST: str = os.getenv('MILVUS_HOST', '127.0.0.1')
    MILVUS_PORT: int = int(os.getenv('MILVUS_PORT', '19530'))
    COLLECTION_NAME: str = os.getenv('MILVUS_COLLECTION', 'study_abroad_vectors')

    # ====== Embedding模型配置（v2: 优先本地路径，降级HF模型名）======
    EMBEDDING_MODEL_NAME: str = _RESOLVED_EMBEDDING
    EMBEDDING_DIMENSION: int = _RESOLVED_EMBEDDING_DIM
    EMBEDDING_BATCH_SIZE: int = int(os.getenv('EMBEDDING_BATCH_SIZE', '32'))
    # 标记是否使用本地路径
    EMBEDDING_IS_LOCAL_PATH: bool = (
        os.path.exists(_RESOLVED_EMBEDDING) if _RESOLVED_EMBEDDING else False
    )

    # ====== Reranker模型配置（v2: 优先本地路径）======
    RERANKER_MODEL_NAME: str = _RESOLVED_RERANKER
    RERANK_TOP_K: int = int(os.getenv('RERANK_TOP_K', '10'))
    # 稀疏粗排序候选数（L3a）
    COARSE_TOP_K: int = int(os.getenv('COARSE_TOP_K', '50'))
    # 精排序阈值（低于此分数的结果丢弃）
    RERANK_SCORE_THRESHOLD: float = float(os.getenv('RERANK_SCORE_THRESHOLD', '0.3'))
    # 标记是否使用本地路径
    RERANKER_IS_LOCAL_PATH: bool = (
        os.path.exists(_RESOLVED_RERANKER) if _RESOLVED_RERANKER else False
    )
    
    # ====== LLM配置 ======
    INTENT_MODEL_NAME: str = os.getenv('INTENT_MODEL_NAME', 'deepseek-chat')
    GENERATION_MODEL_NAME: str = os.getenv('GENERATION_MODEL_NAME', 'deepseek-chat')
    LLM_TEMPERATURE: float = float(os.getenv('LLM_TEMPERATURE', '0.7'))
    LLM_MAX_TOKENS: int = int(os.getenv('LLM_MAX_TOKENS', '2000'))
    
    # ====== 检索配置 ======
    RETRIEVAL_TOP_K: int = int(os.getenv('RETRIEVAL_TOP_K', '10'))
    SIMILARITY_THRESHOLD: float = float(os.getenv('SIMILARITY_THRESHOLD', '0.7'))
    
    # ====== 模型预热配置 ======
    ENABLE_MODEL_WARMUP: bool = os.getenv('ENABLE_MODEL_WARMUP', 'true').lower() == 'true'
    
    # ====== API密钥 ======
    DASHSCOPE_API_KEY: Optional[str] = os.getenv('DASHSCOPE_API_KEY')
    DEEPSEEK_API_KEY: Optional[str] = os.getenv('DEEPSEEK_API_KEY')
    
    # ====== Redis配置（用于缓存） ======
    REDIS_HOST: str = os.getenv('REDIS_HOST', '127.0.0.1')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    REDIS_PASSWORD: str = os.getenv('REDIS_PASSWORD', '1234')
    REDIS_DB: int = int(os.getenv('REDIS_DB', '0'))
    CACHE_TTL: int = int(os.getenv('CACHE_TTL', '3600'))  # 1小时
    
    # ====== PostgreSQL配置 ======
    DB_HOST: str = os.getenv('DB_HOST', '127.0.0.1')
    DB_PORT: int = int(os.getenv('DB_PORT', '5433'))
    DB_USER: str = os.getenv('DB_USER', 'eduagent_user')
    DB_PASSWORD: str = os.getenv('DB_PASSWORD', '123456')
    DB_NAME: str = os.getenv('DB_NAME', 'studyabroad')
    DB_POOL_SIZE: int = int(os.getenv('DB_POOL_SIZE', '10'))  # 数据库连接池大小
    
    @classmethod
    def get_milvus_config(cls) -> dict:
        """获取Milvus配置"""
        return {
            'host': cls.MILVUS_HOST,
            'port': cls.MILVUS_PORT,
            'collection_name': cls.COLLECTION_NAME,
        }
    
    @classmethod
    def get_redis_config(cls) -> dict:
        """获取Redis配置"""
        return {
            'host': cls.REDIS_HOST,
            'port': cls.REDIS_PORT,
            'password': cls.REDIS_PASSWORD,
            'db': cls.REDIS_DB,
            'decode_responses': True,
        }
    
    @classmethod
    def get_db_config(cls) -> dict:
        """获取数据库配置"""
        return {
            'host': cls.DB_HOST,
            'port': cls.DB_PORT,
            'user': cls.DB_USER,
            'password': cls.DB_PASSWORD,
            'database': cls.DB_NAME,
        }
    
    @classmethod
    def validate(cls) -> bool:
        """验证必要配置是否完整"""
        required_keys = ['DASHSCOPE_API_KEY', 'DEEPSEEK_API_KEY']
        missing = [k for k in required_keys if not getattr(cls, k)]
        if missing:
            import warnings
            warnings.warn(f"缺少必要的环境变量: {missing}")
            return False
        return True
    
    @classmethod
    def log_config(cls):
        """打印当前配置（调试用）"""
        print(f"\n{'='*60}")
        print(f"  RAG配置信息")
        print(f"{'='*60}")
        print(f"  Milvus: {cls.MILVUS_HOST}:{cls.MILVUS_PORT}")
        print(f"  Collection: {cls.COLLECTION_NAME}")
        print(f"  Embedding: {cls.EMBEDDING_MODEL_NAME} "
              f"({'本地路径' if cls.EMBEDDING_IS_LOCAL_PATH else 'HF模型名'}, "
              f"dim={cls.EMBEDDING_DIMENSION})")
        print(f"  Reranker: {cls.RERANKER_MODEL_NAME} "
              f"({'本地路径' if cls.RERANKER_IS_LOCAL_PATH else 'HF模型名'})")
        print(f"  Coarse Top-K: {cls.COARSE_TOP_K}, Rerank Top-K: {cls.RERANK_TOP_K}")
        print(f"  Intent Model: {cls.INTENT_MODEL_NAME}")
        print(f"  Generation Model: {cls.GENERATION_MODEL_NAME}")
        print(f"  Model Warmup: {cls.ENABLE_MODEL_WARMUP}")
        print(f"{'='*60}\n")
