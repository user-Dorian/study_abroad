"""对话流程图 - v2 重构（纯LLM驱动 + 并行双分支 + 静默表单填写）

架构设计：
1. 用户 query → 并行执行两个 LLM 分支：
   - 分支A：检索意图识别（intent_classification_node）
   - 分支B：表单信息提取（form_filling_node，静默执行）
2. 分支A 输出 need_retrieval，决定是否调用 retrieval_node
3. 分支B 始终输出最新 profile 快照，供回答生成使用
4. 合并上下文 → stream_response_node 流式生成回答
5. SSE 事件：
   - step / answer_start / answer_chunk / answer_done / execution_path
   - student_field_updated（仅推送字段名+值+完成率给侧边栏面板，不在对话气泡反馈）
   - notes_updated（备注更新事件，供侧边栏面板使用）
   - step_error / error

表单反馈策略（v2 修订）：
- 对话气泡中：完全静默，不出现"已记录您的姓名XXX"等反馈
- 侧边栏面板：通过 student_field_updated 事件实时更新字段，符合工作区规则
- 回答生成 LLM：通过 profile_snapshot 静默感知字段变化，不在回答中复述

无快速路径：所有 query 走完整流程，不跳过节点。
"""
import asyncio
import copy
import json
from typing import AsyncIterator, Optional

from backend.common.basics.utils.logger import logger
from backend.common.functions.rag.models.llm_client import llm_client
from .state import ConversationState, NodeResult
from .nodes import (
    intent_classification_node,
    form_filling_node,
    retrieval_node,
    stream_response_node,
)


