"""WebSocket聊天路由 - 实时聊天通信"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from typing import Dict, Set
import json
from datetime import datetime
import uuid

from backend.common.basics.utils.logger import logger

router = APIRouter(tags=["WebSocket聊天"])


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # user_id -> Set[WebSocket]
        self._connections: Dict[str, Set[WebSocket]] = {}

    def connect(self, user_id: str, websocket: WebSocket):
        """建立连接"""
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(websocket)
        logger.info(f"WebSocket连接建立: user_id={user_id}, 总连接数={len(self._connections[user_id])}")

    def disconnect(self, user_id: str, websocket: WebSocket):
        """断开连接"""
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.info(f"WebSocket连接断开: user_id={user_id}")

    async def send_to_user(self, user_id: str, message: dict):
        """向用户发送消息"""
        if user_id in self._connections:
            disconnected = set()
            for websocket in self._connections[user_id]:
                try:
                    await websocket.send_json(message)
                except Exception as e:
                    logger.warning(f"发送消息失败: {e}")
                    disconnected.add(websocket)

            # 清理断开的连接
            for ws in disconnected:
                self.disconnect(user_id, ws)

    async def broadcast(self, message: dict, exclude_user: str = None):
        """广播消息到所有连接"""
        for user_id in list(self._connections.keys()):
            if exclude_user and user_id == exclude_user:
                continue
            await self.send_to_user(user_id, message)

    def is_online(self, user_id: str) -> bool:
        """检查用户是否在线"""
        return user_id in self._connections and len(self._connections[user_id]) > 0


# 全局连接管理器
manager = ConnectionManager()


async def websocket_chat_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket聊天端点

    Args:
        websocket: WebSocket连接
        user_id: 用户ID（从路径参数获取）
    """
    try:
        # 接受连接
        await websocket.accept()
        manager.connect(user_id, websocket)

        # 发送欢迎消息
        await websocket.send_json({
            "type": "system",
            "content": "连接成功",
            "timestamp": datetime.utcnow().isoformat()
        })

        logger.info(f"WebSocket聊天连接成功: user_id={user_id}")

        # 消息循环
        while True:
            # 接收消息
            data = await websocket.receive_text()

            try:
                message = json.loads(data)

                # 处理消息
                message_type = message.get("type", "chat")
                to_user_id = message.get("to_user_id")
                content = message.get("content", "")

                if message_type == "chat" and to_user_id:
                    # 聊天消息
                    message_id = str(uuid.uuid4())
                    chat_message = {
                        "type": "chat",
                        "message_id": message_id,
                        "from_user_id": user_id,
                        "to_user_id": to_user_id,
                        "content": content,
                        "timestamp": datetime.utcnow().isoformat()
                    }

                    # 发送给接收者
                    await manager.send_to_user(to_user_id, chat_message)

                    # 发送确认给发送者
                    await websocket.send_json({
                        "type": "ack",
                        "message_id": message_id,
                        "status": "delivered",
                        "timestamp": datetime.utcnow().isoformat()
                    })

                    logger.info(
                        f"WebSocket消息转发: from={user_id}, to={to_user_id}, "
                        f"msg_id={message_id}"
                    )

                elif message_type == "ping":
                    # 心跳检测
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "无效的消息格式",
                    "timestamp": datetime.utcnow().isoformat()
                })

    except WebSocketDisconnect:
        manager.disconnect(user_id, websocket)
        logger.info(f"WebSocket正常断开: user_id={user_id}")

    except Exception as e:
        logger.error(f"WebSocket异常: {e}", exc_info=True)
        manager.disconnect(user_id, websocket)


@router.get("/api/chat/online/{user_id}")
async def check_user_online(user_id: str):
    """检查用户是否在线

    Args:
        user_id: 用户ID

    Returns:
        dict: 在线状态
    """
    is_online = manager.is_online(user_id)
    return {
        "user_id": user_id,
        "online": is_online
    }


@router.get("/api/chat/online")
async def get_online_users():
    """获取在线用户列表

    Returns:
        dict: 在线用户列表
    """
    online_users = list(manager._connections.keys())
    return {
        "online_users": online_users,
        "count": len(online_users)
    }
