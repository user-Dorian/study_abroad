"""情景对话功能 - 节点函数模块

职责：
    实现情景对话工作流中的所有节点函数。每个节点：
    - 接收 ScenarioSession 状态对象（及必要参数）
    - 执行 LLM 调用或模板生成
    - 返回 dict（由 graph.py 的 _apply 合并到 state）

节点清单：
    1. init_scenario              构造NPC开场白（模板，不调LLM）
    2. npc_reply_free             自由模式NPC回复（非流式）
    3. npc_reply_free_stream      自由模式NPC回复（流式，yield token）
    4. generate_preset_options    生成预设选项（JSON）
    5. analyze_user_input         实时纠错+润色（JSON）
    6. generate_smart_assist      文化提示+策略建议（JSON）
    7. explain_wrong_option       错误选项解释+错题记录
    8. generate_learning_report   学习报告生成（JSON）

兜底策略：
    每个节点 try/except 包裹 LLM 调用，失败时返回模板化兜底文本，
    并通过 logger.error 记录，确保不向上抛异常导致流程崩溃。
"""
import json
import re
import uuid
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional

from backend.common.basics.utils.logger import logger
from backend.common.functions.rag.models.llm_client import llm_client

from .state import (
    CulturalTip,
    DifficultyLevel,
    ExpressionPolish,
    LanguageCorrection,
    LearningReport,
    MessageType,
    PresetOption,
    PresetOptionType,
    ScenarioConfig,
    ScenarioMessage,
    ScenarioPhase,
    ScenarioSession,
    StrategySuggestion,
    WrongOptionRecord,
)
from .prompts import (
    get_cultural_tip_prompt,
    get_input_analysis_prompt,
    get_learning_report_prompt,
    get_npc_free_reply_prompt,
    get_npc_system_prompt,
    get_preset_options_prompt,
    get_strategy_guide_prompt,
    get_wrong_option_explain_prompt,
)


# ==================== 工具函数 ====================

def _parse_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象

    依次尝试：
    1. 直接 json.loads
    2. 提取 ```json ... ``` 或 ``` ... ``` 围栏内容
    3. 提取首个 { ... } 块
    全部失败返回空 dict
    """
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
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


def _gen_id(prefix: str = "id") -> str:
    """生成短 ID"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _build_scene_desc(config: ScenarioConfig) -> str:
    """根据配置构造场景描述文本"""
    if config.category == "custom" and config.custom_scene_desc:
        return config.custom_scene_desc
    parts = [config.country or "通用场景"]
    if config.city:
        parts.append(config.city)
    parts.append(config.scene_key or "日常对话")
    return " · ".join(parts)


def _language_name(code: str) -> str:
    """语言代码 → 中文名"""
    return {
        "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语",
        "fr": "法语", "de": "德语", "es": "西班牙语",
    }.get(code, "目标语言")


# ==================== 1. init_scenario - 构造NPC开场白 ====================

async def init_scenario(state: ScenarioSession) -> dict:
    """初始化场景：构造 NPC 开场白（不调LLM，纯模板生成）

    Returns:
        dict: {phase, start_time, ai_response, npc_opening_message}
    """
    logger.info(f"[Scenario] init_scenario: session_id={state.session_id}")
    config = state.config

    # 构造开场白 - 使用目标语言
    lang_name = _language_name(config.language)
    greeting_map = {
        "en": "Hello! Welcome",
        "zh": "你好！欢迎",
        "ja": "こんにちは！ようこそ",
        "ko": "안녕하세요! 환영합니다",
        "fr": "Bonjour ! Bienvenue",
        "de": "Hallo! Willkommen",
        "es": "¡Hola! Bienvenido",
    }
    greet = greeting_map.get(config.language, greeting_map["en"])
    npc_role = config.npc_role or "对话伙伴"
    user_role = config.user_role or "朋友"

    # 简短的开场白（目标语言 + 中文翻译）
    opening_text = f"{greet}! I'm your {npc_role} today. How can I help you, {user_role}?"
    opening_translation = f"{greet}！今天我是你的{npc_role}。{user_role}，有什么我可以帮你的吗？"

    # 构造 NPC 开场消息并写入 state.messages
    opening_msg = ScenarioMessage(
        message_id=_gen_id("msg"),
        role=MessageType.NPC,
        content=opening_text,
        language=config.language,
        translation=opening_translation,
        timestamp=datetime.now(),
    )
    state.add_message(opening_msg)

    return {
        "phase": ScenarioPhase.IN_PROGRESS,
        "start_time": datetime.now(),
        "ai_response": opening_text,
        "npc_opening_message": opening_msg,
    }


