"""用户输入处理主函数 - 编排多级检索匹配流程"""
import sys
from handlers.query_handler import QueryHandler
from utils.logger import logger


def handle_query(question: str, handler: QueryHandler = None) -> str:
    """
    处理用户查询的主函数，编排所有匹配逻辑

    匹配流程:
    1. Redis全词匹配 -> 命中则直接返回
    2. BM25相似度计算 + Softmax概率分布
       - 概率 >= 阈值(0.7):
         3. Redis查匹配问题 -> 命中则返回
         4. SQL查匹配问题 -> 命中则返回并缓存到Redis
       - 概率 < 阈值:
         5. 直接走RAG检索
    6. RAG检索(预留接口) -> 返回答案并缓存

    Args:
        question: 用户输入的问题
        handler: QueryHandler实例，为None时自动创建

    Returns:
        问题的答案
    """
    if handler is None:
        handler = QueryHandler()

    # ====== 1. Redis全词匹配 ======
    answer = handler.redis_exact_match(question)
    if answer is not None:
        return answer

    # ====== 2. BM25 + Softmax 匹配 ======
    matched_question, prob = handler.bm25_match_with_softmax(question)

    if prob >= 0.7 and matched_question is not None:
        logger.info(f"BM25匹配成功，尝试从缓存/数据库获取答案: {matched_question}")

        # ====== 3. Redis查匹配的问题 ======
        answer = handler.redis_exact_match(matched_question)
        if answer is not None:
            return answer

        # ====== 4. SQL查匹配的问题 ======
        answer = handler.query_database(matched_question)
        if answer is not None:
            # 写入Redis缓存
            handler.cache_to_redis(matched_question, answer)
            return answer

        # BM25匹配到了问题但Redis和SQL都没有答案，走RAG
        logger.warning(f"BM25匹配到'{matched_question}'但缓存和数据库均无答案，走RAG检索")
    else:
        # BM25匹配度不够，直接走RAG
        logger.info(f"BM25匹配度不足(概率={prob:.4f})，走RAG检索")

    # ====== 5/6. RAG检索 ======
    try:
        answer = handler.rag_retrieve(question)
        if answer:
            handler.cache_to_redis(question, answer)
            return answer
    except NotImplementedError:
        logger.warning("RAG模块尚未实现，走兜底策略")
    except Exception as e:
        logger.error(f"RAG检索异常，走兜底策略: {e}")

    # ====== 7. 兜底策略 - 调用大模型直接回答 ======
    logger.info(f"所有检索方式均失败，触发兜底策略: {question}")
    answer = handler.fallback_to_llm(question)
    if answer:
        return answer

    return "抱歉，暂未找到相关答案。"


def main():
    """交互式命令行入口"""
    print("=" * 60)
    print("RAG用户输入处理系统")
    print("=" * 60)
    print("\n初始化检索组件...")

    handler = QueryHandler()

    print("\n组件状态:")
    print(f"  Redis:   {'已连接' if handler.redis_client else '未连接'}")
    print(f"  BM25:    {'已加载' if handler.bm25_retriever and handler.bm25_retriever.is_loaded else '未加载'}")
    print(f"  数据库:  {'已连接' if handler.db_pool else '未连接'}")
    print(f"  RAG:     预留接口(未实现)")

    print("\n" + "=" * 60)
    print("请输入问题（输入 'quit' 或 'exit' 退出）:")
    print("=" * 60)

    while True:
        try:
            question = input("\n[用户]: ").strip()
            if not question:
                continue
            if question.lower() in ("quit", "exit"):
                print("再见！")
                break

            logger.info(f"收到用户查询: {question}")
            answer = handle_query(question, handler)
            print(f"\n[回答]: {answer}")

        except KeyboardInterrupt:
            print("\n\n程序已中断，再见！")
            break
        except EOFError:
            print("\n\n程序已结束，再见！")
            break


if __name__ == "__main__":
    main()
