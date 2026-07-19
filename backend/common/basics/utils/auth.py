"""认证工具模块 - 提供JWT token验证和用户认证功能"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import jwt
import os
from datetime import datetime, timedelta

from backend.common.basics.utils.logger import logger

# JWT配置
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "rag-secret-key-change-in-production-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Bearer token安全方案
security = HTTPBearer()


class TokenData(BaseModel):
    """Token数据模型"""
    user_id: str
    username: str
    role: str
    exp: Optional[datetime] = None


class User(BaseModel):
    """用户数据模型"""
    user_id: str
    username: str
    role: str
    display_name: Optional[str] = None


def create_access_token(user_id: str, username: str, role: str) -> str:
    """创建访问token

    Args:
        user_id: 用户ID
        username: 用户名
        role: 用户角色 (client/consultant)

    Returns:
        str: JWT token字符串
    """
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "exp": expire
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    logger.info(f"创建token成功: user_id={user_id}, role={role}")
    return token


def decode_token(token: str) -> Optional[TokenData]:
    """解码token

    Args:
        token: JWT token字符串

    Returns:
        TokenData | None: 解码后的token数据，失败返回None
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return TokenData(
            user_id=payload["user_id"],
            username=payload["username"],
            role=payload["role"],
            exp=datetime.fromtimestamp(payload["exp"])
        )
    except jwt.ExpiredSignatureError:
        logger.warning("Token已过期")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"无效的token: {e}")
        return None
    except Exception as e:
        logger.error(f"Token解码异常: {e}")
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[dict]:
    """获取当前用户信息（可选认证）

    Args:
        credentials: HTTP Bearer认证凭据

    Returns:
        dict | None: 用户信息字典，未认证时返回None
    """
    token = credentials.credentials
    token_data = decode_token(token)

    if not token_data:
        return None

    return {
        "user_id": token_data.user_id,
        "username": token_data.username,
        "role": token_data.role
    }


async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """要求用户认证（必须认证）

    Args:
        credentials: HTTP Bearer认证凭据

    Returns:
        dict: 用户信息字典

    Raises:
        HTTPException: 401未认证错误
    """
    token = credentials.credentials
    token_data = decode_token(token)

    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证信息",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": token_data.user_id,
        "username": token_data.username,
        "role": token_data.role
    }


async def require_role(required_role: str):
    """要求特定角色

    Args:
        required_role: 要求的角色 (client/consultant)

    Returns:
        依赖函数
    """
    async def role_checker(current_user: dict = Depends(require_user)) -> dict:
        if current_user["role"] != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {required_role} 角色"
            )
        return current_user

    return role_checker
