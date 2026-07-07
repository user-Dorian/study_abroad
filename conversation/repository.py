"""会话与消息数据库仓库层 - 负责 conversations 和 messages 表的 CRUD 操作"""
import json
import uuid
from datetime import datetime
from typing import Optional
import threading

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from config.database import DatabaseConfig
from utils.logger import logger

_connection_pool = None
_pool_lock = threading.Lock()


def init_pool():
    """主动初始化数据库连接池（在服务器启动时调用，避免首次请求卡住）"""
    global _connection_pool
    if _connection_pool is not None:
        return _connection_pool
    
    with _pool_lock:
        if _connection_pool is not None:
            return _connection_pool
        
        try:
            conn_params = DatabaseConfig.get_connection_params()
            logger.info(f"正在初始化数据库连接池: {conn_params['host']}:{conn_params['port']}")
            _connection_pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                **conn_params
            )
            logger.info(f"数据库连接池创建成功: min=1, max=10")
            return _connection_pool
        except Exception as e:
            logger.error(f"数据库连接池创建失败: {e}")
            raise


def _get_pool():
    """获取全局数据库连接池，线程安全"""
    global _connection_pool
    if _connection_pool is not None:
        return _connection_pool
    
    with _pool_lock:
        if _connection_pool is not None:
            return _connection_pool
        
        try:
            return init_pool()
        except Exception as e:
            logger.error(f"数据库连接池获取失败: {e}")
            raise


def _get_connection():
    """从连接池获取数据库连接"""
    pool = _get_pool()
    return pool.getconn()


def _release_connection(conn):
    """释放数据库连接回连接池"""
    if conn is not None and _connection_pool is not None:
        try:
            _connection_pool.putconn(conn)
        except Exception as e:
            logger.warning(f"释放连接失败: {e}")


