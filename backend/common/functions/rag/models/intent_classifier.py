"""意图分类器 - 多意图识别系统"""
import json
from typing import List, Optional
from enum import Enum
from dataclasses import dataclass
from backend.common.basics.utils.logger import logger
from .llm_client import llm_client
from ..rag_config import RAGConfig


class IntentEnum(str, Enum):
    """意图枚举类型"""
    STUDY_ABROAD = "study_abroad"  # 留学相关问题
    FORM_FILLING = "form_filling"  # 信息填写
    GENERAL = "general"  # 一般对话


@dataclass
class IntentResult:
    """意图识别结果"""
    intents: List[IntentEnum]
    confidence: float
    raw_response: Optional[dict] = None


class IntentClassifier:
    """意图分类器 - 多意图识别
    
    特性：
    - 支持多意图并行识别
    - 使用LLM进行智能分类
    - 完善的错误处理和降级策略
    """
    
    def __init__(self):
        """初始化意图分类器"""
        self._intent_prompt = """你是意图分类器。分析用户输入，判断属于哪些意图（可多选）：

意图类型：
- study_abroad: 留学相关问题（如申请流程、学校选择、签证、专业等）
- form_filling: 用户透露个人信息（如姓名、年龄、学校、专业、成绩等）
- general: 其他闲聊、问候、不相关话题

判断规则：
1. study_abroad: 提到"留学"、"申请"、"学校"、"签证"、"专业"、"雅思"、"托福"等关键词
2. form_filling: 用户在介绍自己的背景信息，透露年龄、学校、专业、成绩、语言成绩等
3. general: 其他情况

返回JSON格式：
{"intents": ["意图1", "意图2"], "confidence": 0.95}

注意：
- 可以同时有多个意图（如用户在咨询留学问题时透露了自己的背景）
- confidence范围0.0-1.0，表示分类置信度
- 必须返回至少一个意图"""
    
    async def async_classify(self, question: str) -> IntentResult:
        """异步意图识别
        
        Args:
            question: 用户问题
            
        Returns:
            IntentResult: 意图识别结果
        """
        try:
            # 构建消息
            messages = [
                {"role": "system", "content": self._intent_prompt},
                {"role": "user", "content": question}
            ]
            
            # 调用LLM获取JSON响应
            response = await llm_client.async_chat_json(
                messages=messages,
                model=RAGConfig.INTENT_MODEL_NAME,
                temperature=0.0
            )
            
            # 解析意图列表
            intent_strs = response.get('intents', [])
            confidence = response.get('confidence', 0.5)
            
            # 转换为枚举类型
            intents = []
            for intent_str in intent_strs:
                try:
                    if isinstance(intent_str, IntentEnum):
                        intents.append(intent_str)
                    else:
                        intents.append(IntentEnum(intent_str))
                except ValueError:
                    logger.warning(f"未知的意图类型: {intent_str}")
                    # 默认归类为general
                    if IntentEnum.GENERAL not in intents:
                        intents.append(IntentEnum.GENERAL)
            
            # 如果没有识别出意图，默认为general
            if not intents:
                intents = [IntentEnum.GENERAL]
                confidence = 0.5
            
            logger.info(
                f"意图识别完成: question={question[:30]}..., "
                f"intents={[i.value for i in intents]}, confidence={confidence:.2f}"
            )
            
            return IntentResult(
                intents=intents,
                confidence=confidence,
                raw_response=response
            )
            
        except Exception as e:
            logger.error(f"意图识别失败: {e}", exc_info=True)
            # 降级策略：默认为general
            return IntentResult(
                intents=[IntentEnum.GENERAL],
                confidence=0.5
            )
    
    def classify(self, question: str) -> IntentResult:
        """同步意图识别（阻塞调用）
        
        Args:
            question: 用户问题
            
        Returns:
            IntentResult: 意图识别结果
        """
        import asyncio
        return asyncio.run(self.async_classify(question))


# 全局单例
intent_classifier = IntentClassifier()
