"""用户个人资料 API 路由 - 双端通用

包括：
1. 获取/更新个人资料
2. 手机号绑定
3. 获取用户详情（公开信息）
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List

from common.utils.auth import require_user
from common.utils.logger import logger
from common.config.async_database import AsyncDatabasePool

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _mask_phone(phone: str) -> str:
    """脱敏手机号"""
    if phone and len(phone) == 11:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone


# ====== 请求/响应模型 ======

class ProfileResponse(BaseModel):
    """个人资料响应"""
    id: str
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_bound: bool = False
    avatar_url: str = ""
    role: str = "client"
    # 个人资料
    nickname: Optional[str] = None
    real_name: Optional[str] = None
    gender: str = "保密"
    birth_year: Optional[str] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    experience_years: Optional[str] = None
    education: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[List[str]] = None
    target_country: Optional[str] = None
    target_level: Optional[str] = None
    language_score: Optional[str] = None
    website: Optional[str] = None
    # 规划师专属
    consultant_bio: Optional[str] = None
    expertise_areas: Optional[List[str]] = None
    service_price: Optional[str] = None
    experience_years_consultant: Optional[str] = None
    success_cases: int = 0
    rating: float = 0.0
    verified: bool = False
    # 时间
    created_at: str
    updated_at: str


class UpdateProfileRequest(BaseModel):
    """更新个人资料请求"""
    display_name: Optional[str] = Field(None, max_length=50, description="显示名称")
    email: Optional[str] = Field(None, max_length=100, description="邮箱")
    avatar_url: Optional[str] = Field(None, max_length=500, description="头像URL")
    nickname: Optional[str] = Field(None, max_length=50, description="昵称")
    real_name: Optional[str] = Field(None, max_length=50, description="真实姓名")
    gender: Optional[str] = Field(None, pattern="^(男|女|保密)$", description="性别")
    birth_year: Optional[str] = Field(None, max_length=10, description="出生年份")
    city: Optional[str] = Field(None, max_length=100, description="所在城市")
    occupation: Optional[str] = Field(None, max_length=100, description="职业")
    industry: Optional[str] = Field(None, max_length=50, description="行业")
    experience_years: Optional[str] = Field(None, max_length=20, description="从业年限")
    education: Optional[str] = Field(None, max_length=200, description="教育背景")
    bio: Optional[str] = Field(None, max_length=500, description="个人简介")
    skills: Optional[List[str]] = Field(None, description="技能标签")
    target_country: Optional[str] = Field(None, max_length=100, description="留学意向国家")
    target_level: Optional[str] = Field(None, max_length=50, description="留学意向阶段")
    language_score: Optional[str] = Field(None, max_length=100, description="语言成绩")
    website: Optional[str] = Field(None, max_length=500, description="个人网站")
    # 规划师专属
    consultant_bio: Optional[str] = Field(None, max_length=1000, description="规划师简介")
    expertise_areas: Optional[List[str]] = Field(None, description="专长领域")
    service_price: Optional[str] = Field(None, max_length=200, description="服务价格")
    experience_years_consultant: Optional[str] = Field(None, max_length=20, description="从业年限")
    success_cases: Optional[int] = Field(None, ge=0, description="成功案例数")
    verified: Optional[bool] = Field(None, description="认证状态")


class UpdatePhoneRequest(BaseModel):
    """更新手机号请求"""
    phone: str = Field(..., pattern=r"^\d{11}$", description="11位手机号")


class UserPublicInfo(BaseModel):
    """用户公开信息（用于展示给其他人）"""
    id: str
    username: str
    display_name: Optional[str] = None
    avatar_url: str = ""
    role: str = "client"
    bio: Optional[str] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    education: Optional[str] = None
    target_country: Optional[str] = None
    target_level: Optional[str] = None
    # 规划师专属
    consultant_bio: Optional[str] = None
    expertise_areas: Optional[List[str]] = None
    service_price: Optional[str] = None
    experience_years_consultant: Optional[str] = None
    success_cases: int = 0
    rating: float = 0.0
    verified: bool = False


# ====== 辅助函数 ======

async def _get_or_create_profile(user_id: str) -> dict:
    """获取用户资料，不存在则创建"""
    profile = await AsyncDatabasePool.execute_one(
        "SELECT * FROM user_profiles WHERE user_id = $1", user_id
    )
    if profile is None:
        # 创建默认资料（使用 SQL 内置 NOW() 函数，而非参数传递）
        await AsyncDatabasePool.execute_command(
            "INSERT INTO user_profiles (user_id, nickname, created_at, updated_at) VALUES ($1, '', NOW(), NOW())",
            user_id,
        )
        profile = await AsyncDatabasePool.execute_one(
            "SELECT * FROM user_profiles WHERE user_id = $1", user_id
        )
    return profile


async def _get_user_info(user_id: str) -> dict:
    """获取用户基本信息"""
    return await AsyncDatabasePool.execute_one(
        "SELECT id, username, display_name, email, phone, avatar_url, role, bio, created_at, updated_at FROM users WHERE id = $1",
        user_id,
    )


# ====== 路由实现 ======

@router.get("/me", response_model=ProfileResponse)
async def get_my_profile(current_user: dict = Depends(require_user)):
    """获取当前用户的完整个人资料"""
    try:
        user_id = current_user["user_id"]
        user = await _get_user_info(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        profile = await _get_or_create_profile(user_id)

        phone = user.get("phone") or ""
        return ProfileResponse(
            id=str(user["id"]),
            username=user["username"],
            display_name=user.get("display_name"),
            email=user.get("email"),
            phone=_mask_phone(phone) if phone else None,
            phone_bound=bool(phone),
            avatar_url=profile.get("avatar_url") or user.get("avatar_url") or "",
            role=user.get("role", "client"),
            nickname=profile.get("nickname"),
            real_name=profile.get("real_name"),
            gender=profile.get("gender", "保密"),
            birth_year=profile.get("birth_year"),
            city=profile.get("city"),
            occupation=profile.get("occupation"),
            industry=profile.get("industry"),
            experience_years=profile.get("experience_years"),
            education=profile.get("education"),
            bio=profile.get("bio") or user.get("bio"),
            skills=profile.get("skills"),
            target_country=profile.get("target_country"),
            target_level=profile.get("target_level"),
            language_score=profile.get("language_score"),
            website=profile.get("website"),
            consultant_bio=profile.get("consultant_bio"),
            expertise_areas=profile.get("expertise_areas"),
            service_price=profile.get("service_price"),
            experience_years_consultant=profile.get("experience_years_consultant"),
            success_cases=profile.get("success_cases", 0),
            rating=float(profile.get("rating") or 0),
            verified=profile.get("verified", False),
            created_at=str(profile.get("created_at", "")),
            updated_at=str(profile.get("updated_at", "")),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取个人资料失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取个人资料失败: {str(e)}")


@router.put("/me")
async def update_my_profile(
    request: UpdateProfileRequest,
    current_user: dict = Depends(require_user),
):
    """更新当前用户的个人资料"""
    try:
        user_id = current_user["user_id"]

        # 更新 users 表字段
        user_updates = {}
        if request.display_name is not None:
            user_updates["display_name"] = request.display_name
        if request.email is not None:
            user_updates["email"] = request.email
        if request.avatar_url is not None:
            user_updates["avatar_url"] = request.avatar_url
        if request.bio is not None:
            user_updates["bio"] = request.bio

        if user_updates:
            set_parts = ", ".join([f"{k} = ${i+1}" for i, k in enumerate(user_updates.keys())])
            values = list(user_updates.values())
            values.append(user_id)
            await AsyncDatabasePool.execute_command(
                f"UPDATE users SET {set_parts} WHERE id = ${len(values)}",
                *values,
            )

        # 更新 user_profiles 表
        profile_fields = [
            "nickname", "real_name", "gender", "birth_year", "city",
            "occupation", "industry", "experience_years", "education",
            "skills", "target_country", "target_level", "language_score",
            "website", "consultant_bio", "expertise_areas", "service_price",
            "experience_years_consultant", "success_cases", "verified",
        ]

        profile_updates = {}
        for field in profile_fields:
            val = getattr(request, field, None)
            if val is not None:
                profile_updates[field] = val

        if profile_updates:
            # 确保资料记录存在
            await _get_or_create_profile(user_id)
            set_parts = ", ".join([f"{k} = ${i+1}" for i, k in enumerate(profile_updates.keys())])
            values = list(profile_updates.values())
            values.append(user_id)
            await AsyncDatabasePool.execute_command(
                f"UPDATE user_profiles SET {set_parts}, updated_at = NOW() WHERE user_id = ${len(values)}",
                *values,
            )

        logger.info(f"更新个人资料成功: user_id={user_id}")
        return {"success": True, "message": "个人资料更新成功"}

    except Exception as e:
        logger.error(f"更新个人资料失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新个人资料失败: {str(e)}")


@router.put("/me/phone")
async def update_phone(
    request: UpdatePhoneRequest,
    current_user: dict = Depends(require_user),
):
    """绑定手机号"""
    try:
        phone = request.phone.strip()
        user_id = current_user["user_id"]

        # 检查手机号是否已被其他用户绑定
        existing = await AsyncDatabasePool.execute_one(
            "SELECT id FROM users WHERE phone = $1 AND id != $2",
            phone, user_id,
        )
        if existing:
            raise HTTPException(status_code=409, detail="该手机号已被其他用户绑定")

        await AsyncDatabasePool.execute_command(
            "UPDATE users SET phone = $1 WHERE id = $2",
            phone, user_id,
        )
        logger.info(f"手机号绑定成功: user_id={user_id}, phone={_mask_phone(phone)}")
        return {"success": True, "phone": _mask_phone(phone)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"手机号绑定失败: {e}")
        raise HTTPException(status_code=500, detail=f"手机号绑定失败: {str(e)}")


@router.get("/me/phone-status")
async def get_phone_status(current_user: dict = Depends(require_user)):
    """获取手机号绑定状态"""
    try:
        user_id = current_user["user_id"]
        row = await AsyncDatabasePool.execute_one(
            "SELECT phone FROM users WHERE id = $1", user_id
        )
        if row is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        phone = row.get("phone")
        return {
            "phone_bound": bool(phone),
            "phone": _mask_phone(phone) if phone else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取手机号状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取手机号状态失败: {str(e)}")


@router.get("/user/{user_id}", response_model=UserPublicInfo)
async def get_user_public_info(user_id: str):
    """获取用户公开信息（无需认证，用于展示给其他人）"""
    try:
        user = await AsyncDatabasePool.execute_one(
            "SELECT id, username, display_name, avatar_url, role, bio FROM users WHERE id = $1",
            user_id,
        )
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")

        profile = await AsyncDatabasePool.execute_one(
            "SELECT * FROM user_profiles WHERE user_id = $1", user_id
        )

        return UserPublicInfo(
            id=str(user["id"]),
            username=user["username"],
            display_name=user.get("display_name"),
            avatar_url=profile.get("avatar_url") if profile else user.get("avatar_url") or "",
            role=user.get("role", "client"),
            bio=profile.get("bio") if profile else user.get("bio"),
            city=profile.get("city") if profile else None,
            occupation=profile.get("occupation") if profile else None,
            industry=profile.get("industry") if profile else None,
            education=profile.get("education") if profile else None,
            target_country=profile.get("target_country") if profile else None,
            target_level=profile.get("target_level") if profile else None,
            consultant_bio=profile.get("consultant_bio") if profile else None,
            expertise_areas=profile.get("expertise_areas") if profile else None,
            service_price=profile.get("service_price") if profile else None,
            experience_years_consultant=profile.get("experience_years_consultant") if profile else None,
            success_cases=profile.get("success_cases", 0) if profile else 0,
            rating=float(profile.get("rating") or 0) if profile else 0.0,
            verified=profile.get("verified", False) if profile else False,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户公开信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户信息失败: {str(e)}")


# ============================
# 资料完整度 + 弹窗引导
# ============================

# 必填字段(用于资料完整度计算)
REQUIRED_FIELDS = {
    "client": ["phone", "real_name", "target_country"],
    "consultant": ["phone", "real_name", "consultant_bio", "expertise_areas"],
}
# 选填字段(影响资料完整度,缺失会扣分)
OPTIONAL_FIELDS = {
    "client": ["bio", "city", "education", "language_score"],
    "consultant": ["service_price", "experience_years_consultant", "success_cases"],
}

# 必填字段权重(影响完整度)
REQUIRED_FIELD_WEIGHT = 25  # 4个必填字段,共100分
OPTIONAL_FIELD_WEIGHT = 5   # 多个选填字段,共20分(超过100按100计算)


@router.get("/completeness")
async def get_profile_completeness(
    current_user: dict = Depends(require_user),
):
    """
    获取当前用户的资料完整度

    返回:
    - completeness: 完整度(0-100)
    - missing_required: 缺失的必填字段列表
    - missing_optional: 缺失的选填字段列表
    - phone_bound: 是否绑定手机号
    """
    user_id = current_user["user_id"]
    role = current_user.get("role", "client")

    try:
        # 获取用户资料
        user = await AsyncDatabasePool.execute_one(
            "SELECT phone FROM users WHERE id = $1", user_id,
        )
        profile = await AsyncDatabasePool.execute_one(
            "SELECT * FROM user_profiles WHERE user_id = $1", user_id,
        )

        phone_bound = bool(user and user.get("phone"))

        # 计算缺失的必填字段
        required_fields = REQUIRED_FIELDS.get(role, REQUIRED_FIELDS["client"])
        missing_required = []

        if not phone_bound:
            missing_required.append("phone")

        if profile:
            for field in required_fields:
                if field == "phone":
                    continue
                val = profile.get(field)
                if val is None or val == "" or val == [] or val == "{}":
                    missing_required.append(field)
        else:
            missing_required.extend([f for f in required_fields if f != "phone"])

        # 计算缺失的选填字段
        optional_fields = OPTIONAL_FIELDS.get(role, OPTIONAL_FIELDS["client"])
        missing_optional = []
        if profile:
            for field in optional_fields:
                val = profile.get(field)
                if val is None or val == "" or val == []:
                    missing_optional.append(field)
        else:
            missing_optional = list(optional_fields)

        # 计算完整度
        # 必填字段分: 100分均分
        total_required = len(required_fields)
        if total_required == 0:
            completeness = 100
        else:
            filled_required = total_required - len(missing_required)
            completeness = int((filled_required / total_required) * 100)

        # 选填字段加分(最多+20)
        total_optional = len(optional_fields)
        if total_optional > 0:
            filled_optional = total_optional - len(missing_optional)
            bonus = int((filled_optional / total_optional) * 20)
            completeness = min(100, completeness + bonus)

        return {
            "completeness": completeness,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
            "phone_bound": phone_bound,
            "role": role,
        }

    except Exception as e:
        logger.error(f"获取资料完整度失败: user_id={user_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"获取完整度失败: {str(e)}")


@router.post("/me/dismiss-phone-reminder")
async def dismiss_phone_reminder(
    current_user: dict = Depends(require_user),
):
    """
    关闭手机号绑定引导弹窗(Redis 24h 静默)

    - 24小时内不再弹窗
    - 不影响其他引导(好友申请、注销等)
    """
    user_id = current_user["user_id"]
    try:
        from common.config.async_redis import AsyncRedisPool
        client = await AsyncRedisPool.get_client()
        key = f"phone_reminder_dismissed:{user_id}"
        await client.setex(key, 86400, "1")  # 24小时
        logger.info(f"[手机号引导] 关闭弹窗24h: user_id={user_id}")
        return {"success": True, "message": "已关闭,24小时内不再提醒"}
    except Exception as e:
        logger.error(f"关闭手机号引导失败: {e}")
        raise HTTPException(status_code=500, detail=f"关闭失败: {str(e)}")


async def should_show_phone_reminder(user_id: str) -> bool:
    """
    检查是否应该显示手机号绑定引导

    规则:
    - 已绑定 → False
    - Redis 24h 静默中 → False
    - 其他 → True
    """
    # 检查是否已绑定
    user = await AsyncDatabasePool.execute_one(
        "SELECT phone FROM users WHERE id = $1", user_id,
    )
    if user and user.get("phone"):
        return False

    # 检查 Redis 静默标记
    try:
        from common.config.async_redis import AsyncRedisPool
        client = await AsyncRedisPool.get_client()
        key = f"phone_reminder_dismissed:{user_id}"
        dismissed = await client.exists(key)
        if dismissed:
            return False
    except Exception as e:
        logger.warning(f"检查 Redis 静默标记失败(非阻塞): {e}")

    return True