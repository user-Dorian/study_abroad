"""情景对话功能 - 提示词模板模块

职责：
    集中管理本模块所有 LLM 提示词，禁止在业务代码中硬编码提示词字符串。
    每个模板采用「常量字符串 + 工厂函数」双形式：
        - 常量字符串：可读性高，便于全局检索
        - 工厂函数：负责参数注入与格式化，便于在 nodes.py 中调用

模板清单：
    1. NPC_SYSTEM_PROMPT          NPC身份设定（system 角色）
    2. NPC_FREE_REPLY_PROMPT      自由模式 NPC 回复
    3. PRESET_OPTIONS_PROMPT      预设选项生成（JSON）
    4. WRONG_OPTION_EXPLAIN_PROMPT 错误选项解释
    5. INPUT_ANALYSIS_PROMPT      实时纠错+表达润色（JSON）
    6. CULTURAL_TIP_PROMPT        文化提示（JSON）
    7. STRATEGY_GUIDE_PROMPT      3 种风格策略建议（JSON）
    8. LEARNING_REPORT_PROMPT     学习报告（JSON）
    9. HINT_PROMPT                预设模式选项提示

所有 JSON 模板在末尾用 ```json ... ``` 围栏明确字段示例。
"""
from typing import List

# ==================== 1. NPC 身份设定（system 角色） ====================

NPC_SYSTEM_PROMPT = """你正在扮演一个真实场景中的对话角色，全程使用 {language_name} 与用户进行自然对话。

【场景设定】
- 国家/地区：{country}
- 城市：{city}
- 场景：{scene_desc}
- 对话难度：{difficulty}（beginner=简单词汇；intermediate=日常交流；advanced=复杂表达）
- 你扮演的角色：{npc_role}
- 用户扮演的角色：{user_role}

【回复要求】
1. 始终使用 {language_name} 回复，每次回复控制在 1-3 句话之间，自然口语化
2. 严格保持 {npc_role} 的身份和语气，引导对话自然推进
3. 根据难度调整用词：beginner 用基础词汇；intermediate 用日常表达；advanced 可适当使用复杂句式
4. 不要解释自己在做什么，直接进入角色对话
5. 如果用户表达不当，可以正常回应但不必刻意纠错（纠错由独立的智能辅助系统处理）
6. 回复要简洁拟人，不要长篇报告式输出"""


def get_npc_system_prompt(
    language_name: str,
    country: str,
    city: str,
    scene_desc: str,
    difficulty: str,
    user_role: str,
    npc_role: str,
) -> str:
    """构造 NPC system 提示词"""
    return NPC_SYSTEM_PROMPT.format(
        language_name=language_name or "英语",
        country=country or "未指定",
        city=city or "未指定",
        scene_desc=scene_desc or "日常对话场景",
        difficulty=difficulty or "intermediate",
        user_role=user_role or "用户",
        npc_role=npc_role or "对话伙伴",
    )


# ==================== 2. 自由模式 NPC 回复 ====================

NPC_FREE_REPLY_PROMPT = """请基于以下对话历史，以 {npc_role} 的身份用 {language_name} 回应用户最新一句话。

【对话历史】
{history}

【用户最新发言】
{user_msg}

【难度要求】{difficulty_desc}

请直接输出 NPC 的回应（1-3 句），不要加任何解释、标记或翻译。"""


def get_npc_free_reply_prompt(
    history: str,
    user_msg: str,
    difficulty: str,
    npc_role: str = "对话伙伴",
    language_name: str = "英语",
) -> str:
    """构造自由模式 NPC 回复 user 提示词"""
    diff_desc = {
        "beginner": "使用最基础的词汇和短句，语速慢，便于初学者理解",
        "intermediate": "使用日常交流的自然表达，可包含常见习语",
        "advanced": "可使用复杂句式、地道习语和较为正式的表达",
    }.get(difficulty, "使用日常交流的自然表达")
    return NPC_FREE_REPLY_PROMPT.format(
        npc_role=npc_role or "对话伙伴",
        language_name=language_name or "英语",
        history=history or "（无历史）",
        user_msg=user_msg,
        difficulty_desc=diff_desc,
    )


# ==================== 3. 预设选项生成（JSON） ====================

