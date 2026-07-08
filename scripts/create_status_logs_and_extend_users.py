"""
创建状态日志表并扩展用户表字段

本脚本用于创建用户资料与状态日志系统所需的数据库表结构，包括：
1. status_logs 表 - 存储RAG查询状态日志
2. users 表字段扩展 - 添加个人资料和简历相关字段
3. 相关索引 - 优化查询性能

脚本设计为幂等的，可以重复执行而不会产生错误。

数据来源: docs/superpowers/specs/2026-07-07-user-profile-and-status-log-design.md
"""

import sys
import os

# 将项目根目录添加到 Python 路径，以便导入 config 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from config.database import DatabaseConfig
from utils.logger import logger


def create_status_logs_table(cursor):
    """
    创建状态日志表 (status_logs)

    表结构说明：
    - id: 日志唯一标识符，使用 UUID 自动生成
    - conversation_id: 所属会话ID，外键关联 conversations 表
    - user_id: 用户ID，外键关联 users 表（冗余设计优化查询性能）
    - step_number: 步骤编号（同一会话不能重复）
    - step_name: 步骤名称
    - status: 状态值（running/success/error/miss/low_match/not_implemented）
    - detail: 详细描述
    - created_at: 创建时间

    索引说明：
    - idx_status_logs_user_created: 按用户查询历史日志
    - idx_status_logs_conv_created: 按会话查询日志
    - idx_status_logs_status: 按状态筛选
    - idx_status_logs_created: 按时间范围筛选

    Args:
        cursor: 数据库游标对象
    """
    # 创建 status_logs 表
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS status_logs (
        -- 主键
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

        -- 关联字段（双重外键，优化查询性能）
        conversation_id UUID NOT NULL
            REFERENCES conversations(id) ON DELETE CASCADE,
        user_id UUID NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,

        -- 状态步骤信息
        step_number INTEGER NOT NULL,
        step_name VARCHAR(100) NOT NULL,
        status VARCHAR(20) NOT NULL CHECK (status IN ('running', 'success', 'error', 'miss', 'low_match', 'not_implemented')),
        detail TEXT,

        -- 时间戳
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),

        -- 约束：同一会话同一步骤不能重复
        CONSTRAINT unique_conv_step UNIQUE (conversation_id, step_number)
    );
    """

    cursor.execute(create_table_sql)
    logger.info("status_logs 表创建成功（或已存在）")

    # 创建索引：按用户查询历史日志（最常用查询）
    create_index_user_sql = """
    CREATE INDEX IF NOT EXISTS idx_status_logs_user_created
    ON status_logs(user_id, created_at DESC);
    """
    cursor.execute(create_index_user_sql)
    logger.info("索引 idx_status_logs_user_created 创建成功（或已存在）")

    # 创建索引：按会话查询日志（会话详情查看）
    create_index_conv_sql = """
    CREATE INDEX IF NOT EXISTS idx_status_logs_conv_created
    ON status_logs(conversation_id, created_at DESC);
    """
    cursor.execute(create_index_conv_sql)
    logger.info("索引 idx_status_logs_conv_created 创建成功（或已存在）")

    # 创建索引：按状态筛选（性能分析）
    create_index_status_sql = """
    CREATE INDEX IF NOT EXISTS idx_status_logs_status
    ON status_logs(status);
    """
    cursor.execute(create_index_status_sql)
    logger.info("索引 idx_status_logs_status 创建成功（或已存在）")

    # 创建索引：按时间范围筛选（日志清理、统计）
    create_index_time_sql = """
    CREATE INDEX IF NOT EXISTS idx_status_logs_created
    ON status_logs(created_at DESC);
    """
    cursor.execute(create_index_time_sql)
    logger.info("索引 idx_status_logs_created 创建成功（或已存在）")


def extend_users_table(cursor):
    """
    扩展 users 表字段（个人资料和简历相关）

    新增字段说明：
    - nickname: 用户昵称
    - occupation: 职业
    - interest_areas: 关注领域（TEXT存储JSON数组）
    - profile_enabled: 是否启用个性化注入
    - resume_file_path: 简历文件路径
    - resume_parsed_data: 简历解析数据（TEXT存储JSON）
    - resume_summary: 简历摘要
    - updated_at: 更新时间（已存在，确保更新触发）

    Args:
        cursor: 数据库游标对象
    """
    # 检查并添加 nickname 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'nickname'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN nickname VARCHAR(50)
        """)
        logger.info("users 表添加 nickname 字段成功")
    else:
        logger.info("users 表已存在 nickname 字段，跳过")

    # 检查并添加 occupation 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'occupation'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN occupation VARCHAR(100)
        """)
        logger.info("users 表添加 occupation 字段成功")
    else:
        logger.info("users 表已存在 occupation 字段，跳过")

    # 检查并添加 interest_areas 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'interest_areas'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN interest_areas TEXT
        """)
        logger.info("users 表添加 interest_areas 字段成功")
    else:
        logger.info("users 表已存在 interest_areas 字段，跳过")

    # 检查并添加 profile_enabled 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'profile_enabled'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN profile_enabled BOOLEAN DEFAULT FALSE
        """)
        logger.info("users 表添加 profile_enabled 字段成功")
    else:
        logger.info("users 表已存在 profile_enabled 字段，跳过")

    # 检查并添加 resume_file_path 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'resume_file_path'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN resume_file_path VARCHAR(200)
        """)
        logger.info("users 表添加 resume_file_path 字段成功")
    else:
        logger.info("users 表已存在 resume_file_path 字段，跳过")

    # 检查并添加 resume_parsed_data 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'resume_parsed_data'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN resume_parsed_data TEXT
        """)
        logger.info("users 表添加 resume_parsed_data 字段成功")
    else:
        logger.info("users 表已存在 resume_parsed_data 字段，跳过")

    # 检查并添加 resume_summary 字段
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'resume_summary'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE users ADD COLUMN resume_summary TEXT
        """)
        logger.info("users 表添加 resume_summary 字段成功")
    else:
        logger.info("users 表已存在 resume_summary 字段，跳过")


