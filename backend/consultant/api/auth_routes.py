"""规划师端认证路由 - 提供规划师登录、注册、token验证等功能

遵循客户端认证路由的实现风格，使用JWT认证机制。
规划师角色标识为 'consultant'。
"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid
import hashlib
import re
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import create_access_token, get_current_user

router = APIRouter()


class LoginRequest(BaseModel):
    """规划师登录请求"""
    username: str
    password: str


class RegisterRequest(BaseModel):
    """规划师注册请求"""
    username: str
    password: str
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    employee_id: Optional[str] = None  # 规划师工号


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str = "consultant"  # 规划师角色固定为 consultant
    display_name: Optional[str] = None
    employee_id: Optional[str] = None


class UserInfo(BaseModel):
    """规划师用户信息"""
    user_id: str
    username: str
    role: str = "consultant"
    display_name: Optional[str] = None
    email: Optional[str] = None
    employee_id: Optional[str] = None
    created_at: Optional[datetime] = None


# 模拟规划师用户数据库（实际项目中应该使用真实数据库）
_fake_consultants_db = {}


def _hash_password(password: str) -> str:
    """密码哈希

    Args:
        password: 原始密码

    Returns:
        str: 哈希后的密码
    """
    return hashlib.sha256(password.encode()).hexdigest()


def _verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码

    Args:
        plain_password: 原始密码
        hashed_password: 哈希密码

    Returns:
        bool: 是否匹配
    """
    return _hash_password(plain_password) == hashed_password


# ====== 输入验证：防止SQL注入与XSS ======
# SQL注入特征模式（大小写不敏感）
_SQL_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"'\s*--",                  # SQL注释 '--
        r"';",                      # 语句分隔 ';
        r"--\s",                    # SQL注释 --
        r"\bunion\b.+\bselect\b",   # UNION SELECT
        r"\bdrop\b\s+\btable\b",    # DROP TABLE
        r"\bdelete\b\s+\bfrom\b",   # DELETE FROM
        r"\binsert\b\s+\binto\b",   # INSERT INTO
        r"\bupdate\b.+\bset\b",     # UPDATE SET
        r"\b(or|and)\b\s+\d+\s*=\s*\d+",  # OR 1=1 / AND 1=1
    ]
]

# XSS payload特征模式（大小写不敏感）
_XSS_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"<\s*script",              # <script
        r"<\s*/\s*script",          # </script
        r"javascript:",             # javascript:
        r"on(error|load|click|mouseover)\s*=",  # onerror= 等
        r"<\s*iframe",              # <iframe
        r"<\s*img[^>]*onerror",     # <img onerror
    ]
]

# 用户名合法字符集：字母、数字、下划线、中文
_USERNAME_CHARSET_RE = re.compile(r'^[\w\u4e00-\u9fa5]+$')


def _validate_login_input(username: str, password: str) -> Optional[str]:
    """登录输入验证

    验证规则：
    - username: 长度2-20字符，只允许字母、数字、中文、下划线
    - password: 长度6-50字符
    - 拒绝SQL注入特征（如 '、--、; 等）和XSS payload（如 <script>）

    Args:
        username: 用户名
        password: 密码

    Returns:
        Optional[str]: 错误信息（None表示验证通过）
    """
    # 用户名基础校验
    if not username or not isinstance(username, str):
        return "用户名不能为空"
    if len(username) < 2 or len(username) > 20:
        return "用户名长度必须为2-20个字符"
    if not _USERNAME_CHARSET_RE.match(username):
        return "用户名只允许字母、数字、下划线和中文"

    # 密码基础校验
    if not password or not isinstance(password, str):
        return "密码不能为空"
    if len(password) < 6 or len(password) > 50:
        return "密码长度必须为6-50个字符"

    # 安全校验：对username和password同时检测注入特征
    combined = f"{username}\n{password}"

    # 单引号是SQL注入的核心字符，直接拒绝
    if "'" in combined:
        return "输入包含非法字符"

    # SQL注入特征检测
    for pattern in _SQL_INJECTION_PATTERNS:
        if pattern.search(combined):
            return "输入包含非法字符"

    # XSS payload检测
    for pattern in _XSS_PATTERNS:
        if pattern.search(combined):
            return "输入包含非法字符"

    return None


