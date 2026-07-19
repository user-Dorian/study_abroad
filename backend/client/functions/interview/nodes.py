"""面试节点函数 - 包含所有 graph 执行节点

节点列表：
- start_interview_node    : 初始化面试，生成问题列表
- ask_question_node       : 输出当前问题（流式）
- receive_answer_node     : 接收用户回答，存储
- evaluate_answer_node    : 评估当前回答（后台异步）
- complete_interview_node : 完成面试，生成分析报告（流式）
"""
import json
import time
from typing import AsyncIterator, Optional

from backend.common.functions.rag.models.llm_client import llm_client
from backend.common.functions.rag.rag_config import RAGConfig
from backend.common.basics.utils.logger import logger

from .state import (
    InterviewState,
    InterviewConfig,
    QuestionItem,
    QuestionScore,
    ScoreDetail,
    NodeResult,
)
from .prompts import interview_prompt_manager


# =============================================================================
# 节点 1: 开始面试 - 生成问题列表
# =============================================================================

async def start_interview_node(state: InterviewState) -> NodeResult:
    """开始面试节点

    功能：
    1. 调用 LLM 生成 N 个面试问题（英文）
    2. 将问题列表保存到 state
    3. 标记面试状态为 in_progress
    4. 返回更新后的状态

    Args:
        state: 面试状态（已含 school/major/degree/interview_type 配置）

    Returns:
        NodeResult: 包含更新后的状态（questions 已填充）
    """
    state.add_node_to_path("start_interview_node")
    start_time = time.time()
    state.status = "in_progress"
    state.started_at = state.started_at or _now()

    logger.info(
        f"[面试节点] 开始 >>> school={state.school}, major={state.major}, "
        f"degree={state.degree}, type={state.interview_type}, "
        f"total={state.total_questions}"
    )

    try:
        messages = interview_prompt_manager.build_messages(
            "generate_questions",
            school=state.school,
            major=state.major,
            degree=state.degree,
            interview_type=state.interview_type,
            total_questions=state.total_questions,
        )

        # 用 JSON 模式获取结构化问题列表
        result = await llm_client.async_chat_json(
            messages=messages,
            model=RAGConfig.GENERATION_MODEL_NAME,
            temperature=0.7,
            default_value=[],
        )

        # 解析问题列表
        questions = _parse_questions(result, state.total_questions)

        if not questions:
            # LLM 返回空，使用兜底问题
            logger.warning("[面试节点] LLM 未生成问题，使用兜底问题")
            questions = _fallback_questions(state.total_questions)

        state.questions = questions
        state.current_question_index = 0

        elapsed = time.time() - start_time
        logger.info(
            f"[面试节点] 问题生成完成 ({elapsed:.2f}s): "
            f"共 {len(questions)} 题, "
            f"维度分布={[q.dimension for q in questions]}"
        )

        return NodeResult(
            success=True,
            state=state,
            message=f"生成 {len(questions)} 个面试问题",
            should_continue=True,
        )

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[面试节点] 生成问题失败 ({elapsed:.2f}s): {e}", exc_info=True)
        state.add_error(f"生成问题失败: {e}")

        # 兜底：使用预设问题
        state.questions = _fallback_questions(state.total_questions)
        state.current_question_index = 0

        return NodeResult(
            success=False,
            state=state,
            message=f"使用兜底问题: {e}",
            should_continue=True,
        )


def _parse_questions(result, total: int) -> list:
    """解析 LLM 返回的问题列表

    Args:
        result: LLM 返回的 JSON 对象（应为 list）
        total: 期望的问题数量

    Returns:
        list[QuestionItem]
    """
    if not isinstance(result, list):
        logger.warning(f"[面试节点] LLM 返回非数组: {type(result)}")
        return []

    valid_dimensions = {"content", "logic", "english", "depth"}
    questions = []
    for i, item in enumerate(result):
        if not isinstance(item, dict):
            continue
        question_text = (item.get("question") or "").strip()
        if not question_text:
            continue
        dimension = (item.get("dimension") or "").strip().lower()
        if dimension not in valid_dimensions:
            # 根据序号轮转分配维度
            dimension = list(valid_dimensions)[i % 4]
        questions.append(QuestionItem(
            index=i,
            dimension=dimension,
            question=question_text,
        ))
        if len(questions) >= total:
            break

    return questions


