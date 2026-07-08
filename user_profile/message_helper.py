"""用户上下文构建helper - 加载用户资料与简历文档，拼装为可注入system message的文本块

客户端使用此模块（依赖 config.settings / user_profile.repository / utils.logger）。
企业端对应 common/user_profile/message_helper.py，逻辑一致但依赖 common 包路径。
"""
from typing import Optional, Tuple

from config.settings import Config
from user_profile.repository import get_user_profile_repo, get_user_document_repo
from utils.logger import logger


def load_user_context_text(user_id: Optional[str]) -> Tuple[str, str]:
    """
    加载用户资料文本与简历文档文本，供拼入大模型system message。

    Args:
        user_id: 用户ID，可为 None

    Returns:
        (user_profile_text, user_docs_text)
        - user_id 为空 / profile 为 None / docs 为空 / 加载异常 时对应项返回 ""
        - 简历每份截取前 Config.USER_DOC_MAX_CHARS_PER_DOC 字（避免token过长）
        - 任何异常仅记 warning 日志，不抛出（不影响主流程）
    """
    if not user_id:
        return ("", "")

    user_profile_text = ""
    user_docs_text = ""

    try:
        # 1. 加载用户资料
        profile = get_user_profile_repo().get_profile(user_id)
        if profile:
            parts = []
            if profile.get("nickname"):
                parts.append(f"姓名：{profile['nickname']}")
            if profile.get("occupation"):
                parts.append(f"职业：{profile['occupation']}")
            if profile.get("industry"):
                parts.append(f"行业：{profile['industry']}")
            if profile.get("experience_years"):
                parts.append(f"工作年限：{profile['experience_years']}")
            if profile.get("skills") and len(profile["skills"]) > 0:
                parts.append(f"技能：{', '.join(profile['skills'])}")
            if profile.get("bio"):
                parts.append(f"个人简介：{profile['bio']}")
            user_profile_text = "\n".join(parts)

        # 2. 加载简历文档内容（仅取解析完成的）
        max_chars = Config.USER_DOC_MAX_CHARS_PER_DOC
        docs = get_user_document_repo().get_user_parsed_texts(user_id)
        if docs:
            doc_parts = []
            for i, text in enumerate(docs, 1):
                truncated = text[:max_chars] + ("...(已截断)" if len(text) > max_chars else "")
                doc_parts.append(f"[简历文档{i}]\n{truncated}")
            user_docs_text = "\n\n".join(doc_parts)

        if user_profile_text or user_docs_text:
            logger.info(
                f"用户上下文已加载: user_id={user_id}, "
                f"profile_len={len(user_profile_text)}, docs_len={len(user_docs_text)}"
            )
    except Exception as e:
        # 加载失败不影响主流程，仅记录警告
        logger.warning(f"加载用户上下文失败（不影响主流程）: user_id={user_id}, error={e}")
        return ("", "")

    return (user_profile_text, user_docs_text)
