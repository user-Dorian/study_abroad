"""检查RAG配置加载情况"""
import os
import sys
from pathlib import Path

# 确保项目路径在sys.path中
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("环境变量检查:")
print("=" * 60)
print(f"EMBEDDING_MODEL_PATH: {os.getenv('EMBEDDING_MODEL_PATH', 'NOT SET')}")
print(f"MILVUS_DATABASE_NAME: {os.getenv('MILVUS_DATABASE_NAME', 'NOT SET')}")
print(f"MILVUS_COLLECTION_NAME: {os.getenv('MILVUS_COLLECTION_NAME', 'NOT SET')}")

print("\n" + "=" * 60)
print("RAGConfig 配置检查:")
print("=" * 60)

from rag.rag_config import RAGConfig

print(f"EMBEDDING_MODEL_NAME: {RAGConfig.EMBEDDING_MODEL_NAME}")
print(f"MILVUS_DATABASE_NAME: {RAGConfig.MILVUS_DATABASE_NAME}")
print(f"MILVUS_COLLECTION_NAME: {RAGConfig.MILVUS_COLLECTION_NAME}")

print("\n" + "=" * 60)
print("配置摘要:")
print("=" * 60)
summary = RAGConfig.get_config_summary()
for key, value in summary.items():
    print(f"{key}: {value}")
