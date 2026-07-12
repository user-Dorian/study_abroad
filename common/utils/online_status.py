"""用户在线状态管理 - 基于 Redis 的实时在线状态追踪

设计原理：
- 用户登录/活跃时，在 Redis 中设置 `online:{user_id}` 键，TTL=120秒
- 用户每次发起带 Token 的 API 请求时，刷新 TTL
- 查询在线状态：检查键是否存在
- 无需显式"离线"操作，TTL 到期自动标记离线
"""
import asyncio
from datetime import datetime
from typing import Optional

from common.config.async_redis import AsyncRedisPool
from common.utils.logger import logger

# Redis 键前缀
ONLINE_KEY_PREFIX = "online:"
ONLINE_TTL_SECONDS = 120  # 2分钟无活动视为离线


async def mark_online(user_id: str) -> bool:
    """标记用户在线（刷新 TTL）

    Args:
        user_id: 用户ID

    Returns:
        bool: 操作是否成功
    """
    try:
        client = await AsyncRedisPool.get_client()
        key = f"{ONLINE_KEY_PREFIX}{user_id}"
        await client.setex(key, ONLINE_TTL_SECONDS, "1")
        return True
    except Exception as e:
        logger.warning(f"标记在线状态失败: user_id={user_id}, error={e}")
        return False


async def mark_offline(user_id: str) -> bool:
    """标记用户离线

    Args:
        user_id: 用户ID

    Returns:
        bool: 操作是否成功
    """
    try:
        client = await AsyncRedisPool.get_client()
        key = f"{ONLINE_KEY_PREFIX}{user_id}"
        await client.delete(key)
        return True
    except Exception as e:
        logger.warning(f"标记离线状态失败: user_id={user_id}, error={e}")
        return False


async def is_online(user_id: str) -> bool:
    """检查用户是否在线

    Args:
        user_id: 用户ID

    Returns:
        bool: True 表示在线
    """
    try:
        client = await AsyncRedisPool.get_client()
        key = f"{ONLINE_KEY_PREFIX}{user_id}"
        result = await client.exists(key)
        return result > 0
    except Exception as e:
        logger.warning(f"查询在线状态失败: user_id={user_id}, error={e}")
        return False


async def batch_check_online(user_ids: list) -> dict:
    """批量查询用户在线状态

    Args:
        user_ids: 用户ID列表

    Returns:
        dict: {user_id: True/False, ...}
    """
    if not user_ids:
        return {}

    try:
        client = await AsyncRedisPool.get_client()
        keys = [f"{ONLINE_KEY_PREFIX}{uid}" for uid in user_ids]
        results = await client.exists(*keys)

        # results is the count of existing keys if passed as *args
        # For each individual check, we need to use mget or pipeline
        pipe = client.pipeline()
        for key in keys:
            pipe.exists(key)
        pipe_results = await pipe.execute()

        return {
            uid: bool(pipe_results[i])
            for i, uid in enumerate(user_ids)
        }
    except Exception as e:
        logger.warning(f"批量查询在线状态失败: error={e}")
        return {uid: False for uid in user_ids}


async def publish_notification(user_id: str, notification: dict) -> bool:
    """向用户发布通知（Redis Pub/Sub）

    用于规划师绑定用户后，通知用户端弹窗。

    Args:
        user_id: 目标用户ID
        notification: 通知内容字典

    Returns:
        bool: 发布是否成功
    """
    try:
        import json
        client = await AsyncRedisPool.get_client()
        channel = f"notification:{user_id}"
        await client.publish(channel, json.dumps(notification, ensure_ascii=False))
        logger.info(f"发布通知成功: user_id={user_id}, type={notification.get('type', 'unknown')}")
        return True
    except Exception as e:
        logger.warning(f"发布通知失败: user_id={user_id}, error={e}")
        return False


async def get_pending_notifications(user_id: str) -> list:
    """获取用户待处理通知（使用Redis List实现持久化通知）

    用于存储用户离线时错过的通知。

    Args:
        user_id: 目标用户ID

    Returns:
        list: 通知列表
    """
    try:
        import json
        client = await AsyncRedisPool.get_client()
        key = f"pending_notifications:{user_id}"
        notifications = []
        while True:
            raw = await client.lpop(key)
            if raw is None:
                break
            try:
                notifications.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return notifications
    except Exception as e:
        logger.warning(f"获取待处理通知失败: user_id={user_id}, error={e}")
        return []


async def add_pending_notification(user_id: str, notification: dict) -> bool:
    """添加待处理通知（用户离线时使用）

    Args:
        user_id: 目标用户ID
        notification: 通知内容

    Returns:
        bool: 添加是否成功
    """
    try:
        import json
        client = await AsyncRedisPool.get_client()
        key = f"pending_notifications:{user_id}"
        await client.rpush(key, json.dumps(notification, ensure_ascii=False))
        await client.expire(key, 86400)  # 24小时过期
        return True
    except Exception as e:
        logger.warning(f"添加待处理通知失败: user_id={user_id}, error={e}")
        return False