@router.post("/api/consultant/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """规划师登录

    Args:
        request: 登录请求

    Returns:
        LoginResponse: 登录响应，包含token和用户信息

    Raises:
        HTTPException: 400 - 输入验证失败
        HTTPException: 401 - 用户名或密码错误
    """
    try:
        # 输入验证（防止SQL注入/XSS，限制长度和字符集）
        validation_error = _validate_login_input(request.username, request.password)
        if validation_error:
            logger.warning(
                f"[规划师端] 登录输入验证失败: username={request.username!r}, "
                f"reason={validation_error}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=validation_error
            )

        # 查找规划师用户（实际项目中应该查询数据库）
        user = _fake_consultants_db.get(request.username)

        # 如果用户不存在，创建默认规划师用户（用于演示）
        if not user:
            user_id = str(uuid.uuid4())
            user = {
                "user_id": user_id,
                "username": request.username,
                "password_hash": _hash_password(request.password),
                "role": "consultant",
                "display_name": request.username,
                "email": None,
                "employee_id": None,
                "created_at": datetime.utcnow()
            }
            _fake_consultants_db[request.username] = user
            logger.info(f"[规划师端] 创建默认用户: username={request.username}, user_id={user_id}")

        # 验证密码
        if not _verify_password(request.password, user["password_hash"]):
            logger.warning(f"[规划师端] 登录失败（密码错误）: username={request.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误"
            )

        # 生成token（角色为 consultant）
        token = create_access_token(
            user_id=user["user_id"],
            username=user["username"],
            role="consultant"
        )

        logger.info(f"[规划师端] 用户登录成功: username={request.username}, user_id={user['user_id']}")

        return LoginResponse(
            access_token=token,
            token_type="bearer",
            user_id=user["user_id"],
            username=user["username"],
            role="consultant",
            display_name=user.get("display_name"),
            employee_id=user.get("employee_id")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 登录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


@router.post("/api/consultant/auth/register", response_model=LoginResponse)
async def register(request: RegisterRequest):
    """规划师注册（可选功能）

    Args:
        request: 注册请求

    Returns:
        LoginResponse: 注册响应，包含token和用户信息

    Raises:
        HTTPException: 400 - 用户名已存在
    """
    try:
        # 检查用户名是否已存在
        if request.username in _fake_consultants_db:
            logger.warning(f"[规划师端] 注册失败（用户名已存在）: username={request.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )

        # 创建新规划师用户
        user_id = str(uuid.uuid4())
        user = {
            "user_id": user_id,
            "username": request.username,
            "password_hash": _hash_password(request.password),
            "role": "consultant",
            "display_name": request.display_name or request.username,
            "email": request.email,
            "employee_id": request.employee_id,
            "created_at": datetime.utcnow()
        }

        _fake_consultants_db[request.username] = user

        # 生成token（角色为 consultant）
        token = create_access_token(
            user_id=user_id,
            username=user["username"],
            role="consultant"
        )

        logger.info(f"[规划师端] 用户注册成功: username={request.username}, user_id={user_id}")

        return LoginResponse(
            access_token=token,
            token_type="bearer",
            user_id=user_id,
            username=user["username"],
            role="consultant",
            display_name=user.get("display_name"),
            employee_id=user.get("employee_id")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@router.get("/api/consultant/auth/me", response_model=UserInfo)
async def get_me(current_user: Optional[dict] = Depends(get_current_user)):
    """获取当前规划师信息

    Args:
        current_user: 当前用户（可选）

    Returns:
        UserInfo: 用户信息

    Raises:
        HTTPException: 401 - 未认证
        HTTPException: 403 - 非规划师角色
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证"
        )

    # 验证角色是否为规划师
    if current_user["role"] != "consultant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要规划师权限"
        )

    # 从数据库获取用户信息（这里使用模拟数据）
    user_data = _fake_consultants_db.get(current_user["username"], {})

    return UserInfo(
        user_id=current_user["user_id"],
        username=current_user["username"],
        role="consultant",
        display_name=user_data.get("display_name"),
        email=user_data.get("email"),
        employee_id=user_data.get("employee_id"),
        created_at=user_data.get("created_at")
    )


@router.post("/api/consultant/auth/validate")
async def validate_token(current_user: Optional[dict] = Depends(get_current_user)):
    """验证token有效性

    Args:
        current_user: 当前用户（可选）

    Returns:
        dict: 验证结果

    Raises:
        HTTPException: 401 - token无效
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的token"
        )

    # 验证角色是否为规划师
    if current_user["role"] != "consultant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要规划师权限"
        )

    return {
        "valid": True,
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "role": "consultant"
    }


@router.post("/api/consultant/auth/logout")
async def logout(current_user: Optional[dict] = Depends(get_current_user)):
    """规划师登出

    注意：JWT是无状态的，实际的登出需要客户端删除token
    这里只是记录登出日志

    Args:
        current_user: 当前用户（可选）

    Returns:
        dict: 登出结果
    """
    if current_user:
        logger.info(f"[规划师端] 用户登出: username={current_user['username']}, user_id={current_user['user_id']}")

    return {
        "success": True,
        "message": "登出成功，请删除客户端token"
    }