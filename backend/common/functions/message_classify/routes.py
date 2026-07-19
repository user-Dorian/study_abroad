"""F-5 智能消息分类 API 路由"""
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.common.basics.utils.auth import require_user
from backend.common.basics.utils.logger import logger

router = APIRouter(prefix="/api/messages", tags=["message_classify"])


class ClassifyItem(BaseModel):
    id: Optional[str] = None
    content: str
    sender: Optional[str] = None


class ClassifyRequest(BaseModel):
    messages: List[ClassifyItem]


def _keyword_classify(content: str) -> dict:
    """基于关键词的快速分类（降级方案）"""
    if not content:
        return {"category": "其他", "priority": 5, "confidence": 0.5}

    urgent_words = ["紧急", "急", "马上", "立即", "催", "尽快", "立刻", "asap"]
    consult_words = ["请问", "咨询", "怎么", "如何", "吗", "?", "？", "能不能", "可以"]
    notify_words = ["通知", "公告", "提醒", "截止", "已", "完成", "安排", "确认"]
    chat_words = ["哈哈", "好的", "嗯", "哦", "谢谢", "感谢", "收到", "👍", "😊", "你好"]

    if any(w in content for w in urgent_words):
        return {"category": "紧急", "priority": 1, "confidence": 0.7}
    if any(w in content for w in notify_words):
        return {"category": "通知", "priority": 3, "confidence": 0.6}
    if any(w in content for w in consult_words):
        return {"category": "咨询", "priority": 2, "confidence": 0.65}
    if any(w in content for w in chat_words):
        return {"category": "闲聊", "priority": 5, "confidence": 0.6}
    return {"category": "其他", "priority": 4, "confidence": 0.4}


@router.post("/classify")
async def classify_messages(req: ClassifyRequest, current_user: dict = Depends(require_user)):
    """批量分类消息（本地实现，AI 降级到关键词）"""
    results = []
    for msg in req.messages:
        try:
            # 先尝试 LLM 分类（如果可用）
            classified = None
            try:
                from client.rag.models.llm_client import llm_client
                from client.rag.prompts.prompt_template import prompt_manager
                messages = prompt_manager.build_messages("classify_message", content=msg.content)
                import json
                response = llm_client.chat(messages=messages, model="deepseek-chat", temperature=0.1, max_tokens=128)
                # 解析 JSON
                response_text = response.strip() if isinstance(response, str) else str(response)
                start = response_text.find("{")
                end = response_text.rfind("}")
                if start >= 0 and end > start:
                    parsed = json.loads(response_text[start:end + 1])
                    classified = {
                        "category": parsed.get("category", "其他"),
                        "priority": int(parsed.get("priority", 4)),
                        "confidence": 0.9,
                    }
            except Exception as llm_err:
                logger.debug(f"[Classify] LLM分类失败,降级到关键词: {llm_err}")
                classified = None

            if not classified:
                classified = _keyword_classify(msg.content)

            results.append({
                "id": msg.id,
                "content": msg.content[:50] + ("..." if len(msg.content) > 50 else ""),
                "sender": msg.sender,
                "category": classified["category"],
                "priority": classified["priority"],
                "confidence": classified.get("confidence", 0.5),
            })
        except Exception as e:
            logger.warning(f"[Classify] 单条分类失败: {e}")
            results.append({
                "id": msg.id, "content": msg.content[:50],
                "category": "其他", "priority": 5, "confidence": 0.0,
            })
    return results


@router.post("/classify-single")
async def classify_single(msg: ClassifyItem, current_user: dict = Depends(require_user)):
    """单条消息分类"""
    result = _keyword_classify(msg.content)
    result["id"] = msg.id
    result["content"] = msg.content
    return result
