"""好友关系 API 路由 - 双端通用

包括：
1. 搜索用户/规划师（数据库级别检索）
2. 发送好友请求
3. 处理好友请求（接受/拒绝）
4. 获取好友列表
5. 删除好友
6. 获取待处理好友请求
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, List

from common.utils.auth import require_user
from common.utils.logger import logger
from common.utils.online_status import batch_check_online, publish_notification
from common.friendship.repository import get_friendship_repo

router = APIRouter(prefix="/api/friendship", tags=["friendship"])


# ====== Pydantic 请求/响应模型 ======

class SendFriendRequest(BaseModel):
    """发送好友请求"""
    receiver_id: str = Field(..., description="接收者用户ID")
    message: Optional[str] = Field(None, max_length=200, description="请求消息（可选）")


class ProcessFriendRequest(BaseModel):
    """处理好友请求"""
    request_id: str = Field(..., description="请求ID")
    action: str = Field(..., pattern="^(accept|reject)$", description="操作：accept 或 reject")


class FriendRequestInfo(BaseModel):
    """好友请求信息"""
    id: str
    sender_id: str
    receiver_id: str
    status: str
    message: Optional[str] = None
    created_at: str
    sender_username: Optional[str] = None
    sender_display_name: Optional[str] = None
    sender_avatar: str = ""


class FriendInfo(BaseModel):
    """好友信息"""
    friendship_id: str
    friend_id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: str = ""
    bio: Optional[str] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    friend_since: str


class UserSearchResult(BaseModel):
    """用户搜索结果"""
    id: str
    username: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str = "client"
    avatar_url: str = ""
    bio: Optional[str] = None
    city: Optional[str] = None
    occupation: Optional[str] = None
    industry: Optional[str] = None
    education: Optional[str] = None
    target_country: Optional[str] = None
    target_level: Optional[str] = None
    # 规划师专属
    consultant_bio: Optional[str] = None
    expertise_areas: Optional[list] = None
    service_price: Optional[str] = None
    experience_years_consultant: Optional[str] = None
    success_cases: Optional[int] = None
    rating: float = 0.0
    verified: bool = False


# ====== 路由实现 ======

# 1. 搜索所有规划师（用户端用）
@router.get("/search-planners", response_model=List[UserSearchResult])
async def search_planners(
    keyword: str = Query("", max_length=100, description="搜索关键词（名字/账号）"),
    expertise_area: Optional[str] = Query(None, description="专长领域筛选"),
    price_min: Optional[float] = Query(None, ge=0, description="最低服务价格"),
    price_max: Optional[float] = Query(None, ge=0, description="最高服务价格"),
    rating_min: Optional[float] = Query(None, ge=0, le=5, description="最低评分"),
    limit: int = Query(20, ge=1, le=50, description="返回数量上限"),
    current_user: dict = Depends(require_user),
):
    """搜索所有在册规划师（用户端使用）

    支持多维度筛选：
    - 关键词搜索：按用户名/显示名/电话/邮箱模糊匹配
    - 专长领域筛选：按规划师专长领域过滤
    - 价格区间筛选：按服务价格区间过滤
    - 评分筛选：按评分过滤

    支持规划师详细信息展示，便于用户选择规划师进行沟通。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        planners = await repo.search_all_planners_with_filters(
            keyword=keyword,
            current_user_id=user_id,
            expertise_area=expertise_area,
            price_min=price_min,
            price_max=price_max,
            rating_min=rating_min,
            limit=limit,
        )
        logger.info(
            f"搜索规划师: keyword={keyword}, expertise={expertise_area}, "
            f"price=[{price_min},{price_max}], rating={rating_min}, 结果数={len(planners)}"
        )
        return planners
    except Exception as e:
        logger.error(f"搜索规划师失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


# 2. 搜索所有用户（规划师端用）
@router.get("/search-users", response_model=List[UserSearchResult])
async def search_users(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=50, description="返回数量上限"),
    current_user: dict = Depends(require_user),
):
    """搜索所有用户（规划师端使用）

    数据库级别检索，按用户名/显示名/电话/邮箱模糊匹配。
    规划师可以搜索所有用户并直接发起会话，无需绑定关系。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        users = await repo.search_all_clients(
            keyword=keyword,
            current_user_id=user_id,
            limit=limit,
        )
        logger.info(f"搜索用户: keyword={keyword}, 结果数={len(users)}")
        return users
    except Exception as e:
        logger.error(f"搜索用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


# 3. 搜索所有人（管理端用）
@router.get("/search-all", response_model=List[UserSearchResult])
async def search_all_users(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    role: Optional[str] = Query(None, description="角色过滤（client/consultant）"),
    limit: int = Query(20, ge=1, le=50, description="返回数量上限"),
    current_user: dict = Depends(require_user),
):
    """搜索所有用户（无角色限制）

    可选的 role 参数过滤角色。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        users = await repo.search_users(
            keyword=keyword,
            current_user_id=user_id,
            role_filter=role,
            limit=limit,
        )
        logger.info(f"搜索全部用户: keyword={keyword}, role={role}, 结果数={len(users)}")
        return users
    except Exception as e:
        logger.error(f"搜索全部用户失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


# 4. 发送好友请求
@router.post("/requests")
async def send_friend_request(
    request: SendFriendRequest,
    current_user: dict = Depends(require_user),
):
    """发送好友请求

    好友关系独立于付费绑定关系。
    发送好友请求是社交行为，用于后续留学圈/人脉圈搭建。
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()

        # 不能给自己发送请求
        if request.receiver_id == user_id:
            raise HTTPException(status_code=400, detail="不能给自己发送好友请求")

        result = await repo.send_friend_request(
            sender_id=user_id,
            receiver_id=request.receiver_id,
            message=request.message,
        )

        # 发送通知给接收者
        try:
            notification = {
                "type": "friend_request",
                "from_user_id": user_id,
                "from_username": current_user.get("username", "用户"),
                "message": f"用户 {current_user.get('username', '')} 向您发送了好友请求",
                "request_id": result["id"],
            }
            await publish_notification(request.receiver_id, notification)
        except Exception:
            pass

        logger.info(f"发送好友请求成功: from={user_id}, to={request.receiver_id}")
        return {"success": True, "request": result}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"发送好友请求失败: {e}")
        raise HTTPException(status_code=500, detail=f"发送好友请求失败: {str(e)}")


# 5. 处理好友请求（接受/拒绝）
@router.post("/requests/process")
async def process_friend_request(
    request: ProcessFriendRequest,
    current_user: dict = Depends(require_user),
):
    """处理好友请求

    action: accept（接受）或 reject（拒绝）
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()

        if request.action == "accept":
            result = await repo.accept_friend_request(
                request_id=request.request_id,
                receiver_id=user_id,
            )
            logger.info(
                f"接受好友请求成功: request_id={request.request_id}, "
                f"user={user_id}, friend={result['sender_id']}"
            )

            # 通知发送者
            try:
                notification = {
                    "type": "friend_request_accepted",
                    "from_user_id": user_id,
                    "from_username": current_user.get("username", "用户"),
                    "message": f"用户 {current_user.get('username', '')} 已接受您的好友请求",
                }
                await publish_notification(result["sender_id"], notification)
            except Exception:
                pass

            return {"success": True, "action": "accepted", "friend_id": result["sender_id"]}

        else:  # reject
            success = await repo.reject_friend_request(
                request_id=request.request_id,
                receiver_id=user_id,
            )
            if not success:
                raise HTTPException(status_code=400, detail="拒绝好友请求失败，可能已被处理")
            logger.info(f"拒绝好友请求成功: request_id={request.request_id}")
            return {"success": True, "action": "rejected"}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理好友请求失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理好友请求失败: {str(e)}")


# 6. 获取待处理好友请求
@router.get("/requests/pending")
async def get_pending_requests(
    current_user: dict = Depends(require_user),
):
    """获取当前用户的待处理好友请求（别人发给我的）"""
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        requests = await repo.get_pending_friend_requests(user_id)
        return {"requests": requests}
    except Exception as e:
        logger.error(f"获取待处理好友请求失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取待处理请求失败: {str(e)}")


# 7. 获取好友列表
@router.get("/friends")
async def get_friends(
    current_user: dict = Depends(require_user),
):
    """获取当前用户的好友列表（含在线状态）"""
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        friends = await repo.get_friends(user_id)

        # 批量查询在线状态
        friend_ids = [f["friend_id"] for f in friends]
        online_status = await batch_check_online(friend_ids) if friend_ids else {}
        for friend in friends:
            friend["online"] = online_status.get(friend["friend_id"], False)

        return {"friends": friends}
    except Exception as e:
        logger.error(f"获取好友列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取好友列表失败: {str(e)}")


# 8. 删除好友
@router.delete("/friends/{friend_id}")
async def remove_friend(
    friend_id: str,
    current_user: dict = Depends(require_user),
):
    """删除好友（双向删除）"""
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        success = await repo.remove_friend(user_id, friend_id)
        if not success:
            raise HTTPException(status_code=404, detail="好友关系不存在")
        logger.info(f"删除好友成功: user={user_id}, friend={friend_id}")
        return {"success": True, "message": "好友已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除好友失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除好友失败: {str(e)}")


# 9. 检查好友关系 - 已废弃,请使用 P0 扩展的 /check/{id} 综合关系接口


# ============================
# P0 扩展接口
# ============================

@router.get("/requests/sent")
async def get_sent_requests(
    current_user: dict = Depends(require_user),
):
    """
    获取我发出的好友申请(用于"申请模块 - 已发送"Tab)
    """
    try:
        user_id = current_user["user_id"]
        from common.config.async_database import AsyncDatabasePool
        rows = await AsyncDatabasePool.execute_query(
            """SELECT fr.id, fr.receiver_id, fr.status, fr.message, fr.created_at, fr.source,
                      u.username AS receiver_username,
                      u.display_name AS receiver_display_name,
                      u.role AS receiver_role
               FROM friend_requests fr
               JOIN users u ON u.id = fr.receiver_id
               WHERE fr.sender_id = $1
               ORDER BY fr.created_at DESC""",
            user_id,
        )
        requests = []
        for r in rows:
            requests.append({
                "id": str(r["id"]),
                "receiver_id": str(r["receiver_id"]),
                "receiver_username": r["receiver_username"],
                "receiver_display_name": r["receiver_display_name"],
                "receiver_role": r["receiver_role"],
                "status": r["status"],
                "message": r["message"],
                "source": r.get("source", "search"),
                "created_at": str(r["created_at"]),
            })
        return {"requests": requests}
    except Exception as e:
        logger.error(f"获取已发送好友申请失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取已发送申请失败: {str(e)}")


@router.get("/requests/inbox")
async def get_inbox_requests(
    current_user: dict = Depends(require_user),
):
    """
    通讯录-申请模块统一接口(合并 pending 收到 + sent 已发送)

    一次返回两类:
    - received: 收到的待处理(供通讯录"申请"Tab主显示)
    - sent: 我发出去的(供"已发送"切换)
    """
    try:
        user_id = current_user["user_id"]
        from common.config.async_database import AsyncDatabasePool

        # 收到的(待处理)
        received_rows = await AsyncDatabasePool.execute_query(
            """SELECT fr.id, fr.sender_id, fr.receiver_id, fr.status, fr.message, fr.created_at, fr.source,
                      u.username AS sender_username,
                      u.display_name AS sender_display_name,
                      u.role AS sender_role
               FROM friend_requests fr
               JOIN users u ON u.id = fr.sender_id
               WHERE fr.receiver_id = $1 AND fr.status = 'pending'
               ORDER BY fr.created_at DESC""",
            user_id,
        )
        received = []
        for r in received_rows:
            received.append({
                "id": str(r["id"]),
                "direction": "received",
                "other_user_id": str(r["sender_id"]),
                "other_username": r["sender_username"],
                "other_display_name": r["sender_display_name"],
                "other_role": r["sender_role"],
                "status": r["status"],
                "message": r["message"],
                "source": r.get("source", "search"),
                "created_at": str(r["created_at"]),
            })

        # 发出的(所有状态)
        sent_rows = await AsyncDatabasePool.execute_query(
            """SELECT fr.id, fr.receiver_id, fr.status, fr.message, fr.created_at, fr.source,
                      u.username AS receiver_username,
                      u.display_name AS receiver_display_name,
                      u.role AS receiver_role
               FROM friend_requests fr
               JOIN users u ON u.id = fr.receiver_id
               WHERE fr.sender_id = $1
               ORDER BY fr.created_at DESC""",
            user_id,
        )
        sent = []
        for r in sent_rows:
            sent.append({
                "id": str(r["id"]),
                "direction": "sent",
                "other_user_id": str(r["receiver_id"]),
                "other_username": r["receiver_username"],
                "other_display_name": r["receiver_display_name"],
                "other_role": r["receiver_role"],
                "status": r["status"],
                "message": r["message"],
                "source": r.get("source", "search"),
                "created_at": str(r["created_at"]),
            })

        return {
            "received": received,
            "received_count": len(received),
            "sent": sent,
            "sent_count": len(sent),
        }

    except Exception as e:
        logger.error(f"获取好友申请收件箱失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取申请收件箱失败: {str(e)}")


@router.get("/check/{other_user_id}")
async def check_relationship_status(
    other_user_id: str,
    current_user: dict = Depends(require_user),
):
    """
    检查与指定用户的综合关系(供前端按钮灰显/文案切换)

    返回:
    - is_friend: 是否已是好友
    - pending_request_id: 我发出的待处理请求ID(若有)
    - pending_request_from_them: 对方发来的待处理请求ID(若有)
    - relationship: none / pending_sent / pending_received / friend
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()
        is_friend = await repo.check_friendship(user_id, other_user_id)

        # 检查我发出去的待处理
        from common.config.async_database import AsyncDatabasePool
        my_sent = await AsyncDatabasePool.execute_one(
            """SELECT id FROM friend_requests
               WHERE sender_id = $1 AND receiver_id = $2
                 AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            user_id, other_user_id,
        )
        # 检查对方发给我的待处理
        from_them = await AsyncDatabasePool.execute_one(
            """SELECT id FROM friend_requests
               WHERE sender_id = $1 AND receiver_id = $2
                 AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            other_user_id, user_id,
        )

        if is_friend:
            relationship = "friend"
        elif my_sent:
            relationship = "pending_sent"
        elif from_them:
            relationship = "pending_received"
        else:
            relationship = "none"

        return {
            "is_friend": is_friend,
            "pending_request_id": str(my_sent["id"]) if my_sent else None,
            "pending_request_from_them": str(from_them["id"]) if from_them else None,
            "relationship": relationship,
        }
    except Exception as e:
        logger.error(f"检查关系状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"检查关系失败: {str(e)}")


# 10. 搜索好友
@router.get("/search-friends", response_model=List[FriendInfo])
async def search_friends(
    keyword: str = Query(..., min_length=1, description="搜索关键词（好友用户名/显示名）"),
    current_user: dict = Depends(require_user),
):
    """搜索当前用户的好友列表（基于 friendships 表）

    功能：
    - 从当前用户的好友列表中搜索匹配关键词的好友
    - 搜索范围：好友的用户名、显示名、电话等
    - 只返回已建立好友关系的用户（status='accepted'）

    Args:
        keyword: 搜索关键词

    Returns:
        list[FriendInfo]: 匹配的好友列表
    """
    try:
        user_id = current_user["user_id"]
        repo = get_friendship_repo()

        # 获取好友列表
        friends = await repo.get_friends(user_id)

        # 在好友列表中搜索关键词
        keyword_lower = keyword.lower()
        matched_friends = []

        for friend in friends:
            # 搜索字段：username, display_name, phone
            username = friend.get("username", "").lower()
            display_name = friend.get("display_name", "").lower()
            phone = friend.get("phone", "").lower()

            # 检查是否匹配
            if (keyword_lower in username or
                keyword_lower in display_name or
                keyword_lower in phone):
                matched_friends.append(friend)

        logger.info(
            f"搜索好友: user_id={user_id}, keyword={keyword}, "
            f"总数={len(friends)}, 匹配数={len(matched_friends)}"
        )
        return matched_friends

    except Exception as e:
        logger.error(f"搜索好友失败: {e}")
        raise HTTPException(status_code=500, detail=f"搜索好友失败: {str(e)}")