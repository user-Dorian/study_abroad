"""创建设置相关数据库表

包含：
- user_settings: 用户设置表（通知、隐私、外观设置等）
- login_history: 登录历史表
"""
import asyncio
import psycopg2
from psycopg2.extensions import connection as PGConnection
from backend.common.basics.utils.logger import logger


def _create_settings_tables_sync(conn: PGConnection = None) -> bool:
    """创建设置相关表（同步版本）
    
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
        
        # 创建用户设置表
        logger.info("创建 user_settings 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id VARCHAR(36) PRIMARY KEY,
                -- 通知设置
                notification_enabled BOOLEAN DEFAULT TRUE,
                email_notification BOOLEAN DEFAULT TRUE,
                push_notification BOOLEAN DEFAULT TRUE,
                message_preview BOOLEAN DEFAULT TRUE,
                -- 隐私设置
                profile_visible BOOLEAN DEFAULT TRUE,
                online_status_visible BOOLEAN DEFAULT TRUE,
                last_seen_visible BOOLEAN DEFAULT TRUE,
                -- 外观设置
                theme VARCHAR(20) DEFAULT 'light',
                language VARCHAR(10) DEFAULT 'zh-CN',
                font_size VARCHAR(20) DEFAULT 'medium',
                -- 其他设置
                timezone VARCHAR(50),
                currency VARCHAR(10),
                -- 元数据
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 创建登录历史表
        logger.info("创建 login_history 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_history (
                login_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                ip_address VARCHAR(45) NOT NULL,
                user_agent TEXT,
                login_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) DEFAULT 'success',
                CONSTRAINT fk_login_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # 创建索引
        logger.info("创建索引...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_login_history_user_id 
            ON login_history(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_login_history_login_at 
            ON login_history(login_at DESC)
        """)
        
        conn.commit()
        cursor.close()
        
        logger.info("设置相关表创建成功")
        return True
        
    except Exception as e:
        logger.error(f"创建设置相关表失败: {e}", exc_info=True)
        if conn:
            conn.rollback()
        return False
        
    finally:
        if should_close_conn and conn:
            from backend.common.functions.conversation.repository import release_connection
            release_connection(conn)


async def create_settings_tables(conn=None) -> bool:
    """创建设置相关表（异步版本，用于 asyncio.run 调用）
    
    Args:
        conn: 数据库连接对象（兼容参数）
        
    Returns:
        bool: 创建成功返回True，失败返回False
    """
    # 在异步上下文中运行同步的数据库操作
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _create_settings_tables_sync, conn)


if __name__ == "__main__":
    # 测试脚本
    from backend.common.functions.conversation.repository import get_connection
    
    conn = get_connection()
    success = create_settings_tables(conn)
    
    if success:
        print("✓ 设置相关表创建成功")
    else:
        print("✗ 设置相关表创建失败")
