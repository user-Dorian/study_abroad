"""规划师端BM25索引构建器 - 从企业QA对表构建索引"""
import os
import psycopg2
import psycopg2.extras
import jieba
from pathlib import Path
from common.retrieval.bm25_retriever import BM25Retriever
from consultant.config.database import ConsultantDatabaseConfig
from common.utils.logger import logger


class ConsultantBM25IndexBuilder:
    """规划师端BM25索引构建器，从 enterprise_qa_pairs 表读取数据"""

    def __init__(self):
        self.retriever = BM25Retriever()
        # 使用独立的缓存文件
        self._cache_dir = Path(__file__).resolve().parent.parent.parent / "bm25_index"
        self._cache_dir.mkdir(exist_ok=True)
        self._cache_file = str(self._cache_dir / "enterprise_bm25_index.pkl")

    def fetch_all_questions(self) -> list:
        """从企业QA对表获取所有问答对"""
        try:
            conn = psycopg2.connect(**ConsultantDatabaseConfig.get_connection_params())
            cursor = conn.cursor()
            cursor.execute("SELECT id, question FROM enterprise_qa_pairs ORDER BY id")
            questions = cursor.fetchall()
            cursor.close()
            conn.close()

            logger.info(f"[规划师端] 从 enterprise_qa_pairs 获取到 {len(questions)} 条问答对")
            return questions
        except Exception as e:
            logger.error(f"[规划师端] 获取企业问答对失败: {e}")
            return []

    def save_tokenized_to_db(self, questions: list) -> bool:
        """将分词结果保存到企业分词表"""
        try:
            conn = psycopg2.connect(**ConsultantDatabaseConfig.get_connection_params())
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS enterprise_tokenized_questions")
            cursor.execute("""
                CREATE TABLE enterprise_tokenized_questions (
                    qa_pair_id INTEGER,
                    question_text TEXT,
                    tokenized_text TEXT
                )
            """)
            for qa_id, question_text in questions:
                tokens = jieba.lcut(question_text)
                tokenized = " ".join(tokens)
                cursor.execute(
                    "INSERT INTO enterprise_tokenized_questions (qa_pair_id, question_text, tokenized_text) VALUES (%s, %s, %s)",
                    (qa_id, question_text, tokenized)
                )
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"[规划师端] 企业分词数据保存成功: {len(questions)} 条")
            return True
        except Exception as e:
            logger.error(f"[规划师端] 保存企业分词数据失败: {e}")
            return False

    def initialize(self):
        """构建并保存企业BM25索引"""
        questions = self.fetch_all_questions()
        if not questions:
            logger.warning("[规划师端] 企业问答对为空，跳过BM25索引构建")
            return self.retriever

        # 构建BM25索引
        texts = [q[1] for q in questions]
        self.retriever.build_index(texts, ids=[q[0] for q in questions])

        # 保存到缓存
        try:
            import pickle
            with open(self._cache_file, 'wb') as f:
                pickle.dump({
                    'questions': self.retriever.questions,
                    'ids': self.retriever.ids,
                }, f)
            logger.info(f"[规划师端] BM25索引已缓存到: {self._cache_file}")
        except Exception as e:
            logger.warning(f"[规划师端] BM25索引缓存失败: {e}")

        self.retriever.is_loaded = True
        logger.info(f"[规划师端] BM25索引构建完成: {len(questions)} 个问题")
        return self.retriever

    def load_from_cache(self) -> bool:
        """从缓存加载BM25索引"""
        try:
            import pickle
            if os.path.exists(self._cache_file):
                with open(self._cache_file, 'rb') as f:
                    data = pickle.load(f)
                self.retriever.questions = data['questions']
                self.retriever.ids = data['ids']
                self.retriever.is_loaded = True
                logger.info(f"[规划师端] 企业BM25索引从缓存加载成功: {len(self.retriever.questions)} 个问题")
                return True
        except Exception as e:
            logger.warning(f"[规划师端] 企业BM25索引从缓存加载失败: {e}")
        return False