def _sse(data: dict) -> str:
    """格式化 SSE 事件

    Args:
        data: 事件数据

    Returns:
        str: SSE 格式字符串 (data: {...}\\n\\n)
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _calc_completion_rate(state: ConversationState) -> int:
    """计算必填字段完成率（百分比整数 0-100，仅供日志/调试用，不推送前端）"""
    try:
        from backend.common.functions.info_collect.model import STUDENT_FIELDS_META
        total_required = sum(
            1 for f, m in STUDENT_FIELDS_META.items() if m.get("required", False)
        )
        if total_required == 0:
            return 0
        filled = sum(
            1 for f, m in STUDENT_FIELDS_META.items()
            if m.get("required", False) and state.user_profile.get(f)
        )
        return int(filled / total_required * 100)
    except Exception as e:
        logger.warning(f"[对话流程] 计算完成率失败: {e}")
        return 0


# 节点执行顺序的规范定义（M6: 确定性排序）
# 定义所有可能出现的节点及其规范顺序，未列出的节点追加到末尾（按出现顺序）
# 注意：_NODE_ORDER 必须在 _reorder_execution_path 之前定义，避免前向引用
_NODE_ORDER = [
    "intent_classification_node",   # 分支A: 意图识别
    "form_filling_node",            # 分支B: 表单填写
    "retrieval_node",               # 检索
    "stream_response_node",         # 回答生成
    # 降级/兜底节点
    "llm_unavailable_fallback",
]


def _reorder_execution_path(path):
    """按规范顺序重排节点执行路径（M6）

    并行分支合并后，node_execution_path 的顺序受 gather 完成顺序影响，
    这里按 _NODE_ORDER 重排，确保日志和 execution_path 事件稳定可比对。

    Args:
        path: 原始执行路径（可能含重复，但去重已在外部完成）

    Returns:
        List[str]: 重排后的执行路径
    """
    if not path:
        return []
    # 去重保序
    seen = set()
    unique = []
    for n in path:
        if n not in seen:
            seen.add(n)
            unique.append(n)

    # 按规范顺序排序
    ordered = [n for n in _NODE_ORDER if n in seen]
    # 未知节点追加到末尾（保持原始出现顺序）
    for n in unique:
        if n not in _NODE_ORDER:
            ordered.append(n)
    return ordered


def _merge_form_branch(main_state: ConversationState, form_state: ConversationState):
    """合并表单分支结果到主 state

    表单分支会更新：
    - form_state（完整替换）
    - user_profile（按字段合并）
    - current_notes（备注重写）
    - errors / node_execution_path（合并）

    v2 修订（M5）：
    - 允许空字符串覆盖（用户明确清空字段时应该生效）
    - 仅当值为 None 时才跳过合并（表示该字段本次无更新）
    - 通过 form_state.extracted_updates 区分"未提取"与"明确清空"

    Args:
        main_state: 主状态
        form_state: 表单分支的状态副本
    """
    # 表单状态完整替换
    main_state.form_state = form_state.form_state

    # user_profile 合并（M5: 仅 None 视为无更新，空字符串允许覆盖以支持清空）
    # 仅合并本次实际提取出的字段（extracted_updates），避免无关字段被误清空
    extracted = form_state.form_state.extracted_updates or {}
    for field_name, field_value in extracted.items():
        if field_value is None:
            continue
        main_state.user_profile[field_name] = field_value

    # 同时同步 form_state.user_profile 中可能存在的非 extracted 字段（兼容旧路径）
    # M5: 与主分支保持一致——仅 None 视为无更新，空字符串允许覆盖以支持清空
    # （上面已 if v is None: continue，此处直接赋值即可）
    for k, v in form_state.user_profile.items():
        if v is None:
            continue
        if k in extracted:
            continue  # 已经在上面处理过
        main_state.user_profile[k] = v

    # 备注重写同步
    if form_state.current_notes:
        main_state.current_notes = form_state.current_notes

    # 合并 errors
    for err in form_state.errors:
        if err not in main_state.errors:
            main_state.errors.append(err)

    # 合并 node_execution_path（M6: 通过 _reorder_execution_path 统一排序）
    for node in form_state.node_execution_path:
        if node not in main_state.node_execution_path:
            main_state.node_execution_path.append(node)
    main_state.node_execution_path = _reorder_execution_path(main_state.node_execution_path)


def _merge_retrieval_branch(main_state: ConversationState, retrieval_state: ConversationState):
    """合并检索分支结果到主 state

    Args:
        main_state: 主状态
        retrieval_state: 检索分支的状态副本
    """
    # 检索状态完整替换
    main_state.retrieval_state = retrieval_state.retrieval_state

    # 合并 errors
    for err in retrieval_state.errors:
        if err not in main_state.errors:
            main_state.errors.append(err)

    # 合并 node_execution_path（M6: 通过 _reorder_execution_path 统一排序）
    for node in retrieval_state.node_execution_path:
        if node not in main_state.node_execution_path:
            main_state.node_execution_path.append(node)
    main_state.node_execution_path = _reorder_execution_path(main_state.node_execution_path)


class ConversationGraph:
    """对话流程图管理器（v2: 并行双分支 + 静默表单）

    流程：
        user_query
            ├── intent_classification_node (分支A: LLM判断 need_retrieval)
            └── form_filling_node (分支B: LLM提取字段+备注重写，静默)
                    ↓
            (合并 profile_snapshot)
                    ↓
        retrieval_node? (根据 need_retrieval 决定是否执行)
                    ↓
        stream_response_node (流式生成回答)
                    ↓
              SSE 推送
    """

    # 各节点超时配置（秒）
    INTENT_TIMEOUT = 8.0
    FORM_TIMEOUT = 10.0
    RETRIEVAL_TIMEOUT = 8.0
    STREAM_CHUNK_TIMEOUT = 30.0
    # M4: 流式生成整体超时（避免长回答或异常累积导致请求长时间挂起）
    STREAM_TOTAL_TIMEOUT = 60.0

    def __init__(self):
        """初始化对话流程图（v2 不使用 LangGraph，直接异步编排）"""
        self.graph = None
        self.app = None
        logger.info("[对话流程图] v2 初始化完成（并行双分支编排）")

    async def run(self, state: ConversationState) -> ConversationState:
        """非流式执行完整对话流程

        Args:
            state: 初始状态

        Returns:
            ConversationState: 最终状态
        """
        try:
            logger.info(f"[对话流程] 开始执行: user_id={state.user_info.user_id}")

            # 并行执行两个分支
            await self._run_parallel_branches(state)

            # 根据意图识别结果决定是否检索
            if state.retrieval_state.retrieval_needed:
                try:
                    result = await asyncio.wait_for(
                        retrieval_node(state), timeout=self.RETRIEVAL_TIMEOUT
                    )
                    if result and result.state:
                        state = result.state
                except asyncio.TimeoutError:
                    logger.error(f"[对话流程] 检索超时({self.RETRIEVAL_TIMEOUT}s)")
                    state.add_error("检索超时")
                except Exception as e:
                    logger.error(f"[对话流程] 检索异常: {e}", exc_info=True)
                    state.add_error(f"检索异常: {e}")

            # 非流式调用 stream_response_node 收集完整回答
            final_answer = ""
            try:
                async for chunk in stream_response_node(state):
                    final_answer += chunk
            except Exception as e:
                logger.error(f"[对话流程] 回答生成异常: {e}", exc_info=True)
                final_answer = "抱歉，系统遇到了一些问题，请稍后再试。"

            state.response_state.final_answer = final_answer
            state.response_state.response_type = (
                "retrieval_based" if state.retrieval_state.final_context else "direct"
            )

            logger.info(
                f"[对话流程] 执行完成: "
                f"path={state.node_execution_path}, "
                f"errors={len(state.errors)}, "
                f"answer_len={len(final_answer)}"
            )

            return state

        except Exception as e:
            logger.error(f"[对话流程] 执行失败: {e}", exc_info=True)
            state.add_error(f"流程执行失败: {str(e)}")
            return state

    async def _run_parallel_branches(self, state: ConversationState):
        """并行执行意图识别和表单填写两个分支

        Args:
            state: 主状态（会被原地更新）
        """
        # 为两个分支各创建一份副本，避免并行修改冲突
        state_for_intent = copy.deepcopy(state)
        state_for_form = copy.deepcopy(state)

        # 并行执行
        intent_task = asyncio.wait_for(
            intent_classification_node(state_for_intent),
            timeout=self.INTENT_TIMEOUT
        )
        form_task = asyncio.wait_for(
            form_filling_node(state_for_form),
            timeout=self.FORM_TIMEOUT
        )

        results = await asyncio.gather(intent_task, form_task, return_exceptions=True)

        # 合并意图分支
        intent_result = results[0]
        if isinstance(intent_result, Exception):
            logger.error(f"[对话流程] 意图识别分支异常: {intent_result}", exc_info=False)
            state.add_error(f"意图识别失败: {intent_result}")
            # 降级：默认不检索
            state.intent_state.need_retrieval = False
            state.retrieval_state.retrieval_needed = False
            state.add_node_to_path("intent_classification_node")
        else:
            if intent_result and intent_result.state:
                # 合并意图识别结果到主state
                state.intent_state = intent_result.state.intent_state
                state.retrieval_state.retrieval_needed = (
                    intent_result.state.retrieval_state.retrieval_needed
                )
                # 合并 errors / path
                for err in intent_result.state.errors:
                    if err not in state.errors:
                        state.errors.append(err)
                for node in intent_result.state.node_execution_path:
                    if node not in state.node_execution_path:
                        state.node_execution_path.append(node)

        # 合并表单分支
        form_result = results[1]
        if isinstance(form_result, Exception):
            logger.error(f"[对话流程] 表单填写分支异常: {form_result}", exc_info=False)
            state.add_error(f"表单填写失败: {form_result}")
            state.form_state.profile_snapshot = dict(state.user_profile)
            state.add_node_to_path("form_filling_node")
        else:
            if form_result and form_result.state:
                _merge_form_branch(state, form_result.state)

    async def stream(self, state: ConversationState) -> AsyncIterator[str]:
        """流式执行对话流程 - 推送完整 SSE 事件流（v2）

        推送顺序：
        - Step 0: 加载对话历史
        - Step 1: 并行双分支（意图识别 + 表单填写，表单静默不推送具体内容）
        - Step 2: 检索（如需）
        - Step 3: 流式回答生成（answer_start/answer_chunk/answer_done）
        - 最终: execution_path

        关键变更：
        - 移除快速路径（所有query走完整流程）
        - 移除 student_field_updated 事件（表单填写静默）
        - 移除 retrieval_strategy_node（意图识别直接输出 need_retrieval）
        - SSE事件简化为: step / answer_start / answer_chunk / answer_done / execution_path / step_error / error

        兜底策略：
        - 单节点超时：推送 step_error，流程继续
        - LLM 不可用：推送 error + 兜底回答
        - 流式生成异常：推送 step_error + 友好提示
        - 全局异常：推送 error 事件

        Args:
            state: 初始状态

        Yields:
            str: SSE 格式事件字符串 (data: {...}\\n\\n)
        """
        try:
            logger.info(
                f"[对话流程] v2 流式执行开始: "
                f"user_id={state.user_info.user_id}, "
                f"msg={state.current_user_message[:50]}"
            )

            # 兜底1：LLM 不可用
            if not llm_client.is_available():
                logger.warning("[对话流程] LLM 不可用，使用兜底回答")
                yield _sse({
                    "type": "error",
                    "message": "LLM 服务不可用，使用兜底回答"
                })
                yield _sse({
                    "type": "step", "step": 3,
                    "name": "LLM生成回答", "status": "fallback",
                    "detail": "LLM 不可用，使用预设回答"
                })
                yield _sse({"type": "answer_start", "detail": "开始生成回答"})
                fallback_text = "抱歉，系统当前无法处理您的问题，请稍后重试或联系客服。"
                yield _sse({"type": "answer_chunk", "content": fallback_text})
                yield _sse({"type": "answer_done"})
                yield _sse({
                    "type": "execution_path",
                    "path": ["llm_unavailable_fallback"],
                    "final_answer": fallback_text
                })
                return

            # ====== Step 0: 加载对话历史 ======
            yield _sse({
                "type": "step", "step": 0,
                "name": "加载对话历史", "status": "success",
                "detail": f"已加载 {len(state.messages)} 条历史消息"
            })

            # ====== Step 1: 并行双分支（意图识别 + 表单填写） ======
            yield _sse({
                "type": "step", "step": 1,
                "name": "意图识别与信息提取", "status": "running",
                "detail": "正在并行分析意图和提取信息..."
            })

            try:
                await self._run_parallel_branches(state)

                need_retrieval = state.intent_state.need_retrieval
                intent_reason = state.intent_state.reason or ""

                yield _sse({
                    "type": "step", "step": 1,
                    "name": "意图识别与信息提取", "status": "success",
                    "detail": (
                        f"需要检索: {'是' if need_retrieval else '否'}"
                        f"{f'（{intent_reason[:50]}）' if intent_reason else ''}"
                    )
                })

                # ====== 推送表单字段更新事件（侧边栏面板用，不在对话气泡反馈） ======
                # v2 修订：恢复 student_field_updated 事件以满足工作区规则的"实时表单填写状态展示面板"要求
                # 但通过 prompt 约束保证 LLM 不在回答气泡中复述字段
                if state.form_state.updated_field_names:
                    completion_rate = _calc_completion_rate(state)
                    for field_name in state.form_state.updated_field_names:
                        field_value = state.form_state.extracted_updates.get(field_name)
                        yield _sse({
                            "type": "student_field_updated",
                            "field": field_name,
                            "value": field_value,
                            "completion_rate": completion_rate
                        })

                # 推送备注更新事件
                if state.form_state.notes_updated and state.form_state.extracted_notes:
                    yield _sse({
                        "type": "notes_updated",
                        "notes": state.form_state.extracted_notes,
                        "completion_rate": _calc_completion_rate(state)
                    })

            except Exception as e:
                logger.error(f"[对话流程] 并行双分支异常: {e}", exc_info=True)
                yield _sse({
                    "type": "step_error", "step": 1,
                    "detail": f"双分支执行异常: {str(e)[:100]}"
                })
                # 降级：默认不检索，使用现有profile
                state.intent_state.need_retrieval = False
                state.retrieval_state.retrieval_needed = False
                state.form_state.profile_snapshot = dict(state.user_profile)

            # ====== Step 2: 检索（如需） ======
            need_retrieval = state.retrieval_state.retrieval_needed
            if need_retrieval:
                yield _sse({
                    "type": "step", "step": 2,
                    "name": "知识库检索", "status": "running",
                    "detail": "正在检索知识库..."
                })
                try:
                    result = await asyncio.wait_for(
                        retrieval_node(state), timeout=self.RETRIEVAL_TIMEOUT
                    )
                    if result and result.state:
                        # retrieval_node 操作的是主 state 本身（无副本），但 result.state 就是 state
                        # 这里同步一下 retrieval_state 以防万一
                        state.retrieval_state = result.state.retrieval_state
                        for err in result.state.errors:
                            if err not in state.errors:
                                state.errors.append(err)
                        for node in result.state.node_execution_path:
                            if node not in state.node_execution_path:
                                state.node_execution_path.append(node)

                    source = state.retrieval_state.retrieval_source or "empty"
                    has_context = bool(state.retrieval_state.final_context)

                    if has_context:
                        yield _sse({
                            "type": "step", "step": 2,
                            "name": "知识库检索", "status": "success",
                            "detail": f"命中来源: {source}"
                        })
                    else:
                        yield _sse({
                            "type": "step", "step": 2,
                            "name": "知识库检索", "status": "miss",
                            "detail": "无命中结果，由LLM凭自身知识回答"
                        })
                except asyncio.TimeoutError:
                    logger.error(f"[对话流程] 检索超时({self.RETRIEVAL_TIMEOUT}s)")
                    yield _sse({
                        "type": "step_error", "step": 2,
                        "detail": f"检索超时({self.RETRIEVAL_TIMEOUT}s)，已降级"
                    })
                    state.retrieval_state.final_context = None
                    state.retrieval_state.retrieval_source = "timeout"
                except Exception as e:
                    logger.error(f"[对话流程] 检索异常: {e}", exc_info=True)
                    yield _sse({
                        "type": "step_error", "step": 2,
                        "detail": f"检索异常: {str(e)[:100]}"
                    })
                    state.retrieval_state.final_context = None
                    state.retrieval_state.retrieval_source = "error"
            else:
                # 不需要检索，跳过
                yield _sse({
                    "type": "step", "step": 2,
                    "name": "知识库检索", "status": "skip",
                    "detail": "无需检索"
                })

            # ====== Step 3: 流式回答生成 ======
            yield _sse({
                "type": "step", "step": 3,
                "name": "LLM生成回答", "status": "running",
                "detail": "基于上下文流式生成回答..."
            })
            yield _sse({"type": "answer_start", "detail": "开始生成回答"})

            final_answer = ""
            stream_start_time = asyncio.get_running_loop().time()
            try:
                gen = stream_response_node(state).__aiter__()
                while True:
                    # M4: 检查整体超时
                    elapsed_total = asyncio.get_running_loop().time() - stream_start_time
                    if elapsed_total > self.STREAM_TOTAL_TIMEOUT:
                        logger.error(
                            f"[对话流程] 流式生成整体超时({self.STREAM_TOTAL_TIMEOUT}s, "
                            f"已生成{len(final_answer)}字符)"
                        )
                        yield _sse({
                            "type": "step_error", "step": 3,
                            "detail": f"流式生成整体超时({self.STREAM_TOTAL_TIMEOUT}s)，已降级处理"
                        })
                        if not final_answer:
                            fallback = "抱歉，回答生成超时，请稍后重试。"
                            yield _sse({"type": "answer_chunk", "content": fallback})
                            final_answer = fallback
                        break

                    try:
                        chunk = await asyncio.wait_for(
                            gen.__anext__(),
                            timeout=self.STREAM_CHUNK_TIMEOUT
                        )
                        final_answer += chunk
                        yield _sse({"type": "answer_chunk", "content": chunk})
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.error(
                            f"[对话流程] 流式生成单 chunk 超时({self.STREAM_CHUNK_TIMEOUT}s)"
                        )
                        yield _sse({
                            "type": "step_error", "step": 3,
                            "detail": "流式生成超时，已降级处理"
                        })
                        if not final_answer:
                            fallback = "抱歉，回答生成超时，请稍后重试。"
                            yield _sse({"type": "answer_chunk", "content": fallback})
                            final_answer = fallback
                        break
            except Exception as e:
                logger.error(f"[对话流程] 流式生成异常: {e}", exc_info=True)
                yield _sse({
                    "type": "step_error", "step": 3,
                    "detail": f"流式生成异常: {str(e)[:100]}"
                })
                if not final_answer:
                    fallback = "抱歉，回答生成遇到问题，请稍后重试。"
                    yield _sse({"type": "answer_chunk", "content": fallback})
                    final_answer = fallback

            yield _sse({"type": "answer_done"})

            # ====== 推送执行路径 ======
            yield _sse({
                "type": "execution_path",
                "path": state.node_execution_path,
                "final_answer": final_answer
            })

            logger.info(
                f"[对话流程] v2 流式执行完成: "
                f"path={state.node_execution_path}, "
                f"answer_len={len(final_answer)}, "
                f"errors={len(state.errors)}"
            )

        except Exception as e:
            logger.error(f"[对话流程] 流式执行全局异常: {e}", exc_info=True)
            yield _sse({
                "type": "error",
                "message": "抱歉，系统暂时遇到问题，请稍后重试"
            })


# 全局单例
conversation_graph = ConversationGraph()


# ====== 对外接口 ======

async def run_conversation(
    user_id: str,
    user_message: str,
    messages: list = None,
    user_profile: dict = None,
    session_id: str = None
) -> ConversationState:
    """运行完整对话流程（非流式）

    Args:
        user_id: 用户ID
        user_message: 用户消息
        messages: 对话历史
        user_profile: 用户档案
        session_id: 会话ID

    Returns:
        ConversationState: 最终状态
    """
    state = ConversationState(
        user_info={
            "user_id": user_id,
            "session_id": session_id,
            "is_new_user": not user_profile or len(user_profile) == 0
        },
        current_user_message=user_message,
        messages=messages or [],
        user_profile=user_profile or {}
    )

    result = await conversation_graph.run(state)
    return result


async def stream_conversation(
    user_id: str,
    user_message: str,
    messages: list = None,
    user_profile: dict = None,
    session_id: str = None
) -> AsyncIterator[str]:
    """流式运行对话流程 - 直接透传 SSE 事件流（v2）

    Args:
        user_id: 用户ID
        user_message: 用户消息
        messages: 对话历史
        user_profile: 用户档案
        session_id: 会话ID

    Yields:
        str: SSE 格式事件字符串 (data: {...}\\n\\n)
    """
    state = ConversationState(
        user_info={
            "user_id": user_id,
            "session_id": session_id,
            "is_new_user": not user_profile or len(user_profile) == 0
        },
        current_user_message=user_message,
        messages=messages or [],
        user_profile=user_profile or {}
    )

    async for chunk in conversation_graph.stream(state):
        yield chunk
