"""规划师端API路由 - 提供Web端查询接口，支持SSE推送执行步骤"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from consultant.handlers.query_handler import ConsultantQueryHandler
from consultant.config.redis_config import ConsultantRedisConfig
from common.utils.logger import logger
import json
import asyncio
import threading
import queue

router = APIRouter()

# 全局QueryHandler实例，服务器启动时初始化，后续复用
_query_handler: ConsultantQueryHandler = None


def init_query_handler(redis_client=None, bm25_retriever=None, db_available=None):
    """
    初始化全局QueryHandler实例，服务器启动时调用一次

    Args:
        redis_client: 已初始化的Redis客户端，传入则复用
        bm25_retriever: 已加载的BM25Retriever实例，传入则复用
        db_available: 数据库是否可用，传入则复用
    """
    global _query_handler
    if _query_handler is None:
        _query_handler = ConsultantQueryHandler(
            redis_client=redis_client,
            bm25_retriever=bm25_retriever,
            db_available=db_available,
        )
        logger.info("[规划师端] QueryHandler全局实例初始化完成")
    return _query_handler


def get_query_handler() -> ConsultantQueryHandler:
    """获取全局QueryHandler实例"""
    if _query_handler is None:
        raise RuntimeError("QueryHandler未初始化，请确保服务器已正常启动")
    return _query_handler


class QueryRequest(BaseModel):
    question: str


@router.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}


@router.post("/api/query")
async def query_stream(request: QueryRequest):
    """
    查询接口 - 使用SSE推送每一步执行过程

    Args:
        request: 查询请求，包含question字段

    Returns:
        SSE流式响应，包含每一步的执行状态
    """
    handler = get_query_handler()

    async def generate_events():
        # 初始化执行路径记录
        execution_path = []
        final_answer = ""

        # ====== 步骤1: Redis全词匹配 ======
        step1 = {
            "step": 1,
            "name": "Redis全词精确匹配",
            "status": "running",
            "detail": "正在查询Redis缓存..."
        }
        yield f"data: {json.dumps(step1, ensure_ascii=False)}\n\n"

        answer = handler.redis_exact_match(request.question)
        if answer is not None:
            step1["status"] = "success"
            step1["detail"] = "Redis缓存命中！"
            yield f"data: {json.dumps(step1, ensure_ascii=False)}\n\n"

            final_answer = answer
            execution_path.append(step1)

            result = {
                "type": "result",
                "answer": final_answer,
                "execution_path": execution_path
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
            return

        step1["status"] = "miss"
        step1["detail"] = "Redis缓存未命中"
        yield f"data: {json.dumps(step1, ensure_ascii=False)}\n\n"
        execution_path.append(step1)

        # ====== 步骤2: BM25分词 + Softmax ======
        step2 = {
            "step": 2,
            "name": "BM25检索 + Softmax概率计算",
            "status": "running",
            "detail": "正在进行分词和相似度计算..."
        }
        yield f"data: {json.dumps(step2, ensure_ascii=False)}\n\n"

        matched_question, prob = handler.bm25_match_with_softmax(request.question)

        step2["status"] = "success" if prob >= 0.7 and matched_question else "low_match"
        step2["detail"] = f"Softmax最高概率: {prob:.4f} (阈值: 0.7)"
        if matched_question:
            step2["matched_question"] = matched_question
        yield f"data: {json.dumps(step2, ensure_ascii=False)}\n\n"
        execution_path.append(step2)

        if prob >= 0.7 and matched_question is not None:
            # ====== 步骤3: Redis查匹配问题 ======
            step3 = {
                "step": 3,
                "name": "Redis检索匹配问题",
                "status": "running",
                "detail": f"正在Redis中查询: {matched_question}"
            }
            yield f"data: {json.dumps(step3, ensure_ascii=False)}\n\n"

            answer = handler.redis_exact_match(matched_question)
            if answer is not None:
                step3["status"] = "success"
                step3["detail"] = "Redis缓存命中！"
                yield f"data: {json.dumps(step3, ensure_ascii=False)}\n\n"

                # 将检索结果写入Redis缓存（只缓存检索结果，不缓存LLM回答）
                handler.cache_retrieval(request.question, answer)

                step5 = {
                    "step": 5,
                    "name": "Redis检索缓存写入",
                    "status": "success",
                    "detail": f"检索结果已缓存到Redis (TTL={ConsultantRedisConfig.TTL}s)"
                }
                yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

                final_answer = answer
                execution_path.append(step3)
                execution_path.append(step5)

                result = {
                    "type": "result",
                    "answer": final_answer,
                    "execution_path": execution_path
                }
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
                return

            step3["status"] = "miss"
            step3["detail"] = "Redis缓存未命中"
            yield f"data: {json.dumps(step3, ensure_ascii=False)}\n\n"
            execution_path.append(step3)

            # ====== 步骤4: SQL查询 ======
            step4 = {
                "step": 4,
                "name": "SQL数据库查询",
                "status": "running",
                "detail": f"正在数据库中查询: {matched_question}"
            }
            yield f"data: {json.dumps(step4, ensure_ascii=False)}\n\n"

            answer = handler.query_database(matched_question)
            if answer is not None:
                step4["status"] = "success"
                step4["detail"] = "数据库查询命中！正在写入Redis缓存..."
                yield f"data: {json.dumps(step4, ensure_ascii=False)}\n\n"

                # 将检索结果写入Redis缓存（只缓存检索结果）
                handler.cache_retrieval(request.question, answer)
                if matched_question != request.question:
                    handler.cache_retrieval(matched_question, answer)

                step5 = {
                    "step": 5,
                    "name": "Redis检索缓存写入",
                    "status": "success",
                    "detail": f"检索结果已缓存到Redis (TTL=3600s)"
                }
                yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

                final_answer = answer
                execution_path.append(step4)
                execution_path.append(step5)

                result = {
                    "type": "result",
                    "answer": final_answer,
                    "execution_path": execution_path
                }
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
                return

            step4["status"] = "miss"
            step4["detail"] = "数据库查询未命中"
            yield f"data: {json.dumps(step4, ensure_ascii=False)}\n\n"
            execution_path.append(step4)

            logger.warning(f"[规划师端] BM25匹配到'{matched_question}'但缓存和数据库均无答案，走RAG检索")
        else:
            logger.info(f"[规划师端] BM25匹配度不足(概率={prob:.4f})，走RAG检索")

        # ====== 步骤5: RAG检索 ======
        rag_start_step = 5
        step5 = {
            "step": rag_start_step,
            "name": "RAG向量检索",
            "status": "running",
            "detail": "正在进入RAG检索模块..."
        }
        yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

        try:
            from common.rag.retrieval.rag_retriever import rag_retriever

            rag_step_offset = 100
            rag_queue = queue.Queue()
            stream_queue = queue.Queue()  # 流式输出队列
            answer_result = [None]
            error_result = [None]
            answer_started = [False]  # 标记是否已推送 answer_start

            def rag_step_callback(step, name, status, detail, extra=None):
                """步骤回调：推送RAG执行步骤"""
                rag_step_info = {
                    "step": rag_step_offset + step,
                    "name": name,
                    "status": status,
                    "detail": detail,
                    "is_rag_substep": True
                }
                if extra:
                    rag_step_info["extra"] = extra
                rag_queue.put(rag_step_info)

            def stream_callback(token: str):
                """流式回调：每个token推送到stream_queue，第一个token时发送answer_start"""
                if not answer_started[0]:
                    answer_started[0] = True
                    stream_queue.put({"type": "answer_start", "detail": "开始生成回答"})
                stream_queue.put({"type": "answer_chunk", "content": token})

            def rag_worker():
                try:
                    answer_result[0] = rag_retriever.query_stream(
                        request.question,
                        stream_callback=stream_callback,
                        step_callback=rag_step_callback
                    )
                except Exception as e:
                    error_result[0] = e
                finally:
                    rag_queue.put(None)
                    stream_queue.put(None)  # 流式输出结束标记

            worker_thread = threading.Thread(target=rag_worker)
            worker_thread.start()

            step5["detail"] = "RAG检索中(意图识别 -> 策略分析 -> 向量化 -> 粗排 -> 精排 -> 生成)..."
            yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

            # 主循环：同时处理 rag_queue 和 stream_queue，流式队列优先
            rag_done = False
            stream_done = False

            while not (rag_done and stream_done):
                # 优先处理流式队列（确保回答内容尽快推送）
                stream_events_batched = []
                if not stream_done:
                    while True:
                        try:
                            stream_event = stream_queue.get_nowait()
                            if stream_event is None:
                                stream_done = True
                                answer_done_event = {"type": "answer_done", "detail": "回答生成完成"}
                                stream_events_batched.append(answer_done_event)
                                break
                            stream_events_batched.append(stream_event)
                        except queue.Empty:
                            break

                for stream_event in stream_events_batched:
                    yield f"data: {json.dumps(stream_event, ensure_ascii=False)}\n\n"

                # 处理步骤队列（非阻塞）
                if not rag_done:
                    try:
                        rag_step = rag_queue.get_nowait()
                        if rag_step is None:
                            rag_done = True
                        else:
                            yield f"data: {json.dumps(rag_step, ensure_ascii=False)}\n\n"
                            execution_path.append(rag_step)
                    except queue.Empty:
                        pass

                # 检查worker线程是否结束
                if not worker_thread.is_alive() and not rag_done:
                    while True:
                        try:
                            rag_step = rag_queue.get_nowait()
                            if rag_step is None:
                                rag_done = True
                                break
                            yield f"data: {json.dumps(rag_step, ensure_ascii=False)}\n\n"
                            execution_path.append(rag_step)
                        except queue.Empty:
                            rag_done = True
                            break

                if not worker_thread.is_alive() and not stream_done:
                    while True:
                        try:
                            stream_event = stream_queue.get_nowait()
                            if stream_event is None:
                                stream_done = True
                                answer_done_event = {"type": "answer_done", "detail": "回答生成完成"}
                                yield f"data: {json.dumps(answer_done_event, ensure_ascii=False)}\n\n"
                                break
                            yield f"data: {json.dumps(stream_event, ensure_ascii=False)}\n\n"
                        except queue.Empty:
                            stream_done = True
                            break

                # 让出CPU，避免忙等待
                await asyncio.sleep(0.005)

            worker_thread.join(timeout=5)

            if error_result[0]:
                raise error_result[0]

            answer = answer_result[0]

            if answer:
                step5["status"] = "success"
                step5["detail"] = "RAG检索成功！（LLM回答不写入Redis缓存）"
                yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

                final_answer = answer
                execution_path.append(step5)

                result = {
                    "type": "result",
                    "answer": final_answer,
                    "execution_path": execution_path
                }
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
                return
        except NotImplementedError:
            step5["status"] = "not_implemented"
            step5["detail"] = "RAG模块尚未实现"
            yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

            execution_path.append(step5)
        except Exception as e:
            step5["status"] = "error"
            step5["detail"] = f"RAG检索异常: {str(e)}"
            yield f"data: {json.dumps(step5, ensure_ascii=False)}\n\n"

            execution_path.append(step5)

        # ====== 兜底策略: LLM直接回答 ======
        if not final_answer:
            step_fallback = {
                "step": 7,
                "name": "兜底策略 - LLM直接回答",
                "status": "running",
                "detail": "所有检索方式均失败，正在调用大模型直接回答..."
            }
            yield f"data: {json.dumps(step_fallback, ensure_ascii=False)}\n\n"

            try:
                from common.rag.models.llm_client import llm_client
                from consultant.rag.prompts.prompt_template import consultant_prompt_manager
                
                messages = consultant_prompt_manager.build_messages('fallback_answer', question=request.question)
                
                yield f"data: {json.dumps({'type': 'answer_start', 'detail': '开始生成回答'}, ensure_ascii=False)}\n\n"
                
                answer = ""
                for chunk in llm_client.chat_stream(messages=messages):
                    answer += chunk
                    yield f"data: {json.dumps({'type': 'answer_chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
                
                yield f"data: {json.dumps({'type': 'answer_done', 'detail': '回答生成完成'}, ensure_ascii=False)}\n\n"
                
                if answer:
                    step_fallback["status"] = "success"
                    step_fallback["detail"] = "大模型兜底回答成功！（LLM回答不写入Redis缓存）"
                    yield f"data: {json.dumps(step_fallback, ensure_ascii=False)}\n\n"

                    final_answer = answer
                    execution_path.append(step_fallback)
                else:
                    step_fallback["status"] = "error"
                    step_fallback["detail"] = "大模型兜底回答失败"
                    yield f"data: {json.dumps(step_fallback, ensure_ascii=False)}\n\n"
                    execution_path.append(step_fallback)
            except Exception as e:
                step_fallback["status"] = "error"
                step_fallback["detail"] = f"兜底策略异常: {str(e)}"
                yield f"data: {json.dumps(step_fallback, ensure_ascii=False)}\n\n"
                execution_path.append(step_fallback)

        if final_answer:
            result = {
                "type": "result",
                "answer": final_answer,
                "execution_path": execution_path
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
        else:
            result = {
                "type": "result",
                "answer": "抱歉，暂未找到相关答案。",
                "execution_path": execution_path
            }
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