class ConversationRepository:
    """会话仓库类，负责 conversations 表的 CRUD 操作"""

    def __init__(self):
        self._conn_params = DatabaseConfig.get_connection_params()

    def create_conversation(self, title: str) -> dict:
        """
        创建新会话

        Args:
            title: 会话标题

        Returns:
            dict: 包含 {id, title, created_at, updated_at} 的会话信息
        """
        conv_id = str(uuid.uuid4())
        now = datetime.utcnow()

        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO conversations (id, title, created_at, updated_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, title, created_at, updated_at
                    """,
                    (conv_id, title, now, now),
                )
                row = cur.fetchone()
            conn.commit()

            result = {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
                "updated_at": row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else str(row["updated_at"]),
            }
            logger.info(f"创建会话成功: id={result['id']}, title={title}")
            return result

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"创建会话失败: title={title}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """
        获取单个会话

        Args:
            conversation_id: 会话ID

        Returns:
            dict | None: 会话信息字典，不存在时返回 None
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, title, created_at, updated_at
                    FROM conversations
                    WHERE id = %s
                    """,
                    (conversation_id,),
                )
                row = cur.fetchone()

            if row is None:
                logger.debug(f"会话不存在: id={conversation_id}")
                return None

            result = {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
                "updated_at": row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else str(row["updated_at"]),
            }
            logger.debug(f"获取会话成功: id={conversation_id}")
            return result

        except psycopg2.Error as e:
            logger.error(f"获取会话失败: id={conversation_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def list_conversations(self) -> list:
        """
        获取所有会话列表，按 updated_at 降序排列

        Returns:
            list[dict]: 会话信息列表
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, title, created_at, updated_at
                    FROM conversations
                    ORDER BY updated_at DESC
                    """
                )
                rows = cur.fetchall()

            results = []
            for row in rows:
                results.append({
                    "id": str(row["id"]),
                    "title": row["title"],
                    "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
                    "updated_at": row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else str(row["updated_at"]),
                })

            logger.debug(f"获取会话列表成功: 共 {len(results)} 条")
            return results

        except psycopg2.Error as e:
            logger.error(f"获取会话列表失败: error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def update_title(self, conversation_id: str, title: str) -> bool:
        """
        更新会话标题

        Args:
            conversation_id: 会话ID
            title: 新标题

        Returns:
            bool: 更新成功返回 True，会话不存在返回 False
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET title = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (title, datetime.utcnow(), conversation_id),
                )
                affected = cur.rowcount
            conn.commit()

            if affected == 0:
                logger.warning(f"更新会话标题失败，会话不存在: id={conversation_id}")
                return False

            logger.info(f"更新会话标题成功: id={conversation_id}, title={title}")
            return True

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"更新会话标题失败: id={conversation_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def update_timestamp(self, conversation_id: str) -> bool:
        """
        更新会话的 updated_at 为当前时间

        Args:
            conversation_id: 会话ID

        Returns:
            bool: 更新成功返回 True，会话不存在返回 False
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE conversations
                    SET updated_at = %s
                    WHERE id = %s
                    """,
                    (datetime.utcnow(), conversation_id),
                )
                affected = cur.rowcount
            conn.commit()

            if affected == 0:
                logger.warning(f"更新时间戳失败，会话不存在: id={conversation_id}")
                return False

            logger.debug(f"更新会话时间戳成功: id={conversation_id}")
            return True

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"更新会话时间戳失败: id={conversation_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        删除会话（级联删除关联消息）

        Args:
            conversation_id: 会话ID

        Returns:
            bool: 删除成功返回 True，会话不存在返回 False
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                # 先删除关联的消息
                cur.execute(
                    "DELETE FROM messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                msg_deleted = cur.rowcount

                # 再删除会话本身
                cur.execute(
                    "DELETE FROM conversations WHERE id = %s",
                    (conversation_id,),
                )
                conv_deleted = cur.rowcount

            conn.commit()

            if conv_deleted == 0:
                logger.warning(f"删除会话失败，会话不存在: id={conversation_id}")
                return False

            logger.info(
                f"删除会话成功: id={conversation_id}, 级联删除消息 {msg_deleted} 条"
            )
            return True

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(f"删除会话失败: id={conversation_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)


class MessageRepository:
    """消息仓库类，负责 messages 表的 CRUD 操作"""

    def __init__(self):
        self._conn_params = DatabaseConfig.get_connection_params()

    def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        保存消息

        Args:
            conversation_id: 所属会话ID
            role: 消息角色（如 user / assistant / system）
            content: 消息内容
            metadata: 可选的元数据字典

        Returns:
            dict: 包含 {id, conversation_id, role, content, metadata, created_at}
        """
        msg_id = str(uuid.uuid4())
        now = datetime.utcnow()
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None

        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, metadata_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, conversation_id, role, content, metadata_json, created_at
                    """,
                    (msg_id, conversation_id, role, content, metadata_json, now),
                )
                row = cur.fetchone()
            conn.commit()

            # 反序列化 metadata_json
            saved_metadata = None
            if row["metadata_json"] is not None:
                saved_metadata = (
                    json.loads(row["metadata_json"])
                    if isinstance(row["metadata_json"], str)
                    else row["metadata_json"]
                )

            result = {
                "id": str(row["id"]),
                "conversation_id": str(row["conversation_id"]),
                "role": row["role"],
                "content": row["content"],
                "metadata": saved_metadata,
                "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
            }
            logger.info(
                f"保存消息成功: id={result['id']}, conversation_id={conversation_id}, role={role}"
            )
            return result

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(
                f"保存消息失败: conversation_id={conversation_id}, role={role}, error={e}"
            )
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_messages(self, conversation_id: str, limit: int = 50) -> list:
        """
        获取消息列表，按 created_at 升序排列

        Args:
            conversation_id: 会话ID
            limit: 最大返回条数，默认 50

        Returns:
            list[dict]: 消息列表
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, conversation_id, role, content, metadata_json, created_at
                    FROM messages
                    WHERE conversation_id = %s
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (conversation_id, limit),
                )
                rows = cur.fetchall()

            results = []
            for row in rows:
                msg_metadata = None
                if row["metadata_json"] is not None:
                    msg_metadata = (
                        json.loads(row["metadata_json"])
                        if isinstance(row["metadata_json"], str)
                        else row["metadata_json"]
                    )
                results.append({
                    "id": str(row["id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": msg_metadata,
                    "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
                })

            logger.debug(
                f"获取消息列表成功: conversation_id={conversation_id}, 共 {len(results)} 条"
            )
            return results

        except psycopg2.Error as e:
            logger.error(
                f"获取消息列表失败: conversation_id={conversation_id}, error={e}"
            )
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_recent_messages(self, conversation_id: str, limit: int) -> list:
        """
        获取最近 N 条消息，按 created_at 升序排列

        实现思路：先按 created_at DESC 取最近 N 条，再在外层按 created_at ASC 排序

        Args:
            conversation_id: 会话ID
            limit: 获取条数

        Returns:
            list[dict]: 消息列表（按时间升序）
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, conversation_id, role, content, metadata_json, created_at
                    FROM (
                        SELECT id, conversation_id, role, content, metadata_json, created_at
                        FROM messages
                        WHERE conversation_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    ) sub
                    ORDER BY sub.created_at ASC
                    """,
                    (conversation_id, limit),
                )
                rows = cur.fetchall()

            results = []
            for row in rows:
                msg_metadata = None
                if row["metadata_json"] is not None:
                    msg_metadata = (
                        json.loads(row["metadata_json"])
                        if isinstance(row["metadata_json"], str)
                        else row["metadata_json"]
                    )
                results.append({
                    "id": str(row["id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": msg_metadata,
                    "created_at": row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else str(row["created_at"]),
                })

            logger.debug(
                f"获取最近消息成功: conversation_id={conversation_id}, limit={limit}, 实际 {len(results)} 条"
            )
            return results

        except psycopg2.Error as e:
            logger.error(
                f"获取最近消息失败: conversation_id={conversation_id}, error={e}"
            )
            raise
        finally:
            if conn:
                _release_connection(conn)

    def delete_messages_by_conversation(self, conversation_id: str) -> bool:
        """
        删除指定会话的所有消息

        Args:
            conversation_id: 会话ID

        Returns:
            bool: 始终返回 True（即使没有消息被删除）
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                deleted = cur.rowcount
            conn.commit()

            logger.info(
                f"删除会话消息成功: conversation_id={conversation_id}, 删除 {deleted} 条"
            )
            return True

        except psycopg2.Error as e:
            if conn:
                conn.rollback()
            logger.error(
                f"删除会话消息失败: conversation_id={conversation_id}, error={e}"
            )
            raise
        finally:
            if conn:
                _release_connection(conn)
