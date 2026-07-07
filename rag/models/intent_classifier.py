"""意图识别模块 - 判断是留学专业问题还是通用问题"""
from rag.prompts.prompt_template import prompt_manager
from rag.models.llm_client import llm_client
from rag.rag_config import RAGConfig
from utils.logger import logger


class IntentClassifier:
    """意图分类器"""
    
    # 留学专业相关关键词 - 命中则直接判定为留学专业问题
    STUDY_ABROAD_KEYWORDS = [
        "留学", "出国", "申请", "offer", "GPA", "雅思", "托福", "GRE", "GMAT",
        "文书", "推荐信", "CV", "PS", "留学申请", "海外", "美国", "英国", "澳洲",
        "加拿大", "日本", "韩国", "新加坡", "欧洲", "硕士", "博士", "本科", "转学",
        "奖学金", "留学费用", "留学中介", "留学机构", "留学顾问", "留学规划",
        "学校排名", "专业排名", "QS", "US News", "泰晤士", "留学条件", "录取要求",
        "签证", "护照", "语言成绩", "成绩单", "在读证明", "毕业证", "学位证",
        "作品集", "面试", "套磁", "导师", "教授", "研究方向", "留学经验", "案例",
    ]
    
    # 通用问题关键词 - 命中则直接判定为通用问题
    GENERAL_KEYWORDS = [
        "你好", "hello", "hi", "嗨", "谢谢", "再见", "拜拜", "晚安", "在吗",
        "今天", "天气", "时间", "日期", "怎么样", "好不好", "可以吗", "是吗",
        "什么意思", "为什么", "怎么", "如何", "哪里", "哪个", "谁", "多少",
        "介绍一下", "解释一下", "告诉我", "帮我", "推荐", "建议", "比较",
    ]
    
    def classify(self, question: str) -> dict:
        """
        识别用户问题的意图
        
        Args:
            question: 用户问题
            
        Returns:
            {"intent": "study_abroad" | "general", "confidence": float, "reason": str}
        """
        # ====== 快速规则判断：避免不必要的LLM调用 ======
        q_lower = question.lower()
        
        # 检查留学专业关键词
        for keyword in self.STUDY_ABROAD_KEYWORDS:
            if keyword in question:
                logger.info(f"意图识别(规则): 命中留学关键词 '{keyword}'，直接判定为留学专业问题")
                return {
                    "intent": "study_abroad",
                    "confidence": 0.95,
                    "reason": f"命中留学关键词: {keyword}"
                }
        
        # 检查通用问题关键词（短句子）
        if len(question) <= 20:
            for keyword in self.GENERAL_KEYWORDS:
                if keyword in question:
                    logger.info(f"意图识别(规则): 命中通用关键词 '{keyword}'，直接判定为通用问题")
                    return {
                        "intent": "general",
                        "confidence": 0.95,
                        "reason": f"命中通用关键词: {keyword}"
                    }
        
        # ====== LLM意图识别（复杂问题） ======
        try:
            messages = prompt_manager.build_messages("intent_classification", question=question)
            result = llm_client.chat_json(messages=messages, model=RAGConfig.INTENT_MODEL_NAME)
            
            intent = result.get("intent", "general")
            confidence = result.get("confidence", 0.0)
            reason = result.get("reason", "")
            
            if intent not in ["study_abroad", "general"]:
                intent = "general"
            
            logger.info(f"意图识别结果: intent={intent}, confidence={confidence:.2f}, reason={reason}")
            
            return {
                "intent": intent,
                "confidence": confidence,
                "reason": reason
            }
            
        except Exception as e:
            logger.error(f"意图识别失败: {e}")
            return {
                "intent": "general",
                "confidence": 0.0,
                "reason": f"意图识别异常，降级为通用问题: {str(e)}"
            }


intent_classifier = IntentClassifier()
