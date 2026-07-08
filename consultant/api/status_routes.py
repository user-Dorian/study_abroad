"""规划师端状态日志路由 - 批量保存和查询检索过程日志"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from common.utils.logger import logger

router = APIRouter()

# 内存存储（规划师端状态日志，后续可扩展为数据库存储）
_status_logs = []


class StatusLogEntry(BaseModel):
    """状态日志条目"""
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    step_number: int
    step_name: str
    status: str
    detail: str
    metadata_json: Optional[dict] = None
    created_at: Optional[str] = None


@router.post("/api/status/logs")
async def save_status_logs(logs: List[StatusLogEntry]):
    """批量保存状态日志"""
    try:
        timestamp = datetime.now().isoformat()
        for log in logs:
            log_entry = log.model_dump()
            log_entry["created_at"] = timestamp
            _status_logs.append(log_entry)

        logger.info(f"[规划师端] 批量保存 {len(logs)} 条状态日志成功")
        return {"success": True, "count": len(logs)}
    except Exception as e:
        logger.error(f"[规划师端] 保存状态日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存状态日志失败: {str(e)}")


@router.get("/api/status/logs")
async def get_status_logs(
    conversation_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    """查询状态日志"""
    try:
        filtered = _status_logs
        if conversation_id:
            filtered = [log for log in filtered if log.get("conversation_id") == conversation_id]

        total = len(filtered)
        page = filtered[offset:offset + limit]

        return {"logs": page, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        logger.error(f"[规划师端] 查询状态日志失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询状态日志失败: {str(e)}")
