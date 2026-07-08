"""认证工具模块 - JWT签发/验证、密码哈希"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from common.config.base_settings import Config
from common.utils.logger import logger

# 密码哈希上下文（自动管理bcrypt版本）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer Token 安全方案
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    return pwd_context.hash(password)


# 兼容旧接口名称
get_password_hash = hash_password


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码与哈希是否匹配"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    # 兼容旧接口参数
    secret_key: Optional[str] = None,
    algorithm: Optional[str] = None,
    expires_hours: Optional[int] = None,
) -> str:
    """
    创建 JWT 访问令牌

    Args:
        data: 要编码的数据（必须包含 user_id, username）
        expires_delta: 过期时间差，为 None 时使用配置的默认值
        secret_key: （兼容旧接口）密钥，忽略，使用配置
        algorithm: （兼容旧接口）算法，忽略，使用配置
        expires_hours: （兼容旧接口）过期小时数，覆盖配置

    Returns:
        str: JWT token 字符串
    """
    to_encode = data.copy()
    expire_hours = expires_hours or Config.JWT_EXPIRATION_HOURS
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=expire_hours))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, Config.JWT_SECRET_KEY, algorithm=Config.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(
    token: str,
    # 兼容旧接口参数
    secret_key: Optional[str] = None,
    algorithm: Optional[str] = None,
) -> Optional[dict]:
    """
    解码并验证 JWT 令牌

    Args:
        token: JWT token 字符串
        secret_key: （兼容旧接口）密钥，忽略，使用配置
        algorithm: （兼容旧接口）算法，忽略，使用配置

    Returns:
        dict | None: 解码后的 payload，验证失败返回 None
    """
    try:
        payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=[Config.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        logger.warning(f"JWT 验证失败: {e}")
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """
    从请求中提取并验证当前用户（FastAPI 依赖注入）

    如果 Authorization header 不存在或 token 无效，返回 None（不抛出异常）。
    这样路由可以根据需要决定是返回 401 还是允许匿名访问。

    Args:
        credentials: HTTP Bearer Token 凭证

    Returns:
        dict | None: 包含 user_id, username 的用户信息，未认证返回 None
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        return None

    # 检查 payload 是否包含必要字段
    user_id = payload.get("user_id")
    username = payload.get("username")
    if user_id is None or username is None:
        return None

    return {"user_id": user_id, "username": username}


async def require_user(
    current_user: Optional[dict] = Depends(get_current_user),
) -> dict:
    """
    强制要求用户已认证（FastAPI 依赖注入）

    与 get_current_user 不同，此依赖会在未认证时抛出 401 异常。

    Args:
        current_user: 当前用户信息

    Returns:
        dict: 包含 user_id, username 的用户信息

    Raises:
        HTTPException: 未认证时返回 401
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证，请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
