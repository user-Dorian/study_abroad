"""规划师端绑定请求API路由 - 提规划师发送和管理绑定请求的接口

严格按照架构师设计实现：
1. POST /api/consultant/binding-requests - 发送绑定请求
2. GET /api/consultant/binding-requests - 查看绑定请求列表

绩效导师高标准要求：
- 完整的状态验证和权限检查
- 完整的错误处理（参数校验、业务逻辑、数据库操作）
- 集成通知机制
- 详细的日志记录
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi import Header as FastAPIHeader
from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime

from common.utils.logger import logger
from common.binding_request_repository import get_binding_request_repo
from common.consultant.repository import AsyncConsultantRelationRepository
from common.utils.online_status import publish_notification, add_pending_notification

router = APIRouter()


# ===== 请求模型定义 =====

class SendBindingRequest(BaseModel):
    """发送绑定请求模型"""
    user_id: str
    message: Optional[str] = None

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("目标用户ID不能为空")
        return v.strip()

    @field_validator("message")
    @classmethod
    def validate_message(cls, v):
        if v and len(v) > 500:
            raise ValueError("绑定请求说明不能超过500字")
        return v


# ===== 认证依赖 =====

def _get_current_user_from_header(
    authorization: str = FastAPIHeader(None, description="Bearer token")
):
    """从请求头获取当前用户（用于需要认证的接口）"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]

    if not token:
        raise HTTPException(status_code=401, detail="无效的认证令牌格式")

    from common.utils.auth import decode_access_token
    from consultant.config.settings import ConsultantConfig

    try:
        payload = decode_access_token(
            token,
            ConsultantConfig.JWT_SECRET_KEY,
            ConsultantConfig.JWT_ALGORITHM
        )
        if payload is None:
            raise HTTPException(status_code=401, detail="无效的认证令牌")

        # 验证角色必须是规划师
        role = payload.get("role", "client")
        if role != "consultant":
            raise HTTPException(
                status_code=403,
                detail="权限不足：只有规划师可以发送绑定请求"
            )

        return {
            "user_id": payload.get("user_id"),
            "username": payload.get("sub"),
            "role": role,
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"认证失败: {str(e)}")


# ===== 仓库实例 =====

_relation_repo = None

def get_relation_repo() -> AsyncConsultantRelationRepository:
    """获取规划师关系仓库单例"""
    global _relation_repo
    if _relation_repo is None:
        _relation_repo = AsyncConsultantRelationRepository()
    return _relation_repo


# ===== API接口实现 =====