def _fallback_questions(total: int) -> list:
    """兜底问题列表（LLM 不可用时使用）

    Args:
        total: 需要的问题数量

    Returns:
        list[QuestionItem]
    """
    presets = [
        QuestionItem(index=0, dimension="content",
                     question="What academic achievements or experiences make you a strong candidate for this program?"),
        QuestionItem(index=1, dimension="logic",
                     question="Describe a complex problem you have solved. Walk me through your thinking process."),
        QuestionItem(index=2, dimension="english",
                     question="Tell me about a time you faced a significant challenge. How did you overcome it?"),
        QuestionItem(index=3, dimension="depth",
                     question="Why did you choose this specific program at our school over similar programs elsewhere?"),
        QuestionItem(index=4, dimension="content",
                     question="What is a current development in your field that excites you, and why?"),
        QuestionItem(index=5, dimension="logic",
                     question="If you were given unlimited resources for one research project, what would you investigate and how?"),
        QuestionItem(index=6, dimension="depth",
                     question="How will this degree help you achieve your long-term career goals?"),
        QuestionItem(index=7, dimension="english",
                     question="Discuss a book, paper, or idea that has profoundly influenced your perspective."),
        QuestionItem(index=8, dimension="content",
                     question="What is your greatest weakness, and what steps are you taking to improve it?"),
        QuestionItem(index=9, dimension="depth",
                     question="How do you plan to contribute to our campus community?"),
    ]
    return presets[:max(total, 0)]


# =============================================================================
# 节点 2: 提问节点 - 流式输出当前问题
# =============================================================================

async def ask_question_node(state: InterviewState) -> AsyncIterator[str]:
    """提问节点 - 流式输出当前问题

    由于问题已经在 start_interview_node 中生成，这里只是按字符流式输出，
    模拟"面试官正在念题"的效果，避免用户等待焦虑。

    Args:
        state: 面试状态

    Yields:
        str: 问题文本片段
    """
    state.add_node_to_path("ask_question_node")

    if state.current_question_index >= len(state.questions):
        logger.error(
            f"[面试节点] 题目序号越界: index={state.current_question_index}, "
            f"total={len(state.questions)}"
        )
        yield "抱歉，面试题目加载异常，请重新开始面试。"
        return

    question = state.questions[state.current_question_index]
    logger.info(
        f"[面试节点] 提问 >>> 第 {state.current_question_index + 1}/{state.total_questions} 题, "
        f"维度={question.dimension}"
    )

    # 按词组切片，模拟自然语速流式输出
    text = question.question
    words = text.split()
    chunk_size = 3  # 每次输出3个词
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        if i + chunk_size < len(words):
            chunk += " "
        yield chunk


# =============================================================================
# 节点 3: 接收回答节点
# =============================================================================

async def receive_answer_node(state: InterviewState, answer: str) -> NodeResult:
    """接收回答节点 - 存储用户回答

    Args:
        state: 面试状态
        answer: 用户回答文本

    Returns:
        NodeResult: 更新后的状态（answers 列表追加新回答）
    """
    state.add_node_to_path("receive_answer_node")

    if not answer or not answer.strip():
        return NodeResult(
            success=False,
            state=state,
            message="回答内容为空",
            should_continue=False,
        )

    # 追加到 answers 列表（按题目序号对齐）
    # 若已有相同序号的回答则覆盖（理论上不应该发生，但做保护）
    while len(state.answers) <= state.current_question_index:
        state.answers.append("")
    state.answers[state.current_question_index] = answer.strip()

    logger.info(
        f"[面试节点] 接收回答 >>> 第 {state.current_question_index + 1} 题, "
        f"长度={len(answer)}"
    )

    return NodeResult(
        success=True,
        state=state,
        message="回答已接收",
        should_continue=True,
    )


# =============================================================================
# 节点 4: 评估回答节点
# =============================================================================

