"""模拟面试路由 - AI驱动的留学申请模拟面试"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user
from .graph import InterviewWorkflow
from .state import InterviewPhase

router = APIRouter(prefix="/api/mock-interview", tags=["模拟面试"])

# 工作流存储
_active_workflows: Dict[str, InterviewWorkflow] = {}


# ========== 请求/响应模型 ==========

class CreateSessionRequest(BaseModel):
    school: str = Field(default="", description="目标院校")
    major: str = Field(default="", description="目标专业")
    interview_type: str = Field(default="academic", description="面试类型")
    difficulty: str = Field(default="advanced", description="难度")
    question_count: int = Field(default=3, ge=1, le=10, description="题目数量")
    personal_background: str = Field(default="", description="个人背景")
    # 评估模式：per_question=逐题判分 / full_simulation=全真模拟
    evaluation_mode: str = Field(default="per_question", description="评估模式")


class SubmitAnswerRequest(BaseModel):
    answer_text: str = Field(..., description="回答内容")
    question_id: str = Field(default="", description="当前问题ID")
    question_index: int = Field(default=0, description="问题序号")


class APIResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    message: str = "操作成功"
    error: Optional[Dict[str, Any]] = None


# ========== API 端点 ==========

@router.post("/sessions", response_model=APIResponse, status_code=status.HTTP_201_CREATED)
async def create_session(request: CreateSessionRequest, current_user: dict = Depends(require_user)):
    """创建面试会话"""
    try:
        user_id = current_user["user_id"]
        workflow = InterviewWorkflow()
        config = request.dict()
        state = workflow.create_session(user_id, config)
        session_id = f"int_{uuid.uuid4().hex[:12]}"
        state.session_id = session_id
        _active_workflows[session_id] = workflow

        logger.info(f"创建面试会话: session_id={session_id}, user={user_id}")
        return APIResponse(data={
            "session_id": session_id,
            "user_id": user_id,
            "phase": state.phase.value,
            "config": config,
            "created_at": state.created_at.isoformat()
        }, message="面试会话创建成功")
    except Exception as e:
        logger.error(f"创建会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/start", response_model=APIResponse)
async def start_interview(session_id: str, current_user: dict = Depends(require_user)):
    """开始面试 - 生成第一题"""
    try:
        workflow = _active_workflows.get(session_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="会话不存在")

        state = workflow.get_state()
        if state.phase.value != "setup":
            raise HTTPException(status_code=400, detail="面试已开始或已结束")

        # 先初始化，再生成第一题
        await workflow.start_interview()
        await workflow.generate_next_question()
        state = workflow.get_state()

        logger.info(f"开始面试: session_id={session_id}, mode={state.config.evaluation_mode}")
        return APIResponse(data={
            "session_id": session_id,
            "phase": state.phase.value,
            "evaluation_mode": state.config.evaluation_mode,
            "current_question_index": state.current_question_index,
            "total_questions": state.config.question_count,
            "current_question": {
                "question_id": state.current_question.question_id,
                "question_text": state.current_question.question_text,
                "dimension": state.current_question.dimension,
                "difficulty": state.current_question.difficulty
            } if state.current_question else None,
            "progress_percentage": state.get_progress_percentage()
        }, message="面试已开始")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"开始面试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/answer", response_model=APIResponse)
async def submit_answer(session_id: str, request: SubmitAnswerRequest,
                        current_user: dict = Depends(require_user)):
    """提交回答 - 根据 evaluation_mode 选择逐题评估或仅记录"""
    try:
        workflow = _active_workflows.get(session_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="会话不存在")

        state = workflow.get_state()
        if state.phase.value != "in_progress":
            raise HTTPException(status_code=400, detail="面试不在进行中")

        answer_text = request.answer_text.strip()
        if not answer_text:
            raise HTTPException(status_code=400, detail="回答不能为空")

        state = await workflow.submit_answer(answer_text, request.question_id)
        mode = state.config.evaluation_mode
        is_last = state.answered_count >= state.config.question_count

        logger.info(f"提交回答: session_id={session_id}, mode={mode}, answered={state.answered_count}/{state.config.question_count}, last={is_last}")

        # 全真模拟模式：不返回 evaluation，仅返回进度
        if mode == "full_simulation":
            return APIResponse(data={
                "session_id": session_id,
                "phase": state.phase.value,
                "evaluation_mode": mode,
                "answered_count": state.answered_count,
                "total_questions": state.config.question_count,
                "is_last_question": is_last,
                "current_evaluation": None
            }, message="回答已记录")

        # 逐题判分模式：返回当前评估
        return APIResponse(data={
            "session_id": session_id,
            "phase": state.phase.value,
            "evaluation_mode": mode,
            "answered_count": state.answered_count,
            "total_score": state.total_score,
            "average_score": state.average_score,
            "is_last_question": is_last,
            "current_evaluation": {
                "question_id": state.current_evaluation.question_id,
                "answer_id": state.current_evaluation.answer_id,
                "overall_score": state.current_evaluation.overall_score,
                "dimension_scores": state.current_evaluation.dimension_scores,
                "ai_feedback": state.current_evaluation.ai_feedback,
                "strengths": state.current_evaluation.strengths,
                "weaknesses": state.current_evaluation.weaknesses,
                "suggestions": state.current_evaluation.suggestions
            } if state.current_evaluation else None
        }, message="回答评估完成")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交回答失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/next", response_model=APIResponse)
async def next_question(session_id: str, current_user: dict = Depends(require_user)):
    """进入下一题 - 若为最后一题则自动完成面试

    健壮性增强：
    - 即使 complete_interview 失败，也返回基本报告结构（避免 500 错误）
    - 标记 is_completed=True 让前端能进入报告阶段
    """
    try:
        workflow = _active_workflows.get(session_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="会话不存在")

        state = workflow.get_state()
        if state.is_completed or state.phase.value == "completed":
            raise HTTPException(status_code=400, detail="面试已结束")

        # 检查是否为最后一题：进入下一题会超出题数，触发完成
        if state.current_question_index + 1 >= state.config.question_count:
            workflow.go_to_next_question()  # 触发 SUMMARY

            # 调用 complete_interview，即使失败也返回基本报告
            completion_error = None
            try:
                state = await workflow.complete_interview()
            except Exception as e:
                logger.error(f"complete_interview 失败，返回基本报告: {e}", exc_info=True)
                completion_error = str(e)
                state = workflow.get_state()
                # 强制标记完成，让前端能进入报告阶段
                state.is_completed = True
                state.phase = InterviewPhase.COMPLETED
                if not state.summary_report:
                    state.summary_report = {
                        "overall_summary": f"面试已完成。" + (f" 生成详细报告时遇到问题：{completion_error}" if completion_error else ""),
                        "average_score": state.average_score,
                        "dimension_analysis": {},
                        "strengths": [],
                        "weaknesses": [],
                        "improvement_suggestions": ["请重试或联系管理员"],
                        "performance_level": "average",
                        "recommendation": "neutral"
                    }

            return APIResponse(data={
                "session_id": session_id,
                "phase": state.phase.value,
                "is_completed": True,
                "progress_percentage": 100,
                "summary": state.summary_report,
                "average_score": state.average_score,
                "answered_count": state.answered_count,
                "questions": [{
                    "question_id": q.question_id,
                    "question_text": q.question_text,
                    "dimension": q.dimension,
                    "difficulty": q.difficulty
                } for q in state.questions],
                "evaluations": [{
                    "question_id": e.question_id,
                    "overall_score": e.overall_score,
                    "dimension_scores": e.dimension_scores,
                    "ai_feedback": e.ai_feedback,
                    "strengths": e.strengths,
                    "weaknesses": e.weaknesses,
                    "suggestions": e.suggestions
                } for e in state.evaluations]
            }, message="面试已完成")

        workflow.go_to_next_question()
        state = await workflow.generate_next_question()

        return APIResponse(data={
            "session_id": session_id,
            "phase": state.phase.value,
            "current_question_index": state.current_question_index,
            "current_question": {
                "question_id": state.current_question.question_id,
                "question_text": state.current_question.question_text,
                "dimension": state.current_question.dimension,
                "difficulty": state.current_question.difficulty
            } if state.current_question else None,
            "progress_percentage": state.get_progress_percentage(),
            "is_completed": False
        }, message="已进入下一题")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下一题失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/complete", response_model=APIResponse)
async def complete_interview(session_id: str, current_user: dict = Depends(require_user)):
    """结束面试 - 生成总结报告"""
    try:
        workflow = _active_workflows.get(session_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="会话不存在")

        state = workflow.get_state()
        if not state.summary_report:
            state = await workflow.complete_interview()

        return APIResponse(data={
            "session_id": session_id,
            "phase": state.phase.value,
            "is_completed": True,
            "summary": state.summary_report,
            "average_score": state.average_score,
            "total_score": state.total_score,
            "answered_count": state.answered_count,
            "questions": [{
                "question_id": q.question_id,
                "question_text": q.question_text,
                "dimension": q.dimension,
                "difficulty": q.difficulty
            } for q in state.questions],
            "evaluations": [{
                "question_id": e.question_id,
                "answer_id": e.answer_id,
                "overall_score": e.overall_score,
                "dimension_scores": e.dimension_scores,
                "ai_feedback": e.ai_feedback,
                "strengths": e.strengths,
                "weaknesses": e.weaknesses
            } for e in state.evaluations]
        }, message="面试已结束")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"结束面试失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}", response_model=APIResponse)
async def get_session(session_id: str, current_user: dict = Depends(require_user)):
    """获取会话详情"""
    try:
        workflow = _active_workflows.get(session_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="会话不存在")

        state = workflow.get_state()
        return APIResponse(data={
            "session_id": state.session_id,
            "user_id": state.user_id,
            "phase": state.phase.value,
            "config": state.config.dict(),
            "current_question_index": state.current_question_index,
            "questions": [{
                "question_id": q.question_id,
                "question_text": q.question_text,
                "dimension": q.dimension,
                "difficulty": q.difficulty
            } for q in state.questions],
            "answers": [{
                "answer_id": a.answer_id,
                "question_id": a.question_id,
                "answer_text": a.answer_text
            } for a in state.answers],
            "evaluations": [{
                "question_id": e.question_id,
                "answer_id": e.answer_id,
                "overall_score": e.overall_score,
                "dimension_scores": e.dimension_scores,
                "ai_feedback": e.ai_feedback,
                "strengths": e.strengths,
                "weaknesses": e.weaknesses
            } for e in state.evaluations],
            "total_score": state.total_score,
            "average_score": state.average_score,
            "answered_count": state.answered_count,
            "is_completed": state.is_completed,
            "summary_report": state.summary_report,
            "created_at": state.created_at.isoformat()
        }, message="获取成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
