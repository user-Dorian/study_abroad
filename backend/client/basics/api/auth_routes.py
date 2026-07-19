"""认证路由 - 提供用户登录、注册、token验证、手机号绑定等功能"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
import uuid
import hashlib
import re
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import create_access_token, get_current_user
from backend.client.basics.config.database import ClientDatabaseConfig

router = APIRouter()


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    password: str
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    role: str
    display_name: Optional[str] = None


class UserInfo(BaseModel):
    """用户信息"""
    user_id: str
    username: str
    role: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    created_at: Optional[datetime] = None


class BindPhoneRequest(BaseModel):
    """绑定手机号请求"""
    phone: str

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """验证手机号格式

        Args:
            v: 手机号字符串

        Returns:
            str: 验证后的手机号

        Raises:
            ValueError: 手机号格式错误
        """
        if not v:
            raise ValueError('手机号不能为空')

        # 验证手机号格式：中国大陆手机号，11位，以1开头，第二位是3-9
        pattern = r'^1[3-9]\d{9}$'
        if not re.match(pattern, v):
            raise ValueError('手机号格式错误，请输入正确的中国大陆手机号')

        return v


class BindPhoneResponse(BaseModel):
    """绑定手机号响应"""
    success: bool
    message: str


class PhoneBindingStatus(BaseModel):
    """手机号绑定状态"""
    phone: Optional[str] = None
    verified: bool = False
    bound: bool = False


# 模拟用户数据库（实际项目中应该使用真实数据库）
_fake_users_db = {}


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


@router.post("/api/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """用户登录

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
                f"登录输入验证失败: username={request.username!r}, "
                f"reason={validation_error}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=validation_error
            )

        # 连接数据库查询用户
        conn = _get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # 查询用户
            cursor.execute("""
                SELECT id, username, password_hash, role, display_name, email
                FROM users
                WHERE username = %s
            """, (request.username,))

            user = cursor.fetchone()

            # 如果用户不存在，创建新用户
            if not user:
                # 创建新用户
                now = datetime.utcnow()
                password_hash = _hash_password(request.password)

                cursor.execute("""
                    INSERT INTO users (username, password_hash, role, display_name, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, username, role, display_name
                """, (request.username, password_hash, 'client', request.username, now, now))

                new_user = cursor.fetchone()
                conn.commit()

                user = {
                    'id': new_user['id'],
                    'username': new_user['username'],
                    'role': new_user['role'],
                    'display_name': new_user['display_name']
                }

                logger.info(f"创建新用户: username={request.username}, user_id={user['id']}")

            else:
                # 验证密码
                if not user.get('password_hash') or not _verify_password(request.password, user['password_hash']):
                    logger.warning(f"登录失败（密码错误）: username={request.username}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="用户名或密码错误"
                    )

            # 生成token（使用数据库中的整数ID）
            token = create_access_token(
                user_id=str(user['id']),  # 转换为字符串
                username=user['username'],
                role=user['role']
            )

            logger.info(f"用户登录成功: username={request.username}, user_id={user['id']}")

            return LoginResponse(
                access_token=token,
                token_type="bearer",
                user_id=str(user['id']),
                username=user['username'],
                role=user['role'],
                display_name=user.get('display_name')
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"登录数据库操作失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"登录失败: {str(e)}"
            )
        finally:
            cursor.close()
            conn.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"登录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


