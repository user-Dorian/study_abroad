"""情景对话功能 - 工作流控制模块

职责：
    封装 ScenarioWorkflow 类，作为外部（routes.py）调用情景对话功能的统一入口。
    - 维护 ScenarioSession 状态对象
    - 串行调度 nodes.py 中的节点函数
    - 将节点返回的 dict 合并回 state（_apply）
    - 暴露高层 API：开始/结束场景、自由模式收发、预设模式请求/选择、收藏、报告等

设计原则：
    - 所有方法在 state 为 None 时抛 ValueError("会话未创建")
    - 节点函数返回 dict 后立即 _apply 合并，避免状态不一致
    - 智能辅助结果按消息角色分别附加到 user_message.assist 和 npc_message.assist
"""
import uuid
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.common.basics.utils.logger import logger

from .state import (
    FavoriteExpression,
    LearningReport,
    MessageType,
    PresetOption,
    PresetOptionType,
    ScenarioConfig,
    ScenarioMessage,
    ScenarioPhase,
    ScenarioSession,
    SmartAssistConfig,
    SmartAssistResult,
    WrongOptionRecord,
)


class ScenarioWorkflow:
    """情景对话工作流管理器

    使用方式：
        wf = ScenarioWorkflow()
        wf.create_session(user_id, config_dict, smart_assist_dict)
        await wf.start_scenario()
        state = await wf.send_free_message("Hello")
    """

    def __init__(self):
        self.state: Optional[ScenarioSession] = None

    # ==================== 会话管理 ====================

    def create_session(
        self,
        user_id: str,
        config: Dict[str, Any],
        smart_assist: Optional[Dict[str, Any]] = None,
    ) -> ScenarioSession:
        """创建新的场景会话

        Args:
            user_id: 用户ID
            config: 场景配置 dict（会被解析为 ScenarioConfig）
            smart_assist: 智能提示配置 dict（可选）

        Returns:
            ScenarioSession: 初始化后的会话状态
        """
        session_id = f"sc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        # 兼容输入：difficulty/mode/category 既支持字符串也支持枚举值
        cfg = ScenarioConfig(**(config or {}))
        sa = SmartAssistConfig(**(smart_assist or {}))
        self.state = ScenarioSession(
            session_id=session_id,
            user_id=user_id,
            config=cfg,
            smart_assist=sa,
            phase=ScenarioPhase.SETUP,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        logger.info(f"[ScenarioWorkflow] 创建会话: session_id={session_id}, user={user_id}")
        return self.state

    async def start_scenario(self) -> ScenarioSession:
        """开始场景：调用 init_scenario 构造 NPC 开场白"""
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import init_scenario
        updates = await init_scenario(self.state)
        self._apply(updates)
        logger.info(f"[ScenarioWorkflow] 场景已开始: session_id={self.state.session_id}")
        return self.state

    async def end_scenario(self) -> ScenarioSession:
        """结束场景：调用 generate_learning_report 生成学习报告"""
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import generate_learning_report
        # 先标记 end_time 进入 report 阶段（节点内部也会设置 end_time）
        self.state.phase = ScenarioPhase.REPORT
        updates = await generate_learning_report(self.state)
        self._apply(updates)
        logger.info(f"[ScenarioWorkflow] 场景已结束: session_id={self.state.session_id}")
        return self.state

    # ==================== 自由对话模式 ====================

    async def send_free_message(self, user_text: str) -> ScenarioSession:
        """自由模式非流式：用户发送消息 → 获取 NPC 回复

        流程（串行）：
        1. 写入用户消息（先写入以便 LLM 看到上下文）
        2. analyze_user_input → 纠错+润色，附加到 user_message.assist
        3. npc_reply_free → NPC 回复
        4. generate_smart_assist → 文化提示+策略建议，附加到 npc_message.assist
        """
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import analyze_user_input, generate_smart_assist, npc_reply_free

        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("消息不能为空")

        # 1. 写入用户消息
        user_message = ScenarioMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            role=MessageType.USER,
            content=user_text,
            language=self.state.config.language,
            timestamp=datetime.now(),
        )
        self.state.add_message(user_message)

        # 2. 实时纠错+润色（附加到 user_message.assist）
        analyze_updates = await analyze_user_input(self.state, user_text)
        corrections = analyze_updates.get("corrections", []) or []
        polishes = analyze_updates.get("polishes", []) or []
        user_message.assist = SmartAssistResult(
            corrections=corrections,
            polishes=polishes,
        )

        # 3. NPC 回复
        reply_updates = await npc_reply_free(self.state, user_text)
        new_message: Optional[ScenarioMessage] = reply_updates.get("new_message")
        # npc_reply_free 内部已经把 NPC 消息 add_message 到 state 了
        if new_message is None:
            # 兜底：从 state 末尾取
            new_message = self.state.messages[-1] if self.state.messages else None

        # 4. 智能辅助（文化提示+策略建议），附加到 NPC 消息的 assist
        assist_updates = await generate_smart_assist(self.state, user_text)
        cultural_tips = assist_updates.get("cultural_tips", []) or []
        strategy_suggestions = assist_updates.get("strategy_suggestions", []) or []
        if new_message is not None:
            new_message.assist = SmartAssistResult(
                cultural_tips=cultural_tips,
                strategy_suggestions=strategy_suggestions,
            )

        self.state.updated_at = datetime.now()
        logger.info(
            f"[ScenarioWorkflow] 自由消息处理完成: session_id={self.state.session_id}, "
            f"corrections={len(corrections)}, polishes={len(polishes)}, "
            f"tips={len(cultural_tips)}, strategies={len(strategy_suggestions)}"
        )
        return self.state

    async def stream_free_reply(self, user_text: str) -> AsyncIterator[str]:
        """自由模式流式版：先非流式跑分析+智能辅助，再流式产出 NPC 回复 token

        使用方式：
            async for chunk in wf.stream_free_reply("hello"):
                print(chunk, end="")

        说明：
            - 用户消息和智能辅助结果在调用本方法时即写入 state
            - NPC 回复流式产出，结束后才将完整消息写入 state
        """
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import analyze_user_input, generate_smart_assist, npc_reply_free_stream

        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("消息不能为空")

        # 1. 写入用户消息
        user_message = ScenarioMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            role=MessageType.USER,
            content=user_text,
            language=self.state.config.language,
            timestamp=datetime.now(),
        )
        self.state.add_message(user_message)

        # 2. 非流式：分析输入（纠错+润色）
        analyze_updates = await analyze_user_input(self.state, user_text)
        corrections = analyze_updates.get("corrections", []) or []
        polishes = analyze_updates.get("polishes", []) or []
        user_message.assist = SmartAssistResult(
            corrections=corrections,
            polishes=polishes,
        )

        # 3. 非流式：生成智能辅助（文化提示+策略建议）- 暂存，待 NPC 消息就绪后附加
        assist_updates = await generate_smart_assist(self.state, user_text)
        cultural_tips = assist_updates.get("cultural_tips", []) or []
        strategy_suggestions = assist_updates.get("strategy_suggestions", []) or []
        pending_assist = SmartAssistResult(
            cultural_tips=cultural_tips,
            strategy_suggestions=strategy_suggestions,
        )

        # 4. 流式产出 NPC 回复 token
        # 注意：npc_reply_free_stream 内部会在流结束后把完整消息写入 state.messages
        # 我们需要把 pending_assist 附加到该消息上
        async for chunk in npc_reply_free_stream(self.state, user_text):
            yield chunk

        # 流结束后，从 state 末尾取出 NPC 消息，附加智能辅助
        if self.state.messages and self.state.messages[-1].role == MessageType.NPC:
            self.state.messages[-1].assist = pending_assist

        self.state.updated_at = datetime.now()
        logger.info(
            f"[ScenarioWorkflow] 流式回复完成: session_id={self.state.session_id}, "
            f"corrections={len(corrections)}, tips={len(cultural_tips)}"
        )

    # ==================== 预设选项模式 ====================

    async def request_preset_options(self) -> ScenarioSession:
        """预设模式：NPC 先提问（调用 npc_reply_free 生成问题），再生成预设选项

        Returns:
            ScenarioSession: 当前会话状态，state.current_preset_options 已填充
        """
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import generate_preset_options, npc_reply_free

        # 让 NPC 主动提问（用空字符串提示 NPC 继续推进对话）
        # 这里传入一个引导性提示词让 NPC 主动提问
        guide_text = "(请主动向用户提出一个与场景相关的问题)"
        reply_updates = await npc_reply_free(self.state, guide_text)
        npc_question = reply_updates.get("ai_response", "")

        # 生成预设选项
        opt_updates = await generate_preset_options(self.state, npc_question)
        self._apply(opt_updates)

        # 把选项也附加到最后一条 NPC 消息上，便于前端渲染
        if self.state.messages and self.state.messages[-1].role == MessageType.NPC:
            self.state.messages[-1].preset_options = list(self.state.current_preset_options)

        logger.info(
            f"[ScenarioWorkflow] 预设选项生成: session_id={self.state.session_id}, "
            f"options={len(self.state.current_preset_options)}"
        )
        return self.state

    async def select_preset_option(self, option_id: str) -> ScenarioSession:
        """预设模式：用户选择某个选项

        - correct/advanced/fun → 推进对话（NPC 简短回应）
        - wrong → 调用 explain_wrong_option 解释 + 记录错题

        Args:
            option_id: 用户选择的选项ID
        """
        if not self.state:
            raise ValueError("会话未创建")
        from .nodes import explain_wrong_option, npc_reply_free

        # 查找被选选项
        selected: Optional[PresetOption] = None
        for opt in self.state.current_preset_options:
            if opt.option_id == option_id:
                selected = opt
                break
        if selected is None:
            raise ValueError(f"找不到选项: {option_id}")

        # 写入用户消息（用户选择的选项文本作为发言）
        user_message = ScenarioMessage(
            message_id=f"msg_{uuid.uuid4().hex[:8]}",
            role=MessageType.USER,
            content=selected.text,
            language=self.state.config.language,
            translation=selected.translation,
            timestamp=datetime.now(),
        )
        self.state.add_message(user_message)

        if selected.type == PresetOptionType.WRONG:
            # 错误选项：找正确选项 + 调 explain_wrong_option
            correct_opt = next(
                (o for o in self.state.current_preset_options if o.type == PresetOptionType.CORRECT),
                PresetOption(
                    option_id="fallback",
                    type=PresetOptionType.CORRECT,
                    text="(标准回复)",
                    translation="",
                    explanation="",
                    cultural_note="",
                ),
            )
            explain_updates = await explain_wrong_option(self.state, selected, correct_opt)
            wrong_record: Optional[WrongOptionRecord] = explain_updates.get("wrong_record")
            if wrong_record is not None:
                self.state.wrong_records.append(wrong_record)
            explanation = explain_updates.get("ai_response", "")

            # 把解释作为 NPC 回复写入
            npc_msg = ScenarioMessage(
                message_id=f"msg_{uuid.uuid4().hex[:8]}",
                role=MessageType.NPC,
                content=explanation,
                language="zh",  # 解释用中文
                translation="",
                timestamp=datetime.now(),
            )
            self.state.add_message(npc_msg)
            logger.info(f"[ScenarioWorkflow] 错题已记录: session_id={self.state.session_id}")
        else:
            # 正确/进阶/趣味选项：NPC 简短回应推进对话
            await npc_reply_free(self.state, selected.text)
            logger.info(
                f"[ScenarioWorkflow] 选项已接受({selected.type.value}): "
                f"session_id={self.state.session_id}"
            )

        # 清空当前选项（已使用）
        self.state.current_preset_options = []
        self.state.updated_at = datetime.now()
        return self.state

    async def get_hint(self) -> dict:
        """获取当前预设选项的提示（文化逻辑和语言要点）"""
        if not self.state:
            raise ValueError("会话未创建")
        from .prompts import get_hint_prompt

        # 收集当前选项文本
        option_texts = [opt.text for opt in self.state.current_preset_options]
        cultural_note = ""
        for opt in self.state.current_preset_options:
            if opt.cultural_note:
                cultural_note = opt.cultural_note
                break

        prompt = get_hint_prompt(option_texts, cultural_note)
        try:
            from backend.common.functions.rag.models.llm_client import llm_client as _llm
            resp = await _llm.async_chat(
                messages=[{"role": "user", "content": prompt}],
                model="deepseek-chat",
                temperature=0.4,
            )
            hint = (resp or "").strip()
            if not hint:
                hint = "建议选择更符合场景礼仪的标准回复，注意当地的文化习惯。"
        except Exception as e:
            logger.error(f"[ScenarioWorkflow] get_hint 失败: {e}", exc_info=True)
            hint = "建议选择更符合场景礼仪的标准回复，注意当地的文化习惯。"

        return {
            "hint": hint,
            "current_options": [opt.model_dump() for opt in self.state.current_preset_options],
        }

    # ==================== 学习反馈 ====================

    def add_favorite(self, text: str, context: str = "", note: str = "") -> FavoriteExpression:
        """收藏一条表达"""
        if not self.state:
            raise ValueError("会话未创建")
        fav = FavoriteExpression(
            expression_id=f"fav_{uuid.uuid4().hex[:8]}",
            text=text,
            context=context,
            note=note,
            collected_at=datetime.now(),
        )
        self.state.favorites.append(fav)
        self.state.updated_at = datetime.now()
        logger.info(f"[ScenarioWorkflow] 收藏表达: session_id={self.state.session_id}")
        return fav

    def list_favorites(self) -> List[FavoriteExpression]:
        """获取收藏列表"""
        if not self.state:
            raise ValueError("会话未创建")
        return list(self.state.favorites)

    def list_wrong_records(self) -> List[WrongOptionRecord]:
        """获取错题列表"""
        if not self.state:
            raise ValueError("会话未创建")
        return list(self.state.wrong_records)

    def get_report(self) -> Optional[LearningReport]:
        """获取学习报告（若已生成）"""
        if not self.state:
            raise ValueError("会话未创建")
        return self.state.report

    def update_smart_assist(self, cfg: Dict[str, Any]) -> SmartAssistConfig:
        """更新智能提示开关配置"""
        if not self.state:
            raise ValueError("会话未创建")
        # 部分更新：只更新 cfg 中提供的字段
        current = self.state.smart_assist.model_dump()
        current.update({k: v for k, v in (cfg or {}).items() if k in current})
        self.state.smart_assist = SmartAssistConfig(**current)
        self.state.updated_at = datetime.now()
        logger.info(f"[ScenarioWorkflow] 智能提示配置已更新: {self.state.smart_assist.model_dump()}")
        return self.state.smart_assist

    def get_progress(self) -> dict:
        """获取当前进度信息"""
        if not self.state:
            raise ValueError("会话未创建")
        return self.state.get_progress()

    # ==================== 内部工具 ====================

    def _apply(self, updates: Dict[str, Any]) -> None:
        """将节点返回的 dict 合并到 state

        - 仅更新 state 上已有的属性
        - 自动刷新 updated_at
        """
        if not self.state or not updates:
            return
        for k, v in updates.items():
            if hasattr(self.state, k):
                setattr(self.state, k, v)
        self.state.updated_at = datetime.now()

    def get_state(self) -> Optional[ScenarioSession]:
        """获取当前会话状态"""
        return self.state
