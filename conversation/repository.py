"""会话与消息数据库仓库层 - 负责 conversations 和 messages 表的 CRUD 操作"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional
import threading

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from config.database import DatabaseConfig
from utils.logger import logger
# 阶段2数据库异步化：导入 asyncpg 异步连接池
from common.config.async_database import AsyncDatabasePool


def _ensure_utc_iso(dt) -> str:
    """确保 datetime 转为带 UTC 时区标识的 ISO 字符串，供前端正确转为本地时间"""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            # 无时区信息视为 UTC，添加 +00:00
            return dt.isoformat() + "+00:00"
        return dt.isoformat()
    return str(dt)

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

    def create_conversation(self, title: str, user_id: Optional[str] = None) -> dict:
        """
        创建新会话

        Args:
            title: 会话标题
            user_id: 可选的用户ID

        Returns:
            dict: 包含 {id, title, created_at, updated_at} 的会话信息
        """
        conv_id = str(uuid.uuid4())
        now = datetime.utcnow()

        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user_id is not None:
                    cur.execute(
                        """
                        INSERT INTO conversations (id, title, user_id, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, title, created_at, updated_at
                        """,
                        (conv_id, title, user_id, now, now),
                    )
                else:
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
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
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

    def find_empty_conversation(self, user_id: str) -> Optional[dict]:
        """
        查找用户的空对话（无消息的对话），每人最多保留一个

        Args:
            user_id: 用户ID

        Returns:
            dict | None: 空对话信息，不存在时返回 None
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT c.id, c.title, c.created_at, c.updated_at
                    FROM conversations c
                    WHERE c.user_id = %s
                      AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)
                    ORDER BY c.created_at DESC
                    LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()

            if row is None:
                return None

            return {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }

        except psycopg2.Error as e:
            logger.error(f"查找空对话失败: user_id={user_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def get_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """
        获取单个会话

        Args:
            conversation_id: 会话ID
            user_id: 可选的用户ID，用于验证归属

        Returns:
            dict | None: 会话信息字典，不存在时返回 None
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user_id is not None:
                    cur.execute(
                        """
                        SELECT id, title, created_at, updated_at
                        FROM conversations
                        WHERE id = %s AND user_id = %s
                        """,
                        (conversation_id, user_id),
                    )
                else:
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
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }
            logger.debug(f"获取会话成功: id={conversation_id}")
            return result

        except psycopg2.Error as e:
            logger.error(f"获取会话失败: id={conversation_id}, error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def list_conversations(self, user_id: Optional[str] = None) -> list:
        """
        获取会话列表，按 updated_at 降序排列

        Args:
            user_id: 可选的用户ID，用于过滤

        Returns:
            list[dict]: 会话信息列表
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if user_id is not None:
                    cur.execute(
                        """
                        SELECT c.id, c.title, c.created_at, c.updated_at
                        FROM conversations c
                        WHERE c.user_id = %s
                        ORDER BY c.updated_at DESC
                        """,
                        (user_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT c.id, c.title, c.created_at, c.updated_at
                        FROM conversations c
                        ORDER BY c.updated_at DESC
                        """
                    )
                rows = cur.fetchall()

            results = []
            for row in rows:
                results.append({
                    "id": str(row["id"]),
                    "title": row["title"],
                    "created_at": _ensure_utc_iso(row["created_at"]),
                    "updated_at": _ensure_utc_iso(row["updated_at"]),
                })

            logger.debug(f"获取会话列表成功: 共 {len(results)} 条")
            return results

        except psycopg2.Error as e:
            logger.error(f"获取会话列表失败: error={e}")
            raise
        finally:
            if conn:
                _release_connection(conn)

    def update_title(self, conversation_id: str, title: str, user_id: Optional[str] = None) -> bool:
        """
        更新会话标题

        Args:
            conversation_id: 会话ID
            title: 新标题
            user_id: 可选的用户ID，用于验证归属

        Returns:
            bool: 更新成功返回 True，会话不存在返回 False
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET title = %s, updated_at = %s
                        WHERE id = %s AND user_id = %s
                        """,
                        (title, datetime.utcnow(), conversation_id, user_id),
                    )
                else:
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

    def update_timestamp(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """
        更新会话的 updated_at 为当前时间

        Args:
            conversation_id: 会话ID
            user_id: 可选的用户ID，用于验证归属

        Returns:
            bool: 更新成功返回 True，会话不存在返回 False
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                if user_id is not None:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET updated_at = %s
                        WHERE id = %s AND user_id = %s
                        """,
                        (datetime.utcnow(), conversation_id, user_id),
                    )
                else:
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

    def delete_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """
        删除会话（级联删除关联消息）

        Args:
            conversation_id: 会话ID
            user_id: 可选的用户ID，用于验证归属

        Returns:
            bool: 删除成功返回 True，会话不存在返回 False
        """
        conn = None
        try:
            conn = _get_connection()
            with conn.cursor() as cur:
                # 先删除会话本身（含用户归属验证）
                if user_id is not None:
                    cur.execute(
                        "DELETE FROM conversations WHERE id = %s AND user_id = %s",
                        (conversation_id, user_id),
                    )
                else:
                    cur.execute(
                        "DELETE FROM conversations WHERE id = %s",
                        (conversation_id,),
                    )
                conv_deleted = cur.rowcount

                # 再删除关联的消息（仅在会话删除成功时执行）
                if conv_deleted > 0:
                    cur.execute(
                        "DELETE FROM messages WHERE conversation_id = %s",
                        (conversation_id,),
                    )
                    msg_deleted = cur.rowcount
                else:
                    msg_deleted = 0

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
                "created_at": _ensure_utc_iso(row["created_at"]),
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
                    "created_at": _ensure_utc_iso(row["created_at"]),
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
                    "created_at": _ensure_utc_iso(row["created_at"]),
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


