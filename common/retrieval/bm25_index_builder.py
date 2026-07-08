"""BM25索引构建器 - 系统首次启动时构建"""
import psycopg2
import psycopg2.extras
import jieba
from common.config.base_database import DatabaseConfig
from common.retrieval.bm25_retriever import BM25Retriever
from common.utils.logger import logger


class BM25IndexBuilder:
    """BM25索引构建器，负责从数据库读取问答对并构建检索索引"""

    def __init__(self):
        self.retriever = BM25Retriever()

    def fetch_all_questions(self) -> list:
        """从数据库获取所有问答对的问题和ID"""
        try:
            conn = psycopg2.connect(**DatabaseConfig.get_connection_params())
            cursor = conn.cursor()

            cursor.execute("SELECT id, question FROM qa_pairs ORDER BY id")
            questions = cursor.fetchall()

            cursor.close()
            conn.close()

            logger.info(f"从数据库获取到 {len(questions)} 条问答对")
            return questions

        except Exception as e:
            logger.error(f"从数据库获取问答对失败: {e}")
            return []

    def save_tokenized_to_db(self, questions: list) -> bool:
        """
        将所有问题的分词结果保存到tokenized_questions表
        每次启动都会完全覆写原有数据，确保与qa_pairs表数据同步

        Args:
            questions: [(id, question_text), ...] 列表

        Returns:
            保存是否成功
        """
        try:
            conn = psycopg2.connect(**DatabaseConfig.get_connection_params())
            cursor = conn.cursor()

            # 每次启动先清空原有分词数据
            cursor.execute("DELETE FROM tokenized_questions")
            logger.info("已清空原有分词数据")

            # 分词并插入
            insert_sql = """
            INSERT INTO tokenized_questions (qa_pair_id, question_text, tokenized_text)
            VALUES (%s, %s, %s)
            """

            data_to_insert = []
            for qa_id, question_text in questions:
                # 使用BM25Retriever的分词方法，保证分词逻辑一致
                tokenized = self.retriever.tokenize(question_text)
                tokenized_str = " ".join(tokenized)
                data_to_insert.append((qa_id, question_text, tokenized_str))

            cursor.executemany(insert_sql, data_to_insert)
            conn.commit()

            logger.info(f"✓ 成功将 {len(data_to_insert)} 条分词结果保存到数据库（完全覆写）")

            cursor.close()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"保存分词结果到数据库失败: {e}")
            return False

    def build_and_save(self) -> bool:
        """
        构建BM25索引并保存到数据库和文件

        Returns:
            构建是否成功
        """
        try:
            # 1. 获取所有问答对
            questions = self.fetch_all_questions()
            if not questions:
                logger.warning("没有获取到问答对数据")
                return False

            question_ids = [q[0] for q in questions]
            question_texts = [q[1] for q in questions]

            # 2. 保存分词结果到数据库（首次启动）
            if not self.save_tokenized_to_db(questions):
                logger.error("保存分词结果到数据库失败")
                return False

            # 3. 构建BM25索引
            if not self.retriever.build_index(question_texts, question_ids):
                logger.error("构建BM25索引失败")
                return False

            # 4. 保存索引到文件（用于快速加载）
            if not self.retriever.save_index():
                logger.warning("保存BM25索引文件失败，但数据库分词已保存")

            logger.info("✓ BM25索引构建完成")
            return True

        except Exception as e:
            logger.error(f"构建BM25索引失败: {e}")
            return False

    def initialize(self, force_rebuild: bool = False) -> BM25Retriever:
        """
        初始化BM25检索器（仅在系统服务器启动时调用一次）
        优先从缓存文件加载，缓存不存在时才从数据库重建

        Args:
            force_rebuild: 是否强制重建索引（忽略缓存）

        Returns:
            BM25Retriever实例
        """
        if not force_rebuild:
            # 优先从缓存文件加载，避免每次启动都重建
            logger.info("尝试从缓存文件加载BM25索引...")
            if self.retriever.load_index():
                count = len(self.retriever.questions)
                logger.info(f"BM25索引从缓存加载成功（{count} 个问题），跳过重建")
                return self.retriever
            logger.info("BM25缓存文件不存在，将从数据库重建索引")

        # 缓存不存在或强制重建，从数据库重新构建
        logger.info("开始构建BM25索引（从数据库重建）...")
        if self.build_and_save():
            logger.info("BM25索引构建成功")
        else:
            logger.error("BM25索引构建失败")

        return self.retriever


if __name__ == "__main__":
    # 测试构建
    builder = BM25IndexBuilder()
    retriever = builder.initialize()

    # 测试检索
    if retriever.is_loaded:
        test_query = "美国留学费用"
        results = retriever.search(test_query, top_k=5)
        print(f"\n测试查询: {test_query}")
        print(f"返回 {len(results)} 个结果:")
        for qa_id, score, question in results:
            print(f"  [ID: {qa_id}] 得分: {score:.4f} - {question}")
