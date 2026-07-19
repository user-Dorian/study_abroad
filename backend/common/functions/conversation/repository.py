"""会话仓储层 - 数据库操作"""
import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
from backend.common.basics.utils.logger import logger
from .config import ConversationConfig

# 延迟导入psycopg2
try:
    import psycopg2
    from psycopg2 import pool
except ImportError:
    psycopg2 = None
    pool = None
    logger.warning("psycopg2未安装，数据库功能将不可用")


# 全局连接池
_pool: Optional[Any] = None


def init_pool():
    """初始化数据库连接池"""
    global _pool
    
    if _pool is not None:
        return
    
    if psycopg2 is None:
        logger.warning("psycopg2未安装，无法初始化数据库连接池")
        return
    
    try:
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=ConversationConfig.DB_POOL_SIZE,
            host=ConversationConfig.DB_HOST,
            port=ConversationConfig.DB_PORT,
            user=ConversationConfig.DB_USER,
            password=ConversationConfig.DB_PASSWORD,
            database=ConversationConfig.DB_NAME
        )
        logger.info("数据库连接池初始化成功")
    except Exception as e:
        logger.error(f"数据库连接池初始化失败: {e}", exc_info=True)
        raise


def get_connection():
    """获取数据库连接"""
    global _pool
    
    if psycopg2 is None:
        raise RuntimeError("psycopg2未安装，无法获取数据库连接")
    
    if _pool is None:
        init_pool()
    
    if _pool is None:
        raise RuntimeError("数据库连接池未初始化")
    
    return _pool.getconn()


def release_connection(conn):
    """释放数据库连接"""
    global _pool
    
    if _pool and conn:
        _pool.putconn(conn)