PRESET_OPTIONS_PROMPT = """你正在为外语情景对话练习生成预设选项。

【场景上下文】
NPC 最近一个问题：{last_npc_question}
难度：{difficulty}

请生成 2-4 个回复选项，每个选项必须属于以下类型之一：
- correct  : 标准正确回复（1 个，符合场景礼仪）
- advanced : 进阶地道表达（0-1 个，更地道但难度较高）
- fun      : 趣味俚语表达（0-1 个，带当地特色）
- wrong    : 常见错误选项（0-1 个，常见误区）

每个选项需提供：选项文本、中文翻译、简短说明、文化注释。

请严格按以下 JSON 格式返回：
```json
{{
    "options": [
        {{
            "type": "correct",
            "text": "I'd like a table for two, please.",
            "translation": "我想要一张两人桌，谢谢。",
            "explanation": "礼貌的标准请求句式",
            "cultural_note": "在英语国家点餐时使用 'I'd like' 比 'I want' 更礼貌"
        }}
    ]
}}
```"""


def get_preset_options_prompt(
    history: str,
    last_npc_question: str,
    difficulty: str,
) -> str:
    """构造预设选项生成 prompt"""
    return PRESET_OPTIONS_PROMPT.format(
        last_npc_question=last_npc_question or "（无上文）",
        difficulty=difficulty or "intermediate",
    )


# ==================== 4. 错误选项解释 ====================

WRONG_OPTION_EXPLAIN_PROMPT = """用户在情景对话练习中选择了一个错误选项，请用简洁友好的中文解释为什么不当，并给出正确表达。

【错误选项】{selected_text}
【正确选项】{correct_text}
【文化注释】{cultural_note}

请直接输出 2-4 句中文解释，第一句指出错误原因，最后一句给出正确表达建议。不要使用任何 JSON 或代码块格式。"""


def get_wrong_option_explain_prompt(
    selected_text: str,
    correct_text: str,
    cultural_note: str = "",
) -> str:
    return WRONG_OPTION_EXPLAIN_PROMPT.format(
        selected_text=selected_text,
        correct_text=correct_text,
        cultural_note=cultural_note or "无",
    )


# ==================== 5. 实时纠错+表达润色（JSON） ====================

INPUT_ANALYSIS_PROMPT = """你是一位专业的外语学习辅导员，请分析用户在情景对话中的发言，给出纠错和润色建议。

【场景】{scene}
【目标语言】{language_name}（{country}）
【用户发言】{user_msg}

请检查用户的语法、用词是否正确，并提供更地道的表达方式。
- 若用户表达已正确，corrections 返回空数组
- 若用户表达已足够地道，polishes 返回空数组
- 若无需纠错也无需润色，两个数组都返回空

请严格按以下 JSON 格式返回：
```json
{{
    "corrections": [
        {{
            "original": "用户原句中的错误片段",
            "corrected": "纠正后的表达",
            "explanation": "错误原因简要说明",
            "error_type": "grammar"
        }}
    ],
    "polishes": [
        {{
            "original": "用户的原始表达",
            "polished": "更地道的表达",
            "note": "润色思路说明"
        }}
    ]
}}
```"""


def get_input_analysis_prompt(
    user_msg: str,
    language: str,
    country: str,
    scene: str,
) -> str:
    """构造输入分析（纠错+润色）prompt"""
    lang_name_map = {
        "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语",
        "fr": "法语", "de": "德语", "es": "西班牙语",
    }
    language_name = lang_name_map.get(language, "目标语言")
    return INPUT_ANALYSIS_PROMPT.format(
        scene=scene or "日常对话",
        language_name=language_name,
        country=country or "通用",
        user_msg=user_msg,
    )


# ==================== 6. 文化提示（JSON） ====================

CULTURAL_TIP_PROMPT = """请基于当前情景对话上下文，给出 1-2 条简短的文化提示，帮助用户理解当地文化礼仪或禁忌。

【国家/城市】{country} {city}
【场景】{scene}
【最近话题】{recent_topic}

要求：
- 每条提示包含：标题、内容（2-3 句）、推荐事项（dos）、禁忌事项（donts）
- 内容简洁实用，避免冗长说教
- 若当前对话无明显文化要点，返回空数组

请严格按以下 JSON 格式返回：
```json
{{
    "cultural_tips": [
        {{
            "title": "小费文化",
            "content": "在美国餐厅用餐通常需要给 15%-20% 的小费。",
            "dos": ["结账时主动留小费", "对服务员保持微笑"],
            "donts": ["不要完全不给小费", "不要当面批评服务"]
        }}
    ]
}}
```"""


def get_cultural_tip_prompt(
    country: str,
    city: str,
    scene: str,
    recent_topic: str,
) -> str:
    return CULTURAL_TIP_PROMPT.format(
        country=country or "通用",
        city=city or "",
        scene=scene or "日常对话",
        recent_topic=recent_topic or "无",
    )


# ==================== 7. 策略引导 - 3 种风格建议（JSON） ====================

