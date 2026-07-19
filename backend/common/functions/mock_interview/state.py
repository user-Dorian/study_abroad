"""模拟面试状态定义"""
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime


class InterviewPhase(str, Enum):
    SETUP = "setup"
    IN_PROGRESS = "in_progress"
    EVALUATION = "evaluation"
    SUMMARY = "summary"
    COMPLETED = "completed"


class DifficultyLevel(str, Enum):
    BASIC = "basic"
    ADVANCED = "advanced"
    CHALLENGE = "challenge"


class QuestionRecord(BaseModel):
    question_id: str
    question_text: str
    dimension: str = "comprehensive"
    difficulty: str = "advanced"
    generated_by_ai: bool = True
    timestamp: datetime = Field(default_factory=datetime.now)


class AnswerRecord(BaseModel):
    answer_id: str
    question_id: str
    answer_text: str
    timestamp: datetime = Field(default_factory=datetime.now)


class EvaluationResult(BaseModel):
    question_id: str
    answer_id: str
    overall_score: int = Field(default=0, ge=0, le=100)
    dimension_scores: Dict[str, int] = Field(default_factory=lambda: {
        "content": 0, "logic": 0, "expression": 0, "depth": 0, "relevance": 0
    })
    ai_feedback: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)
    evaluated_at: datetime = Field(default_factory=datetime.now)


class InterviewConfig(BaseModel):
    school: str = ""
    major: str = ""
    interview_type: str = "academic"  # academic/professional/general
    difficulty: str = "advanced"
    question_count: int = Field(default=3, ge=1, le=10)
    personal_background: str = ""
    # 评估模式：per_question=逐题判分 / full_simulation=全真模拟（全部答完后统一评分）
    evaluation_mode: str = "per_question"


class InterviewState(BaseModel):
    session_id: str = ""
    user_id: str = ""
    config: InterviewConfig = Field(default_factory=InterviewConfig)
    phase: InterviewPhase = InterviewPhase.SETUP
    current_question_index: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    questions: List[QuestionRecord] = Field(default_factory=list)
    answers: List[AnswerRecord] = Field(default_factory=list)
    evaluations: List[EvaluationResult] = Field(default_factory=list)
    conversation_history: List[Dict[str, str]] = Field(default_factory=list)
    current_question: Optional[QuestionRecord] = None
    current_evaluation: Optional[EvaluationResult] = None
    total_score: int = 0
    average_score: float = 0.0
    answered_count: int = 0
    skipped_count: int = 0
    is_completed: bool = False
    summary_report: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def add_question(self, q: QuestionRecord):
        self.questions.append(q)
        self.updated_at = datetime.now()

    def add_answer(self, a: AnswerRecord):
        self.answers.append(a)
        self.answered_count += 1
        self.updated_at = datetime.now()

    def add_evaluation(self, e: EvaluationResult):
        self.evaluations.append(e)
        self.total_score += e.overall_score
        self.average_score = self.total_score / len(self.evaluations)
        self.updated_at = datetime.now()

    def get_progress_percentage(self) -> int:
        if not self.questions:
            return 0
        return int((self.current_question_index / len(self.questions)) * 100)
