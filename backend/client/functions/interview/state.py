"""面试状态定义 - 各节点之间数据传递的 Pydantic 表单

定义模拟面试全流程共享的状态结构：
- InterviewState : 面试会话整体状态
- QuestionItem   : 单个面试题目
- ScoreDetail    : 单题评分细节
- InterviewConfig: 面试配置（启动参数）
"""
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ====== 支持的面试类型 / 学位层次 ======
INTERVIEW_TYPES = ["admission", "visa", "scholarship"]
DEGREE_LEVELS = ["本科", "硕士", "博士"]


class InterviewConfig(BaseModel):
    """面试配置（用户启动面试时填写的参数）"""
    school: str = Field(..., description="目标院校，如 MIT")
    major: str = Field(..., description="目标专业，如 Computer Science")
    degree: str = Field("硕士", description="学位层次：本科/硕士/博士")
    interview_type: str = Field("admission", description="面试类型：admission/visa/scholarship")
    total_questions: int = Field(5, ge=1, le=10, description="问题总数")


class QuestionItem(BaseModel):
    """单个面试题目"""
    index: int = Field(0, description="题目序号，从0开始")
    dimension: str = Field("", description="题目考察维度：content/logic/english/depth")
    question: str = Field("", description="英文问题文本")


class ScoreDetail(BaseModel):
    """单题评分细节（四维度）"""
    content: int = Field(0, ge=0, le=10, description="内容深度 0-10")
    logic: int = Field(0, ge=0, le=10, description="逻辑思维 0-10")
    english: int = Field(0, ge=0, le=10, description="英语表达 0-10")
    depth: int = Field(0, ge=0, le=10, description="个人特质 0-10")


class QuestionScore(BaseModel):
    """单题完整评分"""
    question_index: int = Field(0, description="对应题目序号")
    question: str = Field("", description="题目文本")
    answer: str = Field("", description="用户回答")
    score: int = Field(0, ge=0, le=10, description="总分 0-10")
    dimensions: ScoreDetail = Field(default_factory=ScoreDetail, description="四维度评分")
    feedback: str = Field("", description="改进建议（中文）")


class InterviewState(BaseModel):
    """面试会话状态 - 所有节点共享的数据结构

    生命周期：
    1. start_interview_node 创建状态，生成问题列表
    2. ask_question_node 流式输出当前问题
    3. receive_answer_node 接收用户回答
    4. evaluate_answer_node 评估当前回答
    5. complete_interview_node 生成分析报告
    """
    # ====== 标识 ======
    interview_id: str = Field("", description="面试会话唯一ID")
    user_id: str = Field("", description="用户ID")

    # ====== 配置 ======
    school: str = Field("", description="目标院校")
    major: str = Field("", description="目标专业")
    degree: str = Field("硕士", description="学位层次")
    interview_type: str = Field("admission", description="面试类型")

    # ====== 进度 ======
    current_question_index: int = Field(0, description="当前题目序号(0-based)")
    total_questions: int = Field(5, description="题目总数")

    # ====== 内容 ======
    questions: List[QuestionItem] = Field(default_factory=list, description="题目列表")
    answers: List[str] = Field(default_factory=list, description="用户回答列表(按题目顺序)")
    scores: List[QuestionScore] = Field(default_factory=list, description="每题评分列表")

    # ====== 状态 ======
    status: str = Field("pending", description="状态：pending/in_progress/completed/analyzing")
    started_at: Optional[datetime] = Field(None, description="开始时间")
    completed_at: Optional[datetime] = Field(None, description="完成时间")
    analysis_report: Optional[str] = Field(None, description="综合分析报告（中文）")

    # ====== 错误处理 ======
    errors: List[str] = Field(default_factory=list, description="错误信息列表")
    node_execution_path: List[str] = Field(default_factory=list, description="节点执行路径")

    def add_error(self, error: str) -> None:
        """添加错误信息"""
        self.errors.append(error)

    def add_node_to_path(self, node_name: str) -> None:
        """记录节点执行路径"""
        self.node_execution_path.append(node_name)

    @property
    def is_last_question(self) -> bool:
        """当前问题是否是最后一题"""
        return self.current_question_index >= self.total_questions - 1

    @property
    def progress_percent(self) -> int:
        """进度百分比"""
        if self.total_questions <= 0:
            return 0
        answered = len(self.answers)
        return int(answered / self.total_questions * 100)

    def get_average_score(self) -> float:
        """计算已评分题目的平均分"""
        if not self.scores:
            return 0.0
        return sum(s.score for s in self.scores) / len(self.scores)

    def get_dimension_average(self) -> Dict[str, float]:
        """计算各维度平均分"""
        if not self.scores:
            return {"content": 0.0, "logic": 0.0, "english": 0.0, "depth": 0.0}
        return {
            "content": sum(s.dimensions.content for s in self.scores) / len(self.scores),
            "logic": sum(s.dimensions.logic for s in self.scores) / len(self.scores),
            "english": sum(s.dimensions.english for s in self.scores) / len(self.scores),
            "depth": sum(s.dimensions.depth for s in self.scores) / len(self.scores),
        }


class NodeResult(BaseModel):
    """节点执行结果"""
    success: bool = Field(..., description="执行是否成功")
    state: InterviewState = Field(..., description="更新后的状态")
    message: str = Field("", description="执行消息")
    should_continue: bool = Field(True, description="是否继续执行下一个节点")
