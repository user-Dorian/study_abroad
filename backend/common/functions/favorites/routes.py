"""收藏夹路由 - 管理用户收藏内容"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/favorites", tags=["收藏夹"])


class FavoriteItem(BaseModel):
    """收藏项"""
    favorite_id: str
    user_id: str
    item_type: str  # school/major/article/qa/document
    item_id: str
    title: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    created_at: datetime


class AddFavoriteRequest(BaseModel):
    """添加收藏请求"""
    item_type: str
    item_id: str
    title: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class FavoriteFolder(BaseModel):
    """收藏文件夹"""
    folder_id: str
    user_id: str
    name: str
    description: Optional[str] = None
    item_count: int = 0
    created_at: datetime


class CreateFolderRequest(BaseModel):
    """创建文件夹请求"""
    name: str
    description: Optional[str] = None


# 模拟收藏数据库
_favorites_db = {}
_folders_db = {}


@router.post("", response_model=FavoriteItem)
async def add_favorite(
    request: AddFavoriteRequest,
    current_user: dict = Depends(require_user)
):
    """添加收藏

    Args:
        request: 添加收藏请求
        current_user: 当前用户

    Returns:
        FavoriteItem: 收藏项
    """
    try:
        user_id = current_user["user_id"]

        # 检查是否已收藏
        user_favorites = _favorites_db.get(user_id, {})
        for fav in user_favorites.values():
            if fav["item_id"] == request.item_id and fav["item_type"] == request.item_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="已经收藏过该内容"
                )

        # 创建收藏
        favorite_id = str(uuid.uuid4())
        favorite = {
            "favorite_id": favorite_id,
            "user_id": user_id,
            "item_type": request.item_type,
            "item_id": request.item_id,
            "title": request.title,
            "description": request.description,
            "tags": request.tags or [],
            "created_at": datetime.utcnow()
        }

        if user_id not in _favorites_db:
            _favorites_db[user_id] = {}
        _favorites_db[user_id][favorite_id] = favorite

        logger.info(f"添加收藏: user_id={user_id}, item_type={request.item_type}, item_id={request.item_id}")

        return FavoriteItem(**favorite)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加收藏失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"添加收藏失败: {str(e)}")


@router.get("", response_model=List[FavoriteItem])
async def get_favorites(
    item_type: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(require_user)
):
    """获取收藏列表

    Args:
        item_type: 类型过滤
        limit: 返回数量限制
        current_user: 当前用户

    Returns:
        List[FavoriteItem]: 收藏列表
    """
    try:
        user_id = current_user["user_id"]

        # 获取收藏
        favorites = []
        user_favorites = _favorites_db.get(user_id, {})

        for fav in user_favorites.values():
            if item_type and fav["item_type"] != item_type:
                continue
            favorites.append(fav)

        # 按时间排序
        favorites.sort(key=lambda x: x["created_at"], reverse=True)
        favorites = favorites[:limit]

        logger.info(f"获取收藏列表: user_id={user_id}, count={len(favorites)}")

        return [FavoriteItem(**f) for f in favorites]

    except Exception as e:
        logger.error(f"获取收藏列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取收藏列表失败: {str(e)}")


@router.delete("/{favorite_id}")
async def remove_favorite(
    favorite_id: str,
    current_user: dict = Depends(require_user)
):
    """移除收藏

    Args:
        favorite_id: 收藏ID
        current_user: 当前用户

    Returns:
        dict: 移除结果

    Raises:
        HTTPException: 404 - 收藏不存在
    """
    try:
        user_id = current_user["user_id"]

        # 查找并删除收藏
        user_favorites = _favorites_db.get(user_id, {})

        if favorite_id not in user_favorites:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="收藏不存在"
            )

        del user_favorites[favorite_id]

        logger.info(f"移除收藏: favorite_id={favorite_id}")

        return {
            "success": True,
            "message": "收藏已移除"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移除收藏失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"移除收藏失败: {str(e)}")


@router.post("/folders", response_model=FavoriteFolder)
async def create_folder(
    request: CreateFolderRequest,
    current_user: dict = Depends(require_user)
):
    """创建收藏文件夹

    Args:
        request: 创建文件夹请求
        current_user: 当前用户

    Returns:
        FavoriteFolder: 文件夹
    """
    try:
        user_id = current_user["user_id"]

        # 创建文件夹
        folder_id = str(uuid.uuid4())
        folder = {
            "folder_id": folder_id,
            "user_id": user_id,
            "name": request.name,
            "description": request.description,
            "item_count": 0,
            "created_at": datetime.utcnow()
        }

        if user_id not in _folders_db:
            _folders_db[user_id] = {}
        _folders_db[user_id][folder_id] = folder

        logger.info(f"创建收藏文件夹: user_id={user_id}, folder_id={folder_id}")

        return FavoriteFolder(**folder)

    except Exception as e:
        logger.error(f"创建收藏文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建收藏文件夹失败: {str(e)}")


@router.get("/folders", response_model=List[FavoriteFolder])
async def get_folders(current_user: dict = Depends(require_user)):
    """获取收藏文件夹列表

    Args:
        current_user: 当前用户

    Returns:
        List[FavoriteFolder]: 文件夹列表
    """
    try:
        user_id = current_user["user_id"]

        # 获取文件夹
        folders = list(_folders_db.get(user_id, {}).values())

        logger.info(f"获取收藏文件夹列表: user_id={user_id}, count={len(folders)}")

        return [FavoriteFolder(**f) for f in folders]

    except Exception as e:
        logger.error(f"获取收藏文件夹列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取收藏文件夹列表失败: {str(e)}")


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: str,
    current_user: dict = Depends(require_user)
):
    """删除收藏文件夹

    Args:
        folder_id: 文件夹ID
        current_user: 当前用户

    Returns:
        dict: 删除结果

    Raises:
        HTTPException: 404 - 文件夹不存在
    """
    try:
        user_id = current_user["user_id"]

        # 查找并删除文件夹
        user_folders = _folders_db.get(user_id, {})

        if folder_id not in user_folders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件夹不存在"
            )

        del user_folders[folder_id]

        logger.info(f"删除收藏文件夹: folder_id={folder_id}")

        return {
            "success": True,
            "message": "文件夹已删除"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除收藏文件夹失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除收藏文件夹失败: {str(e)}")


@router.get("/check/{item_type}/{item_id}")
async def check_favorite(
    item_type: str,
    item_id: str,
    current_user: dict = Depends(require_user)
):
    """检查是否已收藏

    Args:
        item_type: 类型
        item_id: 项目ID
        current_user: 当前用户

    Returns:
        dict: 是否已收藏
    """
    try:
        user_id = current_user["user_id"]

        # 检查收藏
        user_favorites = _favorites_db.get(user_id, {})
        is_favorite = any(
            fav["item_id"] == item_id and fav["item_type"] == item_type
            for fav in user_favorites.values()
        )

        return {
            "is_favorite": is_favorite,
            "item_type": item_type,
            "item_id": item_id
        }

    except Exception as e:
        logger.error(f"检查收藏状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查收藏状态失败: {str(e)}")