# ==================== 2. npc_reply_free - 自由模式NPC回复（非流式） ====================

async def npc_reply_free(state: ScenarioSession, user_text: str) -> dict:
    """自由模式：调用 LLM 生成 NPC 回复（非流式）

    Returns:
        dict: {ai_response, new_message}
    """
    config = state.config
    lang_name = _language_name(config.language)
    scene_desc = _build_scene_desc(config)

    system_prompt = get_npc_system_prompt(
        language_name=lang_name,
        country=config.country,
        city=config.city,
        scene_desc=scene_desc,
        difficulty=config.difficulty.value if isinstance(config.difficulty, DifficultyLevel) else str(config.difficulty),
        user_role=config.user_role,
        npc_role=config.npc_role,
    )

    # 构造历史文本
    history = "\n".join(
        f"{'用户' if m.role == MessageType.USER else 'NPC'}: {m.content}"
        for m in state.messages[-10:]  # 最近 10 轮
    ) or "（无历史）"

    user_prompt = get_npc_free_reply_prompt(
        history=history,
        user_msg=user_text,
        difficulty=config.difficulty.value if isinstance(config.difficulty, DifficultyLevel) else str(config.difficulty),
        npc_role=config.npc_role,
        language_name=lang_name,
    )

    try:
        reply = await llm_client.async_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model="deepseek-chat",
            temperature=0.8,
        )
        reply = (reply or "").strip()
        if not reply:
            reply = "I'm sorry, could you say that again?"
        logger.info(f"[Scenario] npc_reply_free 成功: {reply[:60]}...")
    except Exception as e:
        logger.error(f"[Scenario] npc_reply_free LLM调用失败: {e}", exc_info=True)
        reply = "I'm sorry, could you say that again?"

    new_message = ScenarioMessage(
        message_id=_gen_id("msg"),
        role=MessageType.NPC,
        content=reply,
        language=config.language,
        translation="",
        timestamp=datetime.now(),
    )
    state.add_message(new_message)

    return {"ai_response": reply, "new_message": new_message}


# ==================== 3. npc_reply_free_stream - 自由模式NPC回复（流式） ====================

async def npc_reply_free_stream(state: ScenarioSession, user_text: str) -> AsyncIterator[str]:
    """自由模式：调用 LLM 流式生成 NPC 回复

    Yields:
        str: 每次 yield 一个 token 片段
    """
    config = state.config
    lang_name = _language_name(config.language)
    scene_desc = _build_scene_desc(config)

    system_prompt = get_npc_system_prompt(
        language_name=lang_name,
        country=config.country,
        city=config.city,
        scene_desc=scene_desc,
        difficulty=config.difficulty.value if isinstance(config.difficulty, DifficultyLevel) else str(config.difficulty),
        user_role=config.user_role,
        npc_role=config.npc_role,
    )

    history = "\n".join(
        f"{'用户' if m.role == MessageType.USER else 'NPC'}: {m.content}"
        for m in state.messages[-10:]
    ) or "（无历史）"

    user_prompt = get_npc_free_reply_prompt(
        history=history,
        user_msg=user_text,
        difficulty=config.difficulty.value if isinstance(config.difficulty, DifficultyLevel) else str(config.difficulty),
        npc_role=config.npc_role,
        language_name=lang_name,
    )

    accumulated = []
    try:
        async for chunk in llm_client.async_chat_stream(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model="deepseek-chat",
            temperature=0.8,
        ):
            if chunk:
                accumulated.append(chunk)
                yield chunk
    except Exception as e:
        logger.error(f"[Scenario] npc_reply_free_stream 失败: {e}", exc_info=True)
        fallback = "I'm sorry, could you say that again?"
        yield fallback
        accumulated.append(fallback)

    # 流式结束后，将完整回复写入 state.messages
    full_reply = "".join(accumulated).strip()
    if not full_reply:
        full_reply = "I'm sorry, could you say that again?"
    new_message = ScenarioMessage(
        message_id=_gen_id("msg"),
        role=MessageType.NPC,
        content=full_reply,
        language=config.language,
        translation="",
        timestamp=datetime.now(),
    )
    state.add_message(new_message)


