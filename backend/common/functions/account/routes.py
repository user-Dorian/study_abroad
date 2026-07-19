"""账户管理路由 - 用户账户相关功能"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
import hashlib
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user, create_access_token

router = APIRouter(prefix="/api/account", tags=["账户管理"])


class UpdateProfileRequest(BaseModel):
    """更新资料请求"""
    display_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


class AccountInfo(BaseModel):
    """账户信息"""
    user_id: str
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class LoginHistory(BaseModel):
    """登录历史"""
    login_id: str
    ip_address: str
    user_agent: Optional[str] = None
    login_at: datetime
    status: str  # success/failed


# 模拟账户数据库
_accounts_db = {}
_login_history_db = {}


def _hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()


@router.get("/info", response_model=AccountInfo)
async def get_account_info(current_user: dict = Depends(require_user)):
    """获取账户信息

    Args:
        current_user: 当前用户

    Returns:
        AccountInfo: 账户信息
    """
    try:
        user_id = current_user["user_id"]

        # 获取账户信息
        account = _accounts_db.get(user_id, {
            "user_id": user_id,
            "username": current_user["username"],
            "role": current_user["role"],
            "created_at": datetime.utcnow()
        })

        logger.info(f"获取账户信息: user_id={user_id}")

        return AccountInfo(**account)

    except Exception as e:
        logger.error(f"获取账户信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取账户信息失败: {str(e)}")


@router.put("/profile", response_model=AccountInfo)
async def update_account_profile(
    request: UpdateProfileRequest,
    current_user: dict = Depends(require_user)
):
    """更新账户资料

    Args:
        request: 更新资料请求
        current_user: 当前用户

    Returns:
        AccountInfo: 更新后的账户信息
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建账户
        if user_id not in _accounts_db:
            _accounts_db[user_id] = {
                "user_id": user_id,
                "username": current_user["username"],
                "role": current_user["role"],
                "created_at": datetime.utcnow()
            }

        # 更新资料
        account = _accounts_db[user_id]
        if request.display_name:
            account["display_name"] = request.display_name
        if request.email:
            account["email"] = request.email
        if request.phone:
            account["phone"] = request.phone
        if request.avatar_url:
            account["avatar_url"] = request.avatar_url

        account["updated_at"] = datetime.utcnow()

        logger.info(f"更新账户资料: user_id={user_id}")

        return AccountInfo(**account)

    except Exception as e:
        logger.error(f"更新账户资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新账户资料失败: {str(e)}")


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: dict = Depends(require_user)
):
    """修改密码

    Args:
        request: 修改密码请求
        current_user: 当前用户

    Returns:
        dict: 修改结果

    Raises:
        HTTPException: 400 - 原密码错误
    """
    try:
        user_id = current_user["user_id"]

        # 获取账户
        account = _accounts_db.get(user_id, {})
        old_password_hash = account.get("password_hash", "")

        # 验证原密码
        if old_password_hash and _hash_password(request.old_password) != old_password_hash:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="原密码错误"
            )

        # 更新密码
        if user_id not in _accounts_db:
            _accounts_db[user_id] = {
                "user_id": user_id,
                "username": current_user["username"],
                "role": current_user["role"],
                "created_at": datetime.utcnow()
            }

        _accounts_db[user_id]["password_hash"] = _hash_password(request.new_password)
        _accounts_db[user_id]["password_updated_at"] = datetime.utcnow()

        logger.info(f"密码修改成功: user_id={user_id}")

        return {
            "success": True,
            "message": "密码修改成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改密码失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修改密码失败: {str(e)}")


@router.get("/login-history", response_model=list[LoginHistory])
async def get_login_history(
    limit: int = 10,
    current_user: dict = Depends(require_user)
):
    """获取登录历史

    Args:
        limit: 返回记录数量限制
        current_user: 当前用户

    Returns:
        list[LoginHistory]: 登录历史列表
    """
    try:
        user_id = current_user["user_id"]

        # 获取登录历史
        history = _login_history_db.get(user_id, [])

        logger.info(f"获取登录历史: user_id={user_id}, count={len(history)}")

        return [LoginHistory(**h) for h in history[:limit]]

    except Exception as e:
        logger.error(f"获取登录历史失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取登录历史失败: {str(e)}")


@router.post("/deactivate")
async def deactivate_account(current_user: dict = Depends(require_user)):
    """停用账户

    Args:
        current_user: 当前用户

    Returns:
        dict: 停用结果
    """
    try:
        user_id = current_user["user_id"]

        # 标记账户为停用状态
        if user_id in _accounts_db:
            _accounts_db[user_id]["status"] = "deactivated"
            _accounts_db[user_id]["deactivated_at"] = datetime.utcnow()

        logger.info(f"账户已停用: user_id={user_id}")

        return {
            "success": True,
            "message": "账户已停用"
        }

    except Exception as e:
        logger.error(f"停用账户失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"停用账户失败: {str(e)}")


@router.post("/record-login")
async def record_login_event(
    user_id: str,
    ip_address: str,
    user_agent: Optional[str] = None,
    status: str = "success"
):
    """记录登录事件（内部接口）

    Args:
        user_id: 用户ID
        ip_address: IP地址
        user_agent: User-Agent
        status: 登录状态

    Returns:
        dict: 记录结果
    """
    try:
        login_id = str(uuid.uuid4())
        login_record = {
            "login_id": login_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "login_at": datetime.utcnow(),
            "status": status
        }

        if user_id not in _login_history_db:
            _login_history_db[user_id] = []
        _login_history_db[user_id].insert(0, login_record)

        # 更新最后登录时间
        if user_id in _accounts_db:
            _accounts_db[user_id]["last_login_at"] = datetime.utcnow()

        logger.info(f"记录登录事件: user_id={user_id}, status={status}")

        return {
            "success": True,
            "login_id": login_id
        }

    except Exception as e:
        logger.error(f"记录登录事件失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"记录登录事件失败: {str(e)}")
