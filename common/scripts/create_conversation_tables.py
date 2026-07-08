"""
创建对话管理相关的数据库表

本脚本用于创建对话系统所需的数据库表结构，包括：
1. conversations 表 - 存储对话会话信息
2. messages 表 - 存储对话消息详情
3. 相关索引 - 优化查询性能

脚本设计为幂等的，可以重复执行而不会产生错误。
"""

import sys
import os

# 将项目根目录添加到 Python 路径，以便导入 config 模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
from common.config.base_database import DatabaseConfig
from common.utils.logger import logger


def create_users_table(cursor):
    """
    创建用户表 (users)

    表结构说明：
    - id: 用户唯一标识符，使用 UUID 自动生成
    - username: 用户名，唯一
    - password_hash: bcrypt 密码哈希
    - email: 邮箱（可选）
    - display_name: 显示名称
    - created_at: 创建时间
    - updated_at: 更新时间

    Args:
        cursor: 数据库游标对象
    """
    create_users_sql = """
    CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(100),
        display_name VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """
    cursor.execute(create_users_sql)
    logger.info("users 表创建成功（或已存在）")


def add_user_id_to_conversations(cursor):
    """
    为 conversations 表添加 user_id 外键列

    幂等操作：如果列已存在则跳过。

    Args:
        cursor: 数据库游标对象
    """
    # 先检查列是否存在
    cursor.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'conversations' AND column_name = 'user_id'
    """)
    if cursor.fetchone() is None:
        cursor.execute("""
            ALTER TABLE conversations
            ADD COLUMN user_id UUID REFERENCES users(id) ON DELETE CASCADE
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_user_id
            ON conversations(user_id)
        """)
        logger.info("conversations 表添加 user_id 列成功")
    else:
        logger.info("conversations 表已存在 user_id 列，跳过")


def create_conversations_table(cursor):
    """
    创建对话会话表 (conversations)
    
    表结构说明：
    - id: 对话唯一标识符，使用 UUID 自动生成
    - title: 对话标题，默认为 '新对话'
    - created_at: 对话创建时间
    - updated_at: 对话最后更新时间
    
    Args:
        cursor: 数据库游标对象
    """
    # 创建 conversations 表
    # 使用 IF NOT EXISTS 确保脚本幂等性
    create_conversations_sql = """
    CREATE TABLE IF NOT EXISTS conversations (
        -- 对话唯一ID，使用 UUID 自动生成
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        
        -- 对话标题，最大长度200字符，默认为'新对话'
        title VARCHAR(200) NOT NULL DEFAULT '新对话',
        
        -- 对话创建时间，默认为当前时间
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        
        -- 对话最后更新时间，默认为当前时间
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """
    
    cursor.execute(create_conversations_sql)
    logger.info("conversations 表创建成功（或已存在）")


def create_messages_table(cursor):
    """
    创建对话消息表 (messages)
    
    表结构说明：
    - id: 消息唯一标识符，使用 UUID 自动生成
    - conversation_id: 所属对话的ID，外键关联 conversations 表
    - role: 消息角色，只能是 'user'、'assistant' 或 'system'
    - content: 消息内容，文本类型
    - metadata_json: 消息元数据，JSONB 格式存储扩展信息
    - created_at: 消息创建时间
    
    Args:
        cursor: 数据库游标对象
    """
    # 创建 messages 表
    # 使用 IF NOT EXISTS 确保脚本幂等性
    create_messages_sql = """
    CREATE TABLE IF NOT EXISTS messages (
        -- 消息唯一ID，使用 UUID 自动生成
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        
        -- 所属对话ID，外键关联 conversations 表
        -- 使用 ON DELETE CASCADE 确保删除对话时自动删除相关消息
        conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        
        -- 消息角色，限制为 'user'、'assistant' 或 'system'
        role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
        
        -- 消息内容，文本类型
        content TEXT NOT NULL,
        
        -- 消息元数据，使用 JSONB 格式存储灵活的扩展信息
        -- 例如：token数量、处理时间、模型版本等
        metadata_json JSONB,
        
        -- 消息创建时间，默认为当前时间
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    );
    """
    
    cursor.execute(create_messages_sql)
    logger.info("messages 表创建成功（或已存在）")


def create_indexes(cursor):
    """
    创建数据库索引以优化查询性能
    
    索引说明：
    - idx_messages_conv_id: 在 messages 表的 conversation_id 和 created_at 上创建复合索引
      用于优化以下查询场景：
      1. 根据对话ID查询该对话的所有消息
      2. 按时间排序获取对话消息列表
      3. 分页查询对话消息
    
    Args:
        cursor: 数据库游标对象
    """
    # 创建复合索引：conversation_id + created_at
    # 使用 IF NOT EXISTS 确保脚本幂等性
    create_index_sql = """
    CREATE INDEX IF NOT EXISTS idx_messages_conv_id 
    ON messages(conversation_id, created_at);
    """
    
    cursor.execute(create_index_sql)
    logger.info("索引 idx_messages_conv_id 创建成功（或已存在）")


def create_conversation_tables():
    """
    创建对话管理相关的所有数据库表和索引
    
    执行流程：
    1. 从 DatabaseConfig 读取数据库连接配置
    2. 连接到 PostgreSQL 数据库
    3. 创建 conversations 表
    4. 创建 messages 表
    5. 创建相关索引
    6. 提交事务并关闭连接
    
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
        logger.info("开始创建数据库表")
        logger.info("=" * 60)

        # 步骤1: 创建 users 表
        create_users_table(cursor)

        # 步骤2: 为 conversations 表添加 user_id 列（幂等）
        add_user_id_to_conversations(cursor)

        # 步骤3: 创建 conversations 表
        create_conversations_table(cursor)

        # 步骤4: 创建 messages 表
        # 注意：必须在 conversations 表之后创建，因为有外键依赖
        create_messages_table(cursor)

        # 步骤5: 创建索引
        create_indexes(cursor)
        
        # 提交事务
        connection.commit()
        
        logger.info("=" * 60)
        logger.info("所有表和索引创建成功！")
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
        logger.error(f"创建表时发生未知错误: {e}")
        if connection:
            connection.rollback()
        return False
        
    finally:
        # 确保数据库连接被正确关闭
        if connection:
            connection.close()
            logger.info("数据库连接已关闭")


if __name__ == "__main__":
    """
    脚本入口点
    
    直接运行此脚本将创建对话管理相关的所有数据库表和索引。
    脚本是幂等的，可以安全地重复执行。
    """
    print("=" * 60)
    print("对话管理数据库表创建脚本")
    print("=" * 60)
    print(f"数据库主机: {DatabaseConfig.DB_HOST}")
    print(f"数据库端口: {DatabaseConfig.DB_PORT}")
    print(f"数据库名称: {DatabaseConfig.DB_NAME}")
    print(f"数据库用户: {DatabaseConfig.DB_USER}")
    print("=" * 60)
    
    # 执行建表操作
    success = create_conversation_tables()
    
    if success:
        print("\n✓ 数据库表创建成功！")
        sys.exit(0)
    else:
        print("\n✗ 数据库表创建失败，请检查日志获取详细信息。")
        sys.exit(1)