# ==================== 4. generate_preset_options - 生成预设选项 ====================

async def generate_preset_options(state: ScenarioSession, npc_question: str) -> dict:
    """预设模式：生成 2-4 个回复选项

    Returns:
        dict: {current_preset_options: List[PresetOption]}
    """
    config = state.config
    history = "\n".join(
        f"{'用户' if m.role == MessageType.USER else 'NPC'}: {m.content}"
        for m in state.messages[-6:]
    )
    prompt = get_preset_options_prompt(
        history=history,
        last_npc_question=npc_question,
        difficulty=config.difficulty.value if isinstance(config.difficulty, DifficultyLevel) else str(config.difficulty),
    )

    options: List[PresetOption] = []
    try:
        resp = await llm_client.async_chat(
            messages=[{"role": "user", "content": prompt}],
            model="deepseek-chat",
            temperature=0.7,
        )
        result = _parse_json(resp)
        raw_options = result.get("options", []) if isinstance(result, dict) else []
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            try:
                opt_type = PresetOptionType(raw.get("type", "correct"))
            except ValueError:
                opt_type = PresetOptionType.CORRECT
            options.append(PresetOption(
                option_id=_gen_id("opt"),
                type=opt_type,
                text=raw.get("text", ""),
                translation=raw.get("translation", ""),
                explanation=raw.get("explanation", ""),
                cultural_note=raw.get("cultural_note", ""),
            ))
        logger.info(f"[Scenario] generate_preset_options 成功: {len(options)} 个选项")
    except Exception as e:
        logger.error(f"[Scenario] generate_preset_options 失败: {e}", exc_info=True)

    # 兜底：若 LLM 失败或返回为空，给一个标准正确选项
    if not options:
        options.append(PresetOption(
            option_id=_gen_id("opt"),
            type=PresetOptionType.CORRECT,
            text="Could you please say that again?",
            translation="能再说一遍吗？",
            explanation="请求对方重复，是基础但实用的应对策略",
            cultural_note="在英语对话中，礼貌地请求重复是可接受的行为",
        ))

    # 确保至少 1 个 correct 选项
    if not any(o.type == PresetOptionType.CORRECT for o in options):
        options.insert(0, PresetOption(
            option_id=_gen_id("opt"),
            type=PresetOptionType.CORRECT,
            text="Yes, please.",
            translation="好的，麻烦了。",
            explanation="标准礼貌回应",
            cultural_note="简短肯定的回应适用于多种场景",
        ))

    return {"current_preset_options": options}


# ==================== 5. analyze_user_input - 实时纠错+润色 ====================

async def analyze_user_input(state: ScenarioSession, user_text: str) -> dict:
    """分析用户输入：实时纠错 + 表达润色

    若 smart_assist.real_time_correction 和 expression_polish 都关闭，直接返回空结果。

    Returns:
        dict: {corrections: List[LanguageCorrection], polishes: List[ExpressionPolish]}
    """
    sa = state.smart_assist
    # 两个开关都关，直接返回空
    if not sa.real_time_correction and not sa.expression_polish:
        return {"corrections": [], "polishes": []}

    config = state.config
    scene_desc = _build_scene_desc(config)
    prompt = get_input_analysis_prompt(
        user_msg=user_text,
        language=config.language,
        country=config.country,
        scene=scene_desc,
    )

    corrections: List[LanguageCorrection] = []
    polishes: List[ExpressionPolish] = []

    try:
        resp = await llm_client.async_chat(
            messages=[{"role": "user", "content": prompt}],
            model="deepseek-chat",
            temperature=0.2,
        )
        result = _parse_json(resp)
        if isinstance(result, dict):
            # 按开关过滤
            if sa.real_time_correction:
                for raw in result.get("corrections", []) or []:
                    if not isinstance(raw, dict):
                        continue
                    corrections.append(LanguageCorrection(
                        original=raw.get("original", ""),
                        corrected=raw.get("corrected", ""),
                        explanation=raw.get("explanation", ""),
                        error_type=raw.get("error_type", "grammar"),
                    ))
            if sa.expression_polish:
                for raw in result.get("polishes", []) or []:
                    if not isinstance(raw, dict):
                        continue
                    polishes.append(ExpressionPolish(
                        original=raw.get("original", ""),
                        polished=raw.get("polished", ""),
                        note=raw.get("note", ""),
                    ))
        logger.info(f"[Scenario] analyze_user_input 成功: {len(corrections)} 纠错, {len(polishes)} 润色")
    except Exception as e:
        logger.error(f"[Scenario] analyze_user_input 失败: {e}", exc_info=True)

    return {"corrections": corrections, "polishes": polishes}


