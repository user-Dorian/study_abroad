"""面试 Prompt 模板 - 复用 rag 模块的 PromptTemplate 结构

提供 4 个核心 prompt：
- generate_questions  : 根据学校/专业/学位生成 5 个英文面试问题
- evaluate_answer     : 评估单个回答，返回 JSON {score, dimensions, feedback}
- generate_report     : 根据所有评分生成中文综合分析报告
- interview_system    : 面试官角色 system prompt（专业、友好、像真实面试官）
"""
from dataclasses import dataclass, field
from typing import Dict, List

# 复用 rag 模块的 PromptTemplate 基类（保持模板风格一致，避免重复造轮子）
from backend.client.functions.rag.prompts import PromptTemplate


# ====== 面试官角色 system prompt ======
INTERVIEWER_SYSTEM_PROMPT = """You are an experienced admissions interviewer for international study abroad programs.
You conduct realistic mock interviews to help students prepare for their target schools and majors.

【Your Style】
- Professional yet friendly, like a real admissions officer
- Ask one question at a time, wait for the student's answer
- Questions should be clear, specific, and relevant to the program
- Cover different dimensions: academic ability, motivation, personal qualities, communication skills
- Use natural English, avoid mechanical or templated phrasing

【Your Goal】
- Help the student practice and improve through realistic interview scenarios
- Provide constructive feedback after each answer
- Generate a comprehensive analysis report at the end

Remember: You are conducting a real-feeling mock interview, be professional and encouraging."""


# ====== 评估员角色 system prompt（用于评估回答） ======
EVALUATOR_SYSTEM_PROMPT = """你是专业的留学面试评估员，负责对学生的面试回答进行客观、专业的评分。

【评分维度】（每项 1-10 分，整数）
- content (内容深度): 回答是否切题、有深度、有具体例子
- logic (逻辑思维): 回答结构是否清晰、论证是否合理
- english (英语表达): 语法、词汇、流利度（基于英文回答）
- depth (个人特质): 是否展现独特性、动机明确、与项目匹配

【评分标准】
- 9-10 分: 卓越，远超预期，有深刻见解和独特表达
- 7-8 分: 良好，达到预期，内容充实逻辑清晰
- 5-6 分: 合格，基本回答了问题，但深度或表达有不足
- 3-4 分: 较弱，回答浅显、跑题或表达困难
- 1-2 分: 很差，几乎未回答或完全跑题

【输出要求】
必须返回严格 JSON 格式，不要有任何额外文字：
{"score": 1-10的整数, "dimensions": {"content": 1-10, "logic": 1-10, "english": 1-10, "depth": 1-10}, "feedback": "中文改进建议，50-150字，具体可操作"}"""


# ====== 报告生成员 system prompt（用于生成综合分析报告） ======
REPORT_SYSTEM_PROMPT = """你是资深的留学面试顾问，负责根据学生在模拟面试中的所有评分和回答，生成一份专业的中文综合分析报告。

【报告要求】
1. 使用中文撰写，专业但易读
2. 结构清晰，包含：总体评价、各维度分析、优势分析、改进建议
3. 评分客观公正，基于具体数据
4. 建议具体可操作，避免空泛
5. 语气鼓励但不浮夸
6. 输出 Markdown 格式（使用 ## 标题、- 列表等）"""


