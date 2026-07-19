"""用户资料路由 - 管理用户详细资料"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user
from backend.common.functions.info_collect.repository import get_async_student_profile_repo
from backend.common.functions.info_collect.model import STUDENT_FIELDS_META

router = APIRouter(prefix="/api/profile", tags=["用户资料"])

# 独立路由：不带 prefix，直接挂载到 /api/student-profile
# 用于前端 index.html 调用（与 /api/profile/student 保持向后兼容）
student_profile_router = APIRouter(tags=["学生资料"])


class UserProfile(BaseModel):
    """用户资料"""
    user_id: str
    nickname: Optional[str] = None
    real_name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    experience_years: Optional[int] = None
    skills: Optional[List[str]] = None
    bio: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StudentProfile(BaseModel):
    """学生资料"""
    user_id: str
    real_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    target_country: Optional[str] = None
    target_level: Optional[str] = None
    target_major: Optional[str] = None
    current_school: Optional[str] = None
    current_major: Optional[str] = None
    gpa: Optional[float] = None
    language_type: Optional[str] = None
    language_score: Optional[float] = None
    budget: Optional[str] = None
    entry_time: Optional[str] = None
    notes: Optional[str] = None
    completion_rate: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UpdateProfileRequest(BaseModel):
    """更新资料请求"""
    nickname: Optional[str] = None
    real_name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    experience_years: Optional[int] = None
    skills: Optional[List[str]] = None
    bio: Optional[str] = None


class UpdateStudentProfileRequest(BaseModel):
    """更新学生资料请求"""
    real_name: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    phone: Optional[str] = None
    wechat: Optional[str] = None
    target_country: Optional[str] = None
    target_level: Optional[str] = None
    target_major: Optional[str] = None
    current_school: Optional[str] = None
    current_major: Optional[str] = None
    gpa: Optional[float] = None
    language_type: Optional[str] = None
    language_score: Optional[float] = None
    budget: Optional[str] = None
    entry_time: Optional[str] = None
    notes: Optional[str] = None


# 模拟用户资料数据库
_profiles_db = {}
_student_profiles_db = {}


@router.get("", response_model=UserProfile)
async def get_profile(current_user: dict = Depends(require_user)):
    """获取用户资料

    Args:
        current_user: 当前用户

    Returns:
        UserProfile: 用户资料
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建默认资料
        profile = _profiles_db.get(user_id, {
            "user_id": user_id,
            "created_at": datetime.utcnow()
        })

        logger.info(f"获取用户资料: user_id={user_id}")

        return UserProfile(**profile)

    except Exception as e:
        logger.error(f"获取用户资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取用户资料失败: {str(e)}")


@router.put("", response_model=UserProfile)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: dict = Depends(require_user)
):
    """更新用户资料

    Args:
        request: 更新资料请求
        current_user: 当前用户

    Returns:
        UserProfile: 更新后的用户资料
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建资料
        if user_id not in _profiles_db:
            _profiles_db[user_id] = {
                "user_id": user_id,
                "created_at": datetime.utcnow()
            }

        # 更新资料
        profile = _profiles_db[user_id]
        update_data = request.dict(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                profile[key] = value

        profile["updated_at"] = datetime.utcnow()

        logger.info(f"更新用户资料: user_id={user_id}")

        return UserProfile(**profile)

    except Exception as e:
        logger.error(f"更新用户资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新用户资料失败: {str(e)}")


@router.get("/student", response_model=StudentProfile)
async def get_student_profile(current_user: dict = Depends(require_user)):
    """获取学生资料

    Args:
        current_user: 当前用户

    Returns:
        StudentProfile: 学生资料
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建默认资料
        profile = _student_profiles_db.get(user_id, {
            "user_id": user_id,
            "completion_rate": 0,
            "created_at": datetime.utcnow()
        })

        logger.info(f"获取学生资料: user_id={user_id}")

        return StudentProfile(**profile)

    except Exception as e:
        logger.error(f"获取学生资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取学生资料失败: {str(e)}")


@router.put("/student", response_model=StudentProfile)
async def update_student_profile(
    request: UpdateStudentProfileRequest,
    current_user: dict = Depends(require_user)
):
    """更新学生资料

    Args:
        request: 更新资料请求
        current_user: 当前用户

    Returns:
        StudentProfile: 更新后的学生资料
    """
    try:
        user_id = current_user["user_id"]

        # 获取或创建资料
        if user_id not in _student_profiles_db:
            _student_profiles_db[user_id] = {
                "user_id": user_id,
                "completion_rate": 0,
                "created_at": datetime.utcnow()
            }

        # 更新资料
        profile = _student_profiles_db[user_id]
        update_data = request.dict(exclude_unset=True)
        for key, value in update_data.items():
            if value is not None:
                profile[key] = value

        profile["updated_at"] = datetime.utcnow()

        # 计算完成率
        total_fields = len([k for k, v in profile.items()
                          if k not in ['user_id', 'created_at', 'updated_at', 'completion_rate']])
        filled_fields = len([k for k, v in profile.items()
                            if k not in ['user_id', 'created_at', 'updated_at', 'completion_rate'] and v])
        if total_fields > 0:
            profile["completion_rate"] = int((filled_fields / total_fields) * 100)

        logger.info(f"更新学生资料: user_id={user_id}, completion={profile['completion_rate']}%")

        return StudentProfile(**profile)

    except Exception as e:
        logger.error(f"更新学生资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新学生资料失败: {str(e)}")


