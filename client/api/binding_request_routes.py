"""用户端绑定请求审批 API 路由

严格按照架构师的设计方案实现：
1. GET /api/client/binding-requests - 查看待处理绑定请求
2. POST /api/client/binding-requests/{request_id}/accept - 接受绑定请求
3. POST /api/client/binding-requests/{request_id}/reject - 拒绝绑定请求
4. POST /api/client/planner/release - 释放规划师（解除绑定）
5. GET /api/client/planner/current - 查询当前绑定的规划师

业务逻辑要点：
- 状态验证：请求状态、请求归属、绑定关系冲突
- 错误处理：每种错误都要有清晰的用户提示
- 通知机制：接受/拒绝时通知规划师
- 事务处理：accept接口使用Repository层的事务处理（并发安全）
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from common.utils.auth import require_user
from common.utils.logger import logger
from common.utils.online_status import publish_notification
from common.binding_request_repository import get_binding_request_repo
from common.consultant.repository import get_consultant_relation_repo
from common.config.async_database import AsyncDatabasePool


router = APIRouter(prefix="/api/client", tags=["client-binding"])


# ====== Pydantic 请求/响应模型 ======

class BindingRequestInfo(BaseModel):
    """绑定请求信息"""
    id: str
    consultant_id: str
    consultant_name: Optional[str] = None
    consultant_display_name: Optional[str] = None
    user_id: str
    status: str
    message: Optional[str] = None
    created_at: str
    expires_at: str


class PendingRequestsResponse(BaseModel):
    """待处理请求列表响应"""
    requests: List[BindingRequestInfo]


class RejectRequest(BaseModel):
    """拒绝请求"""
    note: Optional[str] = Field(None, max_length=200, description="拒绝原因（可选）")


class AcceptResponse(BaseModel):
    """接受绑定响应"""
    success: bool
    message: str
    new_planner: dict
    released_old_planner: bool


class PlannerInfo(BaseModel):
    """规划师信息"""
    consultant_id: str
    consultant_name: Optional[str] = None
    consultant_display_name: Optional[str] = None
    created_at: str


class PlannerStatusResponse(BaseModel):
    """规划师状态响应"""
    has_planner: bool
    planner: Optional[PlannerInfo] = None


class ReleaseResponse(BaseModel):
    """释放规划师响应"""
    success: bool
    message: str
    old_planner: Optional[dict] = None


# ====== 数据库辅助查询 ======

async def _get_user_display_name(user_id: str) -> Optional[str]:
    """查询用户的显示名称"""
    try:
        row = await AsyncDatabasePool.execute_one(
            "SELECT display_name, username FROM users WHERE id = $1",
            user_id,
        )
        if row:
            return row.get("display_name") or row.get("username")
        return None
    except Exception as e:
        logger.warning(f"查询用户显示名称失败: user_id={user_id}, error={e}")
        return None


# ====== 路由实现 ======

@router.get("/binding-requests", response_model=PendingRequestsResponse)
async def get_pending_binding_requests(current_user: dict = Depends(require_user)):
    """
    查看待处理绑定请求
    
    返回用户的所有状态为 'pending' 的绑定请求列表，
    包含规划师信息（consultant_id, consultant_name, consultant_display_name）。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_binding_request_repo()
        
        # 查询待处理请求
        requests = await repo.get_pending_requests_by_user(user_id)
        
        # 转换为响应格式
        request_list = []
        for req in requests:
            # 查询规划师的显示名称
            consultant_display_name = await _get_user_display_name(req["consultant_id"])
            
            request_info = BindingRequestInfo(
                id=req["id"],
                consultant_id=req["consultant_id"],
                consultant_name=req.get("consultant_name") or req.get("consultant_username"),
                consultant_display_name=consultant_display_name,
                user_id=req["user_id"],
                status=req["status"],
                message=req.get("message"),
                created_at=req["created_at"],
                expires_at=req["expires_at"],
            )
            request_list.append(request_info)
        
        logger.info(
            f"查询待处理绑定请求成功: user_id={user_id}, count={len(request_list)}"
        )
        return PendingRequestsResponse(requests=request_list)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询待处理绑定请求失败: user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"查询待处理请求失败: {str(e)}")


