"""创建会话相关数据库表

包含：
- conversations: 会话表
- messages: 消息表
"""
import psycopg2
from psycopg2.extensions import connection as PGConnection
from backend.common.basics.utils.logger import logger


def create_conversation_tables(conn: PGConnection = None) -> bool:
    """创建会话相关表
    
    Args:
        conn: 数据库连接对象，如果为None则创建新连接
        
    Returns:
        bool: 创建成功返回True，失败返回False
    """
    should_close_conn = False
    
    try:
        # 如果没有提供连接，则创建新连接
        if conn is None:
            from backend.common.functions.conversation.repository import get_connection
            conn = get_connection()
            should_close_conn = True
        
        cursor = conn.cursor()
        
        # 创建会话表
        logger.info("创建 conversations 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36),
                title VARCHAR(255) DEFAULT '新对话',
                dialogue_type VARCHAR(50) DEFAULT 'ai_chat',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_conversation_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # 创建消息表
        logger.info("创建 messages 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id VARCHAR(36) PRIMARY KEY,
                conversation_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        
        # 兼容旧表：确保 metadata 字段存在
        try:
            cursor.execute("""
                ALTER TABLE messages ADD COLUMN IF NOT EXISTS metadata JSONB
            """)
        except Exception as alter_e:
            logger.warning(f"添加 metadata 字段失败(可忽略): {alter_e}")
            conn.rollback()
        
        # 创建索引
        logger.info("创建索引...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id 
            ON conversations(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_updated_at 
            ON conversations(updated_at DESC)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation_id 
            ON messages(conversation_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_created_at 
            ON messages(created_at ASC)
        """)
        
        conn.commit()
        cursor.close()
        
        logger.info("会话相关表创建成功")
        return True
        
    except Exception as e:
        logger.error(f"创建会话相关表失败: {e}", exc_info=True)
        if conn:
            conn.rollback()
        return False
        
    finally:
        if should_close_conn and conn:
            from backend.common.functions.conversation.repository import release_connection
            release_connection(conn)


if __name__ == "__main__":
    # 测试脚本
    from backend.common.functions.conversation.repository import get_connection
    
    conn = get_connection()
    success = create_conversation_tables(conn)
    
    if success:
        print("✓ 会话相关表创建成功")
    else:
        print("✗ 会话相关表创建失败")
