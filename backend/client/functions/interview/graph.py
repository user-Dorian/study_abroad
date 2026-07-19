"""面试流程图 - 使用 LangGraph 编排面试流程

设计说明：
- 面试是交互式流程（问一个问题→等回答→问下一个），不是一次性流程
- 暴露两个入口：
  * start_interview() : 生成问题，返回第一个问题（流式 SSE）
  * process_answer()  : 评估上一个回答，返回下一个问题或完成报告（流式 SSE）

LangGraph 编排：
- start_interview_node 是入口节点
- evaluate_answer_node 后通过条件边决定下一步：
  * 还有下一题 → ask_question_node → END
  * 已是最后一题 → complete_interview_node → END
"""
import json
import uuid
from typing import AsyncIterator, Optional

from langgraph.graph import StateGraph, END

from backend.common.basics.utils.logger import logger
from backend.common.functions.rag.models.llm_client import llm_client

from .state import InterviewState, InterviewConfig
from .nodes import (
    start_interview_node,
    ask_question_node,
    receive_answer_node,
    evaluate_answer_node,
    complete_interview_node,
)


# ====== 内存存储：interview_id → InterviewState ======
# 简化实现，不需要数据库持久化
_interview_store: dict = {}


def _sse(data: dict) -> str:
    """格式化 SSE 事件

    Args:
        data: 事件数据

    Returns:
        str: SSE 格式字符串 (data: {...}\\n\\n)
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _decide_next_step(state: InterviewState) -> str:
    """条件边：判断评估后下一步

    Args:
        state: 当前面试状态

    Returns:
        str: "next_question" 或 "complete"
    """
    if state.is_last_question:
        logger.info(
            f"[流程决策] 已是最后一题(idx={state.current_question_index}, "
            f"total={state.total_questions})，进入报告生成"
        )
        return "complete"
    logger.info(
        f"[流程决策] 还有下一题(idx={state.current_question_index}, "
        f"total={state.total_questions})，继续提问"
    )
    return "next_question"


class InterviewGraph:
    """面试流程图管理器

    使用 LangGraph 编排面试流程：
    1. start_interview_node : 生成问题列表
    2. evaluate_answer_node : 评估当前回答
    3. ask_question_node    : 输出下一题（如果不是最后一题）
    4. complete_interview_node : 生成报告（如果是最后一题）

    对外暴露：
    - start_interview() : 启动面试，流式输出第一个问题
    - process_answer()  : 处理用户回答，流式输出评估结果和下一题/报告
    """

    def __init__(self):
        """初始化面试流程图"""
        self.app = None
        self._build_graph()

    def _build_graph(self):
        """构建面试流程图

        图结构：
            START → generate_questions → END
            evaluate_answer → (next_question | complete)
            next_question → END
            complete → END

        注：generate_questions 是入口节点，仅用于 start_interview 流程
        process_answer 流程从 evaluate_answer 节点开始
        """
        workflow = StateGraph(InterviewState)

        # 添加节点
        workflow.add_node("generate_questions", start_interview_node)
        workflow.add_node("evaluate_answer", evaluate_answer_node)
        workflow.add_node("next_question", _noop_node)
        workflow.add_node("complete", _noop_node)

        # 设置入口
        workflow.set_entry_point("generate_questions")

        # generate_questions → END（start_interview 流程到此结束）
        workflow.add_edge("generate_questions", END)

        # evaluate_answer → 条件分支
        workflow.add_conditional_edges(
            "evaluate_answer",
            _decide_next_step,
            {
                "next_question": "next_question",
                "complete": "complete",
            }
        )

        workflow.add_edge("next_question", END)
        workflow.add_edge("complete", END)

        # 编译
        self.app = workflow.compile()

        logger.info("[面试流程图] 构建完成")


# ====== LangGraph 节点包装（条件分支的占位节点） ======

async def _noop_node(state: InterviewState) -> InterviewState:
    """空操作节点 - 仅用于 LangGraph 占位

    实际的 ask_question 和 complete_interview 是流式函数，
    不适合放在 LangGraph 节点内执行（节点应为非流式）
    """
    return state


# ====== 全局单例 ======
interview_graph = InterviewGraph()


# =============================================================================
# 对外接口
# =============================================================================

async def start_interview(
    user_id: str,
    school: str,
    major: str,
    degree: str = "硕士",
    interview_type: str = "admission",
    total_questions: int = 5,
) -> AsyncIterator[str]:
    """启动面试 - 生成问题列表，流式输出第一个问题

    流程：
    1. 创建 InterviewState
    2. 调用 start_interview_node 生成问题
    3. 保存到内存 store
    4. 流式输出第一个问题（SSE 事件）

    SSE 事件流：
    - {"type":"start","interview_id":"...","total_questions":5}
    - {"type":"question_start","index":0,"dimension":"content","total":5}
    - {"type":"question_chunk","content":"..."} (多次)
    - {"type":"question_done","index":0}
    - {"type":"status","status":"in_progress","progress":0}

    Args:
        user_id: 用户ID
        school: 目标院校
        major: 目标专业
        degree: 学位层次
        interview_type: 面试类型
        total_questions: 题目总数

    Yields:
        str: SSE 格式事件字符串
    """
    # 创建面试状态
    interview_id = str(uuid.uuid4())
    state = InterviewState(
        interview_id=interview_id,
        user_id=user_id,
        school=school,
        major=major,
        degree=degree,
        interview_type=interview_type,
        total_questions=total_questions,
        status="pending",
    )

    # 推送开始事件
    yield _sse({
        "type": "start",
        "interview_id": interview_id,
        "total_questions": total_questions,
        "school": school,
        "major": major,
        "degree": degree,
        "interview_type": interview_type,
    })

    # LLM 不可用：返回错误
    if not llm_client.is_available():
        logger.warning("[面试流程] LLM 不可用，无法启动面试")
        yield _sse({
            "type": "error",
            "message": "AI 服务暂时不可用，请稍后重试",
        })
        return

    # 推送"生成问题中"提示
    yield _sse({
        "type": "status",
        "status": "generating_questions",
        "detail": "AI 正在生成面试问题...",
    })

    # 生成问题
    result = await start_interview_node(state)
    state = result.state

    if not result.success or not state.questions:
        yield _sse({
            "type": "error",
            "message": "生成面试问题失败，请稍后重试",
        })
        return

    # 保存到内存 store
    _interview_store[interview_id] = state
    logger.info(f"[面试流程] 面试已创建: interview_id={interview_id}, questions={len(state.questions)}")

    # 流式输出第一个问题
    first_question = state.questions[0]
    yield _sse({
        "type": "question_start",
        "index": 0,
        "dimension": first_question.dimension,
        "total": state.total_questions,
    })

    async for chunk in ask_question_node(state):
        yield _sse({"type": "question_chunk", "content": chunk})

    yield _sse({
        "type": "question_done",
        "index": 0,
    })

    yield _sse({
        "type": "status",
        "status": "in_progress",
        "progress": 0,
        "current_index": 0,
        "total": state.total_questions,
    })


async def process_answer(
    interview_id: str,
    answer: str,
) -> AsyncIterator[str]:
    """处理用户回答 - 评估当前回答，输出下一题或报告

    流程：
    1. 从内存 store 取出面试状态
    2. 接收回答 (receive_answer_node)
    3. 评估回答 (evaluate_answer_node)
    4. 推送评估结果
    5. 如果不是最后一题：推送下一题（流式）
    6. 如果是最后一题：推送报告（流式）

    SSE 事件流：
    - {"type":"evaluation","score":8,"feedback":"...","dimensions":{...}}
    - 如果不是最后一题：
      * {"type":"question_start","index":1,"dimension":"logic","total":5}
      * {"type":"question_chunk","content":"..."} (多次)
      * {"type":"question_done","index":1}
      * {"type":"status","status":"in_progress","progress":20,...}
    - 如果是最后一题：
      * {"type":"report_start"}
      * {"type":"report_chunk","content":"..."} (多次)
      * {"type":"report_done"}
      * {"type":"interview_completed"}

    Args:
        interview_id: 面试ID
        answer: 用户回答

    Yields:
        str: SSE 格式事件字符串
    """
    # 取出面试状态
    state = _interview_store.get(interview_id)
    if state is None:
        yield _sse({
            "type": "error",
            "message": "面试不存在或已过期，请重新开始",
        })
        return

    if state.status != "in_progress":
        yield _sse({
            "type": "error",
            "message": f"面试状态异常: {state.status}",
        })
        return

    # LLM 不可用检查
    if not llm_client.is_available():
        yield _sse({
            "type": "error",
            "message": "AI 服务暂时不可用，请稍后重试",
        })
        return

    # 接收回答
    receive_result = await receive_answer_node(state, answer)
    if not receive_result.success:
        yield _sse({
            "type": "error",
            "message": receive_result.message,
        })
        return

    state = receive_result.state

    # 评估中提示
    yield _sse({
        "type": "status",
        "status": "evaluating",
        "detail": "AI 正在评估你的回答...",
        "current_index": state.current_question_index,
    })

    # 评估回答
    eval_result = await evaluate_answer_node(state)
    state = eval_result.state

    # 推送评估结果
    score = state.scores[state.current_question_index]
    current_question = state.questions[state.current_question_index] if state.current_question_index < len(state.questions) else None
    yield _sse({
        "type": "evaluation",
        "question_index": score.question_index,
        "question_dimension": current_question.dimension if current_question else "",
        "score": score.score,
        "dimensions": {
            "content": score.dimensions.content,
            "logic": score.dimensions.logic,
            "english": score.dimensions.english,
            "depth": score.dimensions.depth,
        },
        "feedback": score.feedback,
    })

    # 保存状态
    _interview_store[interview_id] = state

    # 判断下一步
    if state.is_last_question:
        # 最后一题：生成报告
        yield _sse({
            "type": "report_start",
            "detail": "AI 正在生成面试报告...",
        })

        report_text = ""
        async for chunk in complete_interview_node(state):
            yield _sse({"type": "report_chunk", "content": chunk})
            report_text += chunk

        # 保存最终状态
        state.analysis_report = report_text
        _interview_store[interview_id] = state

        yield _sse({
            "type": "report_done",
            "average_score": state.get_average_score(),
            "dimension_average": state.get_dimension_average(),
        })
        yield _sse({
            "type": "interview_completed",
            "interview_id": interview_id,
            "average_score": state.get_average_score(),
            "dimension_average": state.get_dimension_average(),
        })
    else:
        # 不是最后一题：推送下一题
        state.current_question_index += 1
        _interview_store[interview_id] = state

        next_idx = state.current_question_index
        next_question = state.questions[next_idx]

        yield _sse({
            "type": "question_start",
            "index": next_idx,
            "dimension": next_question.dimension,
            "total": state.total_questions,
        })

        async for chunk in ask_question_node(state):
            yield _sse({"type": "question_chunk", "content": chunk})

        yield _sse({
            "type": "question_done",
            "index": next_idx,
        })

        yield _sse({
            "type": "status",
            "status": "in_progress",
            "progress": state.progress_percent,
            "current_index": next_idx,
            "total": state.total_questions,
        })


# =============================================================================
# 状态查询接口
# =============================================================================

def get_interview_state(interview_id: str) -> Optional[InterviewState]:
    """获取面试状态

    Args:
        interview_id: 面试ID

    Returns:
        InterviewState | None
    """
    return _interview_store.get(interview_id)


def list_user_interviews(user_id: str) -> list:
    """获取用户的所有面试历史

    Args:
        user_id: 用户ID

    Returns:
        list[dict]: 面试历史摘要列表
    """
    if not user_id:
        return []

    history = []
    for iv_id, state in _interview_store.items():
        if state.user_id != user_id:
            continue
        history.append({
            "interview_id": iv_id,
            "school": state.school,
            "major": state.major,
            "degree": state.degree,
            "interview_type": state.interview_type,
            "total_questions": state.total_questions,
            "answered_questions": len(state.answers),
            "status": state.status,
            "average_score": state.get_average_score(),
            "started_at": state.started_at.isoformat() if state.started_at else None,
            "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        })

    # 按开始时间倒序
    history.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return history
