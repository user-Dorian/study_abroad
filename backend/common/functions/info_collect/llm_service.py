"""
LLM驱动的信息收集服务
负责：
1. 构建包含表单状态的系统提示词
2. 从用户消息中提取结构化字段
3. 生成自然的AI引导对话
"""

import json
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.functions.info_collect.model import (
    STUDENT_FIELDS_META,
    get_field_schema_text,
    validate_and_convert_field,
    get_missing_fields,
)
from backend.common.functions.rag.models.llm_client import llm_client


# ---------------------------------------------------------------------------
# 系统角色设定——让AI理解自己的任务
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """你是一位专业的留学咨询助手，正在通过友好、自然的对话与用户交流，
逐步收集用户的留学相关信息。

## 你的任务
通过对话自然地引导用户提供留学所需信息，并实时更新表单。

## 对话原则
1. 【AI主动引导】每次对话开始时，你应先主动问候并自然引出第一个问题
2. 【每次只问1个问题】不要连珠炮式提问，给用户轻松的对话体验
3. 【不重复提问】已经填写的信息，绝对不要再次询问
4. 【自然过渡】根据用户的回答，自然地将话题引导到下一个需要补充的字段
5. 【友好专业】保持热情、专业的态度

## 当前表单填写状态
{form_state}

## 需要采集的字段说明
{field_schema}

## 对话历史（最近的对话）
{conversation_history}

## 你的输出格式
你必须以JSON格式输出，包含以下两个字段：
```json
{{
    "ai_message": "你回复用户的自然语言消息，只需文字，不要包含任何其他格式",
    "extracted_fields": {{
        "字段名1": "提取的值1",
        "字段名2": "提取的值2"
    }}
}}
```

## 提取字段的规则
- 从用户刚说的内容中提取对应字段的值
- 如果用户回答中包含多个字段信息，可以同时提取多个
- 只能提取当前对话中出现的字段，不要捏造
- 字段值需要匹配该字段的类型要求（见字段说明）
- 如果用户没有提供任何可提取的信息，extracted_fields请返回空对象

记住：表单中已有的信息就是用户的答案，不要假装不知道。
"""


def _build_form_state(profile: Dict[str, Any]) -> str:
    """构建表单状态文本"""
    if not profile:
        return "尚未采集任何信息"

    filled = []
    for field_name, meta in STUDENT_FIELDS_META.items():
        val = profile.get(field_name)
        if val is not None and str(val).strip() != "":
            filled.append(f"  ✅ {meta['label']}({field_name}): {val}")
        else:
            required = "必填" if meta.get("required") else "选填"
            filled.append(f"  ⬜ {meta['label']}({field_name}): 待填写 [{required}]")

    if not filled:
        return "尚未采集任何信息"
    return "\n".join(filled)


def _build_conversation_context(history: List[Dict[str, str]], max_rounds: int = 6) -> str:
    """构建对话历史上下文

    Args:
        history: 历史消息列表 [{role, content}]
        max_rounds: 保留最近对话轮数

    Returns:
        格式化的对话文本
    """
    if not history:
        return "(暂无对话)"

    recent = history[-(max_rounds * 2):]  # 每轮1问1答

    parts = []
    for msg in recent:
        role = "用户" if msg.get("role") == "user" else "AI助手"
        parts.append(f"  {role}: {msg['content']}")

    return "\n".join(parts)


def _parse_llm_response(response: str) -> Tuple[str, Dict[str, Any]]:
    """解析LLM返回的JSON响应

    Args:
        response: LLM原始响应

    Returns:
        (ai_message, extracted_fields)
    """
    # 尝试提取JSON块
    json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
    if json_match:
        json_str = json_match.group(1)
    else:
        # 尝试直接解析整个响应
        json_str = response

    try:
        data = json.loads(json_str)
        ai_msg = data.get("ai_message", response)
        extracted = data.get("extracted_fields", {})
        return ai_msg, extracted
    except json.JSONDecodeError:
        # 回退：将整个响应作为ai_message
        return response, {}


async def generate_response(
    profile: Dict[str, Any],
    conversation_history: List[Dict[str, str]],
    user_message: str = None,
) -> Tuple[str, Dict[str, Any]]:
    """生成AI响应

    Args:
        profile: 当前已收集的用户信息
        conversation_history: 对话历史
        user_message: 用户刚刚发送的消息（为None表示首次对话）

    Returns:
        (ai_message, extracted_fields)
    """
    # 构建上下文
    form_state = _build_form_state(profile)
    field_schema = get_field_schema_text()
    conv_context = _build_conversation_context(conversation_history)

    # 构建系统消息
    system_msg = SYSTEM_PROMPT_TEMPLATE.format(
        form_state=form_state,
        field_schema=field_schema,
        conversation_history=conv_context,
    )

    # 构建消息列表
    messages = [{"role": "system", "content": system_msg}]
    if user_message:
        messages.append({"role": "user", "content": user_message})

    logger.info(f"调用LLM生成响应: profile_fields={len(profile)}, history_len={len(conversation_history)}")

    try:
        response = await llm_client.async_chat(
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )

        ai_message, extracted_fields = _parse_llm_response(response)

        # 验证并转换提取的字段
        validated = {}
        for field_name, value in extracted_fields.items():
            if field_name in STUDENT_FIELDS_META:
                converted, error = validate_and_convert_field(field_name, value)
                if error:
                    logger.warning(f"字段验证失败: {field_name}={value}, error={error}")
                else:
                    validated[field_name] = converted
                    logger.info(f"提取字段: {field_name}={converted}")

        return ai_message, validated

    except Exception as e:
        logger.error(f"LLM调用失败: {e}", exc_info=True)
        # 兜底响应
        if user_message:
            return "好的，我记下了。还有什么想告诉我的吗？", {}
        else:
            return get_welcome_message(), {}


def get_welcome_message() -> str:
    """获取AI首次问候语"""
    return "你好！我是留学通助手，很高兴为你服务！😊 为了给你提供更精准的留学建议，我先简单了解一下你的情况。请问你叫什么名字呢？"


def get_missing_fields_text(fields: List[Dict]) -> str:
    """获取缺失字段的提示文本"""
    if not fields:
        return "所有信息已收集完毕！"

    required = [f for f in fields if f.get("required")]
    if required:
        names = [f["label"] for f in required[:3]]
        return f"还需要补充: {'、'.join(names)}"
    return "信息基本完整，如有更多信息欢迎补充。"
