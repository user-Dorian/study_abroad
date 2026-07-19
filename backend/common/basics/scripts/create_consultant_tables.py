"""创建规划师端功能相关数据库表

包含：
- users表扩展：添加手机验证相关字段
- consultant_client_bindings: 规划师-客户绑定关系表
- ai_generated_reports: AI生成报告表

使用方法:
    conda activate rag_env
    python create_consultant_tables.py
"""
import psycopg2
from psycopg2.extensions import connection as PGConnection
from backend.common.basics.utils.logger import logger


def create_consultant_tables(conn: PGConnection = None) -> bool:
    """创建规划师端功能相关表

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

        # ========== 扩展users表：添加手机验证相关字段 ==========
        logger.info("扩展 users 表：添加手机验证相关字段...")

        # 添加 phone_verified 字段（手机号验证状态）
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'phone_verified'
                ) THEN
                    ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;
                    RAISE NOTICE 'Added phone_verified column';
                END IF;
            END $$;
        """)

        # 添加 phone_bound_at 字段（手机号绑定时间）
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'phone_bound_at'
                ) THEN
                    ALTER TABLE users ADD COLUMN phone_bound_at TIMESTAMP;
                    RAISE NOTICE 'Added phone_bound_at column';
                END IF;
            END $$;
        """)

        # 为 phone 字段创建唯一索引（如果不存在）
        # 注意：只对非空的phone值创建唯一约束
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE tablename = 'users'
                    AND indexname = 'idx_users_phone_unique'
                ) THEN
                    CREATE UNIQUE INDEX idx_users_phone_unique ON users(phone) WHERE phone IS NOT NULL AND phone != '';
                    RAISE NOTICE 'Created unique index on phone column';
                END IF;
            END $$;
        """)

        logger.info("users 表扩展完成")

        # ========== 创建规划师-客户绑定关系表 ==========
        logger.info("创建 consultant_client_bindings 表...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consultant_client_bindings (
                binding_id VARCHAR(36) PRIMARY KEY,
                consultant_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                client_phone VARCHAR(20),
                binding_status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by INTEGER,
                notes TEXT,

                -- 外键约束
                CONSTRAINT fk_binding_consultant FOREIGN KEY (consultant_id)
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_binding_client FOREIGN KEY (client_id)
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_binding_creator FOREIGN KEY (created_by)
                    REFERENCES users(id) ON DELETE SET NULL,

                -- 状态约束
                CONSTRAINT check_binding_status CHECK (binding_status IN ('active', 'inactive', 'dismissed')),

                -- 唯一约束：一个规划师和一个客户之间只能有一条有效绑定
                CONSTRAINT unique_consultant_client UNIQUE (consultant_id, client_id)
            )
        """)

        logger.info("consultant_client_bindings 表创建完成")

        # ========== 创建AI生成报告表 ==========
        logger.info("创建 ai_generated_reports 表...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_generated_reports (
                report_id VARCHAR(36) PRIMARY KEY,
                client_id INTEGER NOT NULL,
                consultant_id INTEGER,
                report_type VARCHAR(50) NOT NULL,
                report_content TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- 外键约束
                CONSTRAINT fk_report_client FOREIGN KEY (client_id)
                    REFERENCES users(id) ON DELETE CASCADE,
                CONSTRAINT fk_report_consultant FOREIGN KEY (consultant_id)
                    REFERENCES users(id) ON DELETE SET NULL,

                -- 报告类型约束
                CONSTRAINT check_report_type CHECK (report_type IN ('background_analysis', 'recommendation', 'profile_summary', 'competitiveness_analysis'))
            )
        """)

        logger.info("ai_generated_reports 表创建完成")

        # ========== 创建索引 ==========
        logger.info("创建索引...")

        # users 表索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_phone_verified
            ON users(phone_verified)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_phone_bound_at
            ON users(phone_bound_at)
        """)

        # consultant_client_bindings 表索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_binding_consultant_id
            ON consultant_client_bindings(consultant_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_binding_client_id
            ON consultant_client_bindings(client_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_binding_status
            ON consultant_client_bindings(binding_status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_binding_created_at
            ON consultant_client_bindings(created_at DESC)
        """)

        # ai_generated_reports 表索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_client_id
            ON ai_generated_reports(client_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_consultant_id
            ON ai_generated_reports(consultant_id)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_type
            ON ai_generated_reports(report_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_generated_at
            ON ai_generated_reports(generated_at DESC)
        """)

        # 复合索引：根据规划师查询客户的报告
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_consultant_client
            ON ai_generated_reports(consultant_id, client_id)
        """)

        conn.commit()
        cursor.close()

        logger.info("✓ 规划师端功能相关表创建成功")
        return True

    except Exception as e:
        logger.error(f"创建规划师端功能相关表失败: {e}", exc_info=True)
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
    success = create_consultant_tables(conn)

    if success:
        print("✓ 规划师端功能相关表创建成功")
        print("\n创建的表：")
        print("  1. users表扩展：")
        print("     - phone_verified: BOOLEAN (手机验证状态)")
        print("     - phone_bound_at: TIMESTAMP (绑定时间)")
        print("     - idx_users_phone_unique: UNIQUE INDEX (手机号唯一索引)")
        print("  2. consultant_client_bindings: 规划师-客户绑定关系表")
        print("  3. ai_generated_reports: AI生成报告表")
    else:
        print("✗ 规划师端功能相关表创建失败")