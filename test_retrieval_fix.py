"""测试RAG检索功能"""
import sys
from pathlib import Path

# 确保项目路径在sys.path中
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from rag.retrieval.rag_retriever import rag_retriever

# 测试问题
test_questions = [
    "美国留学签证需要什么材料？",
    "留学费用大概多少？"
]

print("=" * 60)
print("开始测试RAG检索")
print("=" * 60)

for i, question in enumerate(test_questions, 1):
    print(f"\n测试 {i}: {question}")
    print("-" * 60)
    try:
        answer = rag_retriever.query(question)
        print(f"回答: {answer[:200]}...")
        print("✓ 测试通过")
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
