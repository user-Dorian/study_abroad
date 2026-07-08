"""状态日志 API 路由 - 用于记录和查询RAG系统运行状态"""
import asyncio
import uuid
import json
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, validator
from psycopg2.extras import RealDictCursor

from utils.auth import require_user
from utils.logger import logger
from conversation.repository import _get_connection, _release_connection, _ensure_utc_iso
from common.config.async_database import AsyncDatabasePool
from common.conversation.repository import _parse_metadata

router = APIRouter(prefix="/api/status", tags=["status-logs"])


# ====== Pydantic 请求/响应模型 ======

class StatusLogItem(BaseModel):
    """单个状态日志项"""
    step_number: int = Field(..., ge=1, le=100, description="步骤序号(1-100)")
    step_name: str = Field(..., min_length=2, max_length=100, description="步骤名称")
    status: str = Field(..., description="状态(success/error/miss/running/not_implemented)")
    detail: str = Field(..., min_length=1, max_length=500, description="详细说明")
    metadata: Optional[dict] = Field(None, description="元数据(JSON格式)")

    @validator("status")
    def validate_status(cls, v):
        """验证状态值合法性"""
        allowed_statuses = ["success", "error", "miss", "running", "not_implemented"]
        if v not in allowed_statuses:
            raise ValueError(f"状态值必须是: {allowed_statuses}")
        return v


class BatchStatusLogsRequest(BaseModel):
    """批量保存状态日志请求"""
    conversation_id: str = Field(..., description="会话ID(UUID格式)")
    logs: List[StatusLogItem] = Field(..., min_items=1, max_items=50, description="日志列表(1-50条)")

    @validator("conversation_id")
    def validate_conversation_id(cls, v):
        """验证会话ID格式"""
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError("conversation_id必须是有效的UUID格式")


class StatusLogResponse(BaseModel):
    """单个状态日志响应"""
    id: str
    conversation_id: str
    user_id: str
    step_number: int
    step_name: str
    status: str
    detail: str
    metadata: Optional[dict] = None
    created_at: str


class BatchSaveResponse(BaseModel):
    """批量保存响应"""
    success: bool = True
    saved_count: int
    logs: List[StatusLogResponse]


class StatusLogsQueryResponse(BaseModel):
    """日志查询响应"""
    total: int
    page: int
    limit: int
    logs: List[StatusLogResponse]


# ====== 数据库操作函数 ======

def _verify_conversation_ownership(conversation_id: str, user_id: str) -> bool:
    """验证会话归属,防止伪造"""
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM conversations WHERE id = %s",
                (conversation_id,)
            )
            row = cur.fetchone()
            if row is None:
                logger.warning(f"会话不存在: conversation_id={conversation_id}")
                return False
            if str(row[0]) != user_id:
                logger.warning(
                    f"会话归属验证失败: conversation_id={conversation_id}, "
                    f"user_id={user_id}, owner={row[0]}"
                )
                return False
            return True
    except Exception as e:
        logger.error(f"验证会话归属失败: {e}")
        return False
    finally:
        if conn:
            _release_connection(conn)