async def evaluate_answer_node(state: InterviewState) -> NodeResult:
    """评估回答节点 - 对当前题目的回答进行评分

    功能：
    1. 取出当前题目的回答
    2. 调用 LLM 评估四维度评分
    3. 解析返回的 JSON 评分
    4. 将评分保存到 state.scores

    Args:
        state: 面试状态（answers[current_question_index] 已填充）

    Returns:
        NodeResult: 包含更新后的状态（scores 追加新评分）
    """
    state.add_node_to_path("evaluate_answer_node")
    start_time = time.time()

    idx = state.current_question_index
    if idx >= len(state.questions):
        return NodeResult(
            success=False,
            state=state,
            message="题目序号越界",
            should_continue=False,
        )

    if idx >= len(state.answers) or not state.answers[idx]:
        return NodeResult(
            success=False,
            state=state,
            message="未找到对应回答",
            should_continue=False,
        )

    question = state.questions[idx]
    answer = state.answers[idx]

    logger.info(
        f"[面试节点] 评估 >>> 第 {idx + 1} 题, 维度={question.dimension}, "
        f"回答长度={len(answer)}"
    )

    try:
        messages = interview_prompt_manager.build_messages(
            "evaluate_answer",
            school=state.school,
            major=state.major,
            degree=state.degree,
            question_index=idx + 1,
            total_questions=state.total_questions,
            dimension=question.dimension,
            question=question.question,
            answer=answer,
        )

        result = await llm_client.async_chat_json(
            messages=messages,
            model=RAGConfig.INTENT_MODEL_NAME,
            temperature=0.0,
            default_value={
                "score": 5,
                "dimensions": {"content": 5, "logic": 5, "english": 5, "depth": 5},
                "feedback": "评估失败，已使用默认评分",
            },
        )

        score_obj = _parse_score(result, idx, question.question, answer)

        # 追加到 scores 列表
        while len(state.scores) <= idx:
            state.scores.append(QuestionScore(
                question_index=0, question="", answer="",
                score=0, dimensions=ScoreDetail(), feedback="",
            ))
        state.scores[idx] = score_obj

        elapsed = time.time() - start_time
        logger.info(
            f"[面试节点] 评估完成 ({elapsed:.2f}s): "
            f"score={score_obj.score}, "
            f"dimensions=({score_obj.dimensions.content},"
            f"{score_obj.dimensions.logic},"
            f"{score_obj.dimensions.english},"
            f"{score_obj.dimensions.depth})"
        )

        return NodeResult(
            success=True,
            state=state,
            message=f"评估完成: score={score_obj.score}",
            should_continue=True,
        )

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"[面试节点] 评估失败 ({elapsed:.2f}s): {e}", exc_info=True)
        state.add_error(f"评估失败: {e}")

        # 兜底评分
        fallback_score = QuestionScore(
            question_index=idx,
            question=question.question,
            answer=answer,
            score=5,
            dimensions=ScoreDetail(content=5, logic=5, english=5, depth=5),
            feedback="评估过程出现问题，已使用默认评分。建议重新尝试。",
        )
        while len(state.scores) <= idx:
            state.scores.append(fallback_score)
        state.scores[idx] = fallback_score

        return NodeResult(
            success=False,
            state=state,
            message=f"评估失败，使用默认评分: {e}",
            should_continue=True,
        )


def _parse_score(result: dict, idx: int, question: str, answer: str) -> QuestionScore:
    """解析 LLM 返回的评分 JSON

    Args:
        result: LLM 返回的 dict
        idx: 题目序号
        question: 题目文本
        answer: 用户回答

    Returns:
        QuestionScore: 评分对象
    """
    if not isinstance(result, dict):
        result = {}

    # 解析总分
    try:
        score = int(result.get("score", 5))
        score = max(1, min(10, score))
    except (TypeError, ValueError):
        score = 5

    # 解析维度评分
    dims_raw = result.get("dimensions") or {}
    if not isinstance(dims_raw, dict):
        dims_raw = {}

    def _clamp_int(val, default=5):
        try:
            v = int(val)
            return max(1, min(10, v))
        except (TypeError, ValueError):
            return default

    dimensions = ScoreDetail(
        content=_clamp_int(dims_raw.get("content", 5)),
        logic=_clamp_int(dims_raw.get("logic", 5)),
        english=_clamp_int(dims_raw.get("english", 5)),
        depth=_clamp_int(dims_raw.get("depth", 5)),
    )

    # 若 score 与四维度均值差距过大，以四维度均值为准
    dim_avg = (dimensions.content + dimensions.logic +
               dimensions.english + dimensions.depth) / 4
    if abs(score - dim_avg) > 2:
        score = round(dim_avg)

    feedback = str(result.get("feedback", "")).strip()
    if not feedback:
        feedback = "暂无具体反馈"

    return QuestionScore(
        question_index=idx,
        question=question,
        answer=answer,
        score=score,
        dimensions=dimensions,
        feedback=feedback,
    )


# =============================================================================
# 节点 5: 完成面试 - 流式生成分析报告
# =============================================================================

