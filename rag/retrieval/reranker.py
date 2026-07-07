"""Reranker模块 - bge-reranker-large精排序"""
from typing import List, Tuple, Dict
from rag.rag_config import RAGConfig
from utils.logger import logger
import os
import ssl
import threading


class Reranker:
    """bge-reranker-large重排序器 - 延迟加载模型"""
    
    def __init__(
        self,
        model_name: str = None,
        device: str = None
    ):
        self.model_name = model_name or RAGConfig.RERANKER_MODEL_NAME
        self.device = device or RAGConfig.RERANKER_DEVICE
        self.model = None
        self.tokenizer = None
        self._initialized = False
        self._load_failed = False
        self._init_lock = threading.Lock()
        self._inference_lock = threading.Lock()
    
    def _ensure_loaded(self):
        """延迟加载reranker模型，首次调用时才加载；双重检查锁定保证只加载一次"""
        if self._initialized or self._load_failed:
            return
        
        with self._init_lock:
            if self._initialized or self._load_failed:
                return
            try:
                self._load_model()
                self._initialized = True
            except Exception:
                self._load_failed = True
                raise
    
    def _load_model(self):
        """加载reranker模型"""
        try:
            # 修复Windows SSL证书问题 - 必须在导入FlagEmbedding前设置
            os.environ["HF_HUB_OFFLINE"] = "1"  # 离线模式，模型已缓存
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            os.environ["HF_HUB_DISABLE_VERSION_CHECK"] = "1"
            os.environ["CURL_CA_BUNDLE"] = ""
            os.environ["REQUESTS_CA_BUNDLE"] = ""
            os.environ["SSL_CERT_FILE"] = ""
            
            # 禁用urllib3警告
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            # 禁用SSL验证 - monkey-patch所有层级
            ssl._create_default_https_context = ssl._create_unverified_context
            
            # 也patch huggingface_hub的session（如果已导入）
            try:
                import huggingface_hub
                if hasattr(huggingface_hub, '_hf_api'):
                    huggingface_hub._hf_api = None  # 重置API实例
                # 设置离线模式
                huggingface_hub.constants.HF_HUB_OFFLINE = True
            except (ImportError, AttributeError):
                pass
            
            logger.info("SSL验证已禁用（Reranker模型Windows环境兼容模式），使用离线模式加载本地缓存模型")
            
            from FlagEmbedding import FlagReranker
            logger.info(f"加载Reranker模型: {self.model_name} (device={self.device})")
            self.model = FlagReranker(
                self.model_name,
                use_fp16=True,
                device=self.device
            )
            logger.info("Reranker模型加载成功")
        except ImportError:
            logger.error("FlagEmbedding未安装, 请运行: pip install FlagEmbedding")
            raise
        except Exception as e:
            logger.error(f"Reranker模型加载失败: {e}")
            raise
    
    def rerank(
        self,
        query: str,
        passages: List[dict],
        top_k: int = None
    ) -> List[dict]:
        """
        对候选段落进行重排序
        
        Args:
            query: 查询问题
            passages: 候选段落列表 [{"id": str, "text": str, "parent_id": str, ...}]
            top_k: 返回top-k结果
            
        Returns:
            重排序后的段落列表
        """
        if not passages:
            return []
        
        k = top_k or RAGConfig.RERANK_TOP_K
        
        # 若历史加载已失败，直接降级，避免每次请求重复尝试加载
        if self._load_failed:
            logger.debug("Reranker历史加载失败，直接返回原始结果")
            return passages[:k]
        
        # 构建(query, passage)对
        pairs = [(query, p["text"]) for p in passages]
        
        try:
            with self._inference_lock:
                # 确保模型已加载
                self._ensure_loaded()
                
                # 计算相关性分数
                scores = self.model.compute_score(pairs, normalize=True)
                
                # 处理单元素情况
                if isinstance(scores, (float, int)):
                    scores = [scores]
            
            # 附加分数到结果
            for passage, score in zip(passages, scores):
                passage["rerank_score"] = float(score)
            
            # 按rerank分数排序
            reranked = sorted(passages, key=lambda x: x["rerank_score"], reverse=True)
            
            logger.info(f"Reranker完成: {len(passages)} -> top{min(k, len(reranked))}")
            
            return reranked[:k]
            
        except Exception as e:
            logger.error(f"Reranker计算失败: {e}")
            # 降级：直接返回原始结果
            return passages[:k]
    
    def warmup(
        self,
        query: str = None,
        passage: str = None
    ):
        """
        预热重排序模型，首次调用触发模型加载并完成一次前向推理
        
        Args:
            query: 预热查询文本
            passage: 预热段落文本
        """
        query = query or "留学申请需要准备哪些材料"
        passage = passage or "这是一段用于预热重排序模型的示例文本。"
        
        passages = [{"text": passage}]
        result = self.rerank(query, passages, top_k=1)
        if self._load_failed:
            logger.warning("Reranker warmup 失败，模型加载不可用，后续将降级返回原始结果")
        else:
            logger.info("Reranker warmup 完成")


reranker = Reranker()
