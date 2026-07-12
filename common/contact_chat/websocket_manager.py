"""WebSocket连接管理器 - 管理实时聊天连接

设计原理：
- 维护活跃WebSocket连接字典 {user_id: WebSocket}
- 支持个人消息推送、广播在线状态
- 与Redis集成实现持久化在线状态
- 自动清理断开的连接
"""
import json
from typing import Dict, Optional
from fastapi import WebSocket

from common.utils.logger import logger
from common.utils.online_status import mark_online, mark_offline, is_online
from common.config.async_redis import AsyncRedisPool


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._connection_info: Dict[str, dict] = {}  # 存储连接附加信息

    async def connect(self, websocket: WebSocket, user_id: str, user_info: dict = None):
        """接受WebSocket连接并注册用户

        Args:
            websocket: WebSocket连接对象
            user_id: 用户ID
            user_info: 用户附加信息（role, username等）
        """
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self._connection_info[user_id] = user_info or {}

        # 标记用户在线
        await mark_online(user_id)

        # 广播在线状态更新
        await self.broadcast_online_status(user_id, True)

        logger.info(f"WebSocket连接建立: user_id={user_id}, 当前连接数={len(self.active_connections)}")

    async def disconnect(self, user_id: str):
        """断开WebSocket连接并清理资源

        Args:
            user_id: 用户ID
        """
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            if user_id in self._connection_info:
                del self._connection_info[user_id]

            # 标记用户离线
            await mark_offline(user_id)

            # 广播离线状态更新
            await self.broadcast_online_status(user_id, False)

            logger.info(f"WebSocket连接断开: user_id={user_id}, 当前连接数={len(self.active_connections)}")

    async def send_personal_message(self, message: dict, user_id: str):
        """向指定用户发送消息

        Args:
            message: 消息内容字典
            user_id: 目标用户ID
        """
        if user_id not in self.active_connections:
            logger.warning(f"用户不在线，无法发送WebSocket消息: user_id={user_id}")
            return False

        websocket = self.active_connections[user_id]
        try:
            await websocket.send_json(message)
            logger.debug(f"WebSocket消息发送成功: user_id={user_id}, type={message.get('type')}")
            return True
        except Exception as e:
            logger.error(f"WebSocket消息发送失败: user_id={user_id}, error={e}")
            # 发送失败时断开连接
            await self.disconnect(user_id)
            return False

    async def broadcast_online_status(self, user_id: str, online: bool):
        """广播用户在线状态更新

        Args:
            user_id: 用户ID
            online: 是否在线
        """
        user_info = self._connection_info.get(user_id, {})
        message = {
            "type": "online_status",
            "user_id": user_id,
            "online": online,
            "username": user_info.get("username"),
            "display_name": user_info.get("display_name"),
            "timestamp": json.dumps({"time": str(await self._get_current_time())})
        }

        # 向所有在线连接广播
        disconnected = []
        for uid, ws in self.active_connections.items():
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"广播在线状态失败: uid={uid}, error={e}")
                disconnected.append(uid)

        # 清理发送失败的连接
        for uid in disconnected:
            await self.disconnect(uid)

    async def send_chat_message(self, message_data: dict, target_user_id: str):
        """发送聊天消息到目标用户

        Args:
            message_data: 消息数据（包含conversation_id, content等）
            target_user_id: 目标用户ID
        """
        message = {
            "type": "new_message",
            "conversation_id": message_data.get("conversation_id"),
            "message": message_data,
            "timestamp": str(await self._get_current_time())
        }
        return await self.send_personal_message(message, target_user_id)

    async def send_typing_indicator(self, user_id: str, target_user_id: str, is_typing: bool):
        """发送正在输入提示

        Args:
            user_id: 正在输入的用户ID
            target_user_id: 目标用户ID
            is_typing: 是否正在输入
        """
        user_info = self._connection_info.get(user_id, {})
        message = {
            "type": "typing",
            "user_id": user_id,
            "username": user_info.get("username"),
            "display_name": user_info.get("display_name"),
            "is_typing": is_typing
        }
        return await self.send_personal_message(message, target_user_id)

    def is_connected(self, user_id: str) -> bool:
        """检查用户是否通过WebSocket连接

        Args:
            user_id: 用户ID

        Returns:
            bool: 是否连接
        """
        return user_id in self.active_connections

    def get_connection_count(self) -> int:
        """获取当前活跃连接数"""
        return len(self.active_connections)

    async def _get_current_time(self):
        """获取当前时间"""
        from datetime import datetime
        return datetime.now()


# 全局单例连接管理器
_manager_instance: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """获取全局WebSocket连接管理器单例"""
    if _manager_instance is None:
        _manager_instance = ConnectionManager()
    return _manager_instance