@router.post("/binding-requests/{request_id}/accept", response_model=AcceptResponse)
async def accept_binding_request(
    request_id: str,
    current_user: dict = Depends(require_user),
):
    """
    接受绑定请求
    
    业务逻辑：
    a. 验证请求状态为pending
    b. 验证请求未过期
    c. 自动解除用户旧的绑定关系（关键逻辑）
    d. 创建新的绑定关系
    e. 更新请求状态为accepted
    f. 发送通知给规划师
    
    使用Repository层的事务处理，确保并发安全。
    """
    try:
        user_id = current_user["user_id"]
        user_name = current_user.get("username", "用户")
        
        repo = get_binding_request_repo()
        relation_repo = get_consultant_relation_repo()
        
        # 查询用户是否有旧的绑定关系
        old_relation = await relation_repo.get_active_relation_by_user(user_id)
        released_old = old_relation is not None
        
        # 使用Repository的事务处理接受请求（并发安全）
        result = await repo.accept_request(request_id, user_id)
        
        # 获取新规划师信息
        new_relation_id = result["relation"]["id"]
        consultant_id = result["relation"]["consultant_id"]
        
        # 查询新规划师的详细信息
        consultant_display_name = await _get_user_display_name(consultant_id)
        consultant_row = await AsyncDatabasePool.execute_one(
            "SELECT username, display_name FROM users WHERE id = $1",
            consultant_id,
        )
        consultant_name = (
            consultant_row.get("display_name") 
            or consultant_row.get("username") 
            if consultant_row else None
        )
        
        new_planner = {
            "consultant_id": consultant_id,
            "consultant_name": consultant_name,
            "consultant_display_name": consultant_display_name or consultant_name,
            "relation_id": new_relation_id,
            "created_at": result["relation"]["created_at"],
        }
        
        # 发送通知给规划师
        notification = {
            "type": "binding_accepted",
            "user_id": user_id,
            "user_name": user_name,
            "request_id": request_id,
            "timestamp": result["request"]["processed_at"],
            "message": f"用户 {user_name} 已接受您的绑定请求",
        }
        await publish_notification(consultant_id, notification)
        
        logger.info(
            f"接受绑定请求成功: request_id={request_id}, user_id={user_id}, "
            f"consultant_id={consultant_id}, released_old={released_old}"
        )
        
        return AcceptResponse(
            success=True,
            message="绑定请求已接受，您已成功绑定新规划师",
            new_planner=new_planner,
            released_old_planner=released_old,
        )
    
    except ValueError as e:
        # Repository层的验证错误
        error_msg = str(e)
        logger.warning(f"接受绑定请求验证失败: request_id={request_id}, error={error_msg}")
        
        # 转换为用户友好的错误提示
        if "请求不存在" in error_msg:
            raise HTTPException(status_code=404, detail="绑定请求不存在")
        elif "请求已处理" in error_msg:
            raise HTTPException(status_code=400, detail="该请求已处理，无法重复操作")
        elif "请求已过期" in error_msg:
            raise HTTPException(status_code=400, detail="该请求已过期，无法接受")
        elif "请求归属错误" in error_msg:
            raise HTTPException(status_code=403, detail="该请求不属于您，无法操作")
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"接受绑定请求失败: request_id={request_id}, user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"接受绑定请求失败: {str(e)}")


@router.post("/binding-requests/{request_id}/reject")
async def reject_binding_request(
    request_id: str,
    request: RejectRequest,
    current_user: dict = Depends(require_user),
):
    """
    拒绝绑定请求
    
    业务逻辑：
    a. 验证请求状态为pending
    b. 更新请求状态为rejected
    c. 发送通知给规划师
    
    请求体：{"note": "拒绝原因（可选）"}
    """
    try:
        user_id = current_user["user_id"]
        user_name = current_user.get("username", "用户")
        
        repo = get_binding_request_repo()
        
        # 先查询请求详情获取规划师信息
        request_detail = await repo.get_request_by_id(request_id)
        if request_detail is None:
            raise HTTPException(status_code=404, detail="绑定请求不存在")
        
        consultant_id = request_detail["consultant_id"]
        
        # 拒绝请求
        success = await repo.reject_request(request_id, user_id, request.note)
        
        if not success:
            raise HTTPException(status_code=400, detail="拒绝请求失败，可能已被处理")
        
        # 发送通知给规划师
        notification = {
            "type": "binding_rejected",
            "user_id": user_id,
            "user_name": user_name,
            "request_id": request_id,
            "note": request.note,
            "message": f"用户 {user_name} 已拒绝您的绑定请求",
        }
        if request.note:
            notification["message"] += f"，原因：{request.note}"
        
        await publish_notification(consultant_id, notification)
        
        logger.info(
            f"拒绝绑定请求成功: request_id={request_id}, user_id={user_id}, "
            f"note={request.note}"
        )
        
        return {
            "success": True,
            "message": "绑定请求已拒绝",
        }
    
    except ValueError as e:
        # Repository层的验证错误
        error_msg = str(e)
        logger.warning(f"拒绝绑定请求验证失败: request_id={request_id}, error={error_msg}")
        
        # 转换为用户友好的错误提示
        if "请求不存在" in error_msg:
            raise HTTPException(status_code=404, detail="绑定请求不存在")
        elif "请求已处理" in error_msg:
            raise HTTPException(status_code=400, detail="该请求已处理，无法重复操作")
        elif "请求归属错误" in error_msg:
            raise HTTPException(status_code=403, detail="该请求不属于您，无法操作")
        else:
            raise HTTPException(status_code=400, detail=error_msg)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"拒绝绑定请求失败: request_id={request_id}, user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"拒绝绑定请求失败: {str(e)}")


