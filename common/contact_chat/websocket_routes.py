"""WebSocket路由端点 - 实时聊天通信

提供WebSocket端点用于：
- 实时消息推送
- 在线状态同步
- 正在输入提示
"""
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from pydantic import BaseModel

from common.utils.logger import logger
from common.utils.auth import decode_access_token
from common.contact_chat.websocket_manager import get_connection_manager
from common.config.async_database import AsyncDatabasePool


router = APIRouter(tags=["websocket"])


class WebSocketMessage(BaseModel):
    """WebSocket消息格式"""
    type: str  # new_message, typing, online_status
    data: dict


@router.websocket("/ws/chat/{user_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(...),
):
    """WebSocket聊天端点

    连接流程：
    1. 客户端连接并传递token进行认证
    2. 认证成功后注册连接
    3. 监听客户端消息并处理
    4. 断开时清理连接

    Args:
        websocket: WebSocket连接
        user_id: 用户ID
        token: 认证token
    """
    # 验证token
    try:
        user_data = decode_access_token(token)
        if not user_data or user_data.get("user_id") != user_id:
            await websocket.close(code=4001, reason="认证失败")
            return
    except Exception as e:
        logger.error(f"WebSocket认证失败: user_id={user_id}, error={e}")
        await websocket.close(code=4001, reason="认证失败")
        return

    # 获取用户信息
    user_row = await AsyncDatabasePool.execute_one(
        "SELECT id, username, display_name, role FROM users WHERE id = $1",
        user_id,
    )
    if not user_row:
        await websocket.close(code=4004, reason="用户不存在")
        return

    user_info = {
        "username": user_row["username"],
        "display_name": user_row["display_name"],
        "role": user_row["role"],
    }

    # 注册连接
    manager = get_connection_manager()
    await manager.connect(websocket, user_id, user_info)

    try:
        # 消息循环
        while True:
            # 接收客户端消息
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await handle_websocket_message(websocket, user_id, message, manager)
            except json.JSONDecodeError:
                logger.warning(f"收到非JSON消息: user_id={user_id}, data={data[:100]}")
            except Exception as e:
                logger.error(f"处理WebSocket消息失败: user_id={user_id}, error={e}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket正常断开: user_id={user_id}")
        await manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket异常断开: user_id={user_id}, error={e}")
        await manager.disconnect(user_id)


async def handle_websocket_message(websocket: WebSocket, user_id: str, message: dict, manager):
    """处理WebSocket消息

    Args:
        websocket: WebSocket连接
        user_id: 发送者用户ID
        message: 消息内容
        manager: 连接管理器
    """
    msg_type = message.get("type")

    if msg_type == "ping":
        # 心跳检测
        await websocket.send_json({"type": "pong", "timestamp": str(await manager._get_current_time())})

    elif msg_type == "typing":
        # 正在输入提示
        target_user_id = message.get("target_user_id")
        is_typing = message.get("is_typing", False)
        if target_user_id:
            await manager.send_typing_indicator(user_id, target_user_id, is_typing)

    elif msg_type == "chat_message":
        # 聊天消息 - 保存到数据库并通过WebSocket推送
        conversation_id = message.get("conversation_id")
        content = message.get("content")

        if not conversation_id or not content:
            return

        # 验证对话权限
        conv_row = await AsyncDatabasePool.execute_one(
            "SELECT id, user_id, other_user_id FROM conversations WHERE id = $1 AND (user_id = $2 OR other_user_id = $2)",
            conversation_id, user_id,
        )
        if not conv_row:
            logger.warning(f"无权向对话发送消息: conv={conversation_id}, user={user_id}")
            return

        # 确定接收者
        target_user_id = str(conv_row["other_user_id"]) if str(conv_row["user_id"]) == user_id else str(conv_row["user_id"])

        # 获取发送者角色
        user_role_row = await AsyncDatabasePool.execute_one(
            "SELECT role FROM users WHERE id = $1", user_id
        )
        sender_type = "consultant" if user_role_row["role"] == "consultant" else "user"

        # 保存消息到数据库
        msg_row = await AsyncDatabasePool.execute_one(
            """INSERT INTO messages (conversation_id, role, content, sender_type, sender_id)
               VALUES ($1, 'user', $2, $3, $4)
               RETURNING id, conversation_id, role, content, sender_type, sender_id, created_at""",
            conversation_id, content, sender_type, user_id,
        )

        # 更新对话时间
        await AsyncDatabasePool.execute_command(
            "UPDATE conversations SET updated_at = NOW() WHERE id = $1",
            conversation_id,
        )

        # 构建消息数据
        message_data = {
            "id": str(msg_row["id"]),
            "conversation_id": conversation_id,
            "content": content,
            "sender_type": sender_type,
            "sender_id": user_id,
            "created_at": str(msg_row["created_at"]),
        }

        # 通过WebSocket推送给接收者
        if manager.is_connected(target_user_id):
            await manager.send_chat_message(message_data, target_user_id)
        else:
            # 接收者不在线，添加到待处理通知
            from common.utils.online_status import add_pending_notification
            notification = {
                "type": "new_message",
                "conversation_id": conversation_id,
                "from_id": user_id,
                "message": content[:50],
                "full_message": message_data,
            }
            await add_pending_notification(target_user_id, notification)

        logger.info(f"WebSocket消息发送成功: conv={conversation_id}, from={user_id}, to={target_user_id}")

    else:
        logger.warning(f"未知的WebSocket消息类型: type={msg_type}, user={user_id}")