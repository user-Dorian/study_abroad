"""BM25检索模型 - 基于分词的问题检索"""
import pickle
import os
from pathlib import Path
from typing import List, Tuple, Optional
from rank_bm25 import BM25Okapi
import jieba
from utils.logger import logger


# BM25中文停用词表 - 过滤高频无意义词
BM25_STOP_WORDS = {
    # 助词/介词/连词
    "的", "了", "是", "在", "有", "和", "与", "或", "吗", "呢",
    "吧", "啊", "哦", "嗯", "么", "嘛", "呀", "啦", "哟",
    # 代词
    "你", "我", "他", "她", "它", "们", "您", "自己",
    # 动词（高频泛义）
    "做", "能", "会", "想", "要", "说", "去", "来", "给",
    "让", "把", "被", "看", "叫", "过", "到", "觉得",
    # 副词/程度词
    "很", "最", "太", "更", "都", "也", "还", "就", "才",
    "真", "挺", "非常", "特别",
    # 疑问词
    "什么", "怎么", "怎样", "为什么", "哪些", "哪个", "几个", "多少",
    # 指示词
    "这个", "那个", "这里", "那里", "这样", "那样",
    # 其他泛义词
    "可以", "需要", "应该", "如果", "因为", "所以",
    "但是", "不过", "然后", "而且", "还是",
}


class BM25Retriever:
    """BM25检索器，用于基于关键词匹配的问题检索"""

    def __init__(self, index_dir: Optional[str] = None):
        """
        初始化BM25检索器

        Args:
            index_dir: 索引文件存储目录，默认为项目根目录下的bm25_index
        """
        if index_dir is None:
            self.index_dir = Path(__file__).resolve().parent.parent / "bm25_index"
        else:
            self.index_dir = Path(index_dir)

        self.index_dir.mkdir(exist_ok=True)

        self.bm25_model: Optional[BM25Okapi] = None
        self.corpus: List[List[str]] = []  # 分词后的语料库
        self.questions: List[str] = []  # 原始问题列表
        self.question_ids: List[int] = []  # 问题ID列表
        self.is_loaded = False

    def tokenize(self, text: str) -> List[str]:
        """
        对文本进行分词，仅对英文字母转小写，过滤停用词

        Args:
            text: 输入文本

        Returns:
            分词后的词列表
        """
        # 使用jieba分词
        words = jieba.lcut(text)
        # 过滤空白字符和停用词，仅对英文转小写
        filtered_words = []
        for w in words:
            stripped = w.strip()
            if not stripped:
                continue
            if stripped.lower() in BM25_STOP_WORDS:
                continue
            # 仅对纯英文单词转小写，中文不受影响
            if stripped.isascii():
                filtered_words.append(stripped.lower())
            else:
                filtered_words.append(stripped)
        return filtered_words

    def build_index(self, questions: List[str], question_ids: List[int]) -> bool:
        """
        构建BM25索引

        Args:
            questions: 问题文本列表
            question_ids: 对应的問題ID列表

        Returns:
            构建是否成功
        """
        if not questions or not question_ids:
            logger.warning("问题列表为空，无法构建BM25索引")
            return False

        if len(questions) != len(question_ids):
            logger.error("问题数量和ID数量不匹配")
            return False

        try:
            # 对所有问题进行分词并转小写
            logger.info(f"开始构建BM25索引，共 {len(questions)} 个问题...")
            self.corpus = [self.tokenize(q) for q in questions]
            self.questions = questions
            self.question_ids = question_ids

            # 构建BM25模型
            self.bm25_model = BM25Okapi(self.corpus)
            self.is_loaded = True

            logger.info(f"BM25索引构建完成，共处理 {len(self.corpus)} 个文档")
            return True

        except Exception as e:
            logger.error(f"构建BM25索引失败: {e}")
            return False

    def save_index(self, filename: str = "bm25_index.pkl") -> bool:
        """
        保存BM25索引到文件

        Args:
            filename: 索引文件名

        Returns:
            保存是否成功
        """
        if not self.is_loaded or self.bm25_model is None:
            logger.warning("索引未构建，无法保存")
            return False

        try:
            index_path = self.index_dir / filename

            index_data = {
                "bm25_model": self.bm25_model,
                "corpus": self.corpus,
                "questions": self.questions,
                "question_ids": self.question_ids,
            }

            with open(index_path, "wb") as f:
                pickle.dump(index_data, f)

            logger.info(f"BM25索引已保存到 {index_path}")
            return True

        except Exception as e:
            logger.error(f"保存BM25索引失败: {e}")
            return False

    def load_index(self, filename: str = "bm25_index.pkl") -> bool:
        """
        从文件加载BM25索引

        Args:
            filename: 索引文件名

        Returns:
            加载是否成功
        """
        index_path = self.index_dir / filename

        if not index_path.exists():
            logger.info(f"索引文件不存在: {index_path}")
            return False

        try:
            with open(index_path, "rb") as f:
                index_data = pickle.load(f)

            self.bm25_model = index_data["bm25_model"]
            self.corpus = index_data["corpus"]
            self.questions = index_data["questions"]
            self.question_ids = index_data["question_ids"]
            self.is_loaded = True

            logger.info(f"BM25索引已从 {index_path} 加载")
            return True

        except Exception as e:
            logger.error(f"加载BM25索引失败: {e}")
            return False

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Tuple[int, float, str]]:
        """
        检索与查询最相关的问题

        Args:
            query: 查询文本
            top_k: 返回结果数量

        Returns:
            结果列表，每个元素为 (question_id, score, question_text)
        """
        if not self.is_loaded or self.bm25_model is None:
            logger.error("BM25索引未加载，无法检索")
            return []

        try:
            # 对查询进行分词并转小写
            query_tokens = self.tokenize(query)

            if not query_tokens:
                logger.warning("查询分词结果为空")
                return []

            # 计算BM25得分
            scores = self.bm25_model.get_scores(query_tokens)

            # 获取top_k结果
            top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

            results = []
            for idx in top_indices:
                if scores[idx] > 0:  # 只返回得分大于0的结果
                    results.append((
                        self.question_ids[idx],
                        float(scores[idx]),
                        self.questions[idx],
                    ))

            logger.debug(f"查询 '{query}' 返回 {len(results)} 个结果")
            return results

        except Exception as e:
            logger.error(f"BM25检索失败: {e}")
            return []

    def index_exists(self, filename: str = "bm25_index.pkl") -> bool:
        """检查索引文件是否存在"""
        index_path = self.index_dir / filename
        return index_path.exists()
