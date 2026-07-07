"""RAG数据构建脚本 - 首次启动时加载文档、分块、向量化、存储到Milvus"""
import os
import sys

# 修复Windows SSL证书问题 - 必须在最前面设置
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
except ImportError:
    pass

import importlib
importlib.invalidate_caches()

# 替换ssl.create_default_context，防止aiohttp/datasets在导入时加载Windows证书报错
import ssl
def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

ssl.create_default_context = _patched_create_default_context
ssl._create_default_https_context = _patched_create_default_context

from pathlib import Path
from rag.rag_config import RAGConfig
from rag.data_loader.chunk_and_embed import (
    DocumentLoader,
    ParentChunker,
    ChildChunker,
    EmbeddingModel,
    MilvusManager
)
from utils.logger import logger


class RAGDataBuilder:
    """RAG数据构建器 - 一次性构建整个向量数据库"""
    
    def __init__(self):
        self.doc_loader = DocumentLoader()
        self.parent_chunker = ParentChunker()
        self.child_chunker = ChildChunker()
        self.embedding_model = EmbeddingModel()
        self.milvus_manager = MilvusManager()
    
    def build(self, force_rebuild: bool = False):
        """
        构建完整的RAG向量数据库
        
        Args:
            force_rebuild: 是否强制重建
        """
        logger.info("=" * 60)
        logger.info("RAG数据构建开始")
        logger.info("=" * 60)
        
        if force_rebuild:
            self.milvus_manager.drop_collection()
            self.milvus_manager.clean_old_collections()
        
        self.milvus_manager.ensure_collection()
        
        # 如果已有数据且不强制重建，跳过
        count = self.milvus_manager.get_count()
        if count > 0 and not force_rebuild:
            logger.info(f"Milvus已有 {count} 条记录，跳过构建")
            return
        
        if force_rebuild:
            logger.info("强制重建模式，清空已有数据")
        
        # ====== 步骤1: 加载文档 ======
        logger.info("步骤1: 加载文档...")
        documents = self.doc_loader.load_all()
        if not documents:
            logger.warning("未找到任何文档")
            return
        
        # ====== 步骤2: 分块 + 向量化 + 存储 ======
        all_child_chunks = []
        parent_map = {}  # {parent_id: ParentChunk}
        
        for idx, (file_path, category, content) in enumerate(documents):
            logger.info(f"处理文档 {idx+1}/{len(documents)}: {Path(file_path).name}")
            
            # 2a. 父分块
            parent_chunks = self.parent_chunker.chunk(content, file_path, category)
            
            # 2b. 子分块
            for parent in parent_chunks:
                child_chunks = self.child_chunker.chunk(parent)
                parent_map[parent.id] = parent
                all_child_chunks.extend(child_chunks)
            
            logger.info(f"  父分块: {len(parent_chunks)}, 累计子分块: {len(all_child_chunks)}")
        
        logger.info(f"总子分块数: {len(all_child_chunks)}")
        
        # ====== 步骤3: 批量向量化 ======
        logger.info(f"步骤3: 批量向量化 {len(all_child_chunks)} 个子分块...")
        all_texts = [chunk.text for chunk in all_child_chunks]
        
        dense_vecs, sparse_vecs = self.embedding_model.encode_texts(all_texts, batch_size=32)
        
        # 将向量附加到子分块
        for i, chunk in enumerate(all_child_chunks):
            chunk.dense_vector = dense_vecs[i]
            chunk.sparse_vector = sparse_vecs[i]
        
        logger.info("向量化完成")
        
        # ====== 步骤4: 批量存储到Milvus ======
        import time
        created_at = int(time.time())
        logger.info(f"步骤4: 存储 {len(all_child_chunks)} 条记录到Milvus...")
        logger.info(f"  数据创建时间戳: {created_at} ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created_at))})")

        # 分批插入，避免单次过大
        batch_size = 100
        for i in range(0, len(all_child_chunks), batch_size):
            batch = all_child_chunks[i:i + batch_size]
            self.milvus_manager.insert_with_parent_info(batch, parent_map, created_at=created_at)
            logger.info(f"  已插入 {min(i + batch_size, len(all_child_chunks))}/{len(all_child_chunks)}")
        
        # ====== 保存数据跟踪状态（支持后续增量更新）======
        from rag.data_loader.data_tracker import DataTracker
        tracker = DataTracker()
        for file_path, _, _ in documents:
            # 收集该文件对应的所有子分块信息
            file_chunks = [
                c for c in all_child_chunks
                if parent_map.get(c.parent_id)
                and parent_map[c.parent_id].source_file == file_path
            ]
            chunk_infos = [
                {
                    "child_id": c.id,
                    "text_hash": DataTracker.compute_text_hash(c.text),
                    "parent_id": c.parent_id,
                }
                for c in file_chunks
            ]
            tracker.update_file_state(Path(file_path), chunk_infos)
        tracker.save()
        logger.info(f"数据跟踪状态已保存: {tracker.state_file}")

        # ====== 验证 ======
        final_count = self.milvus_manager.get_count()
        logger.info("=" * 60)
        logger.info(f"RAG数据构建完成！")
        logger.info(f"  文档数: {len(documents)}")
        logger.info(f"  子分块数: {len(all_child_chunks)}")
        logger.info(f"  Milvus记录数: {final_count}")
        logger.info("=" * 60)

    def incremental_update(self) -> bool:
        """
        增量更新向量数据库 - 检测文件变更，只处理变化的分块

        Returns:
            是否有数据更新
        """
        from rag.data_loader.data_tracker import DataTracker
        import time

        tracker = DataTracker()
        changes = tracker.scan_changes()

        if not changes["new"] and not changes["modified"] and not changes["deleted"]:
            logger.info("增量更新: 无文件变更")
            return False

        logger.info("=" * 60)
        logger.info("增量更新开始")
        logger.info(f"  新增: {len(changes['new'])} | 修改: {len(changes['modified'])} | 删除: {len(changes['deleted'])}")
        logger.info("=" * 60)

        self.milvus_manager.ensure_collection()
        created_at = int(time.time())

        # ====== 处理已删除的文件 ======
        for file_path in changes["deleted"]:
            old_ids = tracker.get_child_ids(file_path)
            if old_ids:
                ids_str = ",".join(f"'{cid}'" for cid in old_ids)
                self.milvus_manager.delete_by_expression(f"id in [{ids_str}]")
                logger.info(f"已删除: {file_path.name} ({len(old_ids)}个分块)")
            tracker.remove_file(file_path)

        # ====== 处理新增/修改的文件 ======
        changed_files = changes["new"] + changes["modified"]
        all_new_chunks = []
        parent_map = {}

        for idx, file_path in enumerate(changed_files):
            logger.info(f"处理 {idx+1}/{len(changed_files)}: {file_path.name}")

            ext = file_path.suffix.lower()
            if ext not in RAGConfig.SUPPORTED_FILE_TYPES:
                continue

            try:
                content = self.doc_loader._load_file(file_path, ext)
            except Exception as e:
                logger.error(f"加载失败 {file_path}: {e}")
                continue

            if not content.strip():
                continue

            category = file_path.parent.name
            parent_chunks = self.parent_chunker.chunk(content, str(file_path), category)

            file_new_chunks = []
            file_parent_map = {}
            for parent in parent_chunks:
                children = self.child_chunker.chunk(parent)
                file_parent_map[parent.id] = parent
                file_new_chunks.extend(children)

            # MD5对比：检测真正变化的分块（仅用于统计日志）
            old_hashes = tracker.get_chunk_text_hashes(file_path)
            changed_count = sum(
                1 for c in file_new_chunks
                if DataTracker.compute_text_hash(c.text) not in old_hashes
            )
            skipped_count = len(file_new_chunks) - changed_count
            logger.info(f"  分块: {len(file_new_chunks)} (新/变={changed_count}, 未变={skipped_count})")

            # 删除该文件的旧分块
            old_ids = tracker.get_child_ids(file_path)
            if old_ids:
                ids_str = ",".join(f"'{cid}'" for cid in old_ids)
                self.milvus_manager.delete_by_expression(f"id in [{ids_str}]")

            all_new_chunks.extend(file_new_chunks)
            parent_map.update(file_parent_map)

        # ====== 编码所有新分块 ======
        if all_new_chunks:
            texts = [c.text for c in all_new_chunks]
            logger.info(f"编码 {len(texts)} 个分块...")
            dense_vecs, sparse_vecs = self.embedding_model.encode_texts(texts, batch_size=32)
            for i, c in enumerate(all_new_chunks):
                c.dense_vector = dense_vecs[i]
                c.sparse_vector = sparse_vecs[i]

            # 分批插入
            batch_size = 100
            for i in range(0, len(all_new_chunks), batch_size):
                batch = all_new_chunks[i:i + batch_size]
                self.milvus_manager.insert_with_parent_info(batch, parent_map, created_at=created_at)
        else:
            logger.info("无需要编码的新分块")

        # ====== 更新状态文件 ======
        for file_path in changed_files:
            try:
                file_chunks = [
                    c for c in all_new_chunks
                    if parent_map.get(c.parent_id)
                    and parent_map[c.parent_id].source_file == str(file_path)
                ]
                chunk_infos = [
                    {
                        "child_id": c.id,
                        "text_hash": DataTracker.compute_text_hash(c.text),
                        "parent_id": c.parent_id,
                    }
                    for c in file_chunks
                ]
                tracker.update_file_state(file_path, chunk_infos)
            except Exception as e:
                logger.warning(f"更新文件状态失败 {file_path}: {e}")

        for file_path in changes["deleted"]:
            tracker.remove_file(file_path)

        tracker.save()

        final_count = self.milvus_manager.get_count()
        logger.info("=" * 60)
        logger.info(f"增量更新完成！Milvus 记录数: {final_count}")
        logger.info("=" * 60)
        return True


# ====== 便捷函数 ======

def build_rag_index(force_rebuild: bool = False):
    """构建RAG索引的便捷函数"""
    builder = RAGDataBuilder()
    builder.build(force_rebuild=force_rebuild)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="RAG数据构建脚本")
    parser.add_argument("--rebuild", action="store_true", help="强制重建")
    args = parser.parse_args()
    
    build_rag_index(force_rebuild=args.rebuild)
