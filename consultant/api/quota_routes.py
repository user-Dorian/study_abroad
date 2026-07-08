"""规划师端名额管理 API 路由

为企业内部留学咨询系统提供名额（内推名额、工作推荐名额、院校合作配额等）
的结构化管理，支持 human-in-the-loop 审核流程：
    创建名额(pending_review) → 审核通过(active) → 使用(pending_review) → 审核通过(approved)

重要约束：
- 名额数据会变化，查询结果不写入 Redis 缓存。
- 使用 psycopg2 的 RealDictCursor 返回字典结构。
- 所有接口均需认证（复用 auth_routes._get_current_user_from_header）。
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi import Header as FastAPIHeader
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
import asyncio
import uuid

import psycopg2
from psycopg2.extras import RealDictCursor

from common.utils.logger import logger
from common.config.async_database import AsyncDatabasePool
from common.conversation.repository import _affected_count
from consultant.config.database import ConsultantDatabaseConfig
from consultant.api.auth_routes import _get_current_user_from_header

router = APIRouter()


# ========== 名额类型与状态枚举（文档说明用，实际校验在应用层） ==========

QUOTA_TYPES = {
    "internal_referral": "内推名额",
    "job_recommendation": "工作推荐名额",
    "school_partnership": "院校合作配额",
}

QUOTA_STATUS = {
    "pending_review": "待审核",
    "approved": "已批准",
    "active": "活跃",
    "exhausted": "已用完",
    "closed": "已关闭",
}

USAGE_STATUS = {
    "pending_review": "待审核",
    "approved": "已批准",
    "rejected": "已拒绝",
}


# ========== Pydantic 请求模型 ==========

class CreateQuotaRequest(BaseModel):
    """创建名额请求"""
    quota_type: str
    title: str
    description: Optional[str] = None
    total_count: int

    @field_validator("quota_type")
    @classmethod
    def validate_quota_type(cls, v):
        if v not in QUOTA_TYPES:
            raise ValueError(f"无效的名额类型，可选: {list(QUOTA_TYPES.keys())}")
        return v

    @field_validator("title")
    @classmethod
    def validate_title(cls, v):
        v = (v or "").strip()
        if not v:
            raise ValueError("名额标题不能为空")
        if len(v) > 200:
            raise ValueError("名额标题不能超过200个字符")
        return v

    @field_validator("total_count")
    @classmethod
    def validate_total_count(cls, v):
        if v <= 0:
            raise ValueError("总数量必须大于0")
        return v


class ReviewQuotaRequest(BaseModel):
    """审核名额请求"""
    action: str  # approve / reject
    review_note: Optional[str] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        v = (v or "").lower()
        if v not in ("approve", "reject"):
            raise ValueError("action 只能是 approve 或 reject")
        return v


class UseQuotaRequest(BaseModel):
    """使用名额请求"""
    target_user_id: Optional[str] = None
    target_user_name: Optional[str] = None
    usage_note: Optional[str] = None

    @field_validator("target_user_id")
    @classmethod
    def validate_target_user_id(cls, v):
        if v is None or v == "":
            return None
        try:
            uuid.UUID(v)
        except Exception:
            raise ValueError("target_user_id 不是合法的 UUID")
        return v


class ReviewUsageRequest(BaseModel):
    """审核名额使用请求"""
    action: str  # approve / reject
    review_note: Optional[str] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        v = (v or "").lower()
        if v not in ("approve", "reject"):
            raise ValueError("action 只能是 approve 或 reject")
        return v


# ========== 数据库连接与建表 ==========

def _get_db_connection():
    """获取数据库连接"""
    return psycopg2.connect(**ConsultantDatabaseConfig.get_connection_params())


def _create_quota_tables_if_not_exists():
    """创建名额管理相关表（如果不存在），保持幂等。

    - enterprise_quota: 名额主表，available_count 使用生成列保证 = total_count - used_count
    - enterprise_quota_usage: 名额使用记录表
    """
    conn = None
    try:
        conn = _get_db_connection()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS enterprise_quota (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    quota_code VARCHAR(50) UNIQUE NOT NULL,
                    quota_type VARCHAR(50) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    description TEXT,
                    total_count INT NOT NULL,
                    used_count INT NOT NULL DEFAULT 0,
                    available_count INT GENERATED ALWAYS AS (total_count - used_count) STORED,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
                    created_by UUID REFERENCES enterprise_users(id) ON DELETE SET NULL,
                    reviewed_by UUID REFERENCES enterprise_users(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_quota_type ON enterprise_quota(quota_type);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_quota_status ON enterprise_quota(status);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_enterprise_quota_created_by ON enterprise_quota(created_by);")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS enterprise_quota_usage (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    quota_id UUID NOT NULL REFERENCES enterprise_quota(id) ON DELETE CASCADE,
                    quota_code VARCHAR(50),
                    used_by UUID NOT NULL REFERENCES enterprise_users(id) ON DELETE RESTRICT,
                    target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
                    target_user_name VARCHAR(100),
                    usage_note TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending_review',
                    reviewed_by UUID REFERENCES enterprise_users(id) ON DELETE SET NULL,
                    reviewed_at TIMESTAMP,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quota_usage_quota_id ON enterprise_quota_usage(quota_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quota_usage_used_by ON enterprise_quota_usage(used_by);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_quota_usage_status ON enterprise_quota_usage(status);")
        logger.info("[规划师端] 名额管理表已就绪 (enterprise_quota / enterprise_quota_usage)")
    except Exception as e:
        logger.error(f"[规划师端] 创建名额管理表失败: {e}")
        raise
    finally:
        if conn:
            conn.close()


# 表在服务启动时由 server._init_database() 调用 _create_quota_tables_if_not_exists() 创建，
# 此处不在模块顶层建表，以避免在 .env 未加载（连到错误数据库）或依赖表未就绪时导入失败。


# ========== 编码生成 ==========

def _generate_quota_code(cur) -> str:
    """生成名额编码：QT-YYYY-XXXXX

    规则：QT 前缀 + 当前年份 + 5位递增序号（从 00001 开始）。
    通过查询当前年份已有最大序号 +1 实现，配合 quota_code 的 UNIQUE 约束保证唯一性。
    应在事务内调用以避免并发冲突。

    Args:
        cur: 已开启事务的游标（普通 cursor 或 RealDictCursor 均可）

    Returns:
        形如 "QT-2026-00001" 的编码字符串
    """
    year = datetime.now().year
    prefix = f"QT-{year}-"
    # 查询当前年份最大序号；按字符串排序取最大值（5位定长序号可正确排序）
    cur.execute(
        "SELECT quota_code FROM enterprise_quota WHERE quota_code LIKE %s ORDER BY quota_code DESC LIMIT 1",
        (prefix + "%",),
    )
    row = cur.fetchone()
    if row is None:
        seq = 1
    else:
        # 兼容 RealDictCursor 和普通 cursor
        code = row["quota_code"] if isinstance(row, dict) else row[0]
        try:
            seq = int(code[len(prefix):]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}{seq:05d}"


# 阶段2数据库异步化：异步版名额编码生成（使用 asyncpg 连接，在事务内调用）
async def _async_generate_quota_code(conn) -> str:
    """生成名额编码：QT-YYYY-XXXXX（异步版）

    与同步 _generate_quota_code 行为一致，使用 asyncpg 连接执行查询。
    应在事务内调用以避免并发冲突。

    Args:
        conn: asyncpg 连接（已在事务中）

    Returns:
        形如 "QT-2026-00001" 的编码字符串
    """
    year = datetime.now().year
    prefix = f"QT-{year}-"
    row = await conn.fetchrow(
        "SELECT quota_code FROM enterprise_quota WHERE quota_code LIKE $1 ORDER BY quota_code DESC LIMIT 1",
        prefix + "%",
    )
    if row is None:
        seq = 1
    else:
        code = row["quota_code"]
        try:
            seq = int(code[len(prefix):]) + 1
        except (ValueError, IndexError):
            seq = 1
    return f"{prefix}{seq:05d}"


# ========== 序列化辅助 ==========

def _serialize(row, extra_fields: Optional[dict] = None) -> dict:
    """将数据库行（RealDictRow/dict）序列化为 JSON 可返回的字典，处理 UUID/时间等类型。"""
    if row is None:
        return None
    data = dict(row)
    # 统一转换 UUID/datetime 为字符串
    for k, v in data.items():
        if isinstance(v, uuid.UUID):
            data[k] = str(v)
        elif isinstance(v, datetime):
            data[k] = v.isoformat()
    if extra_fields:
        data.update(extra_fields)
    return data


# ========== API 接口 ==========

@router.get("/api/quota")
async def list_quotas(
    quota_type: Optional[str] = Query(None, description="按名额类型筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取名额列表（支持按类型、状态筛选）

    注意：名额数据会变化，查询结果不写入 Redis 缓存。
    """
    # 阶段2数据库异步化：使用 asyncpg 异步连接池，不再用 asyncio.to_thread 包装同步 psycopg2 调用
    # 动态构建 $1, $2, ... 占位符（asyncpg 风格），按参数顺序编号
    try:
        where_parts = []
        params = []
        idx = 1
        if quota_type:
            where_parts.append(f"quota_type = ${idx}")
            params.append(quota_type)
            idx += 1
        if status:
            where_parts.append(f"status = ${idx}")
            params.append(status)
            idx += 1

        where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""
        limit_idx = idx
        offset_idx = idx + 1
        sql = (
            f"SELECT * FROM enterprise_quota{where_sql} "
            f"ORDER BY created_at DESC LIMIT ${limit_idx} OFFSET ${offset_idx}"
        )
        rows = await AsyncDatabasePool.execute_query(sql, *params, limit, offset)
        return {"items": [_serialize(r) for r in rows], "total": len(rows)}
    except Exception as e:
        logger.error(f"[规划师端] 获取名额列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取名额列表失败: {str(e)}")


