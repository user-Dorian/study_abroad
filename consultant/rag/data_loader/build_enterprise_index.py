"""企业数据构建脚本 - 读取企业数据文件，提取QA对并构建向量索引

功能：
1. 读取 enterprise/ 目录下的所有 Markdown 和 CSV 文件
2. 从表格中提取 QA 对（结构化问答数据）
3. 将 QA 对插入到 PostgreSQL 的 enterprise_qa_pairs 表
4. 将文档内容分块后构建 Milvus 向量索引（企业数据集合 enterprise_data_vectors）
"""

import os
import sys
import re
import csv
import io
import time
import uuid
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Generator

# 确保项目根目录在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pandas as pd

from consultant.config.database import ConsultantDatabaseConfig
from consultant.config.settings import ConsultantConfig
from consultant.rag.rag_config import ConsultantRAGConfig
from common.rag.data_loader.chunk_and_embed import EmbeddingModel, MilvusManager
from common.rag.prompts.prompt_template import prompt_manager
from common.utils.logger import logger


class EnterpriseDataBuilder:
    """企业数据构建器 - 读取企业数据文件，提取QA对并构建向量索引"""

    def __init__(self):
        self.data_dir: Path = ConsultantRAGConfig.DATA_DIR
        self.qa_pairs: List[Dict[str, str]] = []  # [{question, answer, category}]
        self.embedding_model: Optional[EmbeddingModel] = None
        self.milvus_manager: Optional[MilvusManager] = None
        self._init_services()

    def _init_services(self):
        """初始化嵌入模型和 Milvus 管理器（仅在需要时加载）"""
        try:
            self.embedding_model = EmbeddingModel(
                model_name=ConsultantRAGConfig.EMBEDDING_MODEL_NAME,
                device=ConsultantRAGConfig.EMBEDDING_DEVICE,
            )
            self.milvus_manager = MilvusManager(
                host=ConsultantRAGConfig.MILVUS_HOST,
                port=ConsultantRAGConfig.MILVUS_PORT,
                collection_name=ConsultantRAGConfig.MILVUS_COLLECTION_NAME,
            )
            logger.info("[企业数据构建] EmbeddingModel + MilvusManager 初始化完成")
        except Exception as e:
            logger.warning(f"[企业数据构建] 服务初始化失败（可继续数据解析阶段）: {e}")

    # ==================== 文件扫描 ====================

    def scan_data_files(self) -> List[Path]:
        """扫描企业数据目录，返回所有支持的文件列表"""
        if not self.data_dir.exists():
            logger.error(f"企业数据目录不存在: {self.data_dir}")
            return []

        supported_exts = {".md", ".csv"}
        files = []
        for f in sorted(self.data_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in supported_exts:
                files.append(f)
                logger.info(f"发现数据文件: {f.name}")
        logger.info(f"共发现 {len(files)} 个数据文件")
        return files

    # ==================== Markdown 解析 ====================

    def _extract_markdown_section_title(self, lines: List[str], table_start_idx: int) -> str:
        """从 Markdown 中提取表格上方的最近一个章节标题"""
        for i in range(table_start_idx - 1, -1, -1):
            line = lines[i].strip()
            # 匹配 ## 或 ### 等标题
            if line.startswith("#"):
                # 去掉前面的 # 符号
                title = line.lstrip("#").strip()
                # 去除编号前缀如 "1.1 "
                title = re.sub(r"^[\d.]+[\s\u3000]*", "", title)
                return title
        return "通用数据"

    def _parse_markdown_table(self, lines: List[str], start_idx: int) -> Tuple[List[str], int]:
        """
        从指定行开始解析一个 Markdown 表格

        Returns:
            (headers, end_idx) 表头列表和结束行索引（不含）
        """
        # 跳过表头分隔行（|---|---|...|）
        header_line = lines[start_idx].strip()
        headers = [h.strip() for h in header_line.strip("|").split("|")]

        # 跳过分隔行
        row_start = start_idx + 1
        if row_start < len(lines) and "---" in lines[row_start]:
            row_start += 1

        # 收集所有数据行
        data_lines = []
        end_idx = row_start
        for i in range(row_start, len(lines)):
            line = lines[i].strip()
            if not line.startswith("|") or not line.endswith("|"):
                end_idx = i
                break
            data_lines.append(line)
            end_idx = i + 1

        return headers, end_idx, data_lines

    def _markdown_row_to_qa_pairs(
        self, headers: List[str], row_cells: List[str], category: str
    ) -> List[Dict[str, str]]:
        """
        将 Markdown 表格的一行数据转换为多个 QA 对

        规则：第一列是实体名称（如院校名），其余每列标题+值生成一个 QA 对
        例如：| 哈佛大学 | 战略级 | ... |
        → Q: "哈佛大学的合作等级是什么？"  A: "战略级"
        """
        qa_pairs = []
        if len(row_cells) < 2:
            return qa_pairs

        entity = row_cells[0].strip()
        if not entity:
            return qa_pairs

        for i in range(1, min(len(headers), len(row_cells))):
            col_header = headers[i].strip()
            col_value = row_cells[i].strip()
            if not col_header or not col_value or col_value == "-":
                continue

            # 构建自然语言问答
            question = f"{entity}的{col_header}是什么？"
            answer = col_value

            qa_pairs.append({
                "question": question,
                "answer": answer,
                "category": category,
            })

        return qa_pairs

    def parse_markdown_file(self, file_path: Path) -> List[Dict[str, str]]:
        """
        解析 Markdown 文件，提取所有表格中的 QA 对

        Args:
            file_path: Markdown 文件路径

        Returns:
            QA 对列表 [{question, answer, category}]
        """
        qa_pairs = []
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"读取 Markdown 文件失败 {file_path.name}: {e}")
            return qa_pairs

        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            # 检测表格行（以 | 开头和结尾）
            if line.strip().startswith("|") and line.strip().endswith("|"):
                # 确保下一行是分隔行（含 ---）
                if i + 1 < len(lines) and "---" in lines[i + 1]:
                    section_title = self._extract_markdown_section_title(lines, i)
                    headers, end_idx, data_lines = self._parse_markdown_table(lines, i)

                    logger.debug(
                        f"  [Markdown] 表格: '{section_title}' "
                        f"表头={headers}, 行数={len(data_lines)}"
                    )

                    for row_line in data_lines:
                        cells = [c.strip() for c in row_line.strip("|").split("|")]
                        row_qa = self._markdown_row_to_qa_pairs(headers, cells, section_title)
                        qa_pairs.extend(row_qa)

                    i = end_idx
                    continue
            i += 1

        logger.info(f"Markdown [{file_path.name}] 提取 {len(qa_pairs)} 个 QA 对")
        return qa_pairs

    # ==================== CSV 解析 ====================

    def parse_csv_file(self, file_path: Path) -> List[Dict[str, str]]:
        """
        解析 CSV 文件，提取 QA 对

        规则：第一列为实体名，其余每列标题+值生成 QA 对
        文件名（不含扩展名）作为分类

        Args:
            file_path: CSV 文件路径

        Returns:
            QA 对列表 [{question, answer, category}]
        """
        qa_pairs = []
        category = file_path.stem  # 文件名作为分类

        try:
            # 先尝试用 pandas 读取（支持更多编码格式）
            try:
                df = pd.read_csv(file_path, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding="gbk")

            columns = list(df.columns)
            if len(columns) < 2:
                logger.warning(f"CSV 文件列数不足: {file_path.name}")
                return qa_pairs

            first_col = columns[0]

            for _, row in df.iterrows():
                entity = str(row[first_col]).strip()
                if not entity or entity == "nan":
                    continue

                for col in columns[1:]:
                    val = str(row[col]).strip()
                    if not val or val == "nan" or val == "-":
                        continue

                    question = f"{entity}的{col}是什么？"
                    answer = val
                    qa_pairs.append({
                        "question": question,
                        "answer": answer,
                        "category": category,
                    })

        except Exception as e:
            logger.error(f"解析 CSV 文件失败 {file_path.name}: {e}")

        logger.info(f"CSV [{file_path.name}] 提取 {len(qa_pairs)} 个 QA 对")
        return qa_pairs

    # ==================== 文档内容提取（用于向量索引） ====================

    def collect_document_chunks(self, file_paths: List[Path]) -> List[Dict]:
        """
        收集文件中的段落内容，用于构建向量索引

        Returns:
            [{text, source_file, category}] 列表
        """
        doc_chunks = []

        for file_path in file_paths:
            ext = file_path.suffix.lower()
            category = file_path.stem

            try:
                if ext == ".md":
                    chunks = self._extract_markdown_paragraphs(file_path, category)
                    doc_chunks.extend(chunks)
                elif ext == ".csv":
                    chunks = self._extract_csv_records(file_path, category)
                    doc_chunks.extend(chunks)
            except Exception as e:
                logger.error(f"提取文档块失败 {file_path.name}: {e}")

        logger.info(f"共收集 {len(doc_chunks)} 个文档块用于向量索引")
        return doc_chunks

    def _extract_markdown_paragraphs(self, file_path: Path, category: str) -> List[Dict]:
        """提取 Markdown 中的段落（非表格内容）用于向量索引"""
        chunks = []
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"读取失败 {file_path.name}: {e}")
            return chunks

        # 分割段落（按空行）
        paragraphs = re.split(r"\n\s*\n", content)
        for para in paragraphs:
            para = para.strip()
            # 过滤太短或全是表格式的内容
            if len(para) < 20:
                continue
            # 跳过纯表格行
            if all(line.strip().startswith("|") for line in para.split("\n") if line.strip()):
                continue
            # 跳过声明性文字
            if para.startswith("**数据声明：") or para.startswith("---"):
                continue
            if "注意：本文件" in para or "所有数据均为模拟生成" in para:
                continue

            chunks.append({
                "text": para,
                "source_file": str(file_path),
                "category": category,
            })

        return chunks

    def _extract_csv_records(self, file_path: Path, category: str) -> List[Dict]:
        """将 CSV 每行数据格式化为文本描述，用于向量索引"""
        chunks = []
        try:
            try:
                df = pd.read_csv(file_path, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding="gbk")

            columns = list(df.columns)
            for _, row in df.iterrows():
                parts = []
                for col in columns:
                    val = str(row[col]).strip()
                    if val and val != "nan":
                        parts.append(f"{col}: {val}")
                if parts:
                    text = "，".join(parts)
                    chunks.append({
                        "text": text,
                        "source_file": str(file_path),
                        "category": category,
                    })
        except Exception as e:
            logger.error(f"处理 CSV 记录失败 {file_path.name}: {e}")

        return chunks

    # ==================== 数据库操作 ====================

    def _get_db_connection(self):
        """获取 PostgreSQL 数据库连接"""
        import psycopg2
        conn = psycopg2.connect(**ConsultantDatabaseConfig.get_connection_params())
        return conn

    def clear_existing_qa_pairs(self):
        """清空 enterprise_qa_pairs 表中的现有数据"""
        try:
            conn = self._get_db_connection()
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE enterprise_qa_pairs RESTART IDENTITY CASCADE;")
                conn.commit()
            conn.close()
            logger.info("[数据库] 已清空 enterprise_qa_pairs 表")
        except Exception as e:
            logger.warning(f"[数据库] 清空 enterprise_qa_pairs 表失败: {e}")

    def insert_qa_to_database(self, qa_pairs: List[Dict[str, str]], batch_size: int = 100):
        """
        将 QA 对批量插入到 enterprise_qa_pairs 表

        Args:
            qa_pairs: QA 对列表 [{question, answer, category}]
            batch_size: 每批插入条数
        """
        if not qa_pairs:
            logger.warning("[数据库] 无 QA 对可插入")
            return

        import psycopg2.extras

        conn = None
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            # 分批插入
            total = len(qa_pairs)
            inserted = 0

            for i in range(0, total, batch_size):
                batch = qa_pairs[i : i + batch_size]
                values = [
                    (item["question"], item["answer"], item["category"])
                    for item in batch
                ]

                psycopg2.extras.execute_values(
                    cursor,
                    """
                    INSERT INTO enterprise_qa_pairs (question, answer, category)
                    VALUES %s
                    """,
                    values,
                    template="(%s, %s, %s)",
                )
                conn.commit()
                inserted += len(batch)
                logger.info(f"[数据库] 已插入 {inserted}/{total} 条 QA 对")

            conn.close()
            logger.info(f"[数据库] QA 对插入完成，共 {total} 条")

        except Exception as e:
            logger.error(f"[数据库] 插入 QA 对失败: {e}")
            if conn:
                conn.close()

    # ==================== Milvus 向量索引构建 ====================

    def build_milvus_index(self, doc_chunks: List[Dict]):
        """
        将文档块向量化后插入 Milvus

        Args:
            doc_chunks: 文档块列表 [{text, source_file, category}]
        """
        if not doc_chunks:
            logger.warning("[Milvus] 无文档块可索引")
            return

        if self.milvus_manager is None or self.embedding_model is None:
            logger.error("[Milvus] EmbeddingModel 或 MilvusManager 未初始化，跳过向量索引")
            return

        try:
            # 确保集合存在
            self.milvus_manager.ensure_collection()

            # 如果已有数据，先清空
            existing_count = self.milvus_manager.get_count()
            if existing_count > 0:
                logger.info(f"[Milvus] 集合中已有 {existing_count} 条记录，准备重建")
                self.milvus_manager.drop_collection()
                self.milvus_manager.ensure_collection()

            # 构建父分块
            from rag.data_loader.chunk_and_embed import ParentChunker, ChildChunker

            parent_chunker = ParentChunker(
                separator=ConsultantRAGConfig.PARENT_CHUNK_SEPARATOR
            )
            child_chunker = ChildChunker(
                max_chars=ConsultantRAGConfig.CHILD_CHUNK_MAX_CHARS,
                min_chars=ConsultantRAGConfig.CHILD_CHUNK_MIN_CHARS,
            )

            all_child_chunks = []
            parent_map = {}

            for idx, chunk in enumerate(doc_chunks):
                # 每个文档块作为一个父分块
                parents = parent_chunker.chunk(
                    chunk["text"], chunk["source_file"], chunk["category"]
                )
                for parent in parents:
                    children = child_chunker.chunk(parent)
                    parent_map[parent.id] = parent
                    all_child_chunks.extend(children)

                if (idx + 1) % 10 == 0:
                    logger.info(f"  [分块] 处理 {idx+1}/{len(doc_chunks)} 个文档块")

            logger.info(f"[Milvus] 分块完成: {len(all_child_chunks)} 个子分块")

            if not all_child_chunks:
                logger.warning("[Milvus] 无有效子分块，跳过向量化")
                return

            # 批量向量化
            all_texts = [c.text for c in all_child_chunks]
            logger.info(f"[Milvus] 开始向量化 {len(all_texts)} 个文本块...")
            dense_vecs, sparse_vecs = self.embedding_model.encode_texts(
                all_texts, batch_size=32
            )

            for i, chunk in enumerate(all_child_chunks):
                chunk.dense_vector = dense_vecs[i]
                chunk.sparse_vector = sparse_vecs[i]

            logger.info("[Milvus] 向量化完成")

            # 批量插入
            created_at = int(time.time())
            batch_size = 100
            for i in range(0, len(all_child_chunks), batch_size):
                batch = all_child_chunks[i : i + batch_size]
                self.milvus_manager.insert_with_parent_info(
                    batch, parent_map, created_at=created_at
                )
                logger.info(
                    f"  [Milvus] 已插入 {min(i + batch_size, len(all_child_chunks))}"
                    f"/{len(all_child_chunks)}"
                )

            final_count = self.milvus_manager.get_count()
            logger.info(
                f"[Milvus] 向量索引构建完成！Milvus 记录数: {final_count}"
            )

        except Exception as e:
            logger.error(f"[Milvus] 构建向量索引失败: {e}")
            raise

    # ==================== 主构建流程 ====================

    def build(self, force_rebuild: bool = False):
        """
        执行完整的企业数据构建流程

        Args:
            force_rebuild: 是否强制重建（清空现有数据和索引）
        """
        logger.info("=" * 60)
        logger.info("企业数据构建开始")
        logger.info(f"  数据目录: {self.data_dir}")
        logger.info(f"  强制重建: {force_rebuild}")
        logger.info("=" * 60)

        # 步骤 1: 扫描数据文件
        logger.info("步骤 1: 扫描数据文件...")
        files = self.scan_data_files()
        if not files:
            logger.warning("未找到数据文件，构建终止")
            return

        md_files = [f for f in files if f.suffix.lower() == ".md"]
        csv_files = [f for f in files if f.suffix.lower() == ".csv"]

        # 步骤 2: 提取 QA 对
        logger.info("步骤 2: 从文件中提取 QA 对...")
        all_qa_pairs = []

        for md_file in md_files:
            qa = self.parse_markdown_file(md_file)
            all_qa_pairs.extend(qa)
            logger.info(f"  Markdown [{md_file.name}]: {len(qa)} 个 QA 对")

        for csv_file in csv_files:
            qa = self.parse_csv_file(csv_file)
            all_qa_pairs.extend(qa)
            logger.info(f"  CSV [{csv_file.name}]: {len(qa)} 个 QA 对")

        logger.info(f"QA 对提取完成，共 {len(all_qa_pairs)} 个")

        # 步骤 3: 插入 QA 对到数据库
        logger.info("步骤 3: 插入 QA 对到 enterprise_qa_pairs 表...")
        if force_rebuild:
            self.clear_existing_qa_pairs()
        self.insert_qa_to_database(all_qa_pairs)

        # 步骤 4: 收集文档块用于向量索引
        logger.info("步骤 4: 收集文档块用于向量索引...")
        doc_chunks = self.collect_document_chunks(files)
        logger.info(f"文档块收集完成，共 {len(doc_chunks)} 个块")

        # 步骤 5: 构建 Milvus 向量索引
        logger.info("步骤 5: 构建 Milvus 向量索引...")
        self.build_milvus_index(doc_chunks)

        # ====== 统计汇总 ======
        logger.info("=" * 60)
        logger.info("企业数据构建完成！")
        logger.info(f"  数据文件数: {len(files)}")
        logger.info(f"  提取 QA 对: {len(all_qa_pairs)}")
        logger.info(f"  文档块数:   {len(doc_chunks)}")
        logger.info("=" * 60)


def build_enterprise_index(force_rebuild: bool = False):
    """企业数据构建的便捷入口函数"""
    builder = EnterpriseDataBuilder()
    builder.build(force_rebuild=force_rebuild)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="企业数据构建脚本")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="强制重建（清空现有数据后重新构建）",
    )
    args = parser.parse_args()

    build_enterprise_index(force_rebuild=args.rebuild)