@router.post("/api/auth/register", response_model=LoginResponse)
async def register(request: RegisterRequest):
    """用户注册

    Args:
        request: 注册请求

    Returns:
        LoginResponse: 注册响应，包含token和用户信息

    Raises:
        HTTPException: 400 - 用户名已存在
    """
    try:
        # 检查用户名是否已存在
        if request.username in _fake_users_db:
            logger.warning(f"注册失败（用户名已存在）: username={request.username}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在"
            )

        # 创建新用户
        user_id = str(uuid.uuid4())
        user = {
            "user_id": user_id,
            "username": request.username,
            "password_hash": _hash_password(request.password),
            "role": "client",
            "display_name": request.display_name or request.username,
            "email": request.email,
            "created_at": datetime.utcnow()
        }

        _fake_users_db[request.username] = user

        # 生成token
        token = create_access_token(
            user_id=user_id,
            username=user["username"],
            role=user["role"]
        )

        logger.info(f"用户注册成功: username={request.username}, user_id={user_id}")

        return LoginResponse(
            access_token=token,
            token_type="bearer",
            user_id=user_id,
            username=user["username"],
            role=user["role"],
            display_name=user.get("display_name")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@router.get("/api/auth/me", response_model=UserInfo)
async def get_me(current_user: Optional[dict] = Depends(get_current_user)):
    """获取当前用户信息

    Args:
        current_user: 当前用户（可选）

    Returns:
        UserInfo: 用户信息

    Raises:
        HTTPException: 401 - 未认证
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证"
        )

    # 从数据库获取用户信息（这里使用模拟数据）
    user_data = _fake_users_db.get(current_user["username"], {})

    return UserInfo(
        user_id=current_user["user_id"],
        username=current_user["username"],
        role=current_user["role"],
        display_name=user_data.get("display_name"),
        email=user_data.get("email"),
        created_at=user_data.get("created_at")
    )


@router.post("/api/auth/validate")
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

    return {
        "valid": True,
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "role": current_user["role"]
    }


@router.post("/api/auth/logout")
async def logout(current_user: Optional[dict] = Depends(get_current_user)):
    """用户登出

    注意：JWT是无状态的，实际的登出需要客户端删除token
    这里只是记录登出日志

    Args:
        current_user: 当前用户（可选）

    Returns:
        dict: 登出结果
    """
    if current_user:
        logger.info(f"用户登出: username={current_user['username']}, user_id={current_user['user_id']}")

    return {
        "success": True,
        "message": "登出成功，请删除客户端token"
    }


def _get_db_connection():
    """获取数据库连接

    Returns:
        connection: 数据库连接对象

    Raises:
        HTTPException: 500 - 数据库连接失败
    """
    try:
        conn_params = ClientDatabaseConfig.get_connection_params()
        connection = psycopg2.connect(**conn_params)
        return connection
    except Exception as e:
        logger.error(f"数据库连接失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="数据库连接失败"
        )


@router.post("/api/auth/bind-phone", response_model=BindPhoneResponse)
async def bind_phone(
    request: BindPhoneRequest,
    current_user: Optional[dict] = Depends(get_current_user)
):
    """绑定手机号

    Args:
        request: 绑定手机号请求
        current_user: 当前用户

    Returns:
        BindPhoneResponse: 绑定结果

    Raises:
        HTTPException: 401 - 未认证
        HTTPException: 400 - 手机号已被绑定
        HTTPException: 500 - 数据库错误
    """
    # 验证用户登录状态
    if not current_user:
        logger.warning("绑定手机号失败：用户未认证")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户未认证"
        )

    user_id = current_user.get('user_id')
    phone = request.phone

    logger.info(f"开始绑定手机号: user_id={user_id}, phone={phone}")

    try:
        # 连接数据库
        conn = _get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # 1. 检查手机号是否已被其他用户绑定
            check_sql = """
                SELECT id, username
                FROM users
                WHERE phone = %s AND id != %s
            """
            cursor.execute(check_sql, (phone, user_id))
            existing_user = cursor.fetchone()

            if existing_user:
                logger.warning(
                    f"手机号已被其他用户绑定: phone={phone}, "
                    f"existing_user_id={existing_user['id']}"
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="该手机号已被其他用户绑定"
                )

            # 2. 更新用户的手机号信息
            update_sql = """
                UPDATE users
                SET phone = %s,
                    phone_verified = TRUE,
                    phone_bound_at = %s,
                    updated_at = %s
                WHERE id = %s
            """
            now = datetime.utcnow()
            cursor.execute(update_sql, (phone, now, now, user_id))

            # 检查是否更新成功
            if cursor.rowcount == 0:
                logger.warning(f"用户不存在，无法绑定手机号: user_id={user_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="用户不存在"
                )

            # 提交事务
            conn.commit()

            logger.info(
                f"手机号绑定成功: user_id={user_id}, phone={phone}"
            )

            return BindPhoneResponse(
                success=True,
                message="手机号绑定成功"
            )

        except HTTPException:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"绑定手机号数据库操作失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"绑定手机号失败: {str(e)}"
            )
        finally:
            cursor.close()
            conn.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"绑定手机号失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"绑定手机号失败: {str(e)}"
        )


@router.get("/api/auth/check-phone-binding", response_model=PhoneBindingStatus)
async def check_phone_binding(current_user: Optional[dict] = Depends(get_current_user)):
    """检查手机号绑定状态

    Args:
        current_user: 当前用户

    Returns:
        PhoneBindingStatus: 手机号绑定状态

    Raises:
        HTTPException: 401 - 未认证
        HTTPException: 500 - 数据库错误
    """
    # 验证用户登录状态
    if not current_user:
        logger.warning("检查手机号绑定状态失败：用户未认证")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户未认证"
        )

    user_id = current_user.get('user_id')

    logger.info(f"检查手机号绑定状态: user_id={user_id}")

    try:
        # 连接数据库
        conn = _get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            # 查询用户的手机号绑定信息
            query_sql = """
                SELECT phone, phone_verified, phone_bound_at
                FROM users
                WHERE id = %s
            """
            cursor.execute(query_sql, (user_id,))
            user_data = cursor.fetchone()

            if not user_data:
                logger.warning(f"用户不存在: user_id={user_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="用户不存在"
                )

            phone = user_data.get('phone')
            phone_verified = user_data.get('phone_verified', False)
            phone_bound_at = user_data.get('phone_bound_at')

            # 判断绑定状态
            bound = bool(phone and phone_verified)

            result = PhoneBindingStatus(
                phone=phone,
                verified=phone_verified,
                bound=bound
            )

            logger.info(
                f"手机号绑定状态查询成功: user_id={user_id}, "
                f"phone={phone}, verified={phone_verified}, bound={bound}"
            )

            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"查询手机号绑定状态失败: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"查询手机号绑定状态失败: {str(e)}"
            )
        finally:
            cursor.close()
            conn.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"检查手机号绑定状态失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"检查手机号绑定状态失败: {str(e)}"
        )
