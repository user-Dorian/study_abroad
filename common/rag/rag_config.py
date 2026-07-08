"""RAG模块配置管理"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class RAGConfig:
    """RAG模块配置类"""
    
    # 项目根目录
    BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
    
    # ====== Milvus配置 ======
    MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
    MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
    MILVUS_DATABASE_NAME = os.getenv("MILVUS_DATABASE_NAME", "study_abroad_db")
    MILVUS_COLLECTION_NAME = os.getenv("MILVUS_COLLECTION_NAME", "study_abroad_vectors")
    
    # ====== 嵌入模型配置 ======
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_PATH", "") or os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
    EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
    EMBEDDING_DIM = 1024  # bge-m3稠密向量维度
    
    # ====== Reranker模型配置 ======
    RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_PATH", "") or os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-v2-m3")
    RERANKER_DEVICE = os.getenv("RERANKER_DEVICE", "cpu")
    
    # ====== 分块配置 ======
    # 父分块：按段落分块，保持语义完整性
    PARENT_CHUNK_SEPARATOR = "\n\n"  # 段落分隔符
    # 子分块：按句子语义分块
    CHILD_CHUNK_MAX_CHARS = int(os.getenv("CHILD_CHUNK_MAX_CHARS", "200"))
    CHILD_CHUNK_MIN_CHARS = int(os.getenv("CHILD_CHUNK_MIN_CHARS", "50"))
    
    # ====== 检索配置 ======
    # 稀疏向量(Dense)和稠密向量(Sparse)的权重
    DENSE_VECTOR_WEIGHT = float(os.getenv("DENSE_VECTOR_WEIGHT", "0.6"))
    SPARSE_VECTOR_WEIGHT = float(os.getenv("SPARSE_VECTOR_WEIGHT", "0.4"))
    
    # 粗排取top-k
    COARSE_TOP_K = int(os.getenv("COARSE_TOP_K", "20"))
    # 精排取top-k
    RERANK_TOP_K = int(os.getenv("RERANK_TOP_K", "8"))
    # 最终去重后取前N个父块
    FINAL_TOP_K = int(os.getenv("FINAL_TOP_K", "3"))
    
    # ====== LLM配置 ======
    INTENT_MODEL_NAME = os.getenv("INTENT_MODEL_NAME", "deepseek-chat")
    STRATEGY_MODEL_NAME = os.getenv("STRATEGY_MODEL_NAME", "deepseek-chat")
    GENERATION_MODEL_NAME = os.getenv("GENERATION_MODEL_NAME", "deepseek-chat")

    # ====== 启动预热配置 ======
    ENABLE_MODEL_WARMUP = os.getenv("ENABLE_MODEL_WARMUP", "true").lower() == "true"
    WARMUP_QUERIES = [
        q.strip()
        for q in os.getenv("WARMUP_QUERIES", "留学申请流程,签证办理材料").split(",")
        if q.strip()
    ]
    WARMUP_PASSAGE = os.getenv("WARMUP_PASSAGE", "这是一段用于预热重排序模型的示例文本。")

    # ====== 数据源配置 ======
    DATA_DIR = BASE_DIR / "data" / "study_abroad"
    
    # 支持的文件类型及其解析库
    SUPPORTED_FILE_TYPES = {
        ".txt": {"parser": "plain_text", "description": "纯文本文件"},
        ".md": {"parser": "markdown", "description": "Markdown文件"},
        ".html": {"parser": "html", "description": "HTML文件"},
        ".pdf": {"parser": "pdf", "description": "PDF文件"},
        ".doc": {"parser": "doc", "description": "Word DOC文件"},
        ".docx": {"parser": "docx", "description": "Word DOCX文件"},
        ".ppt": {"parser": "ppt", "description": "PowerPoint PPT文件"},
        ".pptx": {"parser": "pptx", "description": "PowerPoint PPTX文件"},
        ".csv": {"parser": "csv", "description": "CSV文件"},
        ".xls": {"parser": "excel", "description": "Excel XLS文件"},
        ".xlsx": {"parser": "excel", "description": "Excel XLSX文件"},
    }
    
    # 分块策略配置（按语言区分）
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
        "ja": {
            "name": "日文",
            "sentence_separators": ["。", "！", "？", "\n"],
            "paragraph_separator": "\n\n",
            "child_chunk_max_chars": 180,
            "child_chunk_min_chars": 40,
            "chunk_overlap": 15,
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
    
    # ====== API Keys (延迟加载，避免循环导入) ======
    @classmethod
    def get_dashscope_api_key(cls) -> str:
        """获取DashScope API Key"""
        from common.config.base_settings import BaseConfig
        return BaseConfig.DASHSCOPE_API_KEY
    
    @classmethod
    def get_deepseek_api_key(cls) -> str:
        """获取DeepSeek API Key"""
        from common.config.base_settings import BaseConfig
        return BaseConfig.DEEPSEEK_API_KEY
    
    @classmethod
    def has_api_key(cls) -> bool:
        """检查是否至少有一个API Key"""
        return bool(cls.get_dashscope_api_key() or cls.get_deepseek_api_key())
    
    @classmethod
    def validate(cls) -> bool:
        """验证RAG配置"""
        from common.utils.logger import logger
        
        if not cls.has_api_key():
            logger.warning("RAG配置: 需要配置DASHSCOPE_API_KEY或DEEPSEEK_API_KEY")
            return False
        
        logger.info("RAG配置验证通过")
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
            "CHUNK_SIZE": f"child_max={cls.CHILD_CHUNK_MAX_CHARS}, child_min={cls.CHILD_CHUNK_MIN_CHARS}",
        }
