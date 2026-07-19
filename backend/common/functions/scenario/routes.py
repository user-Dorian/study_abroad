"""情景对话功能 - API 路由模块

职责：
    定义所有 HTTP 端点，对接 ScenarioWorkflow 工作流。
    - 维护内存级会话存储 _active_workflows
    - 统一使用 require_user 鉴权
    - 统一响应格式 APIResponse
    - 提供真实 SSE 流式端点（/free-stream）以支持前端流式渲染

API 端点清单（prefix: /api/scenario）：
    POST   /sessions                       创建会话
    POST   /sessions/{sid}/start           开始场景
    POST   /sessions/{sid}/free-message    自由模式非流式
    POST   /sessions/{sid}/free-stream     自由模式 SSE 流式
    POST   /sessions/{sid}/preset-request  预设模式请求选项
    POST   /sessions/{sid}/preset-select   预设模式选择选项
    GET    /sessions/{sid}/hint            获取提示
    PATCH  /sessions/{sid}/smart-assist    更新智能提示开关
    GET    /sessions/{sid}/smart-assist    拉取最近智能提示
    POST   /sessions/{sid}/favorites       收藏表达
    GET    /sessions/{sid}/favorites       收藏列表
    GET    /sessions/{sid}/wrong-records   错题列表
    POST   /sessions/{sid}/end             结束并生成报告
    GET    /sessions/{sid}/report          获取学习报告
    GET    /sessions/{sid}                 获取会话详情
    GET    /sessions/{sid}/progress        获取进度
"""
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.common.basics.utils.auth import require_user
from backend.common.basics.utils.logger import logger

from .graph import ScenarioWorkflow
from .state import (
    MessageType,
    ScenarioConfig,
    ScenarioPhase,
    ScenarioSession,
    SmartAssistConfig,
)

router = APIRouter(prefix="/api/scenario", tags=["情景对话"])

# 工作流存储：session_id → ScenarioWorkflow（内存级，重启后丢失）
_active_workflows: Dict[str, ScenarioWorkflow] = {}


# ==================== 请求/响应模型 ====================

class CreateSessionRequest(BaseModel):
    """创建会话请求"""
    config: ScenarioConfig = Field(default_factory=ScenarioConfig)
    smart_assist: SmartAssistConfig = Field(default_factory=SmartAssistConfig)


class FreeMessageRequest(BaseModel):
    """自由模式消息请求"""
    message: str


class SelectOptionRequest(BaseModel):
    """预设选项选择请求"""
    option_id: str


class UpdateSmartAssistRequest(BaseModel):
    """更新智能提示开关请求"""
    smart_assist: SmartAssistConfig


class AddFavoriteRequest(BaseModel):
    """收藏表达请求"""
    text: str
    context: str = ""
    note: str = ""


class APIResponse(BaseModel):
    """统一响应格式"""
    success: bool = True
    data: Optional[Any] = None
    message: str = "操作成功"
    error: Optional[Dict[str, Any]] = None


# ==================== 内部工具 ====================

def _get_workflow(session_id: str, user_id: str = "") -> ScenarioWorkflow:
    """根据 session_id 获取工作流，不存在则抛 404"""
    wf = _active_workflows.get(session_id)
    if not wf:
        raise HTTPException(status_code=404, detail="会话不存在")
    if user_id and wf.state and wf.state.user_id != user_id:
        # 简单的越权检查
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return wf


def _serialize_message(m) -> dict:
    """序列化单条 ScenarioMessage"""
    return {
        "message_id": m.message_id,
        "role": m.role.value if hasattr(m.role, "value") else str(m.role),
        "content": m.content,
        "language": m.language,
        "translation": m.translation,
        "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        "assist": m.assist.model_dump() if m.assist else None,
        "preset_options": [opt.model_dump() for opt in m.preset_options],
    }