def _save_status_log(
    conversation_id: str,
    user_id: str,
    step_number: int,
    step_name: str,
    status: str,
    detail: str,
    metadata: Optional[dict] = None
) -> dict:
    """保存单个状态日志"""
    log_id = str(uuid.uuid4())
    now = datetime.utcnow()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO status_logs 
                (id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at
                """,
                (log_id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, now)
            )
            row = cur.fetchone()
        conn.commit()

        # 解析metadata_json
        saved_metadata = None
        if row["metadata_json"] is not None:
            saved_metadata = (
                json.loads(row["metadata_json"])
                if isinstance(row["metadata_json"], str)
                else row["metadata_json"]
            )

        result = {
            "id": str(row["id"]),
            "conversation_id": str(row["conversation_id"]),
            "user_id": str(row["user_id"]),
            "step_number": row["step_number"],
            "step_name": row["step_name"],
            "status": row["status"],
            "detail": row["detail"],
            "metadata": saved_metadata,
            "created_at": _ensure_utc_iso(row["created_at"])
        }
        
        logger.debug(f"保存状态日志成功: id={result['id']}, step={step_number}, status={status}")
        return result

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"保存状态日志失败: step={step_number}, error={e}")
        raise
    finally:
        if conn:
            _release_connection(conn)


def _query_status_logs(
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    status: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    limit: int = 50
) -> tuple:
    """查询状态日志(带筛选和分页)"""
    # 构建WHERE条件
    conditions = []
    params = []
    
    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)
    
    if conversation_id:
        conditions.append("conversation_id = %s")
        params.append(conversation_id)
    
    if status:
        conditions.append("status = %s")
        params.append(status)
    
    if start_time:
        conditions.append("created_at >= %s")
        params.append(start_time)
    
    if end_time:
        conditions.append("created_at <= %s")
        params.append(end_time)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # 计算分页
    offset = (page - 1) * limit
    
    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 查询总数
            cur.execute(
                f"SELECT COUNT(*) as total FROM status_logs WHERE {where_clause}",
                params
            )
            total = cur.fetchone()["total"]
            
            # 查询数据
            cur.execute(
                f"""
                SELECT id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at
                FROM status_logs
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset]
            )
            rows = cur.fetchall()

        # 转换结果
        logs = []
        for row in rows:
            log_metadata = None
            if row["metadata_json"] is not None:
                log_metadata = (
                    json.loads(row["metadata_json"])
                    if isinstance(row["metadata_json"], str)
                    else row["metadata_json"]
                )
            logs.append({
                "id": str(row["id"]),
                "conversation_id": str(row["conversation_id"]),
                "user_id": str(row["user_id"]),
                "step_number": row["step_number"],
                "step_name": row["step_name"],
                "status": row["status"],
                "detail": row["detail"],
                "metadata": log_metadata,
                "created_at": _ensure_utc_iso(row["created_at"])
            })

        logger.debug(f"查询状态日志成功: total={total}, page={page}, limit={limit}")
        return total, logs

    except Exception as e:
        logger.error(f"查询状态日志失败: error={e}")
        raise
    finally:
        if conn:
            _release_connection(conn)


# ====== 阶段2数据库异步化：异步数据库操作函数（保留同步函数不变，新增 asyncpg 版本） ======

async def _async_verify_conversation_ownership(conversation_id: str, user_id: str) -> bool:
    """验证会话归属,防止伪造（异步版）"""
    try:
        row = await AsyncDatabasePool.execute_one(
            "SELECT user_id FROM conversations WHERE id = $1",
            conversation_id,
        )
        if row is None:
            logger.warning(f"会话不存在: conversation_id={conversation_id}")
            return False
        if str(row["user_id"]) != user_id:
            logger.warning(
                f"会话归属验证失败: conversation_id={conversation_id}, "
                f"user_id={user_id}, owner={row['user_id']}"
            )
            return False
        return True
    except Exception as e:
        logger.error(f"验证会话归属失败: {e}")
        return False


async def _async_save_status_log(
    conversation_id: str,
    user_id: str,
    step_number: int,
    step_name: str,
    status: str,
    detail: str,
    metadata: Optional[dict] = None,
) -> dict:
    """保存单个状态日志（异步版）"""
    log_id = str(uuid.uuid4())
    now = datetime.utcnow()
    metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    try:
        sql = (
            "INSERT INTO status_logs "
            "(id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
            "RETURNING id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at"
        )
        row = await AsyncDatabasePool.execute_one(
            sql, log_id, conversation_id, user_id, step_number,
            step_name, status, detail, metadata_json, now,
        )
        result = {
            "id": str(row["id"]),
            "conversation_id": str(row["conversation_id"]),
            "user_id": str(row["user_id"]),
            "step_number": row["step_number"],
            "step_name": row["step_name"],
            "status": row["status"],
            "detail": row["detail"],
            "metadata": _parse_metadata(row["metadata_json"]),
            "created_at": _ensure_utc_iso(row["created_at"]),
        }
        logger.debug(f"保存状态日志成功: id={result['id']}, step={step_number}, status={status}")
        return result
    except Exception as e:
        logger.error(f"保存状态日志失败: step={step_number}, error={e}")
        raise


