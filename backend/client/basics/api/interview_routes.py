"""模拟面试 API 路由

提供 5 个接口：
- POST /api/interview/start           : 开始面试（SSE 流式返回第一个问题）
- POST /api/interview/{id}/answer     : 提交回答（SSE 流式返回评估+下一题/报告）
- GET  /api/interview/{id}/status     : 获取面试状态
- GET  /api/interview/{id}/report     : 获取分析报告
- GET  /api/interview/history         : 获取用户面试历史
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
import json

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user
from backend.client.functions.interview.graph import (
    start_interview,
    process_answer,
    get_interview_state,
    list_user_interviews,
)

router = APIRouter()


# =============================================================================
# 请求体模型
# =============================================================================

class StartInterviewRequest(BaseModel):
    """开始面试请求"""
    school: str = Field(..., description="目标院校，如 MIT")
    major: str = Field(..., description="目标专业，如 Computer Science")
    degree: str = Field("硕士", description="学位层次：本科/硕士/博士")
    interview_type: str = Field("admission", description="面试类型：admission/visa/scholarship")
    total_questions: int = Field(5, ge=1, le=10, description="问题总数（1-10）")


class SubmitAnswerRequest(BaseModel):
    """提交回答请求"""
    answer: str = Field(..., min_length=1, description="用户的回答内容")


# =============================================================================
# 接口 1: 开始面试
# =============================================================================

@router.post("/api/interview/start")
async def api_start_interview(
    request: StartInterviewRequest,
    current_user: dict = Depends(require_user),
):
    """开始面试 - SSE 流式返回 interview_id 和第一个问题

    SSE 事件流：
    - {"type":"start","interview_id":"...","total_questions":5}
    - {"type":"status","status":"generating_questions","detail":"..."}
    - {"type":"question_start","index":0,"dimension":"content","total":5}
    - {"type":"question_chunk","content":"..."} (多次)
    - {"type":"question_done","index":0}
    - {"type":"status","status":"in_progress","progress":0,...}

    Args:
        request: 面试配置
        current_user: 当前用户

    Returns:
        StreamingResponse: SSE 流
    """
    user_id = current_user.get("user_id", "")

    # 参数校验
    if request.interview_type not in ["admission", "visa", "scholarship"]:
        raise HTTPException(status_code=400, detail="interview_type 必须为 admission/visa/scholarship")
    if request.degree not in ["本科", "硕士", "博士"]:
        raise HTTPException(status_code=400, detail="degree 必须为 本科/硕士/博士")

    logger.info(
        f"[面试API] 开始面试 >>> user_id={user_id}, school={request.school}, "
        f"major={request.major}, degree={request.degree}, type={request.interview_type}, "
        f"total={request.total_questions}"
    )

    async def event_stream():
        try:
            async for sse_chunk in start_interview(
                user_id=user_id,
                school=request.school,
                major=request.major,
                degree=request.degree,
                interview_type=request.interview_type,
                total_questions=request.total_questions,
            ):
                yield sse_chunk
        except Exception as e:
            logger.error(f"[面试API] 开始面试异常: {e}", exc_info=True)
            error_event = {
                "type": "error",
                "message": "面试启动失败，请稍后重试",
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# 接口 2: 提交回答
# =============================================================================

@router.post("/api/interview/{interview_id}/answer")
async def api_submit_answer(
    interview_id: str,
    request: SubmitAnswerRequest,
    current_user: dict = Depends(require_user),
):
    """提交回答 - SSE 流式返回评估结果和下一题/报告

    SSE 事件流：
    - {"type":"status","status":"evaluating",...}
    - {"type":"evaluation","score":8,"dimensions":{...},"feedback":"..."}
    - 如果不是最后一题：
      * {"type":"question_start","index":1,...}
      * {"type":"question_chunk","content":"..."} (多次)
      * {"type":"question_done","index":1}
    - 如果是最后一题：
      * {"type":"report_start"}
      * {"type":"report_chunk","content":"..."} (多次)
      * {"type":"report_done","average_score":7.5,...}
      * {"type":"interview_completed"}

    Args:
        interview_id: 面试ID
        request: 回答内容
        current_user: 当前用户

    Returns:
        StreamingResponse: SSE 流
    """
    user_id = current_user.get("user_id", "")

    # 校验面试存在且属于当前用户
    state = get_interview_state(interview_id)
    if state is None:
        raise HTTPException(status_code=404, detail="面试不存在或已过期")
    if state.user_id != user_id:
        # 安全：不允许查看其他用户的面试
        raise HTTPException(status_code=403, detail="无权访问该面试")
    if state.status != "in_progress":
        raise HTTPException(
            status_code=400,
            detail=f"面试状态不允许提交回答: {state.status}",
        )

    logger.info(
        f"[面试API] 提交回答 >>> interview_id={interview_id}, "
        f"user_id={user_id}, 当前第{state.current_question_index + 1}题, "
        f"回答长度={len(request.answer)}"
    )

    async def event_stream():
        try:
            async for sse_chunk in process_answer(
                interview_id=interview_id,
                answer=request.answer,
            ):
                yield sse_chunk
        except Exception as e:
            logger.error(f"[面试API] 提交回答异常: {e}", exc_info=True)
            error_event = {
                "type": "error",
                "message": "处理回答时遇到问题，请稍后重试",
            }
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# =============================================================================
# 接口 3: 获取面试状态
# =============================================================================

@router.get("/api/interview/{interview_id}/status")
async def api_get_interview_status(
    interview_id: str,
    current_user: dict = Depends(require_user),
):
    """获取面试状态

    Args:
        interview_id: 面试ID
        current_user: 当前用户

    Returns:
        dict: 面试状态信息
    """
    user_id = current_user.get("user_id", "")
    state = get_interview_state(interview_id)

    if state is None:
        raise HTTPException(status_code=404, detail="面试不存在或已过期")
    if state.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该面试")

    return {
        "interview_id": state.interview_id,
        "school": state.school,
        "major": state.major,
        "degree": state.degree,
        "interview_type": state.interview_type,
        "status": state.status,
        "current_question_index": state.current_question_index,
        "total_questions": state.total_questions,
        "answered_questions": len(state.answers),
        "evaluated_questions": len(state.scores),
        "progress_percent": state.progress_percent,
        "average_score": state.get_average_score(),
        "dimension_average": state.get_dimension_average(),
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
        "current_question": (
            state.questions[state.current_question_index].model_dump()
            if state.current_question_index < len(state.questions)
            and state.status == "in_progress"
            else None
        ),
        "scores": [s.model_dump() for s in state.scores],
        "errors": state.errors,
    }


# =============================================================================
# 接口 4: 获取分析报告
# =============================================================================

@router.get("/api/interview/{interview_id}/report")
async def api_get_interview_report(
    interview_id: str,
    current_user: dict = Depends(require_user),
):
    """获取分析报告

    Args:
        interview_id: 面试ID
        current_user: 当前用户

    Returns:
        dict: 报告信息
    """
    user_id = current_user.get("user_id", "")
    state = get_interview_state(interview_id)

    if state is None:
        raise HTTPException(status_code=404, detail="面试不存在或已过期")
    if state.user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问该面试")

    if state.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"面试尚未完成，当前状态: {state.status}",
        )

    return {
        "interview_id": state.interview_id,
        "school": state.school,
        "major": state.major,
        "degree": state.degree,
        "interview_type": state.interview_type,
        "report": state.analysis_report,
        "average_score": state.get_average_score(),
        "dimension_average": state.get_dimension_average(),
        "scores": [s.model_dump() for s in state.scores],
        "questions": [q.model_dump() for q in state.questions],
        "answers": state.answers,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
    }


# =============================================================================
# 接口 5: 获取用户面试历史
# =============================================================================

@router.get("/api/interview/history")
async def api_get_interview_history(
    current_user: dict = Depends(require_user),
):
    """获取用户的面试历史列表

    Args:
        current_user: 当前用户

    Returns:
        list[dict]: 面试历史摘要列表
    """
    user_id = current_user.get("user_id", "")
    history = list_user_interviews(user_id)
    return history
