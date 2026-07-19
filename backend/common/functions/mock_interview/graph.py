"""模拟面试工作流控制"""
from typing import Dict, Any, Optional
from datetime import datetime
from backend.common.basics.utils.logger import logger
from .state import InterviewState, InterviewPhase, InterviewConfig


class InterviewWorkflow:
    """面试工作流管理器"""

    def __init__(self):
        self.state: Optional[InterviewState] = None

    def create_session(self, user_id: str, config: Dict[str, Any]) -> InterviewState:
        self.state = InterviewState(
            session_id=f"iv_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            user_id=user_id,
            config=InterviewConfig(**config),
            phase=InterviewPhase.SETUP,
            created_at=datetime.now()
        )
        return self.state

    async def start_interview(self) -> InterviewState:
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import init_interview
        updates = await init_interview(self.state)
        self._apply(updates)
        return self.state

    async def submit_answer(self, answer_text: str, question_id: str = "") -> InterviewState:
        """提交回答 - 根据 evaluation_mode 选择逐题评估或仅记录"""
        if not self.state:
            raise ValueError("面试尚未开始")
        mode = self.state.config.evaluation_mode
        if mode == "full_simulation":
            from .nodes import submit_answer_only
            updates = await submit_answer_only(self.state, answer_text, question_id)
        else:
            from .nodes import evaluate_answer
            updates = await evaluate_answer(self.state, answer_text, question_id)
        self._apply(updates)
        return self.state

    async def generate_next_question(self) -> InterviewState:
        if not self.state:
            raise ValueError("面试尚未开始")
        from .nodes import generate_question
        updates = await generate_question(self.state)
        self._apply(updates)
        return self.state

    async def complete_interview(self) -> InterviewState:
        """结束面试 - 全真模拟模式下先批量评估，再生成总结"""
        if not self.state:
            raise ValueError("面试尚未开始")
        # 全真模拟模式：先批量评估所有未评估的回答
        if self.state.config.evaluation_mode == "full_simulation":
            from .nodes import batch_evaluate
            updates = await batch_evaluate(self.state)
            self._apply(updates)
        # 生成总结报告
        from .nodes import generate_summary
        updates = await generate_summary(self.state)
        self._apply(updates)
        return self.state

    def go_to_next_question(self) -> InterviewState:
        if not self.state:
            raise ValueError("面试尚未开始")
        idx = self.state.current_question_index + 1
        if idx >= self.state.config.question_count:
            self.state.current_question_index = idx
            self.state.phase = InterviewPhase.SUMMARY
            return self.state
        self.state.current_question_index = idx
        self.state.current_question = None
        self.state.phase = InterviewPhase.IN_PROGRESS
        return self.state

    def get_state(self) -> Optional[InterviewState]:
        return self.state

    def is_completed(self) -> bool:
        return self.state is not None and self.state.is_completed

    def _apply(self, updates: Dict[str, Any]):
        if not self.state:
            return
        for k, v in updates.items():
            if hasattr(self.state, k):
                setattr(self.state, k, v)
        self.state.updated_at = datetime.now()