# ==================== 6. generate_smart_assist - 文化提示+策略建议 ====================

async def generate_smart_assist(state: ScenarioSession, recent_msg: str) -> dict:
    """生成智能辅助：文化提示 + 策略建议

    按 smart_assist.cultural_tip 和 strategy_guide 开关控制。

    Returns:
        dict: {cultural_tips: List[CulturalTip], strategy_suggestions: List[StrategySuggestion]}
    """
    sa = state.smart_assist
    if not sa.cultural_tip and not sa.strategy_guide:
        return {"cultural_tips": [], "strategy_suggestions": []}

    config = state.config
    scene_desc = _build_scene_desc(config)
    cultural_tips: List[CulturalTip] = []
    strategy_suggestions: List[StrategySuggestion] = []

    # 文化提示
    if sa.cultural_tip:
        try:
            tip_prompt = get_cultural_tip_prompt(
                country=config.country,
                city=config.city,
                scene=scene_desc,
                recent_topic=recent_msg,
            )
            resp = await llm_client.async_chat(
                messages=[{"role": "user", "content": tip_prompt}],
                model="deepseek-chat",
                temperature=0.5,
            )
            tip_result = _parse_json(resp)
            if isinstance(tip_result, dict):
                for raw in tip_result.get("cultural_tips", []) or []:
                    if not isinstance(raw, dict):
                        continue
                    cultural_tips.append(CulturalTip(
                        title=raw.get("title", ""),
                        content=raw.get("content", ""),
                        dos=raw.get("dos", []) or [],
                        donts=raw.get("donts", []) or [],
                    ))
            logger.info(f"[Scenario] generate_smart_assist 文化提示: {len(cultural_tips)} 条")
        except Exception as e:
            logger.error(f"[Scenario] generate_smart_assist 文化提示失败: {e}", exc_info=True)

    # 策略建议
    if sa.strategy_guide:
        # 取最近一条 NPC 消息作为「NPC 最近问题」
        last_npc_msg = ""
        for m in reversed(state.messages):
            if m.role == MessageType.NPC:
                last_npc_msg = m.content
                break
        try:
            strat_prompt = get_strategy_guide_prompt(
                last_npc_question=last_npc_msg,
                difficulty=config.difficulty.value if isinstance(config.difficulty, DifficultyLevel) else str(config.difficulty),
            )
            resp = await llm_client.async_chat(
                messages=[{"role": "user", "content": strat_prompt}],
                model="deepseek-chat",
                temperature=0.7,
            )
            strat_result = _parse_json(resp)
            if isinstance(strat_result, dict):
                for raw in strat_result.get("strategies", []) or []:
                    if not isinstance(raw, dict):
                        continue
                    strategy_suggestions.append(StrategySuggestion(
                        style=raw.get("style", ""),
                        style_label=raw.get("style_label", ""),
                        text=raw.get("text", ""),
                    ))
            logger.info(f"[Scenario] generate_smart_assist 策略: {len(strategy_suggestions)} 条")
        except Exception as e:
            logger.error(f"[Scenario] generate_smart_assist 策略失败: {e}", exc_info=True)

    return {"cultural_tips": cultural_tips, "strategy_suggestions": strategy_suggestions}


# ==================== 7. explain_wrong_option - 错误选项解释 ====================

