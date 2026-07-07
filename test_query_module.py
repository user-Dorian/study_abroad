"""测试用户输入模块的完整匹配流程"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import handle_query
from handlers.query_handler import QueryHandler
from utils.logger import logger


def test_query_pipeline():
    """测试查询管线的各个分支"""
    print("=" * 70)
    print("用户输入模块测试")
    print("=" * 70)

    handler = QueryHandler()

    print("\n--- 组件状态 ---")
    print(f"  Redis:   {'已连接' if handler.redis_client else '未连接(将降级)'}")
    print(f"  BM25:    {'已加载' if handler.bm25_retriever and handler.bm25_retriever.is_loaded else '未加载'}")
    print(f"  数据库:  {'已连接' if handler.db_pool else '未连接'}")

    # 测试用例
    test_cases = [
        {
            "name": "BM25高置信度匹配（数据库中有答案）",
            "query": "申请奖学金需要什么条件？",
            "expected": "走BM25 → SQL路径",
        },
        {
            "name": "BM25高置信度匹配（语义相近但不同）",
            "query": "申请奖学金条件",
            "expected": "BM25匹配到'申请奖学金需要什么条件？' → SQL查答案",
        },
        {
            "name": "BM25中等置信度（阈值边界测试）",
            "query": "美国留学费用",
            "expected": "BM25概率分布可能分散，低于0.7 → 走RAG",
        },
        {
            "name": "完全无关问题",
            "query": "怎么做红烧肉",
            "expected": "BM25概率低于阈值 → 走RAG",
        },
    ]

    for i, tc in enumerate(test_cases, 1):
        print(f"\n{'=' * 70}")
        print(f"[测试 {i}/{len(test_cases)}] {tc['name']}")
        print(f"  查询: {tc['query']}")
        print(f"  预期路径: {tc['expected']}")
        print(f"{'=' * 70}")

        try:
            answer = handle_query(tc['query'], handler)
            print(f"  答案: {answer[:100]}...")
            print(f"  ✓ 测试通过")
        except Exception as e:
            print(f"  ✗ 测试失败: {e}")

    # 测试Redis缓存写入（如果Redis可用）
    if handler.redis_client:
        print(f"\n{'=' * 70}")
        print("[测试 Redis缓存写入]")
        print(f"{'=' * 70}")

        test_question = "测试缓存问题"
        test_answer = "这是测试答案"
        success = handler.cache_to_redis(test_question, test_answer)
        print(f"  写入结果: {'成功' if success else '失败'}")

        # 验证读取
        answer = handler.redis_exact_match(test_question)
        print(f"  读取验证: {'成功' if answer == test_answer else '失败'}")

        if answer == test_answer:
            # 验证TTL
            ttl = handler.redis_client.ttl(f"qa:{test_question}")
            print(f"  TTL剩余: {ttl}秒 (预期3600)")

        # 测试全词匹配命中
        answer = handler.redis_exact_match(test_question)
        print(f"  全词匹配: {'命中' if answer else '未命中'}")
    else:
        print(f"\n{'=' * 70}")
        print("[测试 Redis缓存写入] 跳过(Redis不可用)")
        print(f"{'=' * 70}")

    print(f"\n{'=' * 70}")
    print("所有测试完成!")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    test_query_pipeline()
