"""模拟面试节点函数 - AI驱动的面试核心逻辑"""
import asyncio
import json
import re
import uuid
from datetime import datetime
from backend.common.basics.utils.logger import logger
from backend.common.functions.rag.models.llm_client import llm_client
from .state import (
    InterviewState, InterviewPhase, QuestionRecord,
    AnswerRecord, EvaluationResult
)
from .prompts import get_question_gen_prompt, get_evaluation_prompt, get_summary_prompt


def _parse_json(text: str) -> dict:
    """从LLM响应中提取JSON"""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}


async def init_interview(state: InterviewState) -> dict:
    """初始化面试 - 生成欢迎语"""
    logger.info(f"初始化面试: session_id={state.session_id}")
    school = state.config.school or "目标院校"
    msg = f"你好！欢迎参加{school}的模拟面试。我是你的AI面试官，今天的面试将围绕你的学术背景、研究兴趣和职业规划展开。请放松心态，展示真实的自己。我们开始吧！"
    return {
        "phase": InterviewPhase.IN_PROGRESS,
        "start_time": datetime.now(),
        "ai_response": msg
    }


async def generate_question(state: InterviewState) -> dict:
    """AI生成面试问题"""
    if state.current_question_index >= state.config.question_count:
        logger.info("已达到题目上限")
        return {"phase": InterviewPhase.SUMMARY}

    logger.info(f"生成第 {state.current_question_index + 1} 题")
    dimensions = ["academic", "research", "motivation", "career", "personal"]
    dim = dimensions[state.current_question_index % len(dimensions)]

    history = "\n".join([f"Q: {q.question_text}" for q in state.questions]) or "无"
    config = state.config
    prompt = get_question_gen_prompt(
        config.school, config.major, "严格", config.difficulty, dim
    )

    try:
        resp = await llm_client.async_chat([{"role": "user", "content": prompt}], model="deepseek-chat", temperature=0.8)
        result = _parse_json(resp)
        q_text = result.get("question_text", "") or f"请谈谈你在{dim}方面的经历和规划。"
        q_dim = result.get("dimension", dim)
        q_diff = result.get("difficulty", config.difficulty)
    except Exception as e:
        logger.error(f"AI生成问题失败: {e}")
        q_text = f"请谈谈你在{dim}方面的经历和规划。"
        q_dim = dim
        q_diff = config.difficulty

    question = QuestionRecord(
        question_id=f"q_{uuid.uuid4().hex[:8]}",
        question_text=q_text,
        dimension=q_dim,
        difficulty=q_diff,
        generated_by_ai=True
    )
    state.add_question(question)
    logger.info(f"问题生成: {q_text[:50]}...")
    return {"current_question": question, "ai_response": q_text}


async def evaluate_answer(state: InterviewState, answer_text: str, question_id: str = "") -> dict:
    """AI评估学生回答（逐题判分模式）"""
    # 查找目标问题
    target = None
    if question_id:
        target = next((q for q in state.questions if q.question_id == question_id), None)
    if not target:
        target = state.current_question
    if not target:
        logger.error("找不到目标问题")
        return {}

    answer = AnswerRecord(
        answer_id=f"a_{uuid.uuid4().hex[:8]}",
        question_id=target.question_id,
        answer_text=answer_text
    )
    state.add_answer(answer)

    prompt = get_evaluation_prompt(target.question_text, target.dimension, target.difficulty, answer_text)
    try:
        resp = await llm_client.async_chat([{"role": "user", "content": prompt}], model="deepseek-chat", temperature=0.3)
        result = _parse_json(resp)
    except Exception as e:
        logger.error(f"AI评估失败: {e}")
        result = {}

    evaluation = EvaluationResult(
        question_id=target.question_id,
        answer_id=answer.answer_id,
        overall_score=result.get("overall_score", 50),
        dimension_scores=result.get("dimension_scores", {
            "content": 50, "logic": 50, "expression": 50, "depth": 50, "relevance": 50
        }),
        ai_feedback=result.get("ai_feedback", "评估完成"),
        strengths=result.get("strengths", []),
        weaknesses=result.get("weaknesses", []),
        suggestions=result.get("suggestions", [])
    )
    state.add_evaluation(evaluation)
    logger.info(f"评估完成: 得分={evaluation.overall_score}")
    return {"current_evaluation": evaluation, "ai_response": evaluation.ai_feedback}


async def submit_answer_only(state: InterviewState, answer_text: str, question_id: str = "") -> dict:
    """全真模拟模式：仅记录答案，不进行AI评估"""
    target = None
    if question_id:
        target = next((q for q in state.questions if q.question_id == question_id), None)
    if not target:
        target = state.current_question
    if not target:
        logger.error("找不到目标问题")
        return {}

    answer = AnswerRecord(
        answer_id=f"a_{uuid.uuid4().hex[:8]}",
        question_id=target.question_id,
        answer_text=answer_text
    )
    state.add_answer(answer)
    logger.info(f"全真模拟模式：记录答案（不评估），已答 {state.answered_count}/{state.config.question_count}")
    return {"current_evaluation": None, "ai_response": "回答已记录"}


