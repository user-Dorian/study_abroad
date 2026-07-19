"""BM25索引构建器 - 基于关键词的检索系统"""
import os
import json
import pickle
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from backend.common.basics.utils.logger import logger

# 延迟导入rank_bm25
try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None
    logger.warning("rank_bm25未安装，BM25功能将不可用")


class BM25IndexBuilder:
    """BM25索引构建器
    
    特性：
    - BM25算法实现
    - 索引缓存管理
    - 相似度计算
    - 完善的错误处理
    """
    
    def __init__(self, cache_dir: Optional[str] = None):
        """初始化BM25索引构建器
        
        Args:
            cache_dir: 缓存目录
        """
        self._bm25: Optional[BM25Okapi] = None
        self._questions: List[str] = []
        self._answers: List[str] = []
        self._is_loaded = False
        
        # 缓存路径
        if cache_dir:
            self._cache_dir = Path(cache_dir)
        else:
            self._cache_dir = Path(__file__).parent.parent.parent / "data" / "bm25_cache"
        
        self._cache_file = self._cache_dir / "bm25_index.pkl"
    
    def initialize(self, force_reload: bool = False) -> Optional[BM25Okapi]:
        """初始化BM25索引（优先加载缓存）
        
        Args:
            force_reload: 是否强制重新加载
            
        Returns:
            BM25Okapi: BM25索引实例
        """
        if BM25Okapi is None:
            logger.warning("rank_bm25未安装，无法初始化BM25索引")
            return None
        
        if self._is_loaded and not force_reload:
            return self._bm25
        
        try:
            # 尝试加载缓存
            if not force_reload and self._load_from_cache():
                logger.info(f"BM25索引从缓存加载成功: {len(self._questions)} 个问题")
                self._is_loaded = True
                return self._bm25
            
            # 从数据文件加载
            data_file = self._cache_dir / "qa_data.json"
            if data_file.exists():
                self._load_from_data_file(data_file)
                self._save_to_cache()
                logger.info(f"BM25索引构建成功: {len(self._questions)} 个问题")
                self._is_loaded = True
                return self._bm25
            
            # 无数据，创建空索引
            logger.warning("BM25索引数据文件不存在，将创建空索引")
            self._questions = ["测试问题"]
            self._answers = ["测试答案"]
            self._tokenized = [["测试", "问题"]]
            self._bm25 = BM25Okapi(self._tokenized)
            self._is_loaded = True
            
            return self._bm25
            
        except Exception as e:
            logger.error(f"BM25索引初始化失败: {e}", exc_info=True)
            return None
    
    def _load_from_cache(self) -> bool:
        """从缓存加载索引
        
        Returns:
            bool: 是否成功
        """
        try:
            if not self._cache_file.exists():
                return False
            
            with open(self._cache_file, 'rb') as f:
                data = pickle.load(f)
            
            self._bm25 = data['bm25']
            self._questions = data['questions']
            self._answers = data['answers']
            self._tokenized = data['tokenized']
            
            return True
            
        except Exception as e:
            logger.warning(f"BM25索引缓存加载失败: {e}")
            return False
    
    def _save_to_cache(self):
        """保存索引到缓存"""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            
            data = {
                'bm25': self._bm25,
                'questions': self._questions,
                'answers': self._answers,
                'tokenized': self._tokenized,
            }
            
            with open(self._cache_file, 'wb') as f:
                pickle.dump(data, f)
            
            logger.info(f"BM25索引已缓存到: {self._cache_file}")
            
        except Exception as e:
            logger.warning(f"BM25索引缓存保存失败: {e}")
    
    def _load_from_data_file(self, data_file: Path):
        """从数据文件加载
        
        Args:
            data_file: 数据文件路径
        """
        with open(data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self._questions = [item['question'] for item in data]
        self._answers = [item['answer'] for item in data]
        
        # 简单中文分词（按字符分割）
        self._tokenized = [
            list(q.replace(' ', ''))
            for q in self._questions
        ]
        
        self._bm25 = BM25Okapi(self._tokenized)
    
    def search(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Tuple[str, str, float]]:
        """搜索相似问题
        
        Args:
            query: 查询问题
            top_k: 返回数量
            
        Returns:
            List[Tuple]: [(question, answer, score)]
        """
        if not self._is_loaded:
            self.initialize()
        
        if not self._bm25:
            return []
        
        try:
            # 分词查询
            query_tokens = list(query.replace(' ', ''))
            
            # 计算相似度
            scores = self._bm25.get_scores(query_tokens)
            
            # 获取top-k结果
            top_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True
            )[:top_k]
            
            results = []
            for idx in top_indices:
                if idx < len(self._questions):
                    results.append((
                        self._questions[idx],
                        self._answers[idx],
                        float(scores[idx])
                    ))
            
            return results
            
        except Exception as e:
            logger.error(f"BM25搜索失败: {e}", exc_info=True)
            return []
    
    @property
    def is_loaded(self) -> bool:
        """是否已加载"""
        return self._is_loaded
    
    @property
    def questions(self) -> List[str]:
        """问题列表"""
        return self._questions


# 全局单例
_bm25_builder: Optional[BM25IndexBuilder] = None


def get_bm25_builder() -> BM25IndexBuilder:
    """获取BM25索引构建器单例"""
    global _bm25_builder
    if _bm25_builder is None:
        _bm25_builder = BM25IndexBuilder()
    return _bm25_builder
