"""创建 F-1/F-3/F-6 功能相关数据库表

包含：
- application_timeline_events: 申请时间线事件表（F-1功能）
- favorites: 收藏夹表（F-3功能）
- favorite_folders: 收藏文件夹表（F-3功能）
- message_classifications: 消息分类结果表（F-6功能）
"""
import psycopg2
from psycopg2.extensions import connection as PGConnection
from backend.common.basics.utils.logger import logger


def create_f1_f3_f6_tables(conn: PGConnection = None) -> bool:
    """创建 F-1/F-3/F-6 功能相关表
    
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
        
        # ========== F-1: 申请时间线事件表 ==========
        logger.info("创建 application_timeline_events 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS application_timeline_events (
                event_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                event_date TIMESTAMP NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                reminder_enabled BOOLEAN DEFAULT TRUE,
                reminder_days INTEGER DEFAULT 7,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_timeline_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                CONSTRAINT check_event_type CHECK (event_type IN ('application', 'visa', 'test', 'document', 'payment', 'other')),
                CONSTRAINT check_status CHECK (status IN ('pending', 'completed', 'overdue'))
            )
        """)
        
        # ========== F-3: 收藏夹相关表 ==========
        # 收藏文件夹表
        logger.info("创建 favorite_folders 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorite_folders (
                folder_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                item_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_folder_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # 收藏项表
        logger.info("创建 favorites 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                favorite_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                folder_id VARCHAR(36),
                item_type VARCHAR(50) NOT NULL,
                item_id VARCHAR(255) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT,
                tags JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_favorite_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                CONSTRAINT fk_favorite_folder FOREIGN KEY (folder_id) REFERENCES favorite_folders(folder_id) ON DELETE SET NULL,
                CONSTRAINT check_item_type CHECK (item_type IN ('school', 'major', 'article', 'qa', 'document')),
                CONSTRAINT unique_user_item UNIQUE (user_id, item_type, item_id)
            )
        """)
        
        # ========== F-6: 消息分类结果表 ==========
        logger.info("创建 message_classifications 表...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_classifications (
                classification_id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                message_id VARCHAR(36),
                content TEXT NOT NULL,
                sender VARCHAR(255),
                category VARCHAR(50) NOT NULL,
                priority INTEGER DEFAULT 4,
                confidence DECIMAL(3,2) DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_classification_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # ========== 创建索引 ==========
        logger.info("创建索引...")
        
        # F-1 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timeline_user_id 
            ON application_timeline_events(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timeline_event_date 
            ON application_timeline_events(event_date)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timeline_status 
            ON application_timeline_events(status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timeline_event_type 
            ON application_timeline_events(event_type)
        """)
        
        # F-3 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_user_id 
            ON favorites(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_item_type 
            ON favorites(item_type)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_favorites_created_at 
            ON favorites(created_at DESC)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_folders_user_id 
            ON favorite_folders(user_id)
        """)
        
        # F-6 索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_classifications_user_id 
            ON message_classifications(user_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_classifications_category 
            ON message_classifications(category)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_classifications_created_at 
            ON message_classifications(created_at DESC)
        """)
        
        conn.commit()
        cursor.close()
        
        logger.info("F-1/F-3/F-6 功能相关表创建成功")
        return True
        
    except Exception as e:
        logger.error(f"创建 F-1/F-3/F-6 功能相关表失败: {e}", exc_info=True)
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
    success = create_f1_f3_f6_tables(conn)
    
    if success:
        print("✓ F-1/F-3/F-6 功能相关表创建成功")
    else:
        print("✗ F-1/F-3/F-6 功能相关表创建失败")