@router.post("/api/consultant/binding-requests")
async def send_binding_request(
    request: SendBindingRequest,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """发送绑定请求 - 规划师向用户发送绑定请求

    业务逻辑：
    1. 检查是否已有待处理请求（同一用户）
    2. 检查目标用户是否已被其他规划师绑定
    3. 创建绑定请求（status='pending')
    4. 发送通知给用户

    Args:
        request: 绑定请求信息（user_id, message）
        current_user: 当前认证用户信息

    Returns:
        dict: 创建的绑定请求对象

    Raises:
        HTTPException:
            - 409: 已存在待处理请求
            - 400: 目标用户已被其他规划师绑定
            - 403: 规划师不能给自己发送请求
    """
    consultant_id = current_user["user_id"]
    consultant_username = current_user["username"]
    target_user_id = request.user_id
    message = request.message

    logger.info(
        f"[规划师端] 发送绑定请求: consultant={consultant_username}, "
        f"target_user={target_user_id}"
    )

    # ===== 步骤1: 检查是否给自己发送请求 =====
    if consultant_id == target_user_id:
        logger.warning(
            f"[规划师端] 规划师尝试绑定自己: consultant_id={consultant_id}"
        )
        raise HTTPException(
            status_code=400,
            detail="不能向自己发送绑定请求"
        )

    # ===== 步骤2: 检查是否已有待处理请求 =====
    try:
        binding_repo = get_binding_request_repo()
        pending_requests = await binding_repo.get_requests_by_consultant(
            consultant_id=consultant_id,
            status="pending"
        )

        # 检查是否存在针对同一用户的待处理请求
        for req in pending_requests:
            if req["user_id"] == target_user_id:
                logger.warning(
                    f"[规划师端] 已存在待处理请求: consultant={consultant_id}, "
                    f"user={target_user_id}, request_id={req['id']}"
                )
                raise HTTPException(
                    status_code=409,
                    detail="已存在针对该用户的待处理绑定请求，请等待用户处理或取消旧请求"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[规划师端] 查询待处理请求失败: consultant={consultant_id}, "
            f"error={e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"查询绑定请求失败: {str(e)}"
        )

    # ===== 步骤3: 检查目标用户是否已被其他规划师绑定 =====
    try:
        relation_repo = get_relation_repo()
        existing_relation = await relation_repo.get_active_relation_by_user(
            target_user_id
        )

        if existing_relation:
            existing_consultant = existing_relation.get("consultant_id")
            logger.warning(
                f"[规划师端] 用户已被其他规划师绑定: user={target_user_id}, "
                f"bound_consultant={existing_consultant}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"目标用户已被其他规划师绑定，用户需要先释放旧绑定才能接受新请求"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"[规划师端] 查询用户绑定关系失败: user={target_user_id}, "
            f"error={e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"查询用户绑定关系失败: {str(e)}"
        )

    # ===== 步骤4: 创建绑定请求 =====
    try:
        binding_request = await binding_repo.create_request(
            consultant_id=consultant_id,
            user_id=target_user_id,
            message=message,
            expires_days=7  # 默认7天有效期
        )

        logger.info(
            f"[规划师端] 绑定请求创建成功: request_id={binding_request['id']}, "
            f"consultant={consultant_id}, user={target_user_id}"
        )

    except Exception as e:
        error_msg = str(e)

        # 解析数据库约束错误
        if "unique_pending_request" in error_msg:
            logger.warning(
                f"[规划师端] 触发唯一约束: consultant={consultant_id}, "
                f"user={target_user_id}"
            )
            raise HTTPException(
                status_code=409,
                detail="已存在针对该用户的待处理绑定请求"
            )
        elif "check_not_self_request" in error_msg:
            logger.warning(
                f"[规划师端] 触发自绑约束: consultant={consultant_id}"
            )
            raise HTTPException(
                status_code=400,
                detail="不能向自己发送绑定请求"
            )
        else:
            logger.error(
                f"[规划师端] 创建绑定请求失败: consultant={consultant_id}, "
                f"user={target_user_id}, error={e}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"创建绑定请求失败: {str(e)}"
            )

    # ===== 步骤5: 发送通知给用户 =====
    try:
        # 构造通知内容
        notification = {
            "type": "binding_request",
            "request_id": binding_request["id"],
            "consultant_id": consultant_id,
            "consultant_username": consultant_username,
            "message": message,
            "created_at": binding_request["created_at"],
            "expires_at": binding_request["expires_at"],
            "timestamp": datetime.utcnow().isoformat(),
        }

        # 发送实时通知（如果用户在线）
        await publish_notification(target_user_id, notification)

        # 同时存储持久化通知（如果用户离线）
        await add_pending_notification(target_user_id, notification)

        logger.info(
            f"[规划师端] 绑定请求通知已发送: user={target_user_id}, "
            f"request_id={binding_request['id']}"
        )

    except Exception as e:
        # 通知发送失败不影响请求创建，只记录日志
        logger.warning(
            f"[规划师端] 发送绑定请求通知失败: user={target_user_id}, "
            f"error={e}, request_id={binding_request['id']}"
        )

    # ===== 返回响应 =====
    return {
        "id": binding_request["id"],
        "consultant_id": binding_request["consultant_id"],
        "user_id": binding_request["user_id"],
        "status": binding_request["status"],
        "message": binding_request["message"],
        "created_at": binding_request["created_at"],
        "expires_at": binding_request["expires_at"],
    }


@router.get("/api/consultant/binding-requests")
async def list_binding_requests(
    status: Optional[str] = Query(
        None,
        description="请求状态过滤：pending/accepted/rejected/expired/all"
    ),
    current_user: dict = Depends(_get_current_user_from_header),
):
    """查看我的绑定请求列表 - 规划师查看自己发送的所有绑定请求

    Args:
        status: 请求状态过滤（可选）
        current_user: 当前认证用户信息

    Returns:
        list: 绑定请求列表（包含用户信息）

    Raises:
        HTTPException:
            - 400: 无效的状态参数
            - 500: 数据库查询失败
    """
    consultant_id = current_user["user_id"]
    consultant_username = current_user["username"]

    logger.info(
        f"[规划师端] 查询绑定请求列表: consultant={consultant_username}, "
        f"status={status or 'all'}"
    )

    # ===== 步骤1: 验证状态参数 =====
    valid_statuses = ["pending", "accepted", "rejected", "expired", "all"]
    if status and status not in valid_statuses:
        logger.warning(
            f"[规划师端] 无效的状态参数: status={status}, "
            f"valid_values={valid_statuses}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态参数，可选值: {', '.join(valid_statuses)}"
        )

    # ===== 步骤2: 查询绑定请求列表 =====
    try:
        binding_repo = get_binding_request_repo()

        # 如果status是'all'或None，则查询所有状态
        query_status = None if (status == "all" or status is None) else status

        requests = await binding_repo.get_requests_by_consultant(
            consultant_id=consultant_id,
            status=query_status
        )

        logger.info(
            f"[规划师端] 绑定请求列表查询成功: consultant={consultant_id}, "
            f"status={query_status or 'all'}, count={len(requests)}"
        )

        return requests

    except Exception as e:
        logger.error(
            f"[规划师端] 查询绑定请求列表失败: consultant={consultant_id}, "
            f"status={status}, error={e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"查询绑定请求列表失败: {str(e)}"
        )


@router.delete("/api/consultant/binding-requests/{request_id}")
async def cancel_binding_request(
    request_id: str,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """取消绑定请求 - 规划师取消自己发送的待处理绑定请求

    Args:
        request_id: 请求ID
        current_user: 当前认证用户信息

    Returns:
        dict: 取消结果

    Raises:
        HTTPException:
            - 403: 请求不属于当前规划师
            - 400: 请求已处理或不存在
            - 500: 数据库操作失败
    """
    consultant_id = current_user["user_id"]
    consultant_username = current_user["username"]

    logger.info(
        f"[规划师端] 取消绑定请求: consultant={consultant_username}, "
        f"request_id={request_id}"
    )

    # ===== 取消绑定请求 =====
    try:
        binding_repo = get_binding_request_repo()
        success = await binding_repo.cancel_request(request_id, consultant_id)

        if not success:
            logger.warning(
                f"[规划师端] 取消绑定请求失败: request_id={request_id}, "
                f"consultant={consultant_id}"
            )
            raise HTTPException(
                status_code=400,
                detail="取消失败：请求不存在、已处理或不属于您"
            )

        logger.info(
            f"[规划师端] 绑定请求取消成功: request_id={request_id}, "
            f"consultant={consultant_id}"
        )

        return {
            "success": True,
            "message": "绑定请求已取消",
        }

    except ValueError as e:
        logger.warning(
            f"[规划师端] 取消绑定请求验证失败: request_id={request_id}, "
            f"error={e}"
        )
        raise HTTPException(
            status_code=403,
            detail="请求归属错误：该请求不属于您"
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(
            f"[规划师端] 取消绑定请求异常: request_id={request_id}, "
            f"consultant={consultant_id}, error={e}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"取消绑定请求失败: {str(e)}"
        )