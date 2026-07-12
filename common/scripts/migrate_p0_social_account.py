"""
迁移脚本: P0核心功能数据库迁移

【职责】
1. 在 users 表添加 is_deleted / deleted_at / deletion_deadline 软删除字段
2. 在 user_profiles 表添加 profile_completeness / required_fields_missing 字段
3. 在 friend_requests 表添加 source / expires_at 字段
4. 新建 account_deletion_log 表(账户注销审计)
5. 新建 profile_change_log 表(资料变更审计)

【幂等性】
所有 DDL 均使用 IF NOT EXISTS,可重复执行不会产生错误

【数据来源】
设计方案: 架构师 P0 方案(v1.0)
- 软删除策略: 30 天可恢复
- 资料完整度: 用于前端引导
- 审计日志: 全部敏感操作记录
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

import psycopg2
from common.config.base_database import DatabaseConfig
from common.utils.logger import logger


def column_exists(cursor, table_name, column_name):
    """检查表中某列是否存在"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        )
    """, (table_name, column_name))
    return cursor.fetchone()[0]


def table_exists(cursor, table_name):
    """检查表是否存在"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = %s
        )
    """, (table_name,))
    return cursor.fetchone()[0]


def index_exists(cursor, index_name):
    """检查索引是否存在"""
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM pg_indexes WHERE indexname = %s
        )
    """, (index_name,))
    return cursor.fetchone()[0]


def add_column_if_not_exists(cursor, table_name, column_name, column_def):
    """如果列不存在则添加(幂等)"""
    if column_exists(cursor, table_name, column_name):
        logger.info(f"{table_name}.{column_name} 已存在,跳过")
        return
    cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}')
    logger.info(f"添加列: {table_name}.{column_name}")


def create_index_if_not_exists(cursor, index_name, table_name, columns):
    """如果索引不存在则创建(幂等)"""
    if index_exists(cursor, index_name):
        logger.info(f"索引 {index_name} 已存在,跳过")
        return
    cursor.execute(f'CREATE INDEX {index_name} ON {table_name}({columns})')
    logger.info(f"创建索引: {index_name}")


def extend_users_table(cursor):
    """扩展 users 表(软删除字段)"""
    logger.info("--- 扩展 users 表 ---")
    add_column_if_not_exists(cursor, "users", "is_deleted", "BOOLEAN DEFAULT FALSE")
    add_column_if_not_exists(cursor, "users", "deleted_at", "TIMESTAMP")
    add_column_if_not_exists(cursor, "users", "deletion_deadline", "TIMESTAMP")
    create_index_if_not_exists(cursor, "idx_users_is_deleted", "users", "is_deleted")


def extend_user_profiles_table(cursor):
    """扩展 user_profiles 表(资料完整度)"""
    logger.info("--- 扩展 user_profiles 表 ---")
    add_column_if_not_exists(cursor, "user_profiles", "profile_completeness", "SMALLINT DEFAULT 0")
    add_column_if_not_exists(cursor, "user_profiles", "required_fields_missing", "TEXT[] DEFAULT '{}'")
    add_column_if_not_exists(cursor, "user_profiles", "is_deleted", "BOOLEAN DEFAULT FALSE")
    add_column_if_not_exists(cursor, "user_profiles", "deleted_at", "TIMESTAMP")


def extend_friend_requests_table(cursor):
    """扩展 friend_requests 表(申请来源)"""
    logger.info("--- 扩展 friend_requests 表 ---")
    add_column_if_not_exists(cursor, "friend_requests", "source", "VARCHAR(20) DEFAULT 'search'")
    add_column_if_not_exists(cursor, "friend_requests", "expires_at", "TIMESTAMP")


def create_account_deletion_log_table(cursor):
    """创建账户注销审计表"""
    logger.info("--- 创建 account_deletion_log 表 ---")
    if table_exists(cursor, "account_deletion_log"):
        logger.info("account_deletion_log 表已存在,跳过")
        return

    cursor.execute("""
        CREATE TABLE account_deletion_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            deletion_type VARCHAR(20) NOT NULL CHECK (deletion_type IN ('soft', 'hard')),
            reason TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'restored', 'completed')),
            restore_deadline TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    logger.info("account_deletion_log 表创建成功")

    create_index_if_not_exists(
        cursor, "idx_account_deletion_log_user",
        "account_deletion_log", "user_id, status"
    )


def create_profile_change_log_table(cursor):
    """创建资料变更审计表"""
    logger.info("--- 创建 profile_change_log 表 ---")
    if table_exists(cursor, "profile_change_log"):
        logger.info("profile_change_log 表已存在,跳过")
        return

    cursor.execute("""
        CREATE TABLE profile_change_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            field_name VARCHAR(50) NOT NULL,
            old_value TEXT,
            new_value TEXT,
            change_source VARCHAR(20) NOT NULL
                CHECK (change_source IN ('user', 'agent', 'admin', 'import')),
            agent_conversation_id UUID,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    logger.info("profile_change_log 表创建成功")

    create_index_if_not_exists(
        cursor, "idx_profile_change_log_user",
        "profile_change_log", "user_id, created_at DESC"
    )


def run_migration():
    """执行迁移"""
    connection = None

    try:
        if not DatabaseConfig.validate():
            logger.error("数据库配置验证失败")
            return False

        conn_params = DatabaseConfig.get_connection_params()
        connection = psycopg2.connect(**conn_params)
        cursor = connection.cursor()

        logger.info("=" * 60)
        logger.info("开始执行 P0 核心功能迁移")
        logger.info("=" * 60)

        # 步骤1: 扩展 users 表
        logger.info("\n[1/5] 扩展 users 表(软删除字段)")
        extend_users_table(cursor)

        # 步骤2: 扩展 user_profiles 表
        logger.info("\n[2/5] 扩展 user_profiles 表(完整度字段)")
        extend_user_profiles_table(cursor)

        # 步骤3: 扩展 friend_requests 表
        logger.info("\n[3/5] 扩展 friend_requests 表(申请来源)")
        extend_friend_requests_table(cursor)

        # 步骤4: 创建账户注销审计表
        logger.info("\n[4/5] 创建 account_deletion_log 表")
        create_account_deletion_log_table(cursor)

        # 步骤5: 创建资料变更审计表
        logger.info("\n[5/5] 创建 profile_change_log 表")
        create_profile_change_log_table(cursor)

        connection.commit()

        logger.info("\n" + "=" * 60)
        logger.info("P0 核心功能迁移完成!")
        logger.info("=" * 60)
        logger.info("\n变更摘要:")
        logger.info("  - users: 新增 is_deleted / deleted_at / deletion_deadline")
        logger.info("  - user_profiles: 新增 profile_completeness / required_fields_missing / is_deleted")
        logger.info("  - friend_requests: 新增 source / expires_at")
        logger.info("  - 新表 account_deletion_log: 账户注销审计")
        logger.info("  - 新表 profile_change_log: 资料变更审计")
        logger.info("=" * 60)

        cursor.close()
        return True

    except Exception as e:
        logger.error(f"迁移失败: {e}")
        if connection:
            connection.rollback()
        return False
    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
