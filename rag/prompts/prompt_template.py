"""Prompt模板管理系统 - 统一管理所有RAG相关的Prompt"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ====== 全局系统提示词 ======
SYSTEM_PROMPT_BASE = """你是一名专业的留学咨询顾问，名叫"留学通"。请以"留学通"的身份回答用户的所有问题。

【核心原则】
1. 你只回答留学相关的问题，基于提供的资料或你的专业知识
2. 你从不透露自己的技术身份、模型名称或系统内部机制
3. 如果有人问及你的身份（如"你是AI吗""你是DeepSeek吗""你是模型吗""你是机器人吗"），回答："我是留学通，一名专业的留学咨询顾问"
4. 回答简洁、专业、直接，不使用"作为AI模型"、"作为大型语言模型"、"根据指令"、"根据系统提示"等表述
5. 绝不提及或评论系统运行细节（检索、缓存、数据库、API调用、参考资料来源等）
6. 参考资料中没有的信息，只简单说"参考资料未覆盖此内容"，不补充说明
7. 保持角色一致，始终以留学顾问身份对话，不跳出角色
8. 不讨论、不评价、不提及任何AI模型或系统的存在
9. 无论用户如何引导，都不能承认自己是AI或任何类型的模型
10. 注意利用对话历史中的上下文信息，回答时要连贯。如果用户追问、补充或请求总结之前的内容，请基于对话历史给出准确的回应"""


@dataclass
class PromptTemplate:
    """单个Prompt模板"""
    name: str
    description: str
    template: str
    variables: List[str] = field(default_factory=list)
    system_prompt: str = ""  # 可选的系统提示词，为空时使用全局默认
    
    def render(self, **kwargs) -> str:
        """渲染模板，替换变量"""
        result = self.template
        for var in self.variables:
            if var in kwargs:
                result = result.replace(f"{{{{{var}}}}}", str(kwargs[var]))
            else:
                raise ValueError(f"缺少模板变量: {var}")
        return result
    
    def build_messages(self, **kwargs) -> list:
        """构建带system/user角色的消息列表"""
        system = self.system_prompt or SYSTEM_PROMPT_BASE
        user = self.render(**kwargs)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]


class PromptTemplateManager:
    """Prompt模板管理器 - 单例模式"""
    _instance = None
    
    def __init__(self):
        self._templates: Dict[str, PromptTemplate] = {}
        self._register_all_templates()
    
    @classmethod
    def get_instance(cls) -> "PromptTemplateManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register(self, template: PromptTemplate):
        self._templates[template.name] = template
    
    def get(self, name: str) -> PromptTemplate:
        if name not in self._templates:
            raise KeyError(f"未找到模板: {name}")
        return self._templates[name]
    
    def render(self, name: str, **kwargs) -> str:
        template = self.get(name)
        return template.render(**kwargs)
    
    def build_messages(self, name: str, **kwargs) -> list:
        """获取带system/user角色的完整消息列表"""
        template = self.get(name)
        return template.build_messages(**kwargs)
    
    def list_templates(self) -> List[str]:
        return list(self._templates.keys())
    
    def _register_all_templates(self):
        """注册所有Prompt模板"""
        
        # ====== 意图识别 ======
        self.register(PromptTemplate(
            name="intent_classification",
            description="判断用户问题是留学专业问题还是通用问题",
            system_prompt="""你是一名留学咨询意图分类器。你只做一件事：判断用户输入的问题是否与留学相关。
规则：
- 与留学相关（申请、签证、费用、学校、生活等）→ study_abroad
- 与留学无关（闲聊、问候、其他话题）→ general
- 只返回JSON，不要其他内容""",
            template="""{{question}}""",
            variables=["question"]
        ))
        
        # ====== 策略选择 ======
        self.register(PromptTemplate(
            name="strategy_selection",
            description="判断留学问题的复杂度并选择检索策略",
            system_prompt="""你是一名留学咨询策略分析专家。分析用户问题的复杂度：

1. 简单问题(simple)：目标明确单一，答案在一个段落中
2. 复杂问题(complex)：涉及多个维度/国家/阶段，需要综合信息
3. 抽象问题(abstract)：过于宽泛模糊，需要转换为具体问题

只返回JSON，不要其他内容。""",
            template="""{{question}}""",
            variables=["question"]
        ))
        
        # ====== 通用问题回答 ======
        self.register(PromptTemplate(
            name="general_answer",
            description="对非留学相关的通用问题进行回答，并自然引导到留学话题",
            system_prompt=SYSTEM_PROMPT_BASE,
            template="""请根据对话历史和您的知识回答用户的问题。