async def complete_interview_node(state: InterviewState) -> AsyncIterator[str]:
    """完成面试节点 - 流式生成综合分析报告

    功能：
    1. 标记状态为 analyzing
    2. 拼装评分汇总和问答详情
    3. 调用 LLM 流式生成中文报告
    4. 流式输出报告内容片段
    5. 完成后标记状态为 completed

    Args:
        state: 面试状态（scores 已填充）

    Yields:
        str: 报告文本片段
    """
    state.add_node_to_path("complete_interview_node")
    state.status = "analyzing"

    logger.info(
        f"[面试节点] 生成报告 >>> 已答 {len(state.answers)} 题, "
        f"已评分 {len(state.scores)} 题"
    )

    # 拼装 prompt 上下文
    scores_summary = _build_scores_summary(state)
    qa_details = _build_qa_details(state)
    avg = state.get_average_score()
    dim_avg = state.get_dimension_average()

    try:
        messages = interview_prompt_manager.build_messages(
            "generate_report",
            school=state.school,
            major=state.major,
            degree=state.degree,
            total_questions=state.total_questions,
            scores_summary=scores_summary,
            qa_details=qa_details,
            average_score=f"{avg:.1f}",
            content_avg=f"{dim_avg['content']:.1f}",
            logic_avg=f"{dim_avg['logic']:.1f}",
            english_avg=f"{dim_avg['english']:.1f}",
            depth_avg=f"{dim_avg['depth']:.1f}",
        )

        # 累积完整报告
        full_report_parts = []

        async for chunk in llm_client.async_chat_stream(
            messages=messages,
            model=RAGConfig.GENERATION_MODEL_NAME,
            temperature=0.3,
        ):
            if chunk:
                full_report_parts.append(chunk)
                yield chunk

        # 保存完整报告
        state.analysis_report = "".join(full_report_parts)
        state.status = "completed"
        state.completed_at = _now()

        logger.info(
            f"[面试节点] 报告生成完成: 长度={len(state.analysis_report)}, "
            f"状态={state.status}"
        )

    except Exception as e:
        logger.error(f"[面试节点] 报告生成失败: {e}", exc_info=True)
        state.add_error(f"报告生成失败: {e}")
        fallback = (
            "## 面试报告\n\n"
            "抱歉，报告生成过程出现问题。以下是基于评分的简要总结：\n\n"
            f"- 平均分: {avg:.1f}/10\n"
            f"- 内容深度: {dim_avg['content']:.1f}\n"
            f"- 逻辑思维: {dim_avg['logic']:.1f}\n"
            f"- 英语表达: {dim_avg['english']:.1f}\n"
            f"- 个人特质: {dim_avg['depth']:.1f}\n\n"
            "建议您稍后重试或联系顾问获取详细反馈。"
        )
        state.analysis_report = fallback
        state.status = "completed"
        state.completed_at = _now()
        yield fallback


# =============================================================================
# 辅助函数
# =============================================================================

def _now():
    """获取当前时间"""
    from datetime import datetime
    return datetime.now()


def _build_scores_summary(state: InterviewState) -> str:
    """构建评分汇总文本（用于 prompt 上下文）"""
    if not state.scores:
        return "（暂无评分数据）"

    lines = []
    for s in state.scores:
        lines.append(
            f"- 第 {s.question_index + 1} 题 "
            f"[{s.dimensions_to_str()}] 总分 {s.score}/10"
        )
    return "\n".join(lines)


def _build_qa_details(state: InterviewState) -> str:
    """构建问答详情文本（用于 prompt 上下文）"""
    if not state.questions:
        return "（暂无问答数据）"

    lines = []
    for i, q in enumerate(state.questions):
        answer = state.answers[i] if i < len(state.answers) else "（未回答）"
        score = state.scores[i] if i < len(state.scores) else None

        lines.append(f"### 第 {i + 1} 题 [{q.dimension}]")
        lines.append(f"问题: {q.question}")
        lines.append(f"回答: {answer}")
        if score:
            lines.append(
                f"评分: 总分 {score.score}/10, "
                f"内容 {score.dimensions.content}, 逻辑 {score.dimensions.logic}, "
                f"英语 {score.dimensions.english}, 个人特质 {score.dimensions.depth}"
            )
            lines.append(f"反馈: {score.feedback}")
        lines.append("")

    return "\n".join(lines)


# ====== 给 QuestionScore 增加一个工具方法（运行时打补丁，避免修改 state.py 太多） ======
def _score_to_str(self) -> str:
    """将维度评分转为可读字符串"""
    return (f"内容{self.dimensions.content}/逻辑{self.dimensions.logic}/"
            f"英语{self.dimensions.english}/特质{self.dimensions.depth}")


# 给 QuestionScore 类挂上 dimensions_to_str 方法（避免循环引用）
QuestionScore.dimensions_to_str = _score_to_str
