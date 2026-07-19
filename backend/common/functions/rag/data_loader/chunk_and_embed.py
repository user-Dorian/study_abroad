"""Milvus管理器 - 向量数据库操作"""
import os
from typing import List, Dict, Any, Optional
from pymilvus import (
    connections, 
    Collection, 
    FieldSchema, 
    CollectionSchema, 
    DataType, 
    utility
)
from backend.common.basics.utils.logger import logger
from ..rag_config import RAGConfig


class MilvusManager:
    """Milvus向量数据库管理器
    
    特性：
    - 自动连接管理
    - Collection自动创建
    - 向量增删改查
    - 完善的错误处理
    """
    
    def __init__(self):
        """初始化Milvus管理器"""
        self._collection: Optional[Collection] = None
        self._connected = False
    
    def _ensure_connected(self):
        """确保已连接到Milvus"""
        if self._connected:
            return
        
        try:
            # 连接到Milvus
            connections.connect(
                alias="default",
                host=RAGConfig.MILVUS_HOST,
                port=RAGConfig.MILVUS_PORT
            )
            
            # 检查collection是否存在
            if utility.has_collection(RAGConfig.COLLECTION_NAME):
                self._collection = Collection(RAGConfig.COLLECTION_NAME)
                logger.info(f"已连接到现有collection: {RAGConfig.COLLECTION_NAME}")
            else:
                # 创建collection
                self._create_collection()
            
            self._connected = True
            logger.info(f"Milvus连接成功: {RAGConfig.MILVUS_HOST}:{RAGConfig.MILVUS_PORT}")
            
        except Exception as e:
            logger.error(f"Milvus连接失败: {e}", exc_info=True)
            raise
    
    def _create_collection(self):
        """创建Milvus collection"""
        try:
            # 定义字段
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="question", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="answer", dtype=DataType.VARCHAR, max_length=2000),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=RAGConfig.EMBEDDING_DIMENSION),
            ]
            
            # 创建schema
            schema = CollectionSchema(
                fields=fields,
                description="留学问答向量库"
            )
            
            # 创建collection
            self._collection = Collection(
                name=RAGConfig.COLLECTION_NAME,
                schema=schema
            )
            
            # 创建索引
            index_params = {
                "metric_type": "IP",  # 内积相似度
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024}
            }
            self._collection.create_index(
                field_name="embedding",
                index_params=index_params
            )
            
            logger.info(f"Collection创建成功: {RAGConfig.COLLECTION_NAME}")
            
        except Exception as e:
            logger.error(f"Collection创建失败: {e}", exc_info=True)
            raise
    
    def get_count(self) -> int:
        """获取collection中的向量数量
        
        Returns:
            int: 向量数量
        """
        try:
            self._ensure_connected()
            return self._collection.num_entities
        except Exception as e:
            logger.error(f"获取向量数量失败: {e}")
            return 0
    
    def insert(
        self,
        questions: List[str],
        answers: List[str],
        embeddings: List[List[float]]
    ) -> bool:
        """插入向量数据
        
        Args:
            questions: 问题列表
            answers: 答案列表
            embeddings: 向量列表
            
        Returns:
            bool: 是否成功
        """
        try:
            self._ensure_connected()
            
            # 插入数据
            data = [
                questions,
                answers,
                embeddings
            ]
            
            self._collection.insert(data)
            self._collection.flush()
            
            logger.info(f"成功插入 {len(questions)} 条向量数据")
            return True
            
        except Exception as e:
            logger.error(f"向量插入失败: {e}", exc_info=True)
            return False
    
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """搜索相似向量
        
        Args:
            query_embedding: 查询向量
            top_k: 返回top-k结果
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        try:
            self._ensure_connected()
            
            # 加载collection到内存
            self._collection.load()
            
            # 执行搜索
            search_params = {
                "metric_type": "IP",
                "params": {"nprobe": 16}
            }
            
            results = self._collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                output_fields=["question", "answer"]
            )
            
            # 格式化结果
            formatted_results = []
            for hits in results:
                for hit in hits:
                    formatted_results.append({
                        "question": hit.entity.get("question"),
                        "answer": hit.entity.get("answer"),
                        "score": hit.score
                    })
            
            return formatted_results
            
        except Exception as e:
            logger.error(f"向量搜索失败: {e}", exc_info=True)
            return []
    
    def delete_collection(self) -> bool:
        """删除collection（危险操作）
        
        Returns:
            bool: 是否成功
        """
        try:
            self._ensure_connected()
            utility.drop_collection(RAGConfig.COLLECTION_NAME)
            logger.warning(f"Collection已删除: {RAGConfig.COLLECTION_NAME}")
            return True
        except Exception as e:
            logger.error(f"Collection删除失败: {e}", exc_info=True)
            return False


# 全局单例（延迟初始化）
_milvus_manager: Optional[MilvusManager] = None


def get_milvus_manager() -> MilvusManager:
    """获取Milvus管理器单例"""
    global _milvus_manager
    if _milvus_manager is None:
        _milvus_manager = MilvusManager()
    return _milvus_manager