def _serialize_session(state: ScenarioSession) -> dict:
    """序列化整个会话"""
    return {
        "session_id": state.session_id,
        "user_id": state.user_id,
        "phase": state.phase.value if hasattr(state.phase, "value") else str(state.phase),
        "config": state.config.model_dump(),
        "smart_assist": state.smart_assist.model_dump(),
        "messages": [_serialize_message(m) for m in state.messages],
        "favorites": [f.model_dump() for f in state.favorites],
        "wrong_records": [w.model_dump() for w in state.wrong_records],
        "current_preset_options": [o.model_dump() for o in state.current_preset_options],
        "report": state.report.model_dump() if state.report else None,
        "start_time": state.start_time.isoformat() if state.start_time else None,
        "end_time": state.end_time.isoformat() if state.end_time else None,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
    }


# ==================== API 端点 ====================

@router.post("/sessions", response_model=APIResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: CreateSessionRequest,
    current_user: dict = Depends(require_user),
):
    """创建情景对话会话"""
    try:
        user_id = current_user["user_id"]
        workflow = ScenarioWorkflow()
        state = workflow.create_session(
            user_id=user_id,
            config=request.config.model_dump(),
            smart_assist=request.smart_assist.model_dump(),
        )
        _active_workflows[state.session_id] = workflow
        logger.info(f"[ScenarioRoute] 创建会话: session_id={state.session_id}, user={user_id}")
        return APIResponse(
            data={
                "session_id": state.session_id,
                "user_id": state.user_id,
                "phase": state.phase.value,
                "config": state.config.model_dump(),
                "smart_assist": state.smart_assist.model_dump(),
                "created_at": state.created_at.isoformat(),
            },
            message="会话创建成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ScenarioRoute] 创建会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建会话失败: {e}")