@router.get("/completion")
async def get_profile_completion(current_user: dict = Depends(require_user)):
    """获取资料完成度

    Args:
        current_user: 当前用户

    Returns:
        dict: 资料完成度信息
    """
    try:
        user_id = current_user["user_id"]

        # 获取学生资料
        profile = _student_profiles_db.get(user_id, {})
        completion_rate = profile.get("completion_rate", 0)

        # 计算缺失字段
        required_fields = ['real_name', 'age', 'phone', 'target_country',
                          'target_level', 'target_major', 'current_school', 'gpa']
        missing_fields = [f for f in required_fields if not profile.get(f)]

        logger.info(f"获取资料完成度: user_id={user_id}, completion={completion_rate}%")

        return {
            "completion_rate": completion_rate,
            "missing_fields": missing_fields,
            "is_complete": completion_rate >= 80
        }

    except Exception as e:
        logger.error(f"获取资料完成度失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取资料完成度失败: {str(e)}")


# ====== 独立路由：/api/student-profile ======
# 供前端 index.html 直接调用，从真实数据库读取（区别于 /api/profile/student 使用内存字典）

def _calculate_completion_rate(profile: Dict[str, Any]) -> int:
    """基于 STUDENT_FIELDS_META 计算资料完成率

    Args:
        profile: 学生profile字典

    Returns:
        int: 完成率（0-100）
    """
    if not profile:
        return 0
    total = len(STUDENT_FIELDS_META)
    if total == 0:
        return 0
    filled = 0
    for field_name in STUDENT_FIELDS_META.keys():
        val = profile.get(field_name)
        if val is not None and str(val).strip() != "":
            filled += 1
    return int((filled / total) * 100)


@student_profile_router.get("/api/student-profile")
async def get_student_profile_db(current_user: dict = Depends(require_user)):
    """获取学生资料（从真实数据库读取）

    供前端 index.html 第1501行调用，返回格式：
        {"profile": {...}, "completion_rate": int}

    Args:
        current_user: 当前用户

    Returns:
        dict: {"profile": profile, "completion_rate": rate}
    """
    try:
        user_id = current_user["user_id"]

        repo = get_async_student_profile_repo()
        profile = await repo.get_profile(str(user_id))

        if profile is None:
            logger.info(f"学生资料不存在，返回空profile: user_id={user_id}")
            return {"profile": {}, "completion_rate": 0}

        completion_rate = _calculate_completion_rate(profile)
        logger.info(f"获取学生资料成功: user_id={user_id}, completion={completion_rate}%")

        return {"profile": profile, "completion_rate": completion_rate}

    except Exception as e:
        logger.error(f"获取学生资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取学生资料失败: {str(e)}")


@student_profile_router.put("/api/student-profile")
async def update_student_profile_db(
    request: UpdateStudentProfileRequest,
    current_user: dict = Depends(require_user)
):
    """更新学生资料（写入真实数据库）

    供前端调用更新学生信息，使用 repo.upsert_fields 写入数据库。

    Args:
        request: 更新资料请求
        current_user: 当前用户

    Returns:
        dict: {"profile": updated_profile, "completion_rate": rate}
    """
    try:
        user_id = current_user["user_id"]

        # 只取非 None 字段
        update_data = request.dict(exclude_unset=True)
        update_data = {k: v for k, v in update_data.items() if v is not None}

        if not update_data:
            logger.warning(f"更新学生资料无有效字段: user_id={user_id}")
            raise HTTPException(status_code=400, detail="未提供任何有效的更新字段")

        repo = get_async_student_profile_repo()
        success = await repo.upsert_fields(str(user_id), update_data)

        if not success:
            logger.error(f"更新学生资料写入数据库失败: user_id={user_id}")
            raise HTTPException(status_code=500, detail="更新学生资料失败")

        # 读取更新后的 profile 返回
        updated_profile = await repo.get_profile(str(user_id))
        completion_rate = _calculate_completion_rate(updated_profile or {})

        logger.info(f"更新学生资料成功: user_id={user_id}, completion={completion_rate}%")

        return {"profile": updated_profile or {}, "completion_rate": completion_rate}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新学生资料失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新学生资料失败: {str(e)}")
