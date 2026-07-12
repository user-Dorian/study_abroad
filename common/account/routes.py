"""
账户管理 API 路由 - 注销/恢复/状态查询

【设计原则】
- 软删除: 30 天可恢复,保留所有数据
- 密码二次确认: 防止误操作/恶意注销
- 审计日志: 全部操作记录
- 双端通用: 同时供 client 和 consultant 调用

【接口列表】
- POST /api/account/cancel: 软注销(需密码验证)
- POST /api/account/restore: 恢复软注销账户
- POST /api/account/permanent: 永久注销
- GET /api/account/deletion-status: 查询注销状态

【数据来源】
设计方案: 架构师 P0 方案 v1.0
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from common.utils.auth import require_user, verify_password
from common.utils.logger import logger
from common.config.async_database import AsyncDatabasePool
from common.config.async_redis import AsyncRedisPool

router = APIRouter(prefix="/api/account", tags=["account"])

# 软删除恢复期限(天)
SOFT_DELETE_RESTORE_DAYS = 30


# ============================
# Pydantic Models
# ============================
class CancelRequest(BaseModel):
    """注销请求"""
    password: str = Field(..., min_length=6, description="登录密码,用于二次确认")
    reason: Optional[str] = Field(None, max_length=500, description="注销原因(可选)")
    confirm: bool = Field(..., description="必须为 True,二次确认标记")


class RestoreRequest(BaseModel):
    """恢复请求"""
    password: str = Field(..., min_length=6, description="登录密码,用于二次确认")


# ============================
# API Endpoints
# ============================
@router.post("/cancel")
async def cancel_account(
    request: CancelRequest,
    current_user: dict = Depends(require_user),
):
    """
    软注销账户(30天可恢复)

    1. 验证密码
    2. 检查是否已注销
    3. 设置 is_deleted=TRUE, deletion_deadline=NOW+30天
    4. 写审计日志
    5. 标记 Redis 在线状态为离线
    """
    user_id = current_user["user_id"]

    # 1. 验证密码
    user_row = await AsyncDatabasePool.execute_one(
        "SELECT password_hash, is_deleted FROM users WHERE id = $1",
        user_id,
    )
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not verify_password(request.password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="密码错误")

    # 2. 检查是否已注销
    if user_row.get("is_deleted"):
        raise HTTPException(status_code=400, detail="账户已注销,请勿重复操作")

    # 3. 二次确认校验
    if not request.confirm:
        raise HTTPException(status_code=400, detail="需要二次确认(confirm=true)")

    # 计算恢复截止时间
    now = datetime.utcnow()
    restore_deadline = now + timedelta(days=SOFT_DELETE_RESTORE_DAYS)

    try:
        # 4. 软注销: 更新 users + user_profiles
        await AsyncDatabasePool.execute_command(
            """UPDATE users
               SET is_deleted = TRUE,
                   deleted_at = $1,
                   deletion_deadline = $2
               WHERE id = $3""",
            now, restore_deadline, user_id,
        )

        await AsyncDatabasePool.execute_command(
            """UPDATE user_profiles
               SET is_deleted = TRUE, deleted_at = $1
               WHERE user_id = $2""",
            now, user_id,
        )

        # 5. 写审计日志
        await AsyncDatabasePool.execute_command(
            """INSERT INTO account_deletion_log
               (user_id, deletion_type, reason, status, restore_deadline)
               VALUES ($1, 'soft', $2, 'pending', $3)""",
            user_id, request.reason, restore_deadline,
        )

        # 6. 标记离线(Redis)
        try:
            from common.utils.online_status import mark_offline
            await mark_offline(str(user_id))
        except Exception as e:
            logger.warning(f"标记离线失败(非阻塞): {e}")

        logger.info(f"[账户注销] 软注销成功: user_id={user_id}, deadline={restore_deadline}")
        return {
            "success": True,
            "deletion_type": "soft",
            "restore_deadline": str(restore_deadline),
            "message": f"账户已注销,{SOFT_DELETE_RESTORE_DAYS}天内可登录恢复",
            "restore_days": SOFT_DELETE_RESTORE_DAYS,
        }

    except Exception as e:
        logger.error(f"[账户注销] 失败: user_id={user_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"注销失败: {str(e)}")


@router.post("/restore")
async def restore_account(
    request: RestoreRequest,
    current_user: dict = Depends(require_user),
):
    """
    恢复软注销账户(在30天内)
    """
    user_id = current_user["user_id"]

    # 1. 验证密码
    user_row = await AsyncDatabasePool.execute_one(
        """SELECT password_hash, is_deleted, deletion_deadline
           FROM users WHERE id = $1""",
        user_id,
    )
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not verify_password(request.password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="密码错误")

    if not user_row.get("is_deleted"):
        raise HTTPException(status_code=400, detail="账户未注销,无需恢复")

    # 2. 检查是否超过恢复期限
    deadline = user_row.get("deletion_deadline")
    if deadline and datetime.utcnow() > deadline:
        raise HTTPException(
            status_code=400,
            detail=f"已超过恢复期限({deadline}),账户已被永久删除",
        )

    try:
        # 3. 恢复 users + user_profiles
        await AsyncDatabasePool.execute_command(
            """UPDATE users
               SET is_deleted = FALSE,
                   deleted_at = NULL,
                   deletion_deadline = NULL
               WHERE id = $1""",
            user_id,
        )

        await AsyncDatabasePool.execute_command(
            """UPDATE user_profiles
               SET is_deleted = FALSE, deleted_at = NULL
               WHERE user_id = $1""",
            user_id,
        )

        # 4. 更新审计日志
        await AsyncDatabasePool.execute_command(
            """UPDATE account_deletion_log
               SET status = 'restored', updated_at = NOW()
               WHERE user_id = $1 AND status = 'pending'""",
            user_id,
        )

        logger.info(f"[账户恢复] 成功: user_id={user_id}")
        return {"success": True, "message": "账户已恢复,欢迎回来!"}

    except Exception as e:
        logger.error(f"[账户恢复] 失败: user_id={user_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"恢复失败: {str(e)}")


@router.post("/permanent")
async def permanent_delete_account(
    request: CancelRequest,
    current_user: dict = Depends(require_user),
):
    """
    永久注销账户(不可恢复)

    - 软删除标记保留审计
    - 实际数据不物理删除(为审计保留)
    - 设置 is_deleted=TRUE 且 is_anonymized=TRUE(匿名化)
    """
    user_id = current_user["user_id"]

    # 1. 验证密码
    user_row = await AsyncDatabasePool.execute_one(
        "SELECT password_hash, is_deleted FROM users WHERE id = $1",
        user_id,
    )
    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not verify_password(request.password, user_row["password_hash"]):
        raise HTTPException(status_code=401, detail="密码错误")

    if not request.confirm:
        raise HTTPException(status_code=400, detail="需要二次确认(confirm=true)")

    try:
        now = datetime.utcnow()

        # 2. 永久注销: 标记 + 匿名化
        await AsyncDatabasePool.execute_command(
            """UPDATE users
               SET is_deleted = TRUE,
                   deleted_at = $1,
                   username = 'deleted_' || id::text,
                   email = '',
                   password_hash = '',
                   display_name = '已注销用户'
               WHERE id = $2""",
            now, user_id,
        )

        # 3. 匿名化个人资料
        await AsyncDatabasePool.execute_command(
            """UPDATE user_profiles
               SET is_deleted = TRUE, deleted_at = $1,
                   phone = NULL, real_name = NULL,
                   city = NULL, bio = NULL
               WHERE user_id = $2""",
            now, user_id,
        )

        # 4. 写审计日志(永久)
        await AsyncDatabasePool.execute_command(
            """INSERT INTO account_deletion_log
               (user_id, deletion_type, reason, status, restore_deadline)
               VALUES ($1, 'hard', $2, 'completed', NULL)""",
            user_id, request.reason,
        )

        # 5. 标记离线
        try:
            from common.utils.online_status import mark_offline
            await mark_offline(str(user_id))
        except Exception as e:
            logger.warning(f"标记离线失败(非阻塞): {e}")

        logger.info(f"[账户永久注销] 成功: user_id={user_id}")
        return {
            "success": True,
            "deletion_type": "hard",
            "message": "账户已永久注销,数据已匿名化",
        }

    except Exception as e:
        logger.error(f"[账户永久注销] 失败: user_id={user_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"永久注销失败: {str(e)}")


@router.get("/deletion-status")
async def get_deletion_status(
    current_user: dict = Depends(require_user),
):
    """
    查询当前用户的注销状态

    返回:
    - is_deleted: 是否已注销
    - deletion_type: soft(可恢复) / hard(不可恢复) / null(未注销)
    - restore_deadline: 恢复截止时间(soft 状态时)
    - days_remaining: 剩余恢复天数
    """
    user_id = current_user["user_id"]

    user_row = await AsyncDatabasePool.execute_one(
        """SELECT is_deleted, deleted_at, deletion_deadline
           FROM users WHERE id = $1""",
        user_id,
    )

    if not user_row:
        raise HTTPException(status_code=404, detail="用户不存在")

    is_deleted = user_row.get("is_deleted", False)
    deadline = user_row.get("deletion_deadline")
    deleted_at = user_row.get("deleted_at")

    if not is_deleted:
        return {
            "is_deleted": False,
            "deletion_type": None,
            "can_restore": False,
            "days_remaining": 0,
        }

    # 查询最新的注销日志判断类型
    log_row = await AsyncDatabasePool.execute_one(
        """SELECT deletion_type, status
           FROM account_deletion_log
           WHERE user_id = $1
           ORDER BY created_at DESC LIMIT 1""",
        user_id,
    )

    deletion_type = log_row["deletion_type"] if log_row else "soft"
    days_remaining = 0
    if deletion_type == "soft" and deadline:
        remaining = deadline - datetime.utcnow()
        days_remaining = max(0, remaining.days)

    return {
        "is_deleted": True,
        "deletion_type": deletion_type,
        "deleted_at": str(deleted_at) if deleted_at else None,
        "restore_deadline": str(deadline) if deadline else None,
        "days_remaining": days_remaining,
        "can_restore": deletion_type == "soft" and days_remaining > 0,
    }
