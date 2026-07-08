"""创建分词索引表"""
import psycopg2
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.config.base_database import DatabaseConfig
from common.utils.logger import logger


def create_tokenized_questions_table():
    """创建分词后的问题索引表"""
    try:
        conn = psycopg2.connect(**DatabaseConfig.get_connection_params())
        cursor = conn.cursor()

        create_table_sql = """
        CREATE TABLE IF NOT EXISTS tokenized_questions (
            id SERIAL PRIMARY KEY,
            qa_pair_id INT NOT NULL,
            question_text VARCHAR(500) NOT NULL,
            tokenized_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_qa_pair_id ON tokenized_questions(qa_pair_id);
        """

        cursor.execute(create_table_sql)
        conn.commit()
        logger.info("✓ 分词索引表创建成功")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        logger.error(f"✗ 创建分词索引表失败: {e}")
        return False


if __name__ == "__main__":
    create_tokenized_questions_table()
