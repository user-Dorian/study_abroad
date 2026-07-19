"""对话状态管理 - 定义所有节点之间数据传递的Pydantic表单

架构设计（v2 重构）：
- 用户 query 进入后并行分发两个 LLM 分支
- 分支A：检索意图识别（纯LLM判断是否需要检索）
- 分支B：表单信息提取（纯LLM提取字段+备注重写，输出结构化JSON）
- 两个分支的输出合并后注入回答生成 LLM
- 表单填写悄无声息执行，不向用户输出反馈
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from backend.common.functions.rag.models.intent_classifier import IntentEnum


class UserInfo(BaseModel):
    """用户基本信息"""
    user_id: str = Field(..., description="用户ID")
    session_id: Optional[str] = Field(None, description="会话ID")
    is_new_user: bool = Field(True, description="是否新用户")
    info_collection_complete: bool = Field(False, description="信息收集是否完成")
    collected_fields: List[str] = Field(default_factory=list, description="已收集的字段列表")


class IntentState(BaseModel):
    """意图识别状态（v2: 仅判断是否需要检索）"""
    need_retrieval: bool = Field(False, description="是否需要检索")
    confidence: float = Field(0.0, description="意图置信度")
    reason: str = Field("", description="LLM判断理由（日志用）")
    elapsed: float = Field(0.0, description="意图识别耗时(秒)")


class RetrievalState(BaseModel):
    """检索状态（v2: 细化多级检索链路）"""
    retrieval_needed: bool = Field(False, description="是否需要检索")
    # 多级检索结果
    redis_hit: bool = Field(False, description="L1 Redis 是否命中")
    bm25_hit: bool = Field(False, description="L2 BM25+SQL 是否命中")
    rag_hit: bool = Field(False, description="L3 向量检索是否命中")
    # 检索过程数据
    coarse_candidates: List[Dict[str, Any]] = Field(default_factory=list, description="L3a 稀疏向量粗排序候选 (top 50)")
    fine_results: List[Dict[str, Any]] = Field(default_factory=list, description="L3b 精排序后的结果 (top 10)")
    final_context: Optional[str] = Field(None, description="最终检索上下文（合并后用于回答生成）")
    retrieval_source: str = Field("", description="命中的检索来源: redis/bm25/rag/empty")
    retrieval_time: float = Field(0.0, description="检索耗时(秒)")


class FormFillingState(BaseModel):
    """表单填写状态（v2: 静默执行，统一JSON输出）

    LLM 表单提取节点统一输出 JSON 格式：
        { "updates": { field: value, ... }, "notes": "重写内容" or null }
    无任何更新时输出：{ "updates": null, "notes": null }
    """
    raw_llm_output: Dict[str, Any] = Field(default_factory=dict, description="LLM原始JSON输出")
    extracted_updates: Dict[str, Any] = Field(default_factory=dict, description="本次提取的字段更新（已验证转换）")
    extracted_notes: Optional[str] = Field(None, description="本次重写后的备注内容（None表示无重写）")
    # 写入结果
    db_write_success: bool = Field(False, description="数据库写入是否成功")
    updated_field_names: List[str] = Field(default_factory=list, description="本次成功写入的字段名列表")
    notes_updated: bool = Field(False, description="备注是否已更新")
    # 最新profile快照（始终输出给回答生成节点，确保信息对齐）
    profile_snapshot: Dict[str, Any] = Field(default_factory=dict, description="写入后的最新profile快照")
    elapsed: float = Field(0.0, description="表单填写耗时(秒)")


class ResponseState(BaseModel):
    """回答生成状态"""
    response_type: str = Field("", description="回答类型: direct/retrieval_based")
    final_answer: str = Field("", description="最终回答文本")
    response_time: float = Field(0.0, description="生成耗时(秒)")


class ConversationState(BaseModel):
    """完整的对话状态 - 所有节点共享的数据结构（v2 重构）"""
    # 用户信息
    user_info: UserInfo = Field(default_factory=lambda: UserInfo(user_id=""))

    # 意图识别（仅判断是否需要检索）
    intent_state: IntentState = Field(default_factory=IntentState)

    # 检索状态
    retrieval_state: RetrievalState = Field(default_factory=RetrievalState)

    # 表单填写（静默执行）
    form_state: FormFillingState = Field(default_factory=FormFillingState)

    # 回答生成
    response_state: ResponseState = Field(default_factory=ResponseState)

    # 对话历史
    messages: List[Dict[str, str]] = Field(default_factory=list, description="对话历史")
    current_user_message: str = Field("", description="当前用户消息")

    # 用户profile（初始为DB快照，表单填写后会刷新）
    user_profile: Dict[str, Any] = Field(default_factory=dict, description="用户档案数据")
    # 当前备注内容（用于表单LLM判断是否需要重写）
    current_notes: str = Field("", description="当前备注内容")

    # 错误处理
    errors: List[str] = Field(default_factory=list, description="错误信息列表")
    should_fallback: bool = Field(False, description="是否需要降级处理")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")
    node_execution_path: List[str] = Field(default_factory=list, description="节点执行路径")

    def add_error(self, error: str):
        """添加错误信息"""
        self.errors.append(error)
        self.updated_at = datetime.now()

    def add_node_to_path(self, node_name: str):
        """记录节点执行路径"""
        self.node_execution_path.append(node_name)
        self.updated_at = datetime.now()

    def update_profile(self, field_name: str, field_value: Any):
        """更新用户档案"""
        self.user_profile[field_name] = field_value
        self.updated_at = datetime.now()

    def get_missing_required_fields(self) -> List[str]:
        """获取缺失的必填字段"""
        from backend.common.functions.info_collect.model import STUDENT_FIELDS_META
        missing = []
        for field_name, meta in STUDENT_FIELDS_META.items():
            if meta.get("required", False):
                if field_name not in self.user_profile or not self.user_profile[field_name]:
                    missing.append(field_name)
        return missing


class NodeResult(BaseModel):
    """节点执行结果"""
    success: bool = Field(..., description="执行是否成功")
    state: ConversationState = Field(..., description="更新后的状态")
    message: str = Field("", description="执行消息")
    should_continue: bool = Field(True, description="是否继续执行下一个节点")