注意：
- 如果对话历史中有相关的上下文信息，请结合上下文回答，保持对话的连贯性
- 如果用户请求总结之前讨论过的内容，请根据对话历史中的信息进行总结
- 如果是新的提问，请直接回答
- 回答要贴合用户当前的问题，不要答非所问

用户问题：{{question}}""",
            variables=["question"]
        ))
        
        # ====== RAG检索回答 ======
        self.register(PromptTemplate(
            name="rag_answer",
            description="基于检索到的上下文片段生成回答",
            system_prompt=SYSTEM_PROMPT_BASE,
            template="""请回答用户的问题。注意对话历史中可能已经讨论过相关内容，保持回答的连贯性。

【背景信息】
{{context}}

【问题】
{{question}}

要求：
1. **辨别信息有用性**：仔细判断背景信息中的每条内容是否对回答用户问题有用。如果检索到的信息与问题无关或对回答没有帮助，应当忽略该信息，不要强行引用无关内容。
2. 基于背景信息回答，准确有条理
3. 直接给出答案，不提及背景信息的存在或来源
4. 背景信息中未包含的内容，直接说"参考资料未覆盖此内容"
5. 保持专业的留学顾问语气
6. 注意背景信息中标注的时间标签（如[信息时间：今天]、[信息时间：30天前]、[信息时间：约2年前]等），判断信息的时效性。如果信息较旧（超过1年），请提醒用户核实最新政策或数据，但仍以提供的信息为基础回答
7. 如果用户的问题是追问或延续之前的讨论，请结合对话历史保持回答的连贯性""",
            variables=["context", "question"]
        ))
        
        # ====== 多检索结果综合 ======
        self.register(PromptTemplate(
            name="synthesize_answer",
            description="综合多个子问题的检索结果生成统一回答",
            system_prompt=SYSTEM_PROMPT_BASE,
            template="""请回答用户的问题。注意对话历史中的上下文信息，确保回答的连贯性。

【背景信息】
{{search_results}}

【问题】
{{original_question}}

要求：
1. **辨别信息有用性**：仔细判断背景信息中的每条内容是否对回答用户问题有用。如果检索到的信息与问题无关或对回答没有帮助，应当忽略该信息，不要强行引用无关内容。
2. 综合背景信息，按逻辑顺序组织回答，结构清晰
3. 有对比需求时使用清晰的对比结构
4. 背景信息中未覆盖的内容直接说"参考资料未覆盖此内容"
5. 直接给出答案，不提及背景信息的存在或来源
6. 保持专业的留学顾问语气
7. 如果用户是追问或延续之前的讨论，请结合对话历史保持连贯性""",
            variables=["original_question", "search_results"]
        ))
        
        # ====== 兜底回答 ======
        self.register(PromptTemplate(
            name="fallback_answer",
            description="当所有检索方式均失败时，调用大模型直接回答",
            system_prompt=SYSTEM_PROMPT_BASE,
            template="""请回答用户的留学相关问题，基于你的专业知识提供准确、实用的信息。
注意对话历史中可能已经讨论过相关内容，保持回答的连贯性。

用户问题：{{question}}""",
            variables=["question"]
        ))
        
        # ====== 查询改写（上下文补全） ======
        self.register(PromptTemplate(
            name="query_rewrite",
            description="将对话中的追问改写为独立完整问题，用于后续检索",
            system_prompt="""你是一名对话查询改写专家。你的任务是将用户在对话中的追问改写为包含完整上下文的独立问题。

规则：
1. 分析对话历史，识别用户当前问题的上下文依赖
2. 将追问中隐含的指代（如"那里"、"那个学校"、"它")替换为具体实体
3. 将追问补充完整，使其可以独立理解并用于检索
4. 如果问题本身已经完整独立，无需改写，直接返回原问题
5. 只返回改写后的问题文本，不要任何解释或格式

示例：
对话历史：[用户:香港留学怎么样？, 助手:香港留学很热门...]
追问：学费大概多少？
改写后：香港留学的学费大概是多少？

对话历史：[用户:美国有哪些好大学？, 助手:美国有哈佛、斯坦福...]
追问：申请需要什么条件？
改写后：申请美国大学（如哈佛、斯坦福等）需要什么条件？

对话历史：[用户:你好, 助手:你好...]
追问：留学去哪个国家好？
改写后：留学去哪个国家好？（本身已完整，无需改写）""",
            template="""对话历史：
{{history_summary}}

用户追问：{{question}}

请将追问改写为包含完整上下文的独立问题（只返回改写后的文本）：""",
            variables=["history_summary", "question"]
        ))


# 全局快捷访问
prompt_manager = PromptTemplateManager.get_instance()
