"""测试BM25分数经过Softmax后的概率分布，用于设定阈值"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from retrieval.bm25_index_builder import BM25IndexBuilder
from retrieval.bm25_retriever import BM25Retriever


def softmax(scores, temperature=1.0):
    """计算Softmax概率分布"""
    scores = np.array(scores) / temperature
    exp_scores = np.exp(scores - np.max(scores))  # 数值稳定
    return exp_scores / exp_scores.sum()


def test_softmax_distribution():
    """测试不同查询的Softmax概率分布"""
    print("=" * 80)
    print("BM25 + Softmax 概率分布测试")
    print("=" * 80)
    
    # 初始化检索器
    builder = BM25IndexBuilder()
    retriever = builder.initialize()
    
    if not retriever.is_loaded:
        print("✗ 检索器初始化失败")
        return
    
    print(f"\n✓ 检索器初始化成功，共索引 {len(retriever.questions)} 个问题\n")
    
    # 测试查询
    test_queries = [
        "美国留学费用",
        "英国签证怎么办",
        "申请奖学金条件",
        "计算机专业前景",
        "留学需要准备什么材料",
        "澳洲打工政策",
        "完全无关的问题比如怎么做红烧肉",
    ]
    
    # 测试不同的temperature和top_k
    for top_k in [3, 5]:
        print(f"\n{'=' * 80}")
        print(f"Top-{top_k} 结果分析")
        print(f"{'=' * 80}")
        
        for query in test_queries:
            results = retriever.search(query, top_k=top_k)
            if not results:
                print(f"\n查询: {query}")
                print("  无结果")
                continue
            
            scores = [r[1] for r in results]
            probs = softmax(scores, temperature=1.0)
            
            print(f"\n查询: {query}")
            print(f"  Top-1 概率: {probs[0]:.4f} (原始分数: {scores[0]:.4f})")
            if top_k >= 3 and len(probs) >= 3:
                print(f"  Top-2 概率: {probs[1]:.4f} (原始分数: {scores[1]:.4f})")
                print(f"  Top-3 概率: {probs[2]:.4f} (原始分数: {scores[2]:.4f})")
            
            # 分析：Top-1概率是否超过某些阈值
            if probs[0] > 0.8:
                print(f"  → 极高置信度 (>{0.8})")
            elif probs[0] > 0.6:
                print(f"  → 高置信度 (>{0.6})")
            elif probs[0] > 0.4:
                print(f"  → 中等置信度 (>{0.4})")
            else:
                print(f"  → 低置信度 (<{0.4})")


if __name__ == "__main__":
    test_softmax_distribution()
