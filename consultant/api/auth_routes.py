"""规划师端认证路由 - 基于JWT的用户认证，使用 enterprise_users 表"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi import Header as FastAPIHeader
from pydantic import BaseModel, field_validator
from typing import Optional
import re

from common.utils.logger import logger
from consultant.config.settings import ConsultantConfig

router = APIRouter()


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    password: str
    email: Optional[str] = None
    display_name: Optional[str] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]{2,50}$', v):
            raise ValueError("用户名只能包含字母、数字和下划线（2-50位）")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 6:
            raise ValueError("密码长度至少6位")
        return v


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


class RefreshRequest(BaseModel):
    """令牌刷新请求"""
    refresh_token: str


def _get_db_connection():
    """获取数据库连接"""
    import psycopg2
    from consultant.config.database import ConsultantDatabaseConfig
    return psycopg2.connect(**ConsultantDatabaseConfig.get_connection_params())


def _create_enterprise_users_table_if_not_exists():
    """创建 enterprise_users 表（如果不存在）"""
    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS enterprise_users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    email VARCHAR(255) DEFAULT '',
                    display_name VARCHAR(100) DEFAULT '',
                    role VARCHAR(20) DEFAULT 'consultant',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        logger.info("[规划师端] enterprise_users 表已就绪")
    except Exception as e:
        logger.error(f"[规划师端] 创建 enterprise_users 表失败: {e}")
        raise
    finally:
        if conn:
            conn.close()


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
    try:
        payload = decode_access_token(token, ConsultantConfig.JWT_SECRET_KEY, ConsultantConfig.JWT_ALGORITHM)
        if payload is None:
            raise HTTPException(status_code=401, detail="无效的认证令牌")
        return {
            "user_id": payload.get("user_id"),
            "username": payload.get("sub"),
            "role": payload.get("role", "client"),
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"认证失败: {str(e)}")


@router.post("/api/auth/register")
async def register(request: RegisterRequest):
    """规划师注册 - 使用 enterprise_users 表，同时同步到 users 表（满足 conversations 外键约束）"""
    from common.utils.auth import get_password_hash
    import uuid

    # 确保 enterprise_users 表存在
    _create_enterprise_users_table_if_not_exists()

    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM enterprise_users WHERE username = %s", (request.username,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="用户名已存在")

            user_id = str(uuid.uuid4())
            password_hash = get_password_hash(request.password)

            # 插入 enterprise_users 表
            cur.execute(
                """INSERT INTO enterprise_users (id, username, password_hash, email, display_name, role, created_at)
                   VALUES (%s, %s, %s, %s, %s, 'consultant', NOW())""",
                (user_id, request.username, password_hash,
                 request.email or "", request.display_name or request.username)
            )

            # 同步插入 users 表（满足 conversations 表外键约束）
            cur.execute("""
                INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """, (
                user_id,
                request.username,
                request.email or "",
                password_hash,
                "consultant",
            ))

            conn.commit()

        from common.utils.auth import create_access_token
        access_token = create_access_token(
            data={"sub": request.username, "user_id": user_id, "role": "consultant"},
            secret_key=ConsultantConfig.JWT_SECRET_KEY,
            algorithm=ConsultantConfig.JWT_ALGORITHM,
            expires_hours=ConsultantConfig.JWT_EXPIRATION_HOURS,
        )

        logger.info(f"[规划师端] 新用户注册: {request.username} (id={user_id})")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "user_id": user_id,
                "username": request.username,
                "display_name": request.display_name or request.username,
                "email": request.email or "",
                "role": "consultant",
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 注册失败: {e}")
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.post("/api/auth/login")
async def login(request: LoginRequest):
    """规划师登录 - 使用 enterprise_users 表"""
    from common.utils.auth import verify_password, create_access_token

    conn = None
    try:
        conn = _get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, email, display_name, role FROM enterprise_users WHERE username = %s",
                (request.username,)
            )
            user = cur.fetchone()

            if not user:
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            stored_hash = user["password_hash"] if isinstance(user, dict) else user[2]
            if not verify_password(request.password, stored_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            user_id = user["id"] if isinstance(user, dict) else user[0]
            username = user["username"] if isinstance(user, dict) else user[1]
            email = user["email"] if isinstance(user, dict) else (user[3] if len(user) > 3 else "")
            display_name = user["display_name"] if isinstance(user, dict) else (user[4] if len(user) > 4 else username)
            role = user["role"] if isinstance(user, dict) else (user[5] if len(user) > 5 else "client")

            # 同步到 users 表（兼容旧用户，确保 conversations 外键约束满足）
            cur.execute("""
                INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """, (
                user_id,
                username,
                email,
                stored_hash,
                role,
            ))
            conn.commit()

        access_token = create_access_token(
            data={"sub": username, "user_id": user_id, "role": role},
            secret_key=ConsultantConfig.JWT_SECRET_KEY,
            algorithm=ConsultantConfig.JWT_ALGORITHM,
            expires_hours=ConsultantConfig.JWT_EXPIRATION_HOURS,
        )

        logger.info(f"[规划师端] 用户登录: {username} (role={role})")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "user_id": user_id,
                "username": username,
                "display_name": display_name,
                "email": email,
                "role": role,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[规划师端] 登录失败: {e}")
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.get("/api/auth/me")
async def get_current_user_info(
    current_user: dict = Depends(_get_current_user_from_header),
):
    """获取当前用户信息"""
    return current_user


@router.put("/api/auth/me")
async def update_current_user(
    request: dict,
    current_user: dict = Depends(_get_current_user_from_header),
):
    """更新当前用户信息"""
    conn = None
    try:
        conn = _get_db_connection()
        user_id = current_user["user_id"]

        updates = []
        params = []
        for field in ["display_name", "email"]:
            if field in request:
                updates.append(f"{field} = %s")
                params.append(request[field])

        if not updates:
            return {"message": "无更新内容"}

        params.append(user_id)
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE enterprise_users SET {', '.join(updates)} WHERE id = %s",
                params
            )
            conn.commit()

        logger.info(f"[规划师端] 用户信息更新: {user_id}")
        return {"message": "更新成功"}
    except Exception as e:
        logger.error(f"[规划师端] 更新用户信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
    finally:
        if conn:
            conn.close()


@router.post("/api/auth/refresh")
async def refresh_token(request: RefreshRequest):
    """刷新JWT令牌"""
    from common.utils.auth import decode_access_token, create_access_token
    try:
        payload = decode_access_token(
            request.refresh_token,
            ConsultantConfig.JWT_SECRET_KEY,
            ConsultantConfig.JWT_ALGORITHM
        )
        if payload is None:
            raise HTTPException(status_code=401, detail="无效的刷新令牌")

        new_token = create_access_token(
            data={"sub": payload["sub"], "user_id": payload["user_id"], "role": payload.get("role", "client")},
            secret_key=ConsultantConfig.JWT_SECRET_KEY,
            algorithm=ConsultantConfig.JWT_ALGORITHM,
            expires_hours=ConsultantConfig.JWT_EXPIRATION_HOURS,
        )
        return {"access_token": new_token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"令牌刷新失败: {str(e)}")
