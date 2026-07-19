"""情景对话功能 - 状态定义模块

职责：
    定义情景对话功能模块的全局状态结构，包括：
    - 枚举类型（场景阶段、对话模式、难度、场景类别、预设选项类型、消息角色）
    - Pydantic 数据模型（场景配置、智能提示配置/结果、文化提示、策略建议、语言纠错、
      表达润色、预设选项、对话消息、收藏表达、错题记录、学习报告、会话状态）
    - ScenarioSession 主状态对象：贯穿整个工作流的数据载体

设计原则：
    - 所有节点之间传递的数据必须使用 Pydantic 模型，禁止裸 dict
    - 模型字段必须有合理默认值，避免空值异常
    - 列表字段统一使用 Field(default_factory=list) 防止可变默认值共享
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==================== 枚举定义 ====================

class ScenarioPhase(str, Enum):
    """场景会话阶段"""
    SETUP = "setup"               # 已创建未开始
    IN_PROGRESS = "in_progress"   # 进行中
    REPORT = "report"             # 已结束，待生成报告
    COMPLETED = "completed"       # 已生成报告


class DialogueMode(str, Enum):
    """对话模式：自由对话 / 预设选项"""
    FREE_CHOICE = "free_choice"        # 自由对话模式
    PRESET_OPTIONS = "preset_options"  # 预设选项模式


class DifficultyLevel(str, Enum):
    """难度等级"""
    BEGINNER = "beginner"        # 初级：简单词汇
    INTERMEDIATE = "intermediate"  # 中级：日常交流
    ADVANCED = "advanced"        # 高级：复杂表达


class ScenarioCategory(str, Enum):
    """场景类别"""
    DAILY = "daily"      # 日常场景（餐厅、购物、酒店、机场等）
    BUSINESS = "business"  # 商务场景（会议、谈判、接待等）
    TRAVEL = "travel"    # 旅游场景（景点、交通、紧急情况等）
    CUSTOM = "custom"    # 自定义场景


class PresetOptionType(str, Enum):
    """预设选项类型"""
    CORRECT = "correct"    # 标准正确回复
    ADVANCED = "advanced"  # 进阶地道表达
    FUN = "fun"            # 趣味俚语表达
    WRONG = "wrong"        # 常见错误选项


class MessageType(str, Enum):
    """消息角色类型"""
    USER = "user"      # 用户发言
    NPC = "npc"        # NPC角色发言
    SYSTEM = "system"  # 系统消息


# ==================== 配置模型 ====================

class ScenarioConfig(BaseModel):
    """场景配置 - 由用户在配置界面选择"""
    language: str = "en"  # 目标语言代码：zh/en/ja/ko/fr/de/es
    country: str = ""     # 国家/地区（中文名）
    city: str = ""        # 城市（可选，中文名）
    category: ScenarioCategory = ScenarioCategory.DAILY
    scene_key: str = "restaurant"  # 场景标识（如 restaurant/airport/meeting）
    custom_scene_desc: str = ""    # 自定义场景描述（category=CUSTOM 时生效）
    difficulty: DifficultyLevel = DifficultyLevel.INTERMEDIATE
    user_role: str = ""   # 用户扮演的角色（如"游客"）
    npc_role: str = ""    # NPC扮演的角色（如"服务员"）
    mode: DialogueMode = DialogueMode.FREE_CHOICE
    target_language_name: str = "英语"  # 目标语言中文名（用于报告展示）


class SmartAssistConfig(BaseModel):
    """智能提示开关配置"""
    cultural_tip: bool = True             # 文化科普提示
    strategy_guide: bool = True           # 策略引导
    real_time_correction: bool = True     # 实时纠错
    expression_polish: bool = True        # 表达润色


# ==================== 智能提示结果模型 ====================

class CulturalTip(BaseModel):
    """文化提示"""
    title: str = ""
    content: str = ""
    dos: List[str] = Field(default_factory=list)    # 推荐事项
    donts: List[str] = Field(default_factory=list)  # 禁忌事项


class StrategySuggestion(BaseModel):
    """策略回复建议"""
    style: str = ""        # polite/direct/humorous
    style_label: str = ""  # 礼貌型/直接型/幽默型
    text: str = ""         # 建议回复内容


class LanguageCorrection(BaseModel):
    """语言纠错"""
    original: str = ""    # 用户原始表达
    corrected: str = ""   # 纠正后表达
    explanation: str = ""  # 纠错说明
    error_type: str = ""   # grammar/word-choice/spelling


class ExpressionPolish(BaseModel):
    """表达润色"""
    original: str = ""   # 原始表达
    polished: str = ""   # 润色后表达
    note: str = ""       # 润色说明


class SmartAssistResult(BaseModel):
    """智能提示聚合结果 - 一条消息对应的辅助信息"""
    cultural_tips: List[CulturalTip] = Field(default_factory=list)
    strategy_suggestions: List[StrategySuggestion] = Field(default_factory=list)
    corrections: List[LanguageCorrection] = Field(default_factory=list)
    polishes: List[ExpressionPolish] = Field(default_factory=list)


# ==================== 预设选项模型 ====================

class PresetOption(BaseModel):
    """预设对话选项"""
    option_id: str = ""
    type: PresetOptionType = PresetOptionType.CORRECT
    text: str = ""           # 选项文本（目标语言）
    translation: str = ""    # 中文翻译
    explanation: str = ""    # 选项说明
    cultural_note: str = ""  # 背后的文化逻辑


# ==================== 对话消息模型 ====================

class ScenarioMessage(BaseModel):
    """单条对话消息"""
    message_id: str = ""
    role: MessageType = MessageType.USER
    content: str = ""
    language: str = "en"
    translation: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    assist: Optional[SmartAssistResult] = None  # 该条消息附带的智能提示
    preset_options: List[PresetOption] = Field(default_factory=list)  # NPC消息附带选项


# ==================== 学习反馈模型 ====================

class FavoriteExpression(BaseModel):
    """收藏的表达"""
    expression_id: str = ""
    text: str = ""
    context: str = ""
    note: str = ""
    collected_at: datetime = Field(default_factory=datetime.now)


class WrongOptionRecord(BaseModel):
    """错题记录"""
    record_id: str = ""
    session_id: str = ""
    question_text: str = ""
    selected_option: str = ""
    correct_option: str = ""
    explanation: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class LearningReport(BaseModel):
    """学习报告"""
    session_id: str = ""
    vocabulary_accuracy: int = Field(default=0, ge=0, le=100)  # 用词准确度
    culture_mastery: int = Field(default=0, ge=0, le=100)      # 文化礼仪掌握度
    grammar_accuracy: int = Field(default=0, ge=0, le=100)     # 语法准确度
    fluency: int = Field(default=0, ge=0, le=100)              # 流利度
    overall_score: int = Field(default=0, ge=0, le=100)        # 综合得分
    overall_summary: str = ""
    strengths: List[str] = Field(default_factory=list)
    weaknesses: List[str] = Field(default_factory=list)
    improvement_directions: List[str] = Field(default_factory=list)
    recommended_phrases: List[str] = Field(default_factory=list)
    performance_level: str = "average"  # excellent/good/average/below_average/poor
    message_count: int = 0
    duration_seconds: int = 0
    generated_at: datetime = Field(default_factory=datetime.now)


# ==================== 主会话状态 ====================

class ScenarioSession(BaseModel):
    """情景对话会话状态 - 贯穿整个工作流的主数据载体

    由 ScenarioWorkflow.create_session 创建，节点函数读取并修改该对象，
    graph.py 的 _apply() 方法将节点返回的 dict 合并回该对象。
    """
    session_id: str = ""
    user_id: str = ""
    config: ScenarioConfig = Field(default_factory=ScenarioConfig)
    smart_assist: SmartAssistConfig = Field(default_factory=SmartAssistConfig)
    phase: ScenarioPhase = ScenarioPhase.SETUP
    messages: List[ScenarioMessage] = Field(default_factory=list)
    favorites: List[FavoriteExpression] = Field(default_factory=list)
    wrong_records: List[WrongOptionRecord] = Field(default_factory=list)
    current_preset_options: List[PresetOption] = Field(default_factory=list)
    report: Optional[LearningReport] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def add_message(self, m: ScenarioMessage) -> None:
        """追加一条消息并刷新 updated_at"""
        self.messages.append(m)
        self.updated_at = datetime.now()

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """构造喂给 LLM 的对话历史（system 角色由调用方附加）"""
        history: List[Dict[str, str]] = []
        for m in self.messages:
            if m.role == MessageType.USER:
                history.append({"role": "user", "content": m.content})
            elif m.role == MessageType.NPC:
                history.append({"role": "assistant", "content": m.content})
        return history

    def get_progress(self) -> dict:
        """返回当前进度信息（供前端展示）"""
        user_count = sum(1 for m in self.messages if m.role == MessageType.USER)
        npc_count = sum(1 for m in self.messages if m.role == MessageType.NPC)
        duration = 0
        if self.start_time:
            end = self.end_time or datetime.now()
            duration = int((end - self.start_time).total_seconds())
        return {
            "phase": self.phase.value,
            "message_count": len(self.messages),
            "user_message_count": user_count,
            "npc_message_count": npc_count,
            "favorite_count": len(self.favorites),
            "wrong_record_count": len(self.wrong_records),
            "duration_seconds": duration,
            "has_report": self.report is not None,
        }
