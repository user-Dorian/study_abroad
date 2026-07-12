"""好友关系异步仓库层 - 负责 friendships 和 friend_requests 表的 CRUD 操作

好友关系（friendships）与付费绑定（consultant_relations）完全分离：
- friendships: 纯社交好友关系，用于后续留学圈/人脉圈搭建
- consultant_relations: 付费规划师绑定关系

所有方法均为 async def，使用 AsyncDatabasePool 进行异步数据库操作。
"""
from datetime import datetime
from typing import Optional, List

from common.config.async_database import AsyncDatabasePool
from common.utils.logger import logger


def _ensure_utc_iso(dt) -> str:
    """确保 datetime 转为带 UTC 时区标识的 ISO 字符串"""
    if hasattr(dt, 'isoformat'):
        if dt.tzinfo is None:
            return dt.isoformat() + "+00:00"
        return dt.isoformat()
    return str(dt)


class AsyncFriendshipRepository:
    """好友关系异步仓库类（asyncpg），负责 friendships 和 friend_requests 表的异步 CRUD 操作"""

    # ==================== 好友关系操作 ====================

    async def send_friend_request(
        self, sender_id: str, receiver_id: str, message: str = None
    ) -> dict:
        """发送好友请求

        Args:
            sender_id: 发送者用户ID
            receiver_id: 接收者用户ID
            message: 请求附带消息（可选）

        Returns:
            dict: 好友请求信息

        Raises:
            ValueError: 如果已是好友、已有待处理请求或自己加自己
        """
        now = datetime.utcnow()
        try:
            sql = """
                INSERT INTO friend_requests (sender_id, receiver_id, status, message, created_at)
                VALUES ($1, $2, 'pending', $3, $4)
                RETURNING id, sender_id, receiver_id, status, message, created_at
            """
            row = await AsyncDatabasePool.execute_one(
                sql, sender_id, receiver_id, message, now
            )
            result = {
                "id": str(row["id"]),
                "sender_id": str(row["sender_id"]),
                "receiver_id": str(row["receiver_id"]),
                "status": row["status"],
                "message": row["message"],
                "created_at": _ensure_utc_iso(row["created_at"]),
            }
            logger.info(
                f"发送好友请求成功: sender={sender_id}, receiver={receiver_id}"
            )
            return result
        except Exception as e:
            error_msg = str(e)
            if "unique_pending_friend_request" in error_msg:
                raise ValueError("已向该用户发送过好友请求，请等待处理")
            if "check_not_self_friend_request" in error_msg:
                raise ValueError("不能给自己发送好友请求")
            logger.error(f"发送好友请求失败: {e}")
            raise

    async def accept_friend_request(self, request_id: str, receiver_id: str) -> dict:
        """接受好友请求

        在事务中同时更新请求状态和创建好友关系。

        Args:
            request_id: 请求ID
            receiver_id: 接收者用户ID（验证归属）

        Returns:
            dict: 包含请求信息和好友关系信息

        Raises:
            ValueError: 请求不存在、已处理或归属错误
        """
        now = datetime.utcnow()
        pool = await AsyncDatabasePool.get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                try:
                    # 查询并锁定请求
                    request_row = await conn.fetchrow(
                        "SELECT id, sender_id, receiver_id, status FROM friend_requests WHERE id = $1 FOR UPDATE",
                        request_id,
                    )
                    if not request_row:
                        raise ValueError("好友请求不存在")
                    if str(request_row["receiver_id"]) != receiver_id:
                        raise ValueError("好友请求归属错误")
                    if request_row["status"] != "pending":
                        raise ValueError("好友请求已处理")

                    sender_id = str(request_row["sender_id"])

                    # 更新请求状态
                    await conn.execute(
                        "UPDATE friend_requests SET status = 'accepted', processed_at = $1 WHERE id = $2",
                        now, request_id,
                    )

                    # 创建双向好友关系
                    await conn.execute(
                        """INSERT INTO friendships (user_id, friend_id, status, created_at, updated_at)
                           VALUES ($1, $2, 'accepted', $3, $3)""",
                        sender_id, receiver_id, now,
                    )
                    await conn.execute(
                        """INSERT INTO friendships (user_id, friend_id, status, created_at, updated_at)
                           VALUES ($1, $2, 'accepted', $3, $3)""",
                        receiver_id, sender_id, now,
                    )

                    logger.info(f"接受好友请求成功: request_id={request_id}")
                    return {
                        "request_id": request_id,
                        "sender_id": sender_id,
                        "receiver_id": receiver_id,
                        "status": "accepted",
                    }
                except Exception as e:
                    logger.error(f"接受好友请求事务失败: {e}")
                    raise

    async def reject_friend_request(self, request_id: str, receiver_id: str) -> bool:
        """拒绝好友请求

        Args:
            request_id: 请求ID
            receiver_id: 接收者用户ID（验证归属）

        Returns:
            bool: 拒绝成功返回 True
        """
        try:
            sql = """
                UPDATE friend_requests
                SET status = 'rejected', processed_at = $1
                WHERE id = $2 AND receiver_id = $3 AND status = 'pending'
            """
            status = await AsyncDatabasePool.execute_command(
                sql, datetime.utcnow(), request_id, receiver_id
            )
            affected = int(status.split()[-1]) if status else 0
            if affected == 0:
                logger.warning(f"拒绝好友请求失败，请求不存在或已处理: request_id={request_id}")
                return False
            logger.info(f"拒绝好友请求成功: request_id={request_id}")
            return True
        except Exception as e:
            logger.error(f"拒绝好友请求失败: {e}")
            raise

    async def get_pending_friend_requests(self, user_id: str) -> List[dict]:
        """获取用户待处理的好友请求（别人发给我的）

        Args:
            user_id: 用户ID

        Returns:
            list[dict]: 待处理请求列表
        """
        try:
            sql = """
                SELECT fr.id, fr.sender_id, fr.receiver_id, fr.status, fr.message, fr.created_at,
                       u.username AS sender_username, u.display_name AS sender_display_name,
                       COALESCE(up.avatar_url, '') AS sender_avatar
                FROM friend_requests fr
                LEFT JOIN users u ON u.id = fr.sender_id
                LEFT JOIN user_profiles up ON up.user_id = fr.sender_id
                WHERE fr.receiver_id = $1 AND fr.status = 'pending'
                ORDER BY fr.created_at DESC
            """
            rows = await AsyncDatabasePool.execute_query(sql, user_id)
            result = []
            for row in rows:
                result.append({
                    "id": str(row["id"]),
                    "sender_id": str(row["sender_id"]),
                    "receiver_id": str(row["receiver_id"]),
                    "status": row["status"],
                    "message": row["message"],
                    "created_at": _ensure_utc_iso(row["created_at"]),
                    "sender_username": row.get("sender_username"),
                    "sender_display_name": row.get("sender_display_name"),
                    "sender_avatar": row.get("sender_avatar") or "",
                })
            return result
        except Exception as e:
            logger.error(f"获取待处理好友请求失败: {e}")
            return []

    async def get_friends(self, user_id: str) -> List[dict]:
        """获取用户的好友列表

        Args:
            user_id: 用户ID

        Returns:
            list[dict]: 好友列表
        """
        try:
            sql = """
                SELECT f.id, f.friend_id, f.created_at AS friend_since,
                       u.username, u.display_name, u.phone, u.avatar_url,
                       up.avatar_url AS profile_avatar, up.bio, up.city,
                       up.occupation, up.industry
                FROM friendships f
                LEFT JOIN users u ON u.id = f.friend_id
                LEFT JOIN user_profiles up ON up.user_id = f.friend_id
                WHERE f.user_id = $1 AND f.status = 'accepted'
                ORDER BY f.created_at DESC
            """
            rows = await AsyncDatabasePool.execute_query(sql, user_id)
            result = []
            for row in rows:
                result.append({
                    "friendship_id": str(row["id"]),
                    "friend_id": str(row["friend_id"]),
                    "username": row.get("username"),
                    "display_name": row.get("display_name"),
                    "phone": row.get("phone"),
                    "avatar_url": row.get("profile_avatar") or row.get("avatar_url") or "",
                    "bio": row.get("bio"),
                    "city": row.get("city"),
                    "occupation": row.get("occupation"),
                    "industry": row.get("industry"),
                    "friend_since": _ensure_utc_iso(row["friend_since"]),
                })
            return result
        except Exception as e:
            logger.error(f"获取好友列表失败: {e}")
            return []

    async def remove_friend(self, user_id: str, friend_id: str) -> bool:
        """删除好友关系（双向删除）

        Args:
            user_id: 当前用户ID
            friend_id: 好友用户ID

        Returns:
            bool: 删除成功返回 True
        """
        try:
            # 双向删除
            await AsyncDatabasePool.execute_command(
                "DELETE FROM friendships WHERE user_id = $1 AND friend_id = $2 AND status = 'accepted'",
                user_id, friend_id,
            )
            await AsyncDatabasePool.execute_command(
                "DELETE FROM friendships WHERE user_id = $1 AND friend_id = $2 AND status = 'accepted'",
                friend_id, user_id,
            )
            logger.info(f"删除好友成功: user={user_id}, friend={friend_id}")
            return True
        except Exception as e:
            logger.error(f"删除好友失败: {e}")
            return False

    async def check_friendship(self, user_id: str, other_user_id: str) -> bool:
        """检查两个用户是否为好友

        Args:
            user_id: 用户ID
            other_user_id: 对方用户ID

        Returns:
            bool: 是好友返回 True
        """
        try:
            row = await AsyncDatabasePool.execute_one(
                "SELECT 1 FROM friendships WHERE user_id = $1 AND friend_id = $2 AND status = 'accepted' LIMIT 1",
                user_id, other_user_id,
            )
            return row is not None
        except Exception as e:
            logger.error(f"检查好友关系失败: {e}")
            return False

    async def ensure_bidirectional_friendship(self, user_id: str, other_user_id: str) -> dict:
        """确保双向好友关系存在,不存在则创建

        功能:
        - 检查是否已存在好友关系
        - 不存在则创建双向好友记录(两条 friendships 表记录)
        - 使用事务确保原子性
        - 返回 {created: True/False, friendship_id: ...}

        Args:
            user_id: 用户ID
            other_user_id: 对方用户ID

        Returns:
            dict: {
                created: bool,  # True表示新创建,False表示已存在
                friendship_id: str,  # 好友关系ID
                message: str  # 描述信息
            }

        Raises:
            ValueError: 参数错误(user_id和other_user_id相同)
        """
        # 参数检查
        if user_id == other_user_id:
            raise ValueError("不能与自己建立好友关系")

        now = datetime.utcnow()
        pool = await AsyncDatabasePool.get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                try:
                    # 检查是否已存在好友关系(任意方向)
                    existing = await conn.fetchrow(
                        """SELECT id, user_id, friend_id, status FROM friendships
                           WHERE (user_id = $1 AND friend_id = $2 AND status = 'accepted')
                              OR (user_id = $2 AND friend_id = $1 AND status = 'accepted')
                           LIMIT 1""",
                        user_id, other_user_id,
                    )

                    if existing:
                        friendship_id = str(existing["id"])
                        logger.info(
                            f"好友关系已存在: user={user_id}, friend={other_user_id}, friendship_id={friendship_id}"
                        )
                        return {
                            "created": False,
                            "friendship_id": friendship_id,
                            "message": "好友关系已存在",
                        }

                    # 不存在则创建双向好友关系
                    # 插入第一条记录: user_id -> friend_id
                    row1 = await conn.fetchrow(
                        """INSERT INTO friendships (user_id, friend_id, status, created_at, updated_at)
                           VALUES ($1, $2, 'accepted', $3, $3)
                           RETURNING id""",
                        user_id, other_user_id, now,
                    )

                    # 插入第二条记录: friend_id -> user_id
                    row2 = await conn.fetchrow(
                        """INSERT INTO friendships (user_id, friend_id, status, created_at, updated_at)
                           VALUES ($1, $2, 'accepted', $3, $3)
                           RETURNING id""",
                        other_user_id, user_id, now,
                    )

                    friendship_id = str(row1["id"])
                    logger.info(
                        f"成功创建双向好友关系: user={user_id}, friend={other_user_id}, "
                        f"friendship_ids=[{friendship_id}, {str(row2['id'])}]"
                    )
                    return {
                        "created": True,
                        "friendship_id": friendship_id,
                        "message": "成功创建双向好友关系",
                    }

                except Exception as e:
                    error_msg = str(e)
                    if "unique_friendship_pair" in error_msg or "check_not_self_friend" in error_msg:
                        logger.warning(
                            f"好友关系创建失败(约束冲突): user={user_id}, friend={other_user_id}, error={error_msg}"
                        )
                        # 约束冲突表示关系已存在或参数错误,返回失败信息
                        return {
                            "created": False,
                            "friendship_id": None,
                            "message": f"好友关系创建失败: {error_msg}",
                        }
                    logger.error(f"创建好友关系事务失败: {e}")
                    raise

    # ==================== 搜索用户/规划师 ====================

    async def search_users(
        self, keyword: str, current_user_id: str, role_filter: str = None, limit: int = 20
    ) -> List[dict]:
        """搜索所有用户（数据库级别检索）

        Args:
            keyword: 搜索关键词（用户名/显示名/电话/邮箱）
            current_user_id: 当前用户ID（排除自己）
            role_filter: 角色过滤（'client'=只搜索用户, 'consultant'=只搜索规划师, None=搜索全部）
            limit: 返回数量上限

        Returns:
            list[dict]: 用户信息列表
        """
        try:
            pattern = f"%{keyword}%"

            # 构建查询条件
            conditions = ["u.id != $1"]
            params = [current_user_id, pattern]

            if role_filter:
                conditions.append("u.role = $3")
                params.append(role_filter)

            conditions.append(
                "(u.username ILIKE $2 OR u.display_name ILIKE $2 "
                "OR u.phone ILIKE $2 OR u.email ILIKE $2)"
            )

            where_clause = " AND ".join(conditions)

            sql = f"""
                SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.avatar_url,
                       up.avatar_url AS profile_avatar, up.bio, up.city, up.occupation,
                       up.industry, up.education, up.target_country, up.target_level,
                       up.consultant_bio, up.expertise_areas, up.service_price,
                       up.experience_years_consultant, up.success_cases, up.rating, up.verified
                FROM users u
                LEFT JOIN user_profiles up ON up.user_id = u.id
                WHERE {where_clause}
                ORDER BY u.display_name ASC, u.username ASC
                LIMIT ${len(params) + 1}
            """
            params.append(limit)

            rows = await AsyncDatabasePool.execute_query(sql, *params)
            result = []
            for row in rows:
                result.append({
                    "id": str(row["id"]),
                    "username": row["username"],
                    "display_name": row.get("display_name"),
                    "email": row.get("email"),
                    "phone": row.get("phone"),
                    "role": row.get("role", "client"),
                    "avatar_url": row.get("profile_avatar") or row.get("avatar_url") or "",
                    "bio": row.get("bio"),
                    "city": row.get("city"),
                    "occupation": row.get("occupation"),
                    "industry": row.get("industry"),
                    "education": row.get("education"),
                    "target_country": row.get("target_country"),
                    "target_level": row.get("target_level"),
                    # 规划师专属字段
                    "consultant_bio": row.get("consultant_bio"),
                    "expertise_areas": row.get("expertise_areas"),
                    "service_price": row.get("service_price"),
                    "experience_years_consultant": row.get("experience_years_consultant"),
                    "success_cases": row.get("success_cases"),
                    "rating": float(row.get("rating") or 0),
                    "verified": row.get("verified") or False,
                })
            return result
        except Exception as e:
            logger.error(f"搜索用户失败: keyword={keyword}, error={e}")
            return []

    async def search_all_planners(
        self, keyword: str, current_user_id: str, limit: int = 20
    ) -> List[dict]:
        """搜索所有规划师（用户端搜索规划师专用）

        Args:
            keyword: 搜索关键词
            current_user_id: 当前用户ID
            limit: 返回数量上限

        Returns:
            list[dict]: 规划师信息列表
        """
        return await self.search_users(
            keyword=keyword,
            current_user_id=current_user_id,
            role_filter="consultant",
            limit=limit,
        )

    async def search_all_planners_with_filters(
        self,
        keyword: str,
        current_user_id: str,
        expertise_area: Optional[str] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        rating_min: Optional[float] = None,
        limit: int = 20,
    ) -> List[dict]:
        """搜索所有规划师（支持多维度筛选）

        Args:
            keyword: 搜索关键词（用户名/显示名/电话/邮箱）
            current_user_id: 当前用户ID（排除自己）
            expertise_area: 专长领域筛选
            price_min: 最低服务价格
            price_max: 最高服务价格
            rating_min: 最低评分
            limit: 返回数量上限

        Returns:
            list[dict]: 规划师信息列表
        """
        try:
            params = [current_user_id]
            param_index = 2

            # 构建基础条件
            conditions = ["u.id != $1", "u.role = 'consultant'"]

            # 关键词搜索条件（如果关键词不为空）
            if keyword and keyword.strip():
                pattern = f"%{keyword.strip()}%"
                conditions.append(
                    f"(u.username ILIKE ${param_index} OR u.display_name ILIKE ${param_index} "
                    f"OR u.phone ILIKE ${param_index} OR u.email ILIKE ${param_index})"
                )
                params.append(pattern)
                param_index += 1

            # 专长领域筛选
            if expertise_area and expertise_area.strip():
                # expertise_areas是数组字段，使用ANY或@>操作符
                conditions.append(f"up.expertise_areas @> ${param_index}")
                params.append([expertise_area.strip()])
                param_index += 1

            # 价格区间筛选
            # 注意：service_price是字符串字段，需要转换为数值比较
            # 假设价格存储为数值字符串或数值字段，这里用正则提取数值比较
            if price_min is not None or price_max is not None:
                # 使用 CAST 或正则提取数值进行比较
                # 这里假设service_price存储的是纯数值字符串（如"500"）
                if price_min is not None:
                    conditions.append(
                        f"CAST(NULLIF(regexp_replace(up.service_price, '[^0-9.]', '', 'g'), '') AS FLOAT) >= ${param_index}"
                    )
                    params.append(price_min)
                    param_index += 1
                if price_max is not None:
                    conditions.append(
                        f"CAST(NULLIF(regexp_replace(up.service_price, '[^0-9.]', '', 'g'), '') AS FLOAT) <= ${param_index}"
                    )
                    params.append(price_max)
                    param_index += 1

            # 评分筛选
            if rating_min is not None:
                conditions.append(f"up.rating >= ${param_index}")
                params.append(rating_min)
                param_index += 1

            where_clause = " AND ".join(conditions)

            sql = f"""
                SELECT u.id, u.username, u.display_name, u.email, u.phone, u.role, u.avatar_url,
                       up.avatar_url AS profile_avatar, up.bio, up.city, up.occupation,
                       up.industry, up.education, up.target_country, up.target_level,
                       up.consultant_bio, up.expertise_areas, up.service_price,
                       up.experience_years_consultant, up.success_cases, up.rating, up.verified
                FROM users u
                LEFT JOIN user_profiles up ON up.user_id = u.id
                WHERE {where_clause}
                ORDER BY up.rating DESC, u.display_name ASC, u.username ASC
                LIMIT ${param_index}
            """
            params.append(limit)

            rows = await AsyncDatabasePool.execute_query(sql, *params)
            result = []
            for row in rows:
                result.append({
                    "id": str(row["id"]),
                    "username": row["username"],
                    "display_name": row.get("display_name"),
                    "email": row.get("email"),
                    "phone": row.get("phone"),
                    "role": row.get("role", "client"),
                    "avatar_url": row.get("profile_avatar") or row.get("avatar_url") or "",
                    "bio": row.get("bio"),
                    "city": row.get("city"),
                    "occupation": row.get("occupation"),
                    "industry": row.get("industry"),
                    "education": row.get("education"),
                    "target_country": row.get("target_country"),
                    "target_level": row.get("target_level"),
                    # 规划师专属字段
                    "consultant_bio": row.get("consultant_bio"),
                    "expertise_areas": row.get("expertise_areas"),
                    "service_price": row.get("service_price"),
                    "experience_years_consultant": row.get("experience_years_consultant"),
                    "success_cases": row.get("success_cases"),
                    "rating": float(row.get("rating") or 0),
                    "verified": row.get("verified") or False,
                })
            return result
        except Exception as e:
            logger.error(
                f"搜索规划师失败(带筛选): keyword={keyword}, expertise={expertise_area}, "
                f"price=[{price_min},{price_max}], rating={rating_min}, error={e}"
            )
            return []

    async def search_all_clients(
        self, keyword: str, current_user_id: str, limit: int = 20
    ) -> List[dict]:
        """搜索所有普通用户（规划师端搜索用户专用）

        Args:
            keyword: 搜索关键词
            current_user_id: 当前用户ID
            limit: 返回数量上限

        Returns:
            list[dict]: 用户信息列表
        """
        return await self.search_users(
            keyword=keyword,
            current_user_id=current_user_id,
            role_filter="client",
            limit=limit,
        )

    async def get_contacts_with_binding_status(
        self, consultant_id: str, filter_type: str = "all"
    ) -> List[dict]:
        """获取规划师的好友联系人列表，并区分绑定状态

        Args:
            consultant_id: 规划师用户ID
            filter_type: 篮选类型
                - 'all': 返回全部好友联系人
                - 'bound': 返回已绑定用户（在consultant_relations表中）
                - 'unbound': 返回未绑定用户（好友但未绑定）

        Returns:
            list[dict]: 联系人信息列表，每个联系人包含：
                - user_id: 用户ID
                - username: 用户名
                - display_name: 显示名
                - avatar_url: 头像URL
                - is_bound: 是否已绑定
                - bound_at: 绑定时间（已绑定的用户）

        Raises:
            ValueError: filter_type 参数无效时，降级返回全部联系人
        """
        # 参数验证：无效参数降级为返回全部
        valid_types = ["all", "bound", "unbound"]
        if filter_type not in valid_types:
            logger.warning(
                f"[筛选参数无效] filter_type={filter_type}, 降级返回全部联系人"
            )
            filter_type = "all"

        try:
            # 构建SQL查询：查询好友列表并关联绑定关系
            sql = """
                SELECT 
                    f.friend_id AS user_id,
                    u.username,
                    u.display_name,
                    COALESCE(up.avatar_url, u.avatar_url, '') AS avatar_url,
                    CASE 
                        WHEN cr.id IS NOT NULL AND cr.status = 'active' THEN TRUE 
                        ELSE FALSE 
                    END AS is_bound,
                    cr.created_at AS bound_at
                FROM friendships f
                LEFT JOIN users u ON u.id = f.friend_id
                LEFT JOIN user_profiles up ON up.user_id = f.friend_id
                LEFT JOIN consultant_relations cr 
                    ON cr.user_id = f.friend_id 
                    AND cr.consultant_id = $1 
                    AND cr.status = 'active'
                WHERE f.user_id = $1 
                    AND f.status = 'accepted'
            """

            # 根据筛选类型添加过滤条件
            if filter_type == "bound":
                sql += " AND cr.id IS NOT NULL AND cr.status = 'active'"
            elif filter_type == "unbound":
                sql += " AND (cr.id IS NULL OR cr.status != 'active')"

            # 添加排序
            sql += " ORDER BY f.created_at DESC"

            rows = await AsyncDatabasePool.execute_query(sql, consultant_id)

            result = []
            for row in rows:
                contact = {
                    "user_id": str(row["user_id"]),
                    "username": row.get("username"),
                    "display_name": row.get("display_name"),
                    "avatar_url": row.get("avatar_url") or "",
                    "is_bound": row["is_bound"],
                }
                # 只有已绑定的用户才包含 bound_at
                if row["is_bound"]:
                    contact["bound_at"] = (
                        _ensure_utc_iso(row["bound_at"]) 
                        if row["bound_at"] else None
                    )
                result.append(contact)

            logger.info(
                f"[通讯录筛选] consultant_id={consultant_id}, "
                f"filter_type={filter_type}, 结果数={len(result)}"
            )
            return result

        except Exception as e:
            logger.error(
                f"[通讯录筛选失败] consultant_id={consultant_id}, "
                f"filter_type={filter_type}, error={e}"
            )
            return []


# 单例实例
_friendship_repo = None


def get_friendship_repo() -> AsyncFriendshipRepository:
    """获取好友关系仓库单例"""
    global _friendship_repo
    if _friendship_repo is None:
        _friendship_repo = AsyncFriendshipRepository()
    return _friendship_repo