class InterviewPromptManager:
    """面试 Prompt 模板管理器 - 单例模式"""

    _instance = None

    def __init__(self):
        self._templates: Dict[str, PromptTemplate] = {}
        self._register_all_templates()

    @classmethod
    def get_instance(cls) -> "InterviewPromptManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, template: PromptTemplate) -> None:
        self._templates[template.name] = template

    def get(self, name: str) -> PromptTemplate:
        if name not in self._templates:
            raise KeyError(f"未找到面试模板: {name}")
        return self._templates[name]

    def render(self, name: str, **kwargs) -> str:
        return self.get(name).render(**kwargs)

    def build_messages(self, name: str, **kwargs) -> list:
        return self.get(name).build_messages(**kwargs)

    def list_templates(self) -> List[str]:
        return list(self._templates.keys())

    def _register_all_templates(self) -> None:
        """注册所有面试 Prompt 模板"""

        # ====== 1. 生成面试问题 ======
        self.register(PromptTemplate(
            name="generate_questions",
            description="根据学校/专业/学位生成 N 个英文面试问题",
            system_prompt=INTERVIEWER_SYSTEM_PROMPT,
            template="""Please generate {{total_questions}} interview questions for a student applying to:
- School: {{school}}
- Major: {{major}}
- Degree: {{degree}}
- Interview Type: {{interview_type}}

【Requirements】
1. All questions must be in English
2. Cover different dimensions evenly:
   - Academic ability & background (content)
   - Logical thinking & problem-solving (logic)
   - English communication skills (english)
   - Personal qualities & motivation (depth)
3. Questions should be realistic, similar to actual admissions interviews
4. Avoid generic questions like "Tell me about yourself"; be specific to the school and major
5. Each question should be answerable in 2-4 minutes

【Output Format】
Return ONLY a valid JSON array, no other text. Each element must have:
- "dimension": one of ["content", "logic", "english", "depth"]
- "question": the English question text

Example:
[{"dimension": "content", "question": "What specific research area in {{major}} interests you most and why?"}, ...]

Now generate {{total_questions}} questions:""",
            variables=["school", "major", "degree", "interview_type", "total_questions"]
        ))

        # ====== 2. 评估单个回答 ======
        self.register(PromptTemplate(
            name="evaluate_answer",
            description="评估单个面试回答，返回 JSON 评分",
            system_prompt=EVALUATOR_SYSTEM_PROMPT,
            template="""【面试背景】
- 学校: {{school}}
- 专业: {{major}}
- 学位: {{degree}}
- 题目序号: 第 {{question_index}}/{{total_questions}} 题
- 考察维度: {{dimension}}

【面试问题（英文）】
{{question}}

【学生回答】
{{answer}}

【任务】
对学生的回答进行评分。注意：
1. 评分要客观，不要因为鼓励而虚高
2. feedback 必须用中文，具体指出优点和不足
3. dimensions 各项必须为 1-10 的整数
4. score 为四维度平均分四舍五入到整数

只返回 JSON，不要其他文字：
{"score": 整数, "dimensions": {"content": 整数, "logic": 整数, "english": 整数, "depth": 整数}, "feedback": "中文改进建议"}""",
            variables=["school", "major", "degree", "question_index", "total_questions",
                       "dimension", "question", "answer"]
        ))

        # ====== 3. 生成综合分析报告 ======
        self.register(PromptTemplate(
            name="generate_report",
            description="根据所有评分生成中文综合分析报告",
            system_prompt=REPORT_SYSTEM_PROMPT,
            template="""【面试信息】
- 学校: {{school}}
- 专业: {{major}}
- 学位: {{degree}}
- 题目数: {{total_questions}}

【各题评分汇总】
{{scores_summary}}

【各题问答详情】
{{qa_details}}

【统计数据】
- 平均分: {{average_score}} / 10
- 各维度平均分: 内容={{content_avg}}, 逻辑={{logic_avg}}, 英语={{english_avg}}, 个人特质={{depth_avg}}

【任务】
请生成一份完整的中文综合分析报告，使用 Markdown 格式。报告应包含以下部分：

## 总体评价
（2-3段，概括整体表现）

## 各维度分析
### 内容深度
### 逻辑思维
### 英语表达
### 个人特质
（每个维度一段，结合具体题目分析）

## 优势分析
（列出 2-3 个明显优势，结合具体回答）

## 改进建议
（列出 3-5 条具体可操作的建议）

## 备考建议
（针对该校该专业的面试准备建议）

请确保报告专业、客观、有建设性，避免空话套话。""",
            variables=["school", "major", "degree", "total_questions",
                       "scores_summary", "qa_details", "average_score",
                       "content_avg", "logic_avg", "english_avg", "depth_avg"]
        ))

        # ====== 4. 面试官 system prompt（单独可用） ======
        self.register(PromptTemplate(
            name="interview_system_prompt",
            description="面试官角色 system prompt",
            system_prompt=INTERVIEWER_SYSTEM_PROMPT,
            template="",
            variables=[]
        ))


# 全局快捷访问
interview_prompt_manager = InterviewPromptManager.get_instance()