# ====== 阶段2数据库异步化：异步仓库类（保留同步类不变，新增 asyncpg 版本） ======

def _parse_metadata(metadata_json) -> Optional[dict]:
    """反序列化 metadata_json（asyncpg 的 jsonb 默认返回字符串，与 psycopg2 保持一致兼容）"""
    if metadata_json is None:
        return None
    if isinstance(metadata_json, str):
        return json.loads(metadata_json)
    return metadata_json


def _affected_count(status: str) -> int:
    """从 asyncpg execute 返回的状态字符串中解析受影响行数

    asyncpg 的 execute 返回形如 "INSERT 0 1" / "UPDATE 3" / "DELETE 0" 的状态字符串，
    末段数字即受影响行数。
    """
    if not status:
        return 0
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0


class AsyncConversationRepository:
    """异步会话仓库类（asyncpg），负责 conversations 表的异步 CRUD 操作

    与同步 ConversationRepository 行为一致，SQL 占位符从 %s 改为 $1, $2, ...
    所有方法均为 async def，使用 AsyncDatabasePool，避免阻塞事件循环。
    """

    async def create_conversation(self, title: str, user_id: Optional[str] = None) -> dict:
        """创建新会话（异步版）"""
        conv_id = str(uuid.uuid4())
        now = datetime.utcnow()
        try:
            if user_id is not None:
                sql = (
                    "INSERT INTO conversations (id, title, user_id, created_at, updated_at) "
                    "VALUES ($1, $2, $3, $4, $5) "
                    "RETURNING id, title, created_at, updated_at"
                )
                row = await AsyncDatabasePool.execute_one(sql, conv_id, title, user_id, now, now)
            else:
                sql = (
                    "INSERT INTO conversations (id, title, created_at, updated_at) "
                    "VALUES ($1, $2, $3, $4) "
                    "RETURNING id, title, created_at, updated_at"
                )
                row = await AsyncDatabasePool.execute_one(sql, conv_id, title, now, now)

            result = {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }
            logger.info(f"创建会话成功: id={result['id']}, title={title}")
            return result

        except Exception as e:
            logger.error(f"创建会话失败: title={title}, error={e}")
            raise

    async def find_empty_conversation(self, user_id: str) -> Optional[dict]:
        """查找用户的空对话（无消息），每人最多保留一个（异步版）"""
        try:
            sql = (
                "SELECT c.id, c.title, c.created_at, c.updated_at "
                "FROM conversations c "
                "WHERE c.user_id = $1 "
                "  AND NOT EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id) "
                "ORDER BY c.created_at DESC "
                "LIMIT 1"
            )
            row = await AsyncDatabasePool.execute_one(sql, user_id)
            if row is None:
                return None
            return {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }

        except Exception as e:
            logger.error(f"查找空对话失败: user_id={user_id}, error={e}")
            raise

    async def get_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """获取单个会话（异步版）"""
        try:
            if user_id is not None:
                sql = "SELECT id, title, created_at, updated_at FROM conversations WHERE id = $1 AND user_id = $2"
                row = await AsyncDatabasePool.execute_one(sql, conversation_id, user_id)
            else:
                sql = "SELECT id, title, created_at, updated_at FROM conversations WHERE id = $1"
                row = await AsyncDatabasePool.execute_one(sql, conversation_id)

            if row is None:
                logger.debug(f"会话不存在: id={conversation_id}")
                return None

            result = {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": _ensure_utc_iso(row["created_at"]),
                "updated_at": _ensure_utc_iso(row["updated_at"]),
            }
            logger.debug(f"获取会话成功: id={conversation_id}")
            return result

        except Exception as e:
            logger.error(f"获取会话失败: id={conversation_id}, error={e}")
            raise

    async def list_conversations(self, user_id: Optional[str] = None) -> list:
        """获取会话列表，按 updated_at 降序排列（异步版）"""
        try:
            if user_id is not None:
                sql = (
                    "SELECT c.id, c.title, c.created_at, c.updated_at "
                    "FROM conversations c WHERE c.user_id = $1 "
                    "ORDER BY c.updated_at DESC"
                )
                rows = await AsyncDatabasePool.execute_query(sql, user_id)
            else:
                sql = (
                    "SELECT c.id, c.title, c.created_at, c.updated_at "
                    "FROM conversations c ORDER BY c.updated_at DESC"
                )
                rows = await AsyncDatabasePool.execute_query(sql)

            results = [
                {
                    "id": str(row["id"]),
                    "title": row["title"],
                    "created_at": _ensure_utc_iso(row["created_at"]),
                    "updated_at": _ensure_utc_iso(row["updated_at"]),
                }
                for row in rows
            ]
            logger.debug(f"获取会话列表成功: 共 {len(results)} 条")
            return results

        except Exception as e:
            logger.error(f"获取会话列表失败: error={e}")
            raise

    async def update_title(self, conversation_id: str, title: str, user_id: Optional[str] = None) -> bool:
        """更新会话标题（异步版）"""
        try:
            now = datetime.utcnow()
            if user_id is not None:
                sql = "UPDATE conversations SET title = $1, updated_at = $2 WHERE id = $3 AND user_id = $4"
                status = await AsyncDatabasePool.execute_command(sql, title, now, conversation_id, user_id)
            else:
                sql = "UPDATE conversations SET title = $1, updated_at = $2 WHERE id = $3"
                status = await AsyncDatabasePool.execute_command(sql, title, now, conversation_id)

            affected = _affected_count(status)
            if affected == 0:
                logger.warning(f"更新会话标题失败，会话不存在: id={conversation_id}")
                return False

            logger.info(f"更新会话标题成功: id={conversation_id}, title={title}")
            return True

        except Exception as e:
            logger.error(f"更新会话标题失败: id={conversation_id}, error={e}")
            raise

    async def update_timestamp(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """更新会话的 updated_at 为当前时间（异步版）"""
        try:
            now = datetime.utcnow()
            if user_id is not None:
                sql = "UPDATE conversations SET updated_at = $1 WHERE id = $2 AND user_id = $3"
                status = await AsyncDatabasePool.execute_command(sql, now, conversation_id, user_id)
            else:
                sql = "UPDATE conversations SET updated_at = $1 WHERE id = $2"
                status = await AsyncDatabasePool.execute_command(sql, now, conversation_id)

            affected = _affected_count(status)
            if affected == 0:
                logger.warning(f"更新时间戳失败，会话不存在: id={conversation_id}")
                return False

            logger.debug(f"更新会话时间戳成功: id={conversation_id}")
            return True

        except Exception as e:
            logger.error(f"更新会话时间戳失败: id={conversation_id}, error={e}")
            raise

    async def delete_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """删除会话（级联删除关联消息，异步版）"""
        try:
            pool = await AsyncDatabasePool.get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if user_id is not None:
                        status = await conn.execute(
                            "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
                            conversation_id, user_id,
                        )
                    else:
                        status = await conn.execute(
                            "DELETE FROM conversations WHERE id = $1",
                            conversation_id,
                        )
                    conv_deleted = _affected_count(status)

                    msg_deleted = 0
                    if conv_deleted > 0:
                        msg_status = await conn.execute(
                            "DELETE FROM messages WHERE conversation_id = $1",
                            conversation_id,
                        )
                        msg_deleted = _affected_count(msg_status)

            if conv_deleted == 0:
                logger.warning(f"删除会话失败，会话不存在: id={conversation_id}")
                return False

            logger.info(f"删除会话成功: id={conversation_id}, 级联删除消息 {msg_deleted} 条")
            return True

        except Exception as e:
            logger.error(f"删除会话失败: id={conversation_id}, error={e}")
            raise


class AsyncMessageRepository:
    """异步消息仓库类（asyncpg），负责 messages 表的异步 CRUD 操作

    与同步 MessageRepository 行为一致，SQL 占位符从 %s 改为 $1, $2, ...
    """

    async def save_message(self, conversation_id: str, role: str, content: str, metadata: Optional[dict] = None) -> dict:
        """保存消息（异步版）"""
        msg_id = str(uuid.uuid4())
        now = datetime.utcnow()
        metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata is not None else None
        try:
            sql = (
                "INSERT INTO messages (id, conversation_id, role, content, metadata_json, created_at) "
                "VALUES ($1, $2, $3, $4, $5, $6) "
                "RETURNING id, conversation_id, role, content, metadata_json, created_at"
            )
            row = await AsyncDatabasePool.execute_one(sql, msg_id, conversation_id, role, content, metadata_json, now)

            result = {
                "id": str(row["id"]),
                "conversation_id": str(row["conversation_id"]),
                "role": row["role"],
                "content": row["content"],
                "metadata": _parse_metadata(row["metadata_json"]),
                "created_at": _ensure_utc_iso(row["created_at"]),
            }
            logger.info(f"保存消息成功: id={result['id']}, conversation_id={conversation_id}, role={role}")
            return result

        except Exception as e:
            logger.error(f"保存消息失败: conversation_id={conversation_id}, role={role}, error={e}")
            raise

    async def get_messages(self, conversation_id: str, limit: int = 50) -> list:
        """获取消息列表，按 created_at 升序排列（异步版）"""
        try:
            sql = (
                "SELECT id, conversation_id, role, content, metadata_json, created_at "
                "FROM messages WHERE conversation_id = $1 "
                "ORDER BY created_at ASC LIMIT $2"
            )
            rows = await AsyncDatabasePool.execute_query(sql, conversation_id, limit)

            results = [
                {
                    "id": str(row["id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": _parse_metadata(row["metadata_json"]),
                    "created_at": _ensure_utc_iso(row["created_at"]),
                }
                for row in rows
            ]
            logger.debug(f"获取消息列表成功: conversation_id={conversation_id}, 共 {len(results)} 条")
            return results

        except Exception as e:
            logger.error(f"获取消息列表失败: conversation_id={conversation_id}, error={e}")
            raise

    async def get_recent_messages(self, conversation_id: str, limit: int) -> list:
        """获取最近 N 条消息，按 created_at 升序排列（异步版）

        实现思路：先按 created_at DESC 取最近 N 条，再在外层按 created_at ASC 排序
        """
        try:
            sql = (
                "SELECT id, conversation_id, role, content, metadata_json, created_at FROM ("
                "  SELECT id, conversation_id, role, content, metadata_json, created_at "
                "  FROM messages WHERE conversation_id = $1 "
                "  ORDER BY created_at DESC LIMIT $2"
                ") sub ORDER BY sub.created_at ASC"
            )
            rows = await AsyncDatabasePool.execute_query(sql, conversation_id, limit)

            results = [
                {
                    "id": str(row["id"]),
                    "conversation_id": str(row["conversation_id"]),
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": _parse_metadata(row["metadata_json"]),
                    "created_at": _ensure_utc_iso(row["created_at"]),
                }
                for row in rows
            ]
            logger.debug(f"获取最近消息成功: conversation_id={conversation_id}, limit={limit}, 实际 {len(results)} 条")
            return results

        except Exception as e:
            logger.error(f"获取最近消息失败: conversation_id={conversation_id}, error={e}")
            raise

    async def delete_messages_by_conversation(self, conversation_id: str) -> bool:
        """删除指定会话的所有消息（异步版）"""
        try:
            status = await AsyncDatabasePool.execute_command(
                "DELETE FROM messages WHERE conversation_id = $1",
                conversation_id,
            )
            deleted = _affected_count(status)
            logger.info(f"删除会话消息成功: conversation_id={conversation_id}, 删除 {deleted} 条")
            return True

        except Exception as e:
            logger.error(f"删除会话消息失败: conversation_id={conversation_id}, error={e}")
            raise