@router.post("/sessions/{session_id}/start", response_model=APIResponse)
async def start_session(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """开始场景 - 构造 NPC 开场白"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        state = workflow.get_state()
        if state.phase != ScenarioPhase.SETUP:
            raise HTTPException(status_code=400, detail="场景已开始或已结束")
        await workflow.start_scenario()
        state = workflow.get_state()
        logger.info(f"[ScenarioRoute] 场景已开始: session_id={session_id}")
        return APIResponse(
            data={
                "session_id": state.session_id,
                "phase": state.phase.value,
                "opening_message": _serialize_message(state.messages[-1]) if state.messages else None,
                "start_time": state.start_time.isoformat() if state.start_time else None,
            },
            message="场景已开始",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 开始场景失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"开始场景失败: {e}")


@router.post("/sessions/{session_id}/free-message", response_model=APIResponse)
async def free_message(
    session_id: str,
    request: FreeMessageRequest,
    current_user: dict = Depends(require_user),
):
    """自由模式 - 非流式发送消息"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        text = (request.message or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="消息不能为空")
        await workflow.send_free_message(text)
        state = workflow.get_state()
        # 返回最新的用户消息和 NPC 消息
        last_user = next((m for m in reversed(state.messages) if m.role == MessageType.USER), None)
        last_npc = next((m for m in reversed(state.messages) if m.role == MessageType.NPC), None)
        return APIResponse(
            data={
                "session_id": state.session_id,
                "phase": state.phase.value,
                "user_message": _serialize_message(last_user) if last_user else None,
                "npc_message": _serialize_message(last_npc) if last_npc else None,
            },
            message="消息已处理",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 自由消息处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"消息处理失败: {e}")


@router.post("/sessions/{session_id}/free-stream")
async def free_stream(
    session_id: str,
    request: FreeMessageRequest,
    current_user: dict = Depends(require_user),
):
    """自由模式 - SSE 流式发送消息

    SSE 事件类型：
    - event: stage    阶段切换（analyze / assist / reply / done）
    - event: token    NPC 回复 token 片段
    - event: error    错误信息
    - event: done     流结束，附带最终状态
    """
    workflow = _get_workflow(session_id, current_user["user_id"])
    text = (request.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="消息不能为空")

    async def event_generator():
        # 1. 分析阶段事件
        yield 'event: stage\ndata: ' + json.dumps(
            {"stage": "analyze", "label": "分析输入中..."}, ensure_ascii=False
        ) + '\n\n'

        # 2. 智能提示阶段事件
        yield 'event: stage\ndata: ' + json.dumps(
            {"stage": "assist", "label": "生成智能提示..."}, ensure_ascii=False
        ) + '\n\n'

        # 3. NPC 流式回复阶段
        yield 'event: stage\ndata: ' + json.dumps(
            {"stage": "reply", "label": "生成回复中..."}, ensure_ascii=False
        ) + '\n\n'

        try:
            # 调用工作流的流式接口
            # stream_free_reply 内部已串行执行：写入用户消息 → analyze_user_input
            # → generate_smart_assist → 流式产出 NPC 回复
            # 注意：SSE 数据中用 json.dumps 序列化，自动处理换行等特殊字符
            async for chunk in workflow.stream_free_reply(text):
                yield 'event: token\ndata: ' + json.dumps(
                    {"text": chunk}, ensure_ascii=False
                ) + '\n\n'
        except Exception as e:
            logger.error(f"[ScenarioRoute] SSE 流式失败: {e}", exc_info=True)
            yield 'event: error\ndata: ' + json.dumps(
                {"message": "回复生成失败，请稍后重试"}, ensure_ascii=False
            ) + '\n\n'
            return

        # 4. 完成事件 - 附带最终状态（包括智能辅助结果）
        state = workflow.get_state()
        last_user = next((m for m in reversed(state.messages) if m.role == MessageType.USER), None)
        last_npc = next((m for m in reversed(state.messages) if m.role == MessageType.NPC), None)
        done_payload = {
            "session_id": state.session_id,
            "phase": state.phase.value,
            "user_message": _serialize_message(last_user) if last_user else None,
            "npc_message": _serialize_message(last_npc) if last_npc else None,
            # 前端友好字段：直接给出字符串与智能提示对象，避免前端再做一次拉取
            "npc_reply": last_npc.content if last_npc else "",
            "assist": last_npc.assist.model_dump() if (last_npc and last_npc.assist) else None,
        }
        yield 'event: done\ndata: ' + json.dumps(
            done_payload, ensure_ascii=False
        ) + '\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


@router.post("/sessions/{session_id}/preset-request", response_model=APIResponse)
async def preset_request(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """预设模式 - 请求生成下一轮选项"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        await workflow.request_preset_options()
        state = workflow.get_state()
        last_npc = next((m for m in reversed(state.messages) if m.role == MessageType.NPC), None)
        return APIResponse(
            data={
                "session_id": state.session_id,
                "phase": state.phase.value,
                "npc_message": _serialize_message(last_npc) if last_npc else None,
                "preset_options": [o.model_dump() for o in state.current_preset_options],
            },
            message="预设选项已生成",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 预设选项生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"预设选项生成失败: {e}")


@router.post("/sessions/{session_id}/preset-select", response_model=APIResponse)
async def preset_select(
    session_id: str,
    request: SelectOptionRequest,
    current_user: dict = Depends(require_user),
):
    """预设模式 - 选择选项"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        # 记录选前错题数，用于判断本次是否选错
        wrong_count_before = len(workflow.get_state().wrong_records)
        await workflow.select_preset_option(request.option_id)
        state = workflow.get_state()
        wrong_count_after = len(state.wrong_records)
        is_wrong = wrong_count_after > wrong_count_before

        # 末尾两条消息：用户选择的 + NPC 回应/解释
        recent = state.messages[-2:] if len(state.messages) >= 2 else state.messages
        # 提取 NPC 反馈文本（最后一条 NPC 消息的 content）
        last_npc = next((m for m in reversed(state.messages) if m.role == MessageType.NPC), None)
        npc_feedback = last_npc.content if last_npc else ""
        # 错误选项时，NPC 反馈即为解释
        explanation = npc_feedback if is_wrong else ""

        return APIResponse(
            data={
                "session_id": state.session_id,
                "phase": state.phase.value,
                "recent_messages": [_serialize_message(m) for m in recent],
                "npc_feedback": npc_feedback,
                "is_wrong": is_wrong,
                "explanation": explanation,
                "wrong_record_count": wrong_count_after,
            },
            message="选项已处理",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 选项处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"选项处理失败: {e}")


@router.get("/sessions/{session_id}/hint", response_model=APIResponse)
async def get_hint(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取当前预设选项的提示"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        result = await workflow.get_hint()
        return APIResponse(data=result, message="提示获取成功")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取提示失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取提示失败: {e}")


@router.patch("/sessions/{session_id}/smart-assist", response_model=APIResponse)
async def update_smart_assist(
    session_id: str,
    request: UpdateSmartAssistRequest,
    current_user: dict = Depends(require_user),
):
    """更新智能提示开关"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        cfg = workflow.update_smart_assist(request.smart_assist.model_dump())
        return APIResponse(
            data={"smart_assist": cfg.model_dump()},
            message="智能提示配置已更新",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 更新智能提示失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新失败: {e}")


@router.get("/sessions/{session_id}/smart-assist", response_model=APIResponse)
async def get_smart_assist(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取最近一条 NPC 消息附带的智能提示结果"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        state = workflow.get_state()
        # 优先找最近一条带 assist 的 NPC 消息
        assist_data = None
        for m in reversed(state.messages):
            if m.role == MessageType.NPC and m.assist is not None:
                assist_data = m.assist.model_dump()
                break
        return APIResponse(
            data={
                "config": state.smart_assist.model_dump(),
                "latest_assist": assist_data,
            },
            message="获取成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取智能提示失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {e}")


@router.post("/sessions/{session_id}/favorites", response_model=APIResponse)
async def add_favorite(
    session_id: str,
    request: AddFavoriteRequest,
    current_user: dict = Depends(require_user),
):
    """收藏一条表达"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        text = (request.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="收藏内容不能为空")
        fav = workflow.add_favorite(text=text, context=request.context, note=request.note)
        return APIResponse(
            data=fav.model_dump(),
            message="已收藏",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 收藏失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"收藏失败: {e}")


@router.get("/sessions/{session_id}/favorites", response_model=APIResponse)
async def list_favorites(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取收藏列表"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        favs = workflow.list_favorites()
        return APIResponse(
            data=[f.model_dump() for f in favs],
            message=f"共 {len(favs)} 条收藏",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取收藏失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {e}")


@router.get("/sessions/{session_id}/wrong-records", response_model=APIResponse)
async def list_wrong_records(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取错题列表"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        records = workflow.list_wrong_records()
        return APIResponse(
            data=[r.model_dump() for r in records],
            message=f"共 {len(records)} 条错题",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取错题失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {e}")


@router.post("/sessions/{session_id}/end", response_model=APIResponse)
async def end_session(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """结束场景并生成学习报告"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        state = workflow.get_state()
        if state.phase == ScenarioPhase.COMPLETED and state.report is not None:
            # 已结束，直接返回
            return APIResponse(
                data={"report": state.report.model_dump()},
                message="场景已结束（报告已生成）",
            )
        await workflow.end_scenario()
        state = workflow.get_state()
        logger.info(f"[ScenarioRoute] 场景已结束: session_id={session_id}")
        return APIResponse(
            data={
                "session_id": state.session_id,
                "phase": state.phase.value,
                "report": state.report.model_dump() if state.report else None,
            },
            message="场景已结束，报告已生成",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 结束场景失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"结束失败: {e}")


@router.get("/sessions/{session_id}/report", response_model=APIResponse)
async def get_report(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取学习报告"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        report = workflow.get_report()
        if report is None:
            return APIResponse(
                success=False,
                data=None,
                message="报告尚未生成，请先结束场景",
            )
        return APIResponse(
            data=report.model_dump(),
            message="报告获取成功",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取报告失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {e}")


@router.get("/sessions/{session_id}", response_model=APIResponse)
async def get_session(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取会话详情"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        state = workflow.get_state()
        return APIResponse(
            data=_serialize_session(state),
            message="获取成功",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {e}")


@router.get("/sessions/{session_id}/progress", response_model=APIResponse)
async def get_progress(
    session_id: str,
    current_user: dict = Depends(require_user),
):
    """获取当前进度"""
    try:
        workflow = _get_workflow(session_id, current_user["user_id"])
        progress = workflow.get_progress()
        return APIResponse(
            data=progress,
            message="进度获取成功",
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[ScenarioRoute] 获取进度失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取失败: {e}")
