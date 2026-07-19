"""用户设置路由 - 管理用户偏好设置"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/settings", tags=["用户设置"])


class UserSettings(BaseModel):
    """用户设置"""
    user_id: str
    # 通知设置
    notification_enabled: bool = True
    email_notification: bool = True
    push_notification: bool = True
    message_preview: bool = True
    # 隐私设置
    profile_visible: bool = True
    online_status_visible: bool = True
    last_seen_visible: bool = True
    # 外观设置
    theme: str = "light"  # light/dark/auto
    language: str = "zh-CN"
    font_size: str = "medium"  # small/medium/large
    # 其他设置
    timezone: Optional[str] = None
    currency: Optional[str] = None
    # 元数据
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UpdateSettingsRequest(BaseModel):
    """更新设置请求"""
    notification_enabled: Optional[bool] = None
    email_notification: Optional[bool] = None
    push_notification: Optional[bool] = None
    message_preview: Optional[bool] = None
    profile_visible: Optional[bool] = None
    online_status_visible: Optional[bool] = None
    last_seen_visible: Optional[bool] = None
    theme: Optional[str] = None
    language: Optional[str] = None
    font_size: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None


# 模拟用户设置数据库
_settings_db = {}


@router.get("", response_model=UserSettings)
async def get_settings(current_user: dict = Depends(require_user)):
    """获取用户设置

    Args:
        current_user: 当前用户

    Returns:
        UserSettings: 用户设置
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建默认设置
        settings = _settings_db.get(user_id, {
            "user_id": user_id,
            "notification_enabled": True,
            "email_notification": True,
            "push_notification": True,
            "message_preview": True,
            "profile_visible": True,
            "online_status_visible": True,
            "last_seen_visible": True,
            "theme": "light",
            "language": "zh-CN",
            "font_size": "medium",
            "created_at": datetime.utcnow()
        })

        logger.info(f"获取用户设置: user_id={user_id}")

        return UserSettings(**settings)

    except Exception as e:
        logger.error(f"获取用户设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取用户设置失败: {str(e)}")


@router.put("", response_model=UserSettings)
async def update_settings(
    request: UpdateSettingsRequest,
    current_user: dict = Depends(require_user)
):
    """更新用户设置

    Args:
        request: 更新设置请求
        current_user: 当前用户

    Returns:
        UserSettings: 更新后的用户设置
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建设置
        if user_id not in _settings_db:
            _settings_db[user_id] = {
                "user_id": user_id,
                "notification_enabled": True,
                "email_notification": True,
                "push_notification": True,
                "message_preview": True,
                "profile_visible": True,
                "online_status_visible": True,
                "last_seen_visible": True,
                "theme": "light",
                "language": "zh-CN",
                "font_size": "medium",
                "created_at": datetime.utcnow()
            }

        # 更新设置
        settings = _settings_db[user_id]
        update_data = request.dict(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                settings[key] = value

        settings["updated_at"] = datetime.utcnow()

        logger.info(f"更新用户设置: user_id={user_id}")

        return UserSettings(**settings)

    except Exception as e:
        logger.error(f"更新用户设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新用户设置失败: {str(e)}")


@router.post("/reset")
async def reset_settings(current_user: dict = Depends(require_user)):
    """重置用户设置为默认值

    Args:
        current_user: 当前用户

    Returns:
        dict: 重置结果
    """
    try:
        user_id = current_user["user_id"]

        # 重置为默认设置
        _settings_db[user_id] = {
            "user_id": user_id,
            "notification_enabled": True,
            "email_notification": True,
            "push_notification": True,
            "message_preview": True,
            "profile_visible": True,
            "online_status_visible": True,
            "last_seen_visible": True,
            "theme": "light",
            "language": "zh-CN",
            "font_size": "medium",
            "updated_at": datetime.utcnow()
        }

        logger.info(f"重置用户设置: user_id={user_id}")

        return {
            "success": True,
            "message": "设置已重置为默认值"
        }

    except Exception as e:
        logger.error(f"重置用户设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"重置用户设置失败: {str(e)}")


@router.get("/notifications")
async def get_notification_settings(current_user: dict = Depends(require_user)):
    """获取通知设置

    Args:
        current_user: 当前用户

    Returns:
        dict: 通知设置
    """
    try:
        user_id = current_user["user_id"]
        settings = _settings_db.get(user_id, {})

        return {
            "notification_enabled": settings.get("notification_enabled", True),
            "email_notification": settings.get("email_notification", True),
            "push_notification": settings.get("push_notification", True),
            "message_preview": settings.get("message_preview", True)
        }

    except Exception as e:
        logger.error(f"获取通知设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取通知设置失败: {str(e)}")


@router.get("/privacy")
async def get_privacy_settings(current_user: dict = Depends(require_user)):
    """获取隐私设置

    Args:
        current_user: 当前用户

    Returns:
        dict: 隐私设置
    """
    try:
        user_id = current_user["user_id"]
        settings = _settings_db.get(user_id, {})

        return {
            "profile_visible": settings.get("profile_visible", True),
            "online_status_visible": settings.get("online_status_visible", True),
            "last_seen_visible": settings.get("last_seen_visible", True)
        }

    except Exception as e:
        logger.error(f"获取隐私设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取隐私设置失败: {str(e)}")


@router.get("/appearance")
async def get_appearance_settings(current_user: dict = Depends(require_user)):
    """获取外观设置

    Args:
        current_user: 当前用户

    Returns:
        dict: 外观设置
    """
    try:
        user_id = current_user["user_id"]
        settings = _settings_db.get(user_id, {})

        return {
            "theme": settings.get("theme", "light"),
            "language": settings.get("language", "zh-CN"),
            "font_size": settings.get("font_size", "medium")
        }

    except Exception as e:
        logger.error(f"获取外观设置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取外观设置失败: {str(e)}")
