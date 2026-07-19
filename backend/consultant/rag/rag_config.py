"""规划师端RAG配置类 - 继承通用RAG配置并指定企业数据集合

企业数据使用独立的Milvus集合和数据库，与客户端的公开数据隔离。
"""
import os
from backend.common.functions.rag.rag_config import RAGConfig


class ConsultantRAGConfig(RAGConfig):
    """规划师端RAG配置类 - 面向对象管理企业数据RAG配置

    继承通用RAG配置，重写企业数据相关的配置项：
    - Milvus集合：enterprise_vectors（企业私有数据）
    - Milvus数据库：enterprise_db（可选，用于数据隔离）
    """

    # ====== 企业数据Milvus配置 ======
    MILVUS_COLLECTION_NAME: str = os.getenv('CONSULTANT_MILVUS_COLLECTION', 'enterprise_vectors')
    MILVUS_DATABASE_NAME: str = os.getenv('CONSULTANT_MILVUS_DATABASE', 'enterprise_db')

    # ====== 企业数据Redis配置（可选独立配置） ======
    CONSULTANT_REDIS_HOST: str = os.getenv('CONSULTANT_REDIS_HOST', '127.0.0.1')
    CONSULTANT_REDIS_PORT: int = int(os.getenv('CONSULTANT_REDIS_PORT', '6379'))
    CONSULTANT_REDIS_PASSWORD: str = os.getenv('CONSULTANT_REDIS_PASSWORD', '1234')
    CONSULTANT_REDIS_DB: int = int(os.getenv('CONSULTANT_REDIS_DB', '1'))  # 使用不同的DB索引

    # ====== 企业数据PostgreSQL配置（可选独立配置） ======
    CONSULTANT_DB_HOST: str = os.getenv('CONSULTANT_DB_HOST', '127.0.0.1')
    CONSULTANT_DB_PORT: int = int(os.getenv('CONSULTANT_DB_PORT', '5432'))
    CONSULTANT_DB_USER: str = os.getenv('CONSULTANT_DB_USER', 'eduagent_user')
    CONSULTANT_DB_PASSWORD: str = os.getenv('CONSULTANT_DB_PASSWORD', '123456')
    CONSULTANT_DB_NAME: str = os.getenv('CONSULTANT_DB_NAME', 'studyabroad')

    @classmethod
    def get_milvus_config(cls) -> dict:
        """获取企业数据Milvus配置"""
        return {
            'host': cls.MILVUS_HOST,
            'port': cls.MILVUS_PORT,
            'collection_name': cls.MILVUS_COLLECTION_NAME,
            'database_name': cls.MILVUS_DATABASE_NAME,
        }

    @classmethod
    def get_redis_config(cls) -> dict:
        """获取企业数据Redis配置"""
        return {
            'host': cls.CONSULTANT_REDIS_HOST,
            'port': cls.CONSULTANT_REDIS_PORT,
            'password': cls.CONSULTANT_REDIS_PASSWORD,
            'db': cls.CONSULTANT_REDIS_DB,
            'decode_responses': True,
        }

    @classmethod
    def get_db_config(cls) -> dict:
        """获取企业数据数据库配置"""
        return {
            'host': cls.CONSULTANT_DB_HOST,
            'port': cls.CONSULTANT_DB_PORT,
            'user': cls.CONSULTANT_DB_USER,
            'password': cls.CONSULTANT_DB_PASSWORD,
            'database': cls.CONSULTANT_DB_NAME,
        }

    @classmethod
    def log_config(cls):
        """打印当前配置（调试用）"""
        print(f"\n{'='*60}")
        print(f"  规划师端RAG配置信息")
        print(f"{'='*60}")
        print(f"  Milvus: {cls.MILVUS_HOST}:{cls.MILVUS_PORT}")
        print(f"  Collection: {cls.MILVUS_COLLECTION_NAME}")
        print(f"  Database: {cls.MILVUS_DATABASE_NAME}")
        print(f"  Embedding: {cls.EMBEDDING_MODEL_NAME} "
              f"({'本地路径' if cls.EMBEDDING_IS_LOCAL_PATH else 'HF模型名'}, "
              f"dim={cls.EMBEDDING_DIMENSION})")
        print(f"  Reranker: {cls.RERANKER_MODEL_NAME} "
              f"({'本地路径' if cls.RERANKER_IS_LOCAL_PATH else 'HF模型名'})")
        print(f"  Redis: {cls.CONSULTANT_REDIS_HOST}:{cls.CONSULTANT_REDIS_PORT} (DB:{cls.CONSULTANT_REDIS_DB})")
        print(f"  Database: {cls.CONSULTANT_DB_HOST}:{cls.CONSULTANT_DB_PORT}/{cls.CONSULTANT_DB_NAME}")
        print(f"  Model Warmup: {cls.ENABLE_MODEL_WARMUP}")
        print(f"{'='*60}\n")