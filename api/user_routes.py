"""用户资料与文档管理 API 路由"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from typing import Optional, List
import os

from utils.auth import decode_access_token
from utils.logger import logger
from user_profile.repository import get_user_profile_repo, get_user_document_repo, start_async_parse
from user_profile.document_parser import parse_document, structure_parsed_text
# 阶段2数据库异步化：导入 asyncpg 异步仓库类
from common.user_profile.repository import AsyncUserProfileRepository, AsyncUserDocumentRepository

security = HTTPBearer()
router = APIRouter()

# 阶段2数据库异步化：全局异步仓库单例（无状态，全局复用）
_async_profile_repo = AsyncUserProfileRepository()
_async_document_repo = AsyncUserDocumentRepository()


# ========== Pydantic 模型 ==========


class UserProfile(BaseModel):
    """用户资料模型"""
    nickname: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    experience_years: Optional[str] = None
    skills: Optional[List[str]] = None
    bio: Optional[str] = None


class DocumentInfo(BaseModel):
    """文档信息模型"""
    id: str
    filename: str
    file_type: str
    file_size: int
    upload_time: str


# ========== 认证依赖 ==========


async def get_current_user(credentials=Depends(security)) -> dict:
    """获取当前认证用户"""
    token = credentials.credentials
    user_info = decode_access_token(token)
    if user_info is None:
        raise HTTPException(status_code=401, detail="无效的认证令牌")
    return user_info


# ========== 用户资料 API ==========


@router.get("/api/user/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    """获取当前用户资料"""
    try:
        user_id = current_user.get("user_id")
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        profile = await _async_profile_repo.get_profile(user_id)

        if profile is None:
            # 返回空资料（前端会显示默认值）
            return {
                "nickname": None,
                "occupation": None,
                "industry": None,
                "experience_years": None,
                "skills": [],
                "bio": None,
            }

        return profile

    except Exception as e:
        logger.error(f"获取用户资料失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取用户资料失败: {str(e)}")


@router.post("/api/user/profile")
async def update_user_profile(
    profile: UserProfile,
    current_user: dict = Depends(get_current_user),
):
    """更新用户资料"""
    try:
        user_id = current_user.get("user_id")
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        updated = await _async_profile_repo.create_or_update_profile(
            user_id=user_id,
            nickname=profile.nickname,
            occupation=profile.occupation,
            industry=profile.industry,
            experience_years=profile.experience_years,
            skills=profile.skills,
            bio=profile.bio,
        )
        logger.info(f"用户资料已更新: user_id={user_id}")
        return updated

    except Exception as e:
        logger.error(f"更新用户资料失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新用户资料失败: {str(e)}")


# ========== 文档管理 API ==========


@router.get("/api/user/documents")
async def list_user_documents(current_user: dict = Depends(get_current_user)):
    """获取用户上传的文档列表"""
    try:
        user_id = current_user.get("user_id")
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        documents = await _async_document_repo.list_documents(user_id)
        # 不返回parsed_text（隐私保护）
        return [
            {
                "id": doc["id"],
                "filename": doc["filename"],
                "file_type": doc["file_type"],
                "file_size": doc["file_size"],
                "parse_status": doc["parse_status"],
                "upload_time": doc["upload_time"],
            }
            for doc in documents
        ]

    except Exception as e:
        logger.error(f"获取文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")


@router.post("/api/user/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """上传文档文件（异步解析）
    
    新流程：
    1. 保存原始文件内容和初始状态(uploading)
    2. 立即返回文档信息
    3. 后台异步解析文档
    """
    try:
        user_id = current_user.get("user_id")

        # 验证文件类型
        allowed_types = ["pdf", "docx", "txt"]
        file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
        if file_ext not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {file_ext}，仅支持PDF/DOCX/TXT"
            )

        # 验证文件大小（10MB限制）
        file_content = await file.read()
        file_size = len(file_content)
        max_size = 10 * 1024 * 1024  # 10MB
        if file_size > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"文件过大: {file_size / 1024 / 1024:.2f}MB，最大10MB"
            )

        # 创建文档记录（保存原始内容，状态为uploading，异步解析）
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        doc = await _async_document_repo.create_document(
            user_id=user_id,
            filename=file.filename,
            file_type=file_ext.upper(),
            file_size=file_size,
            file_content=file_content,
            parsed_text=None,  # 异步解析，暂无结果
        )

        # 启动后台异步解析
        start_async_parse(doc["id"], user_id)

        logger.info(f"文档上传成功（异步解析中）: user_id={user_id}, filename={file.filename}, doc_id={doc['id']}")
        return {
            "id": doc["id"],
            "filename": doc["filename"],
            "file_type": doc["file_type"],
            "file_size": doc["file_size"],
            "parse_status": doc["parse_status"],
            "upload_time": doc["upload_time"],
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"文档上传失败: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"上传文档失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传文档失败: {str(e)}")


@router.get("/api/user/documents/{document_id}/status")
async def get_document_parse_status(
    document_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取文档解析状态（用于前端轮询）"""
    try:
        user_id = current_user.get("user_id")
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        status_info = await _async_document_repo.get_document_status(document_id, user_id)

        if status_info is None:
            raise HTTPException(status_code=404, detail="文档不存在")

        return status_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取文档状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取文档状态失败: {str(e)}")


@router.delete("/api/user/documents/{document_id}")
async def delete_document(
    document_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除文档"""
    try:
        user_id = current_user.get("user_id")
        # 阶段2数据库异步化：调用 asyncpg 异步仓库，不再用 asyncio.to_thread 包装同步仓库
        deleted = await _async_document_repo.delete_document(document_id, user_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="文档不存在或无权删除")

        logger.info(f"文档已删除: id={document_id}")
        return {"success": True, "message": "文档已删除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除文档失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除文档失败: {str(e)}")