async def _async_query_status_logs(
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    status: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    page: int = 1,
    limit: int = 50,
) -> tuple:
    """查询状态日志(带筛选和分页，异步版)

    动态构建 $1, $2, ... 占位符（asyncpg 风格），按参数顺序编号。
    """
    # 构建WHERE条件，动态编号占位符
    conditions = []
    params = []
    idx = 1
    if user_id:
        conditions.append(f"user_id = ${idx}")
        params.append(user_id)
        idx += 1
    if conversation_id:
        conditions.append(f"conversation_id = ${idx}")
        params.append(conversation_id)
        idx += 1
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if start_time:
        conditions.append(f"created_at >= ${idx}")
        params.append(start_time)
        idx += 1
    if end_time:
        conditions.append(f"created_at <= ${idx}")
        params.append(end_time)
        idx += 1

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    offset = (page - 1) * limit

    try:
        # 查询总数
        count_sql = f"SELECT COUNT(*) AS total FROM status_logs WHERE {where_clause}"
        count_row = await AsyncDatabasePool.execute_one(count_sql, *params)
        total = count_row["total"]

        # 查询数据（LIMIT/OFFSET 占位符接续编号）
        limit_idx = idx
        offset_idx = idx + 1
        data_sql = (
            f"SELECT id, conversation_id, user_id, step_number, step_name, status, detail, "
            f"metadata_json, created_at FROM status_logs WHERE {where_clause} "
            f"ORDER BY created_at DESC LIMIT ${limit_idx} OFFSET ${offset_idx}"
        )
        rows = await AsyncDatabasePool.execute_query(data_sql, *params, limit, offset)

        logs = []
        for row in rows:
            logs.append({
                "id": str(row["id"]),
                "conversation_id": str(row["conversation_id"]),
                "user_id": str(row["user_id"]),
                "step_number": row["step_number"],
                "step_name": row["step_name"],
                "status": row["status"],
                "detail": row["detail"],
                "metadata": _parse_metadata(row["metadata_json"]),
                "created_at": _ensure_utc_iso(row["created_at"]),
            })

        logger.debug(f"查询状态日志成功: total={total}, page={page}, limit={limit}")
        return total, logs

    except Exception as e:
        logger.error(f"查询状态日志失败: error={e}")
        raise


async def _async_batch_save_status_logs(
    conversation_id: str,
    user_id: str,
    logs: list,
) -> list:
    """批量保存状态日志（使用事务，异步版）

    Args:
        conversation_id: 会话ID
        user_id: 用户ID
        logs: StatusLogItem 列表

    Returns:
        list[dict]: 已保存的日志列表
    """
    saved_logs = []
    pool = await AsyncDatabasePool.get_pool()
    try:
        async with pool.acquire() as conn:
            # 整批在一个事务内提交，任一失败则整体回滚
            async with conn.transaction():
                sql = (
                    "INSERT INTO status_logs "
                    "(id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
                    "RETURNING id, conversation_id, user_id, step_number, step_name, status, detail, metadata_json, created_at"
                )
                for log_item in logs:
                    log_id = str(uuid.uuid4())
                    now = datetime.utcnow()
                    metadata_json = json.dumps(log_item.metadata, ensure_ascii=False) if log_item.metadata else None
                    row = await conn.fetchrow(
                        sql, log_id, conversation_id, user_id, log_item.step_number,
                        log_item.step_name, log_item.status, log_item.detail, metadata_json, now,
                    )
                    saved_logs.append({
                        "id": str(row["id"]),
                        "conversation_id": str(row["conversation_id"]),
                        "user_id": str(row["user_id"]),
                        "step_number": row["step_number"],
                        "step_name": row["step_name"],
                        "status": row["status"],
                        "detail": row["detail"],
                        "metadata": _parse_metadata(row["metadata_json"]),
                        "created_at": _ensure_utc_iso(row["created_at"]),
                    })
    except Exception as e:
        logger.error(f"批量保存状态日志失败: conversation_id={conversation_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")
    return saved_logs


# ====== 路由实现 ======