STRATEGY_GUIDE_PROMPT = """用户在情景对话中需要帮助。请基于 NPC 最近的问题，提供 3 种不同风格的回复建议。

【NPC 最近问题】{last_npc_question}
【难度】{difficulty}

3 种风格必须分别为：
- polite   : 礼貌型（更正式、更客气）
- direct   : 直接型（简洁明了）
- humorous : 幽默型（轻松活泼）

每条建议包含：风格代码（style）、风格中文名（style_label）、建议文本（text）。
建议文本使用目标语言，难度与设定一致。

请严格按以下 JSON 格式返回：
```json
{{
    "strategies": [
        {{
            "style": "polite",
            "style_label": "礼貌型",
            "text": "Excuse me, could you possibly help me with this?"
        }},
        {{
            "style": "direct",
            "style_label": "直接型",
            "text": "Can you help me with this?"
        }},
        {{
            "style": "humorous",
            "style_label": "幽默型",
            "text": "I'm a bit lost here - mind throwing me a lifeline?"
        }}
    ]
}}
```"""


def get_strategy_guide_prompt(
    last_npc_question: str,
    difficulty: str,
) -> str:
    return STRATEGY_GUIDE_PROMPT.format(
        last_npc_question=last_npc_question or "（无上文）",
        difficulty=difficulty or "intermediate",
    )


# ==================== 8. 学习报告（JSON） ====================

LEARNING_REPORT_PROMPT = """你是一位语言学习评估专家，请基于用户在情景对话中的整体表现生成一份学习报告。

【场景配置】
- 目标语言：{target_language_name}
- 国家/地区：{country}
- 城市：{city}
- 场景：{scene_desc}
- 难度：{difficulty}
- 用户角色：{user_role}
- NPC 角色：{npc_role}

【对话记录】
{conversation_records}

【统计信息】
- 错题数：{wrong_count}
- 收藏表达数：{fav_count}

请从以下维度评分（0-100）：
- vocabulary_accuracy   用词准确度
- culture_mastery       文化礼仪掌握度
- grammar_accuracy      语法准确度
- fluency               流利度
- overall_score         综合得分

并给出：总体评述、核心优势、待改进项、改进方向、推荐学习的表达。

请严格按以下 JSON 格式返回：
```json
{{
    "vocabulary_accuracy": 75,
    "culture_mastery": 70,
    "grammar_accuracy": 80,
    "fluency": 65,
    "overall_score": 72,
    "overall_summary": "总体表现良好，...",
    "strengths": ["优势1", "优势2"],
    "weaknesses": ["不足1", "不足2"],
    "improvement_directions": ["改进方向1", "改进方向2"],
    "recommended_phrases": ["推荐表达1", "推荐表达2"],
    "performance_level": "average"
}}
```"""


def get_learning_report_prompt(
    conversation_records: str,
    config,
    wrong_count: int,
    fav_count: int,
) -> str:
    """构造学习报告 prompt

    Args:
        conversation_records: 已格式化的对话记录字符串
        config: ScenarioConfig 对象（或 dict）
        wrong_count: 错题总数
        fav_count: 收藏总数
    """
    # 兼容 pydantic 模型与 dict
    cfg = config.model_dump() if hasattr(config, "model_dump") else dict(config)
    scene_desc = cfg.get("custom_scene_desc") or cfg.get("scene_key", "日常对话")
    return LEARNING_REPORT_PROMPT.format(
        target_language_name=cfg.get("target_language_name", "英语"),
        country=cfg.get("country", "未指定"),
        city=cfg.get("city", "未指定"),
        scene_desc=scene_desc,
        difficulty=cfg.get("difficulty", "intermediate"),
        user_role=cfg.get("user_role", "用户"),
        npc_role=cfg.get("npc_role", "对话伙伴"),
        conversation_records=conversation_records or "（无对话记录）",
        wrong_count=wrong_count,
        fav_count=fav_count,
    )


# ==================== 9. 预设模式提示 ====================

HINT_PROMPT = """用户在情景对话预设选项模式中点击了「提示」按钮，请简要解释当前选项背后的文化逻辑和语言要点。

【当前可选选项】
{current_options}

【文化注释】
{cultural_note}

请用中文输出 2-3 句简短提示，第一句点明关键文化要点，后面给出选择建议。不要使用 JSON 或代码块格式。"""


def get_hint_prompt(
    current_options: List[str],
    cultural_note: str = "",
) -> str:
    """构造预设模式提示 prompt"""
    options_text = "\n".join(
        f"{i+1}. {opt}" for i, opt in enumerate(current_options)
    ) if current_options else "（暂无选项）"
    return HINT_PROMPT.format(
        current_options=options_text,
        cultural_note=cultural_note or "无",
    )