@router.post("/api/quota")
async def create_quota(
    request: CreateQuotaRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """创建名额（自动生成编码，状态为 pending_review）

    流程：创建后处于待审核状态，需经审核通过后变为 active 才能被使用。
    """
    # 阶段2数据库异步化：使用 asyncpg 事务保证编码生成与插入的原子性，不再用 asyncio.to_thread 包装同步调用
    user_id = current_user["user_id"]
    try:
        pool = await AsyncDatabasePool.get_pool()
        async with pool.acquire() as conn:
            # 编码生成 + 插入在同一事务内，避免并发冲突
            async with conn.transaction():
                quota_code = await _async_generate_quota_code(conn)
                row = await conn.fetchrow(
                    """
                    INSERT INTO enterprise_quota
                        (quota_code, quota_type, title, description, total_count, used_count, status, created_by)
                    VALUES
                        ($1, $2, $3, $4, $5, 0, 'pending_review', $6)
                    RETURNING *
                    """,
                    quota_code,
                    request.quota_type,
                    request.title,
                    request.description,
                    request.total_count,
                    user_id,
                )
        logger.info(
            f"[规划师端] 创建名额: code={quota_code}, type={request.quota_type}, "
            f"total={request.total_count}, created_by={user_id}"
        )
        return _serialize(dict(row))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 创建名额失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建名额失败: {str(e)}")


@router.get("/api/quota/{quota_id}")
async def get_quota(
    quota_id: str,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取单个名额详情"""
    # 阶段2数据库异步化：使用 asyncpg 异步连接池，不再用 asyncio.to_thread 包装同步调用
    try:
        # 校验 UUID 格式
        try:
            uuid.UUID(quota_id)
        except Exception:
            raise HTTPException(status_code=400, detail="quota_id 不是合法的 UUID")

        row = await AsyncDatabasePool.execute_one(
            "SELECT * FROM enterprise_quota WHERE id = $1",
            quota_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="名额不存在")
        return _serialize(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 获取名额详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取名额详情失败: {str(e)}")


@router.put("/api/quota/{quota_id}/review")
async def review_quota(
    quota_id: str,
    request: ReviewQuotaRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """审核名额（human-in-the-loop）

    - approve: pending_review -> active（批准并激活，可被使用）
    - reject:  pending_review -> closed（拒绝并关闭）
    """
    # 阶段2数据库异步化：使用 asyncpg 事务保证 FOR UPDATE + UPDATE 原子性，不再用 asyncio.to_thread 包装同步调用
    try:
        try:
            uuid.UUID(quota_id)
        except Exception:
            raise HTTPException(status_code=400, detail="quota_id 不是合法的 UUID")

        reviewer_id = current_user["user_id"]
        pool = await AsyncDatabasePool.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 锁定名额行，校验状态
                row = await conn.fetchrow(
                    "SELECT id, status, title, quota_code FROM enterprise_quota WHERE id = $1 FOR UPDATE",
                    quota_id,
                )
                if row is None:
                    raise HTTPException(status_code=404, detail="名额不存在")

                current_status = row["status"]
                if current_status != "pending_review":
                    raise HTTPException(
                        status_code=400,
                        detail=f"当前状态为 {current_status}，仅 pending_review 状态可审核",
                    )

                new_status = "active" if request.action == "approve" else "closed"
                updated = await conn.fetchrow(
                    """
                    UPDATE enterprise_quota
                    SET status = $1, reviewed_by = $2, reviewed_at = NOW(), updated_at = NOW()
                    WHERE id = $3
                    RETURNING *
                    """,
                    new_status, reviewer_id, quota_id,
                )
        # 事务提交成功后记录日志
        logger.info(
            f"[规划师端] 审核名额: code={row['quota_code']}, action={request.action}, "
            f"{current_status}->{new_status}, reviewer={reviewer_id}"
        )
        return _serialize(dict(updated), {"action": request.action})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 审核名额失败: {e}")
        raise HTTPException(status_code=500, detail=f"审核名额失败: {str(e)}")


@router.post("/api/quota/{quota_id}/use")
async def use_quota(
    quota_id: str,
    request: UseQuotaRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """使用名额（记录使用信息，状态为 pending_review）

    要求名额状态为 active 且有剩余可用数量。
    创建使用记录后需经审核通过才会真正扣减 used_count。
    """
    # 阶段2数据库异步化：使用 asyncpg 事务保证 FOR UPDATE + INSERT 原子性，不再用 asyncio.to_thread 包装同步调用
    try:
        try:
            uuid.UUID(quota_id)
        except Exception:
            raise HTTPException(status_code=400, detail="quota_id 不是合法的 UUID")

        user_id = current_user["user_id"]
        pool = await AsyncDatabasePool.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 锁定名额行，校验状态与可用数量
                quota = await conn.fetchrow(
                    "SELECT id, quota_code, status, total_count, used_count, available_count "
                    "FROM enterprise_quota WHERE id = $1 FOR UPDATE",
                    quota_id,
                )
                if quota is None:
                    raise HTTPException(status_code=404, detail="名额不存在")

                if quota["status"] != "active":
                    raise HTTPException(
                        status_code=400,
                        detail=f"名额当前状态为 {quota['status']}，仅 active 状态可使用",
                    )
                if quota["available_count"] <= 0:
                    raise HTTPException(status_code=400, detail="名额剩余可用数量为 0，无法使用")

                # 创建使用记录（待审核）；不立即扣减 used_count
                usage = await conn.fetchrow(
                    """
                    INSERT INTO enterprise_quota_usage
                        (quota_id, quota_code, used_by, target_user_id, target_user_name, usage_note, status)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, 'pending_review')
                    RETURNING *
                    """,
                    quota_id,
                    quota["quota_code"],
                    user_id,
                    request.target_user_id,
                    request.target_user_name,
                    request.usage_note,
                )
        # 事务提交成功后记录日志
        logger.info(
            f"[规划师端] 使用名额申请: quota_code={quota['quota_code']}, used_by={user_id}, "
            f"target={request.target_user_name}"
        )
        return _serialize(dict(usage))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 使用名额失败: {e}")
        raise HTTPException(status_code=500, detail=f"使用名额失败: {str(e)}")


@router.put("/api/quota/usage/{usage_id}/review")
async def review_quota_usage(
    usage_id: str,
    request: ReviewUsageRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """审核名额使用（approve/reject，human-in-the-loop）

    - approve: 使用记录 status -> approved，并扣减对应名额 used_count +1；
               若扣减后 used_count 达到 total_count，名额状态变为 exhausted。
    - reject:  使用记录 status -> rejected，不扣减数量。
    仅 pending_review 状态的使用记录可审核。
    """
    # 阶段2数据库异步化：使用 asyncpg 事务保证多表锁定与更新的原子性，不再用 asyncio.to_thread 包装同步调用
    try:
        try:
            uuid.UUID(usage_id)
        except Exception:
            raise HTTPException(status_code=400, detail="usage_id 不是合法的 UUID")

        reviewer_id = current_user["user_id"]
        pool = await AsyncDatabasePool.get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # 锁定使用记录
                usage = await conn.fetchrow(
                    "SELECT * FROM enterprise_quota_usage WHERE id = $1 FOR UPDATE",
                    usage_id,
                )
                if usage is None:
                    raise HTTPException(status_code=404, detail="名额使用记录不存在")

                if usage["status"] != "pending_review":
                    raise HTTPException(
                        status_code=400,
                        detail=f"使用记录当前状态为 {usage['status']}，仅 pending_review 状态可审核",
                    )

                new_status = "approved" if request.action == "approve" else "rejected"

                if request.action == "approve":
                    # 锁定名额行并扣减数量
                    quota = await conn.fetchrow(
                        "SELECT id, quota_code, total_count, used_count, status "
                        "FROM enterprise_quota WHERE id = $1 FOR UPDATE",
                        usage["quota_id"],
                    )
                    if quota is None:
                        raise HTTPException(status_code=404, detail="关联名额不存在")
                    if quota["status"] not in ("active", "exhausted"):
                        raise HTTPException(
                            status_code=400,
                            detail=f"名额当前状态为 {quota['status']}，无法批准使用",
                        )
                    if quota["used_count"] + 1 > quota["total_count"]:
                        raise HTTPException(status_code=400, detail="名额已用完，无法批准使用")

                    new_used = quota["used_count"] + 1
                    # 用完则置为 exhausted，否则保持 active
                    quota_new_status = "exhausted" if new_used >= quota["total_count"] else "active"
                    await conn.execute(
                        """
                        UPDATE enterprise_quota
                        SET used_count = $1, status = $2, updated_at = NOW()
                        WHERE id = $3
                        """,
                        new_used, quota_new_status, quota["id"],
                    )

                # 更新使用记录状态
                updated_usage = await conn.fetchrow(
                    """
                    UPDATE enterprise_quota_usage
                    SET status = $1, reviewed_by = $2, reviewed_at = NOW()
                    WHERE id = $3
                    RETURNING *
                    """,
                    new_status, reviewer_id, usage_id,
                )
        # 事务提交成功后记录日志
        logger.info(
            f"[规划师端] 审核名额使用: usage_id={usage_id}, action={request.action}, "
            f"reviewer={reviewer_id}"
        )
        return _serialize(dict(updated_usage), {"action": request.action})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 审核名额使用失败: {e}")
        raise HTTPException(status_code=500, detail=f"审核名额使用失败: {str(e)}")


@router.get("/api/quota/{quota_id}/usage")
async def list_quota_usage(
    quota_id: str,
    status: Optional[str] = Query(None, description="按使用状态筛选"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取指定名额的使用记录列表"""
    # 阶段2数据库异步化：使用 asyncpg 异步连接池，不再用 asyncio.to_thread 包装同步调用
    # 动态构建 $1, $2, ... 占位符（asyncpg 风格），按参数顺序编号
    try:
        try:
            uuid.UUID(quota_id)
        except Exception:
            raise HTTPException(status_code=400, detail="quota_id 不是合法的 UUID")

        # 校验名额存在
        quota = await AsyncDatabasePool.execute_one(
            "SELECT id, quota_code FROM enterprise_quota WHERE id = $1",
            quota_id,
        )
        if quota is None:
            raise HTTPException(status_code=404, detail="名额不存在")

        # 动态构建 WHERE 子句与占位符编号
        # $1 固定为 quota_id，$2 可选为 status，$3/$4 为 limit/offset
        params = [quota_id]
        where_parts = ["quota_id = $1"]
        idx = 2
        if status:
            where_parts.append(f"status = ${idx}")
            params.append(status)
            idx += 1

        limit_idx = idx
        offset_idx = idx + 1
        where_sql = " AND ".join(where_parts)
        sql = (
            f"SELECT * FROM enterprise_quota_usage WHERE {where_sql} "
            f"ORDER BY created_at DESC LIMIT ${limit_idx} OFFSET ${offset_idx}"
        )
        rows = await AsyncDatabasePool.execute_query(sql, *params, limit, offset)
        return {
            "quota_id": str(quota["id"]),
            "quota_code": quota["quota_code"],
            "items": [_serialize(r) for r in rows],
            "total": len(rows),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 获取名额使用记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取名额使用记录失败: {str(e)}")