@router.post("/logs", response_model=BatchSaveResponse)
async def batch_save_status_logs(
    request: BatchStatusLogsRequest,
    current_user: dict = Depends(require_user)
):
    """
    批量保存状态日志
    
    用于记录RAG检索过程中的各个步骤状态(如Redis缓存检索、BM25检索等)。
    
    **权限要求**: JWT认证,会话必须属于当前用户
    
    **限流策略**: 100次/分钟(高频操作)
    
    **请求示例**:
    ```json
    {
      "conversation_id": "uuid-string",
      "logs": [
        {
          "step_number": 1,
          "step_name": "Redis缓存检索",
          "status": "success",
          "detail": "命中缓存",
          "metadata": {"cache_key": "rag:query", "ttl": 3600}
        },
        {
          "step_number": 2,
          "step_name": "BM25检索",
          "status": "miss",
          "detail": "未找到相关文档"
        }
      ]
    }
    ```
    """
    try:
        user_id = current_user["user_id"]

        # 1. 验证会话归属(防止伪造)（阶段2数据库异步化：调用异步函数，不再用 asyncio.to_thread 包装）
        if not await _async_verify_conversation_ownership(request.conversation_id, user_id):
            raise HTTPException(
                status_code=403,
                detail="无权限:会话不属于当前用户"
            )

        # 2. 批量保存日志(使用事务)（阶段2数据库异步化：调用异步批量保存函数，使用 asyncpg 事务）
        saved_logs = await _async_batch_save_status_logs(request.conversation_id, user_id, request.logs)

        logger.info(
            f"批量保存状态日志成功: user_id={user_id}, "
            f"conversation_id={request.conversation_id}, "
            f"count={len(saved_logs)}"
        )

        return BatchSaveResponse(
            success=True,
            saved_count=len(saved_logs),
            logs=saved_logs
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量保存状态日志接口异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"服务器内部错误: {str(e)}"
        )


@router.get("/logs", response_model=StatusLogsQueryResponse)
async def query_status_logs(
    conversation_id: Optional[str] = Query(None, description="按会话ID筛选(UUID格式)"),
    user_id: Optional[str] = Query(None, description="按用户ID筛选(管理员用)"),
    status: Optional[str] = Query(None, description="按状态筛选(success/error/miss等)"),
    start_time: Optional[str] = Query(None, description="开始时间(ISO格式,如2026-07-01T00:00:00)"),
    end_time: Optional[str] = Query(None, description="结束时间(ISO格式)"),
    page: int = Query(1, ge=1, le=1000, description="页码(1-1000)"),
    limit: int = Query(50, ge=1, le=100, description="每页条数(1-100)"),
    current_user: dict = Depends(require_user)
):
    """
    获取历史状态日志
    
    支持多种筛选条件:会话ID、用户ID、状态、时间范围、分页。
    
    **权限要求**: JWT认证
    
    **限流策略**: 60次/分钟
    
    **查询参数示例**:
    - conversation_id: 查询特定会话的日志
    - status=error: 只查询错误日志
    - start_time=2026-07-01T00:00:00: 查询7月份的日志
    - page=1&limit=20: 分页查询
    """
    try:
        current_user_id = current_user["user_id"]
        
        # 参数校验
        if conversation_id:
            try:
                uuid.UUID(conversation_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="conversation_id格式错误")
        
        if user_id:
            try:
                uuid.UUID(user_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="user_id格式错误")
        
        # 权限校验:普通用户只能查询自己的日志,管理员可查询所有
        # TODO: 后续添加管理员权限判断
        query_user_id = user_id if user_id else current_user_id
        
        # 时间参数解析
        parsed_start_time = None
        parsed_end_time = None
        
        if start_time:
            try:
                parsed_start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="start_time格式错误")
        
        if end_time:
            try:
                parsed_end_time = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="end_time格式错误")
        
        # 查询日志（阶段2数据库异步化：调用异步查询函数，使用 asyncpg 原生异步 I/O，不再用 asyncio.to_thread 包装）
        total, logs = await _async_query_status_logs(
            user_id=query_user_id,
            conversation_id=conversation_id,
            status=status,
            start_time=parsed_start_time,
            end_time=parsed_end_time,
            page=page,
            limit=limit,
        )
        
        logger.info(
            f"查询状态日志成功: user_id={current_user_id}, "
            f"total={total}, page={page}, filters={conversation_id or status or 'none'}"
        )
        
        return StatusLogsQueryResponse(
            total=total,
            page=page,
            limit=limit,
            logs=logs
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询状态日志接口异常: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"服务器内部错误: {str(e)}"
        )