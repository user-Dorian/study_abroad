"""用户认证 API 路由"""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, validator
from common.conversation.repository import _ensure_utc_iso
from typing import Optional

from common.utils.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    require_user,
)
from common.utils.logger import logger
from client.config.settings import Config

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ====== Pydantic 请求/响应模型 ======

class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=2, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: Optional[str] = Field(None, max_length=100, description="邮箱（可选）")

    @validator("username")
    def validate_username(cls, v):
        if not v.strip():
            raise ValueError("用户名不能为空")
        if not v.replace("_", "").isalnum():
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v.strip()

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("密码长度不能少于6位")
        return v


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class AuthResponse(BaseModel):
    """认证响应"""
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    """用户信息响应"""
    id: str
    username: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    created_at: str


class UpdateUserRequest(BaseModel):
    """更新用户信息请求"""
    email: Optional[str] = None
    display_name: Optional[str] = None


# ====== 数据库操作函数 ======

def _get_connection():
    """获取数据库连接"""
    from common.conversation.repository import _get_connection
    return _get_connection()


def _release_connection(conn):
    """释放数据库连接"""
    from common.conversation.repository import _release_connection
    _release_connection(conn)


def _find_user_by_username(username: str) -> Optional[dict]:
    """根据用户名查找用户"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, password_hash, email, display_name, created_at FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "id": str(row["id"]),
                "username": row["username"],
                "password_hash": row["password_hash"],
                "email": row["email"],
                "display_name": row["display_name"],
                "created_at": _ensure_utc_iso(row["created_at"]),
            }
    except Exception as e:
        logger.error(f"查询用户失败: {e}")
        return None
    finally:
        if conn:
            _release_connection(conn)


def _find_user_by_id(user_id: str) -> Optional[dict]:
    """根据用户ID查找用户（不返回密码哈希）"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, display_name, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "id": str(row["id"]),
                "username": row["username"],
                "email": row["email"],
                "display_name": row["display_name"],
                "created_at": _ensure_utc_iso(row["created_at"]),
            }
    except Exception as e:
        logger.error(f"查询用户失败: {e}")
        return None
    finally:
        if conn:
            _release_connection(conn)


def _create_user(username: str, password_hash: str, email: Optional[str] = None) -> dict:
    """创建新用户"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    user_id = str(uuid.uuid4())
    now = datetime.utcnow()

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO users (id, username, password_hash, email, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, username, email, display_name, created_at
                """,
                (user_id, username, password_hash, email, now, now),
            )
            row = cur.fetchone()
        conn.commit()

        return {
            "id": str(row["id"]),
            "username": row["username"],
            "email": row["email"],
            "display_name": row["display_name"],
            "created_at": _ensure_utc_iso(row["created_at"]),
        }
    except psycopg2.errors.UniqueViolation:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=409, detail="用户名已被注册")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"创建用户失败: {e}")
        raise
    finally:
        if conn:
            _release_connection(conn)


def _update_user(user_id: str, email: Optional[str] = None, display_name: Optional[str] = None) -> Optional[dict]:
    """更新用户信息"""
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = None
    try:
        conn = _get_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE users SET email = COALESCE(%s, email), display_name = COALESCE(%s, display_name), updated_at = %s
                WHERE id = %s
                RETURNING id, username, email, display_name, created_at
                """,
                (email, display_name, datetime.utcnow(), user_id),
            )
            row = cur.fetchone()
        conn.commit()

        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "username": row["username"],
            "email": row["email"],
            "display_name": row["display_name"],
            "created_at": _ensure_utc_iso(row["created_at"]),
        }
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"更新用户失败: {e}")
        raise
    finally:
        if conn:
            _release_connection(conn)


# ====== 路由 ======

@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest):
    """
    用户注册

    创建新用户账户并返回JWT令牌，注册成功后自动登录。
    """
    try:
        # 检查用户名是否已存在
        existing = _find_user_by_username(request.username)
        if existing is not None:
            raise HTTPException(status_code=409, detail="用户名已被注册")

        # 创建用户
        password_hash = get_password_hash(request.password)
        user = _create_user(request.username, password_hash, request.email)

        # 生成JWT令牌
        access_token = create_access_token(
            data={"user_id": user["id"], "username": user["username"]}
        )

        logger.info(f"用户注册成功: username={request.username}, id={user['id']}")
        return AuthResponse(
            access_token=access_token,
            user={
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "display_name": user["display_name"],
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"用户注册失败: {e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """
    用户登录

    验证用户名和密码，返回JWT令牌。
    """
    try:
        # 查找用户
        user = _find_user_by_username(request.username)
        if user is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        # 验证密码
        if not verify_password(request.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        # 生成JWT令牌
        access_token = create_access_token(
            data={"user_id": user["id"], "username": user["username"]}
        )

        # 标记用户在线
        try:
            from common.utils.online_status import mark_online
            await mark_online(str(user["id"]))
        except Exception as e:
            logger.warning(f"标记在线状态失败: {e}")

        logger.info(f"用户登录成功: username={request.username}")
        return AuthResponse(
            access_token=access_token,
            user={
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "display_name": user["display_name"],
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"用户登录失败: {e}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(require_user)):
    """
    获取当前用户信息

    需要 JWT 认证。
    """
    try:
        user = _find_user_by_id(current_user["user_id"])
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        return UserResponse(**user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户信息失败: {str(e)}")


@router.put("/me", response_model=UserResponse)
async def update_me(request: UpdateUserRequest, current_user: dict = Depends(require_user)):
    """
    更新当前用户信息

    需要 JWT 认证。可更新 email 和 display_name。
    """
    try:
        user = _update_user(current_user["user_id"], request.email, request.display_name)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        logger.info(f"用户信息更新成功: id={current_user['user_id']}")
        return UserResponse(**user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新用户信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新用户信息失败: {str(e)}")


@router.post("/refresh")
async def refresh_token(current_user: dict = Depends(require_user)):
    """
    刷新JWT令牌

    需要 JWT 认证。返回新的令牌。
    """
    try:
        new_token = create_access_token(
            data={"user_id": current_user["user_id"], "username": current_user["username"]}
        )
        return {"access_token": new_token, "token_type": "bearer"}
    except Exception as e:
        logger.error(f"刷新令牌失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新令牌失败: {str(e)}")
