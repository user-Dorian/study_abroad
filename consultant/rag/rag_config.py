"""规划师端RAG模块配置 - 使用独立的Milvus集合和检索参数"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class ConsultantRAGConfig:
    """规划师端RAG配置类"""

    # 项目根目录
    BASE_DIR = Path(__file__).resolve().parent.parent.parent

    # ====== Milvus配置（独立集合，与客户端隔离） ======
    MILVUS_HOST = os.getenv("CONSULTANT_MILVUS_HOST", os.getenv("MILVUS_HOST", "localhost"))
    MILVUS_PORT = int(os.getenv("CONSULTANT_MILVUS_PORT", os.getenv("MILVUS_PORT", "19530")))
    MILVUS_DATABASE_NAME = os.getenv("CONSULTANT_MILVUS_DATABASE_NAME", os.getenv("MILVUS_DATABASE_NAME", "study_abroad_db"))
    MILVUS_COLLECTION_NAME = os.getenv("CONSULTANT_MILVUS_COLLECTION_NAME", "enterprise_data_vectors")

    # ====== 嵌入模型配置（复用客户端模型） ======
    EMBEDDING_MODEL_NAME = os.getenv("CONSULTANT_EMBEDDING_MODEL_PATH", "") or os.getenv("EMBEDDING_MODEL_PATH", "") or os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
    EMBEDDING_DEVICE = os.getenv("CONSULTANT_EMBEDDING_DEVICE", os.getenv("EMBEDDING_DEVICE", "cpu"))
    EMBEDDING_DIM = 1024

    # ====== Reranker模型配置 ======
    RERANKER_MODEL_NAME = os.getenv("CONSULTANT_RERANKER_MODEL_PATH", "") or os.getenv("RERANKER_MODEL_PATH", "") or os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
    RERANKER_DEVICE = os.getenv("CONSULTANT_RERANKER_DEVICE", os.getenv("RERANKER_DEVICE", "cpu"))

    # ====== 分块配置 ======
    PARENT_CHUNK_SEPARATOR = "\n\n"
    CHILD_CHUNK_MAX_CHARS = int(os.getenv("CONSULTANT_CHILD_CHUNK_MAX_CHARS", "200"))
    CHILD_CHUNK_MIN_CHARS = int(os.getenv("CONSULTANT_CHILD_CHUNK_MIN_CHARS", "50"))

    # ====== 检索配置 ======
    DENSE_VECTOR_WEIGHT = float(os.getenv("CONSULTANT_DENSE_VECTOR_WEIGHT", "0.6"))
    SPARSE_VECTOR_WEIGHT = float(os.getenv("CONSULTANT_SPARSE_VECTOR_WEIGHT", "0.4"))

    COARSE_TOP_K = int(os.getenv("CONSULTANT_COARSE_TOP_K", "20"))
    RERANK_TOP_K = int(os.getenv("CONSULTANT_RERANK_TOP_K", "8"))
    FINAL_TOP_K = int(os.getenv("CONSULTANT_FINAL_TOP_K", "3"))

    # ====== LLM配置 ======
    INTENT_MODEL_NAME = os.getenv("CONSULTANT_INTENT_MODEL_NAME", "deepseek-chat")
    STRATEGY_MODEL_NAME = os.getenv("CONSULTANT_STRATEGY_MODEL_NAME", "deepseek-chat")
    GENERATION_MODEL_NAME = os.getenv("CONSULTANT_GENERATION_MODEL_NAME", "deepseek-chat")

    # ====== 启动预热配置 ======
    ENABLE_MODEL_WARMUP = os.getenv("CONSULTANT_ENABLE_MODEL_WARMUP", "true").lower() == "true"
    WARMUP_QUERIES = [
        q.strip()
        for q in os.getenv("CONSULTANT_WARMUP_QUERIES", "合作院校资源,客户等级划分,特殊申请渠道").split(",")
        if q.strip()
    ]
    WARMUP_PASSAGE = os.getenv("CONSULTANT_WARMUP_PASSAGE", "这是一段用于预热企业数据检索模型的示例文本。")

    # ====== 数据源配置 ======
    DATA_DIR = BASE_DIR / "data" / "study_abroad" / "enterprise"

    SUPPORTED_FILE_TYPES = {
        ".txt": {"parser": "plain_text", "description": "纯文本文件"},
        ".md": {"parser": "markdown", "description": "Markdown文件"},
        ".html": {"parser": "html", "description": "HTML文件"},
        ".csv": {"parser": "csv", "description": "CSV文件"},
        ".xls": {"parser": "excel", "description": "Excel XLS文件"},
        ".xlsx": {"parser": "excel", "description": "Excel XLSX文件"},
    }

    CHUNK_STRATEGIES = {
        "zh": {
            "name": "中文",
            "sentence_separators": ["。", "！", "？", "；", "\n"],
            "paragraph_separator": "\n\n",
            "child_chunk_max_chars": 200,
            "child_chunk_min_chars": 50,
            "chunk_overlap": 20,
        },
        "en": {
            "name": "英文",
            "sentence_separators": [". ", "! ", "? ", "\n"],
            "paragraph_separator": "\n\n",
            "child_chunk_max_chars": 250,
            "child_chunk_min_chars": 60,
            "chunk_overlap": 30,
        },
        "default": {
            "name": "默认",
            "sentence_separators": [".", "!", "?", "。", "！", "？", "\n"],
            "paragraph_separator": "\n\n",
            "child_chunk_max_chars": 200,
            "child_chunk_min_chars": 50,
            "chunk_overlap": 20,
        },
    }

    @classmethod
    def get_dashscope_api_key(cls) -> str:
        """获取DashScope API Key"""
        from consultant.config.settings import ConsultantConfig
        return ConsultantConfig.DASHSCOPE_API_KEY

    @classmethod
    def get_deepseek_api_key(cls) -> str:
        """获取DeepSeek API Key"""
        from consultant.config.settings import ConsultantConfig
        return ConsultantConfig.DEEPSEEK_API_KEY

    @classmethod
    def has_api_key(cls) -> bool:
        """检查是否至少有一个API Key"""
        return bool(cls.get_dashscope_api_key() or cls.get_deepseek_api_key())

    @classmethod
    def validate(cls) -> bool:
        """验证RAG配置"""
        from utils.logger import logger

        if not cls.has_api_key():
            logger.warning("[规划师端RAG] 需要配置DASHSCOPE_API_KEY或DEEPSEEK_API_KEY")
            return False

        logger.info("[规划师端RAG] 配置验证通过")
        return True

    @classmethod
    def get_config_summary(cls) -> dict:
        """获取配置摘要"""
        return {
            "MILVUS": f"{cls.MILVUS_HOST}:{cls.MILVUS_PORT}/{cls.MILVUS_COLLECTION_NAME}",
            "EMBEDDING_MODEL": cls.EMBEDDING_MODEL_NAME,
            "RERANKER_MODEL": cls.RERANKER_MODEL_NAME,
            "VECTORS_WEIGHT": f"dense={cls.DENSE_VECTOR_WEIGHT}, sparse={cls.SPARSE_VECTOR_WEIGHT}",
            "RETRIEVAL": f"coarse_top{cls.COARSE_TOP_K} -> rerank_top{cls.RERANK_TOP_K}",
        }