def create_database_migration():
    """
    执行数据库迁移：创建表和扩展字段

    执行流程：
    1. 从 DatabaseConfig 读取数据库连接配置
    2. 连接到 PostgreSQL 数据库
    3. 创建 status_logs 表及相关索引
    4. 扩展 users 表字段
    5. 提交事务并关闭连接

    Returns:
        bool: 创建成功返回 True，失败返回 False
    """
    connection = None

    try:
        # 验证数据库配置
        if not DatabaseConfig.validate():
            logger.error("数据库配置验证失败")
            return False

        # 获取数据库连接参数
        conn_params = DatabaseConfig.get_connection_params()
        logger.info(f"正在连接数据库: {conn_params['host']}:{conn_params['port']}/{conn_params['database']}")

        # 建立数据库连接
        connection = psycopg2.connect(**conn_params)
        cursor = connection.cursor()

        logger.info("=" * 60)
        logger.info("开始执行数据库迁移")
        logger.info("=" * 60)

        # 步骤1: 创建 status_logs 表及索引
        create_status_logs_table(cursor)

        # 步骤2: 扩展 users 表字段
        extend_users_table(cursor)

        # 提交事务
        connection.commit()

        logger.info("=" * 60)
        logger.info("数据库迁移完成！")
        logger.info("=" * 60)

        # 关闭游标
        cursor.close()

        return True

    except psycopg2.Error as e:
        logger.error(f"数据库操作错误: {e}")
        if connection:
            connection.rollback()
        return False

    except Exception as e:
        logger.error(f"迁移过程中发生未知错误: {e}")
        if connection:
            connection.rollback()
        return False

    finally:
        # 确保数据库连接被正确关闭
        if connection:
            connection.close()
            logger.info("数据库连接已关闭")


def verify_table_structure():
    """
    验证表结构是否创建成功

    Returns:
        bool: 验证成功返回 True，失败返回 False
    """
    connection = None

    try:
        # 获取数据库连接参数
        conn_params = DatabaseConfig.get_connection_params()
        connection = psycopg2.connect(**conn_params)
        cursor = connection.cursor()

        logger.info("=" * 60)
        logger.info("开始验证表结构")
        logger.info("=" * 60)

        # 验证 status_logs 表
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'status_logs'
            ORDER BY ordinal_position
        """)
        status_logs_columns = cursor.fetchall()
        logger.info(f"status_logs 表字段数: {len(status_logs_columns)}")
        for col in status_logs_columns:
            logger.info(f"  - {col[0]} ({col[1]})")

        # 验证 status_logs 索引
        cursor.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'status_logs'
        """)
        status_logs_indexes = cursor.fetchall()
        logger.info(f"status_logs 表索引数: {len(status_logs_indexes)}")
        for idx in status_logs_indexes:
            logger.info(f"  - {idx[0]}")

        # 验证 users 表扩展字段
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'users'
              AND column_name IN ('nickname', 'occupation', 'interest_areas', 'profile_enabled',
                                   'resume_file_path', 'resume_parsed_data', 'resume_summary')
            ORDER BY column_name
        """)
        users_new_columns = cursor.fetchall()
        logger.info(f"users 表新增字段数: {len(users_new_columns)}")
        for col in users_new_columns:
            logger.info(f"  - {col[0]} ({col[1]})")

        # 关闭游标
        cursor.close()

        logger.info("=" * 60)
        logger.info("表结构验证完成！")
        logger.info("=" * 60)

        return True

    except psycopg2.Error as e:
        logger.error(f"验证过程中数据库错误: {e}")
        return False

    except Exception as e:
        logger.error(f"验证过程中发生未知错误: {e}")
        return False

    finally:
        if connection:
            connection.close()
            logger.info("数据库连接已关闭")


if __name__ == "__main__":
    """
    脚本入口点

    直接运行此脚本将执行数据库迁移并验证表结构。
    脚本是幂等的，可以安全地重复执行。
    """
    print("=" * 60)
    print("状态日志与用户资料数据库迁移脚本")
    print("=" * 60)
    print(f"数据库主机: {DatabaseConfig.DB_HOST}")
    print(f"数据库端口: {DatabaseConfig.DB_PORT}")
    print(f"数据库名称: {DatabaseConfig.DB_NAME}")
    print(f"数据库用户: {DatabaseConfig.DB_USER}")
    print("=" * 60)

    # 执行迁移操作
    success = create_database_migration()

    if success:
        print("\n✓ 数据库迁移成功！")

        # 验证表结构
        print("\n正在验证表结构...")
        verify_success = verify_table_structure()

        if verify_success:
            print("\n✓ 表结构验证成功！")
            sys.exit(0)
        else:
            print("\n✗ 表结构验证失败，请检查日志获取详细信息。")
            sys.exit(1)
    else:
        print("\n✗ 数据库迁移失败，请检查日志获取详细信息。")
        sys.exit(1)