class ConversationRepository:
    """会话仓储层 - 处理会话相关数据库操作
    
    特性：
    - 连接池管理
    - CRUD操作
    - 事务支持
    - 完善的错误处理
    """
    
    def create_conversation(
        self,
        conversation_id: str,
        user_id: Optional[str] = None,
        title: str = "新对话",
    ) -> bool:
        """创建会话
        
        Args:
            conversation_id: 会话ID
            user_id: 用户ID
            title: 会话标题
            
        Returns:
            bool: 是否成功
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO conversations (id, user_id, title, dialogue_type, created_at, updated_at)
                VALUES (%s, %s, %s, 'ai_chat', %s, %s)
            """, (conversation_id, user_id, title, datetime.utcnow(), datetime.utcnow()))
            
            conn.commit()
            cursor.close()
            release_connection(conn)
            
            return True
            
        except Exception as e:
            logger.error(f"创建会话失败: {e}", exc_info=True)
            return False
    
    def get_conversation(
        self,
        conversation_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取会话信息
        
        Args:
            conversation_id: 会话ID
            user_id: 用户ID
            
        Returns:
            Dict: 会话信息
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            if user_id:
                cursor.execute("""
                    SELECT id, user_id, title, dialogue_type, created_at, updated_at
                    FROM conversations
                    WHERE id = %s AND user_id = %s
                """, (conversation_id, user_id))
            else:
                cursor.execute("""
                    SELECT id, user_id, title, dialogue_type, created_at, updated_at
                    FROM conversations
                    WHERE id = %s
                """, (conversation_id,))
            
            row = cursor.fetchone()
            cursor.close()
            release_connection(conn)
            
            if not row:
                return None
            
            return {
                "id": str(row[0]),
                "user_id": row[1],
                "title": row[2],
                "dialogue_type": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
                "updated_at": row[5].isoformat() if row[5] else None,
            }
            
        except Exception as e:
            logger.error(f"获取会话失败: {e}", exc_info=True)
            return None
    
    def list_conversations(
        self,
        user_id: Optional[str] = None,
        dialogue_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取会话列表
        
        Args:
            user_id: 用户ID
            dialogue_type: 对话类型
            
        Returns:
            List[Dict]: 会话列表
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            query = "SELECT id, user_id, title, dialogue_type, created_at, updated_at FROM conversations WHERE 1=1"
            params = []
            
            if user_id:
                query += " AND user_id = %s"
                params.append(user_id)
            
            if dialogue_type:
                query += " AND (dialogue_type = %s OR dialogue_type IS NULL)"
                params.append(dialogue_type)
            
            query += " ORDER BY updated_at DESC LIMIT 100"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()
            release_connection(conn)
            
            return [
                {
                    "id": str(row[0]),
                    "user_id": row[1],
                    "title": row[2],
                    "dialogue_type": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None,
                }
                for row in rows
            ]
            
        except Exception as e:
            logger.error(f"获取会话列表失败: {e}", exc_info=True)
            return []
    
    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """更新会话标题
        
        Args:
            conversation_id: 会话ID
            title: 新标题
            
        Returns:
            bool: 是否成功
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE conversations
                SET title = %s, updated_at = %s
                WHERE id = %s
            """, (title, datetime.utcnow(), conversation_id))
            
            conn.commit()
            success = cursor.rowcount > 0
            cursor.close()
            release_connection(conn)
            
            return success
            
        except Exception as e:
            logger.error(f"更新会话标题失败: {e}", exc_info=True)
            return False
    
    def delete_conversation(
        self,
        conversation_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """删除会话
        
        Args:
            conversation_id: 会话ID
            user_id: 用户ID
            
        Returns:
            bool: 是否成功
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # 先删除消息
            cursor.execute("DELETE FROM messages WHERE conversation_id = %s", (conversation_id,))
            
            # 删除会话
            if user_id:
                cursor.execute("DELETE FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user_id))
            else:
                cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            
            conn.commit()
            success = cursor.rowcount > 0
            cursor.close()
            release_connection(conn)
            
            return success
            
        except Exception as e:
            logger.error(f"删除会话失败: {e}", exc_info=True)
            return False
    
    def add_message(
        self,
        message_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """添加消息
        
        Args:
            message_id: 消息ID
            conversation_id: 会话ID
            role: 角色
            content: 内容
            metadata: 元数据
            
        Returns:
            bool: 是否成功
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            import json
            metadata_json = json.dumps(metadata) if metadata else None
            
            cursor.execute("""
                INSERT INTO messages (id, conversation_id, role, content, metadata, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (message_id, conversation_id, role, content, metadata_json, datetime.utcnow()))
            
            # 更新会话时间
            cursor.execute("""
                UPDATE conversations
                SET updated_at = %s
                WHERE id = %s
            """, (datetime.utcnow(), conversation_id))
            
            conn.commit()
            cursor.close()
            release_connection(conn)
            
            return True
            
        except Exception as e:
            logger.error(f"添加消息失败: {e}", exc_info=True)
            return False
    
    def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取消息列表
        
        Args:
            conversation_id: 会话ID
            limit: 返回数量限制
            
        Returns:
            List[Dict]: 消息列表
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, conversation_id, role, content, metadata, created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC
                LIMIT %s
            """, (conversation_id, limit))
            
            rows = cursor.fetchall()
            cursor.close()
            release_connection(conn)
            
            import json
            return [
                {
                    "id": str(row[0]),
                    "conversation_id": str(row[1]),
                    "role": row[2],
                    "content": row[3],
                    # 兼容jsonb已解析为dict和原始字符串两种情况
                    "metadata": (
                        row[4]
                        if row[4] is None or isinstance(row[4], (dict, list))
                        else (json.loads(row[4]) if isinstance(row[4], str) else row[4])
                    ),
                    "created_at": row[5].isoformat() if row[5] else None,
                }
                for row in rows
            ]
            
        except Exception as e:
            logger.error(f"获取消息列表失败: {e}", exc_info=True)
            return []
    
    def find_empty_conversation(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """查找空对话
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict: 空对话信息
        """
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # 查找没有消息的会话
            cursor.execute("""
                SELECT c.id, c.user_id, c.title, c.dialogue_type, c.created_at, c.updated_at
                FROM conversations c
                LEFT JOIN messages m ON c.id = m.conversation_id
                WHERE c.user_id = %s AND m.id IS NULL
                ORDER BY c.created_at DESC
                LIMIT 1
            """, (user_id,))
            
            row = cursor.fetchone()
            cursor.close()
            release_connection(conn)
            
            if not row:
                return None
            
            return {
                "id": str(row[0]),
                "user_id": row[1],
                "title": row[2],
                "dialogue_type": row[3],
                "created_at": row[4].isoformat() if row[4] else None,
                "updated_at": row[5].isoformat() if row[5] else None,
            }
            
        except Exception as e:
            logger.error(f"查找空对话失败: {e}", exc_info=True)
            return None


# 全局单例
_repo: Optional[ConversationRepository] = None


def get_conversation_repo() -> ConversationRepository:
    """获取会话仓储层单例"""
    global _repo
    if _repo is None:
        _repo = ConversationRepository()
    return _repo
