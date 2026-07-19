"""好友关系路由 - 管理用户好友、联系人"""
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger
from backend.common.basics.utils.auth import require_user

router = APIRouter(prefix="/api/friendship", tags=["好友管理"])


class FriendshipRequest(BaseModel):
    """好友请求"""
    to_user_id: str
    message: Optional[str] = None


class FriendshipResponse(BaseModel):
    """好友关系响应"""
    friendship_id: str
    user_id: str
    friend_id: str
    status: str  # pending/accepted/rejected
    created_at: datetime
    updated_at: Optional[datetime] = None


class FriendInfo(BaseModel):
    """好友信息"""
    user_id: str
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str  # online/offline


# 模拟好友数据库
_friendships_db = {}
_friend_requests_db = {}


@router.post("/request", response_model=FriendshipResponse)
async def send_friend_request(
    request: FriendshipRequest,
    current_user: dict = Depends(require_user)
):
    """发送好友请求

    Args:
        request: 好友请求
        current_user: 当前用户

    Returns:
        FriendshipResponse: 好友关系响应

    Raises:
        HTTPException: 400 - 不能添加自己为好友/已是好友/请求已存在
    """
    try:
        user_id = current_user["user_id"]

        # 检查是否添加自己
        if user_id == request.to_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能添加自己为好友"
            )

        # 检查是否已是好友
        friendship_key = f"{user_id}:{request.to_user_id}"
        if friendship_key in _friendships_db:
            friendship = _friendships_db[friendship_key]
            if friendship["status"] == "accepted":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="已经是好友关系"
                )

        # 创建好友请求
        friendship_id = str(uuid.uuid4())
        friendship = {
            "friendship_id": friendship_id,
            "user_id": user_id,
            "friend_id": request.to_user_id,
            "status": "pending",
            "message": request.message,
            "created_at": datetime.utcnow()
        }

        _friendships_db[friendship_key] = friendship
        _friend_requests_db[friendship_id] = friendship

        logger.info(f"好友请求发送成功: from={user_id}, to={request.to_user_id}")

        return FriendshipResponse(
            friendship_id=friendship_id,
            user_id=user_id,
            friend_id=request.to_user_id,
            status="pending",
            created_at=friendship["created_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"发送好友请求失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"发送好友请求失败: {str(e)}")


@router.post("/accept/{friendship_id}", response_model=FriendshipResponse)
async def accept_friend_request(
    friendship_id: str,
    current_user: dict = Depends(require_user)
):
    """接受好友请求

    Args:
        friendship_id: 好友关系ID
        current_user: 当前用户

    Returns:
        FriendshipResponse: 好友关系响应

    Raises:
        HTTPException: 404 - 好友请求不存在
    """
    try:
        # 查找好友请求
        friendship = _friend_requests_db.get(friendship_id)
        if not friendship:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="好友请求不存在"
            )

        # 检查是否是请求的接收者
        if friendship["friend_id"] != current_user["user_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权处理此好友请求"
            )

        # 更新状态
        friendship["status"] = "accepted"
        friendship["updated_at"] = datetime.utcnow()

        # 创建反向关系
        reverse_key = f"{friendship['friend_id']}:{friendship['user_id']}"
        _friendships_db[reverse_key] = friendship.copy()

        logger.info(f"好友请求已接受: friendship_id={friendship_id}")

        return FriendshipResponse(
            friendship_id=friendship_id,
            user_id=friendship["user_id"],
            friend_id=friendship["friend_id"],
            status="accepted",
            created_at=friendship["created_at"],
            updated_at=friendship["updated_at"]
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"接受好友请求失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"接受好友请求失败: {str(e)}")


@router.get("/list", response_model=List[FriendInfo])
async def get_friends_list(current_user: dict = Depends(require_user)):
    """获取好友列表

    Args:
        current_user: 当前用户

    Returns:
        List[FriendInfo]: 好友列表
    """
    try:
        user_id = current_user["user_id"]
        friends = []

        # 遍历好友关系
        for key, friendship in _friendships_db.items():
            if key.startswith(f"{user_id}:") and friendship["status"] == "accepted":
                friend_id = friendship["friend_id"]
                friends.append(FriendInfo(
                    user_id=friend_id,
                    username=f"用户{friend_id[:8]}",
                    display_name=None,
                    avatar_url=None,
                    status="offline"
                ))

        logger.info(f"获取好友列表: user_id={user_id}, count={len(friends)}")
        return friends

    except Exception as e:
        logger.error(f"获取好友列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取好友列表失败: {str(e)}")


@router.get("/requests", response_model=List[FriendshipResponse])
async def get_friend_requests(current_user: dict = Depends(require_user)):
    """获取好友请求列表

    Args:
        current_user: 当前用户

    Returns:
        List[FriendshipResponse]: 好友请求列表
    """
    try:
        user_id = current_user["user_id"]
        requests = []

        # 查找发送给当前用户的请求
        for friendship in _friend_requests_db.values():
            if friendship["friend_id"] == user_id and friendship["status"] == "pending":
                requests.append(FriendshipResponse(
                    friendship_id=friendship["friendship_id"],
                    user_id=friendship["user_id"],
                    friend_id=friendship["friend_id"],
                    status=friendship["status"],
                    created_at=friendship["created_at"]
                ))

        logger.info(f"获取好友请求列表: user_id={user_id}, count={len(requests)}")
        return requests

    except Exception as e:
        logger.error(f"获取好友请求列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取好友请求列表失败: {str(e)}")


@router.delete("/{friend_id}")
async def remove_friend(
    friend_id: str,
    current_user: dict = Depends(require_user)
):
    """删除好友

    Args:
        friend_id: 好友ID
        current_user: 当前用户

    Returns:
        dict: 删除结果
    """
    try:
        user_id = current_user["user_id"]

        # 删除好友关系
        key1 = f"{user_id}:{friend_id}"
        key2 = f"{friend_id}:{user_id}"

        if key1 in _friendships_db:
            del _friendships_db[key1]
        if key2 in _friendships_db:
            del _friendships_db[key2]

        logger.info(f"删除好友成功: user_id={user_id}, friend_id={friend_id}")

        return {
            "success": True,
            "message": "好友关系已删除"
        }

    except Exception as e:
        logger.error(f"删除好友失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除好友失败: {str(e)}")