@router.post("/planner/release", response_model=ReleaseResponse)
async def release_planner(current_user: dict = Depends(require_user)):
    """
    释放规划师（解除绑定）
    
    业务逻辑：
    a. 查询用户当前的活跃绑定关系
    b. 将绑定关系设置为inactive
    c. 发送通知给原规划师
    
    响应：返回成功信息+原规划师信息
    """
    try:
        user_id = current_user["user_id"]
        user_name = current_user.get("username", "用户")
        
        relation_repo = get_consultant_relation_repo()
        
        # 查询当前的活跃绑定关系
        relation = await relation_repo.get_active_relation_by_user(user_id)
        
        if relation is None:
            raise HTTPException(status_code=404, detail="您当前没有绑定规划师")
        
        relation_id = relation["id"]
        consultant_id = relation["consultant_id"]
        consultant_name = relation.get("consultant_name") or relation.get("consultant_username")
        
        # 解除绑定关系（使用unbind_relation需要验证consultant_id）
        # 这里用户主动解除，我们直接通过SQL更新
        from datetime import datetime
        now = datetime.utcnow()
        
        await AsyncDatabasePool.execute_command(
            "UPDATE consultant_relations SET status = 'inactive', updated_at = $1 "
            "WHERE id = $2 AND user_id = $3 AND status = 'active'",
            now, relation_id, user_id,
        )
        
        old_planner = {
            "consultant_id": consultant_id,
            "consultant_name": consultant_name,
            "relation_id": relation_id,
        }
        
        # 发送通知给原规划师
        notification = {
            "type": "binding_released",
            "user_id": user_id,
            "user_name": user_name,
            "message": f"用户 {user_name} 已解除与您的绑定关系",
            "timestamp": now.isoformat() + "+00:00",
        }
        await publish_notification(consultant_id, notification)
        
        logger.info(
            f"释放规划师成功: user_id={user_id}, consultant_id={consultant_id}, "
            f"relation_id={relation_id}"
        )
        
        return ReleaseResponse(
            success=True,
            message="已成功解除与规划师的绑定关系",
            old_planner=old_planner,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"释放规划师失败: user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"释放规划师失败: {str(e)}")


@router.get("/planner/current", response_model=PlannerStatusResponse)
async def get_current_planner(current_user: dict = Depends(require_user)):
    """
    查询当前绑定的规划师
    
    响应：返回绑定状态和规划师信息
    """
    try:
        user_id = current_user["user_id"]
        
        relation_repo = get_consultant_relation_repo()
        
        # 查询当前的活跃绑定关系
        relation = await relation_repo.get_active_relation_by_user(user_id)
        
        if relation is None:
            logger.info(f"用户未绑定规划师: user_id={user_id}")
            return PlannerStatusResponse(
                has_planner=False,
                planner=None,
            )
        
        consultant_id = relation["consultant_id"]
        
        # 查询规划师的显示名称
        consultant_display_name = await _get_user_display_name(consultant_id)
        
        planner = PlannerInfo(
            consultant_id=consultant_id,
            consultant_name=relation.get("consultant_name") or relation.get("consultant_username"),
            consultant_display_name=consultant_display_name or relation.get("consultant_name"),
            created_at=relation["created_at"],
        )
        
        logger.info(f"查询当前规划师成功: user_id={user_id}, consultant_id={consultant_id}")
        
        return PlannerStatusResponse(
            has_planner=True,
            planner=planner,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询当前规划师失败: user_id={current_user.get('user_id')}, error={e}")
        raise HTTPException(status_code=500, detail=f"查询规划师失败: {str(e)}")