async def explain_wrong_option(
    state: ScenarioSession,
    option: PresetOption,
    correct_option: PresetOption,
) -> dict:
    """错误选项解释：调用 LLM 生成解释，并构造错题记录

    Args:
        state: 会话状态
        option: 用户选错的选项
        correct_option: 正确选项

    Returns:
        dict: {ai_response: str, wrong_record: WrongOptionRecord}
    """
    prompt = get_wrong_option_explain_prompt(
        selected_text=option.text,
        correct_text=correct_option.text,
        cultural_note=option.cultural_note or correct_option.cultural_note,
    )

    try:
        resp = await llm_client.async_chat(
            messages=[{"role": "user", "content": prompt}],
            model="deepseek-chat",
            temperature=0.4,
        )
        explanation = (resp or "").strip()
        if not explanation:
            explanation = f"你选的「{option.text}」不太合适，更推荐的表达是「{correct_option.text}」。"
        logger.info(f"[Scenario] explain_wrong_option 成功: {explanation[:60]}...")
    except Exception as e:
        logger.error(f"[Scenario] explain_wrong_option 失败: {e}", exc_info=True)
        explanation = f"你选的「{option.text}」不太合适，更推荐的表达是「{correct_option.text}」。"

    # 构造错题记录
    # 取最近一条 NPC 消息作为问题文本
    last_npc_msg = ""
    for m in reversed(state.messages):
        if m.role == MessageType.NPC:
            last_npc_msg = m.content
            break

    wrong_record = WrongOptionRecord(
        record_id=_gen_id("wr"),
        session_id=state.session_id,
        question_text=last_npc_msg,
        selected_option=option.text,
        correct_option=correct_option.text,
        explanation=explanation,
        timestamp=datetime.now(),
    )

    return {"ai_response": explanation, "wrong_record": wrong_record}


# ==================== 8. generate_learning_report - 学习报告 ====================

async def generate_learning_report(state: ScenarioSession) -> dict:
    """生成学习报告：基于完整对话记录调用 LLM 生成结构化报告

    Returns:
        dict: {report: LearningReport, phase: ScenarioPhase.COMPLETED, end_time: datetime}
    """
    config = state.config

    # 构造对话记录文本
    records = []
    for m in state.messages:
        role_label = "用户" if m.role == MessageType.USER else "NPC"
        records.append(f"[{role_label}] {m.content}")
        if m.translation:
            records.append(f"  翻译: {m.translation}")
    conversation_records = "\n".join(records) or "（无对话记录）"

    prompt = get_learning_report_prompt(
        conversation_records=conversation_records,
        config=config,
        wrong_count=len(state.wrong_records),
        fav_count=len(state.favorites),
    )

    # 计算时长
    duration_seconds = 0
    if state.start_time:
        end = state.end_time or datetime.now()
        duration_seconds = int((end - state.start_time).total_seconds())

    try:
        resp = await llm_client.async_chat(
            messages=[{"role": "user", "content": prompt}],
            model="deepseek-chat",
            temperature=0.3,
        )
        result = _parse_json(resp)
        logger.info(f"[Scenario] generate_learning_report 成功")
    except Exception as e:
        logger.error(f"[Scenario] generate_learning_report 失败: {e}", exc_info=True)
        result = {}

    # 综合得分兜底计算（若 LLM 未返回）
    vocab = int(result.get("vocabulary_accuracy", 60))
    culture = int(result.get("culture_mastery", 60))
    grammar = int(result.get("grammar_accuracy", 60))
    fluency = int(result.get("fluency", 60))
    overall = int(result.get("overall_score", (vocab + culture + grammar + fluency) // 4))

    report = LearningReport(
        session_id=state.session_id,
        vocabulary_accuracy=vocab,
        culture_mastery=culture,
        grammar_accuracy=grammar,
        fluency=fluency,
        overall_score=overall,
        overall_summary=result.get("overall_summary", "本次对话已完成，请继续练习以提升熟练度。"),
        strengths=result.get("strengths", []) or [],
        weaknesses=result.get("weaknesses", []) or [],
        improvement_directions=result.get("improvement_directions", []) or [],
        recommended_phrases=result.get("recommended_phrases", []) or [],
        performance_level=result.get("performance_level", "average"),
        message_count=len(state.messages),
        duration_seconds=duration_seconds,
        generated_at=datetime.now(),
    )

    return {
        "report": report,
        "phase": ScenarioPhase.COMPLETED,
        "end_time": datetime.now(),
    }