async def _evaluate_single(q, a) -> EvaluationResult:
    """评估单个问答对（供 batch_evaluate 并发调用）"""
    prompt = get_evaluation_prompt(q.question_text, q.dimension, q.difficulty, a.answer_text)
    try:
        resp = await llm_client.async_chat(
            [{"role": "user", "content": prompt}],
            model="deepseek-chat",
            temperature=0.3
        )
        result = _parse_json(resp)
    except Exception as e:
        logger.error(f"批量评估失败（问题 {q.question_id}）: {e}")
        result = {}

    return EvaluationResult(
        question_id=q.question_id,
        answer_id=a.answer_id,
        overall_score=result.get("overall_score", 50),
        dimension_scores=result.get("dimension_scores", {
            "content": 50, "logic": 50, "expression": 50, "depth": 50, "relevance": 50
        }),
        ai_feedback=result.get("ai_feedback", "评估完成"),
        strengths=result.get("strengths", []),
        weaknesses=result.get("weaknesses", []),
        suggestions=result.get("suggestions", [])
    )


async def batch_evaluate(state: InterviewState) -> dict:
    """全真模拟模式：批量评估所有未评估的回答

    性能优化：使用 asyncio.gather 并发评估，将 N 题评估时间从 N×T 压缩到 ~T
    """
    evaluated_ids = {e.question_id for e in state.evaluations}
    to_evaluate = [(q, a) for q in state.questions for a in state.answers
                   if a.question_id == q.question_id and q.question_id not in evaluated_ids]

    logger.info(f"批量评估：共 {len(to_evaluate)} 个回答待评估（并发执行）")

    if not to_evaluate:
        return {"ai_response": "无待评估回答"}

    # 并发评估所有题目
    tasks = [_evaluate_single(q, a) for q, a in to_evaluate]
    evaluations = await asyncio.gather(*tasks, return_exceptions=False)

    # 按原始顺序加入 state
    for ev in evaluations:
        state.add_evaluation(ev)
        logger.info(f"批量评估：问题 {ev.question_id} 得分={ev.overall_score}")

    return {"ai_response": f"已完成 {len(to_evaluate)} 个回答的评估"}


async def generate_summary(state: InterviewState) -> dict:
    """AI生成面试总结报告

    健壮性增强：
    - 处理 evaluations 为空或长度不一致的情况
    - LLM 调用增加 fallback_response，避免返回 None
    - 即使 LLM 完全失败，也返回基本报告结构
    """
    # 安全构建面试记录（避免 zip 长度不一致导致数据丢失）
    records = []
    n = max(len(state.questions), len(state.answers), len(state.evaluations))
    for i in range(n):
        q_text = state.questions[i].question_text if i < len(state.questions) else "(问题缺失)"
        a_text = state.answers[i].answer_text if i < len(state.answers) else "(未作答)"
        if i < len(state.evaluations):
            e = state.evaluations[i]
            records.append(
                f"问题{i+1}: {q_text}\n  回答: {a_text}\n  得分: {e.overall_score}\n  反馈: {e.ai_feedback}"
            )
        else:
            records.append(f"问题{i+1}: {q_text}\n  回答: {a_text}\n  得分: 未评估")

    records_str = "\n---\n".join(records) if records else "无面试记录"
    config = state.config
    prompt = get_summary_prompt(config.school, config.major, config.interview_type, records_str)

    # LLM 调用兜底响应（确保 JSON 格式有效）
    fallback_json = json.dumps({
        "overall_summary": "面试已完成。基于已有评分生成简要报告。",
        "dimension_analysis": {},
        "strengths": [],
        "weaknesses": [],
        "improvement_suggestions": ["请继续练习，提升回答的针对性和深度"],
        "performance_level": "average",
        "recommendation": "neutral"
    }, ensure_ascii=False)

    try:
        resp = await llm_client.async_chat(
            [{"role": "user", "content": prompt}],
            model="deepseek-chat",
            temperature=0.5,
            fallback_response=fallback_json,
        )
        result = _parse_json(resp) if resp else {}
        logger.info(f"AI总结响应长度: {len(resp) if resp else 0}")
    except Exception as e:
        logger.error(f"AI总结失败: {e}", exc_info=True)
        result = {}

    # 计算各维度平均分（用于 dimension_analysis 兜底）
    dim_avg = {}
    if state.evaluations:
        dim_keys = ["content", "logic", "expression", "depth", "relevance"]
        for k in dim_keys:
            scores = [e.dimension_scores.get(k, 0) for e in state.evaluations if e.dimension_scores]
            dim_avg[k] = round(sum(scores) / len(scores), 1) if scores else 0

    report = {
        "overall_summary": result.get("overall_summary", "面试完成。"),
        "average_score": state.average_score,
        "dimension_analysis": result.get("dimension_analysis") or dim_avg,
        "strengths": result.get("strengths", []),
        "weaknesses": result.get("weaknesses", []),
        "improvement_suggestions": result.get("improvement_suggestions", ["请继续努力"]),
        "performance_level": result.get("performance_level", "average"),
        "recommendation": result.get("recommendation", "neutral")
    }

    logger.info(
        f"总结生成完成: 平均分={state.average_score}, 问题数={len(state.questions)}, "
        f"评估数={len(state.evaluations)}, 报告键={list(report.keys())}"
    )
    return {
        "phase": InterviewPhase.COMPLETED,
        "is_completed": True,
        "end_time": datetime.now(),
        "summary_report": report,
        "ai_response": json.dumps(report, ensure_ascii=False)
    }
