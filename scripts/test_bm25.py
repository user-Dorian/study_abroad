"""测试BM25检索功能"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retrieval.bm25_index_builder import BM25IndexBuilder
from utils.logger import logger


def test_bm25_retrieval():
    """测试BM25检索功能"""
    print("=" * 60)
    print("BM25检索功能测试")
    print("=" * 60)

    # 1. 初始化检索器
    print("\n[1] 初始化BM25检索器...")
    builder = BM25IndexBuilder()
    retriever = builder.initialize()

    if not retriever.is_loaded:
        print("✗ 检索器初始化失败")
        return False

    print(f"✓ 检索器初始化成功，共索引 {len(retriever.questions)} 个问题")

    # 2. 测试多个查询
    test_queries = [
        ("美国留学费用", 5),
        ("英国签证怎么办", 3),
        "申请奖学金条件",
        "计算机专业前景",
        "留学需要准备什么材料",
        "澳洲打工政策",
    ]

    print("\n" + "=" * 60)
    print("[2] 测试检索功能")
    print("=" * 60)

    for item in test_queries:
        if isinstance(item, tuple):
            query, top_k = item
        else:
            query = item
            top_k = 5

        print(f"\n查询: {query}")
        results = retriever.search(query, top_k=top_k)

        if not results:
            print("  无结果")
        else:
            for i, (qa_id, score, question) in enumerate(results, 1):
                print(f"  {i}. [ID:{qa_id}] 得分:{score:.4f} - {question}")

    # 3. 测试从文件加载索引
    print("\n" + "=" * 60)
    print("[3] 测试索引文件加载")
    print("=" * 60)

    retriever2 = builder.initialize()
    if retriever2.is_loaded:
        print(f"✓ 从文件加载索引成功，共 {len(retriever2.questions)} 个问题")
    else:
        print("✗ 从文件加载索引失败")

    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    test_bm25_retrieval()
