"""策略选择模块 - 判断问题复杂度并选择检索策略"""
from typing import List
from client.rag.prompts.prompt_template import prompt_manager
from common.rag.models.llm_client import llm_client
from common.rag.rag_config import RAGConfig
from common.utils.logger import logger


class StrategySelector:
    """策略选择器"""
    
    # 复杂问题关键词 - 命中则判定为复杂问题
    COMPLEX_KEYWORDS = [
        "哪些", "哪些学校", "哪些专业", "多个", "对比", "比较", "和", "与", "以及",
        "区别", "差异", "不同", "优缺点", "各有什么", "分别是", "各自",
        "排名", "top", "前", "最好", "最适合", "性价比", "综合",
    ]
    
    # 抽象问题关键词 - 命中则判定为抽象问题
    ABSTRACT_KEYWORDS = [
        "如何", "怎么", "怎样", "方法", "技巧", "攻略", "流程", "步骤",
        "建议", "意见", "经验", "心得", "总结", "指南", "规划",
        "趋势", "前景", "未来", "发展", "方向", "选择",
    ]
    
    def analyze(self, question: str) -> dict:
        """
        分析问题复杂度并返回检索策略
        
        Args:
            question: 用户问题
            
        Returns:
            {
                "complexity": "simple" | "complex" | "abstract",
                "confidence": float,
                "sub_questions": List[str],
                "reason": str
            }
        """
        # ====== 快速规则判断：避免不必要的LLM调用 ======
        
        # 短问题直接判定为简单问题
        if len(question) <= 15:
            logger.info(f"策略分析(规则): 短问题({len(question)}字)，直接判定为简单问题")
            return {
                "complexity": "simple",
                "confidence": 0.95,
                "sub_questions": [],
                "reason": f"问题长度较短({len(question)}字)，按简单问题处理"
            }
        
        # 检查复杂问题关键词
        for keyword in self.COMPLEX_KEYWORDS:
            if keyword in question:
                logger.info(f"策略分析(规则): 命中复杂问题关键词 '{keyword}'，直接判定为复杂问题")
                return {
                    "complexity": "complex",
                    "confidence": 0.90,
                    "sub_questions": [],
                    "reason": f"命中复杂问题关键词: {keyword}"
                }
        
        # 检查抽象问题关键词
        for keyword in self.ABSTRACT_KEYWORDS:
            if keyword in question:
                logger.info(f"策略分析(规则): 命中抽象问题关键词 '{keyword}'，直接判定为抽象问题")
                return {
                    "complexity": "abstract",
                    "confidence": 0.90,
                    "sub_questions": [],
                    "reason": f"命中抽象问题关键词: {keyword}"
                }
        
        # ====== LLM策略分析（复杂问题） ======
        try:
            messages = prompt_manager.build_messages("strategy_selection", question=question)
            result = llm_client.chat_json(messages=messages, model=RAGConfig.STRATEGY_MODEL_NAME)
            
            complexity = result.get("complexity", "simple")
            confidence = result.get("confidence", 0.0)
            sub_questions = result.get("sub_questions", [])
            reason = result.get("reason", "")
            
            if complexity not in ["simple", "complex", "abstract"]:
                complexity = "simple"
            
            if not isinstance(sub_questions, list):
                sub_questions = []
            
            logger.info(
                f"策略分析结果: complexity={complexity}, "
                f"confidence={confidence:.2f}, "
                f"sub_questions={len(sub_questions)}"
            )
            
            return {
                "complexity": complexity,
                "confidence": confidence,
                "sub_questions": sub_questions,
                "reason": reason
            }
            
        except Exception as e:
            logger.error(f"策略选择失败: {e}")
            return {
                "complexity": "simple",
                "confidence": 0.0,
                "sub_questions": [],
                "reason": f"策略选择异常，降级为简单问题: {str(e)}"
            }
    
    def get_query_list(self, question: str, strategy: dict) -> List[str]:
        """
        根据策略获取需要检索的查询列表
        
        Args:
            question: 原始问题
            strategy: 策略分析结果
            
        Returns:
            查询列表
        """
        complexity = strategy["complexity"]
        
        if complexity == "simple":
            # 简单问题：直接使用原问题
            return [question]
        elif complexity == "complex":
            # 复杂问题：使用拆解后的子问题
            sub_qs = strategy.get("sub_questions", [])
            if sub_qs:
                return sub_qs
            return [question]
        elif complexity == "abstract":
            # 抽象问题：使用转换后的精确问题
            sub_qs = strategy.get("sub_questions", [])
            if sub_qs:
                return sub_qs
            return [question]
        
        return [question]


strategy_selector = StrategySelector()
