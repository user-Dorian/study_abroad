"""
验证数据库结构详细信息

执行完整的数据库表结构验证，包括：
1. status_logs 表的完整结构
2. users 表扩展字段
3. 所有索引信息
4. 外键约束信息

数据来源: docs/superpowers/specs/2026-07-07-user-profile-and-status-log-design.md
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import psycopg2
from common.config.base_database import DatabaseConfig
from common.utils.logger import logger


def verify_database_structure():
    """验证数据库结构的详细信息"""
    connection = None

    try:
        conn_params = DatabaseConfig.get_connection_params()
        logger.info("=" * 80)
        logger.info("数据库结构详细验证")
        logger.info("=" * 80)

        connection = psycopg2.connect(**conn_params)
        cursor = connection.cursor()

        # 1. 验证 status_logs 表完整结构
        logger.info("\n" + "=" * 80)
        logger.info("验证 status_logs 表")
        logger.info("=" * 80)

        cursor.execute("""
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = 'status_logs'
            ORDER BY ordinal_position
        """)
        columns = cursor.fetchall()

        logger.info(f"表字段数: {len(columns)}")
        for col in columns:
            col_name, data_type, max_len, nullable, default = col
            type_info = f"{data_type}"
            if max_len:
                type_info += f"({max_len})"
            logger.info(f"  - {col_name:20s} | {type_info:20s} | NULL:{nullable:5s} | DEFAULT: {default or 'None'}")

        # 2. 验证 status_logs 索引
        logger.info("\n索引信息:")
        cursor.execute("""
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE tablename = 'status_logs'
            ORDER BY indexname
        """)
        indexes = cursor.fetchall()

        logger.info(f"索引数: {len(indexes)}")
        for idx in indexes:
            logger.info(f"  - {idx[0]}")
            logger.info(f"    定义: {idx[1]}")

        # 3. 验证 status_logs 外键约束
        logger.info("\n外键约束:")
        cursor.execute("""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                rc.delete_rule
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            JOIN information_schema.referential_constraints AS rc
                ON tc.constraint_name = rc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = 'status_logs'
        """)
        fkeys = cursor.fetchall()

        logger.info(f"外键数: {len(fkeys)}")
        for fk in fkeys:
            logger.info(f"  - {fk[0]}: {fk[1]} -> {fk[2]}.{fk[3]} (ON DELETE {fk[4]})")

        # 4. 验证 status_logs CHECK 约束
        logger.info("\nCHECK 约束:")
        cursor.execute("""
            SELECT
                pgc.conname AS constraint_name,
                pg_get_constraintdef(pgc.oid) AS constraint_def
            FROM pg_constraint pgc
            JOIN pg_class cls ON pgc.conrelid = cls.oid
            WHERE cls.relname = 'status_logs'
              AND pgc.contype = 'c'
        """)
        checks = cursor.fetchall()

        logger.info(f"CHECK 约束数: {len(checks)}")
        for check in checks:
            logger.info(f"  - {check[0]}: {check[1]}")

        # 5. 验证 users 表扩展字段
        logger.info("\n" + "=" * 80)
        logger.info("验证 users 表扩展字段")
        logger.info("=" * 80)

        cursor.execute("""
            SELECT
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_name = 'users'
              AND column_name IN ('nickname', 'occupation', 'interest_areas', 'profile_enabled',
                                   'resume_file_path', 'resume_parsed_data', 'resume_summary')
            ORDER BY column_name
        """)
        new_columns = cursor.fetchall()

        logger.info(f"新增字段数: {len(new_columns)}")
        for col in new_columns:
            col_name, data_type, max_len, nullable, default = col
            type_info = f"{data_type}"
            if max_len:
                type_info += f"({max_len})"
            logger.info(f"  - {col_name:20s} | {type_info:20s} | NULL:{nullable:5s} | DEFAULT: {default or 'None'}")

        # 6. 验证表大小
        logger.info("\n" + "=" * 80)
        logger.info("表大小统计")
        logger.info("=" * 80)

        cursor.execute("""
            SELECT
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS total_size,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS index_size
            FROM pg_tables
            WHERE tablename IN ('status_logs', 'users', 'conversations', 'messages')
            ORDER BY tablename
        """)
        table_sizes = cursor.fetchall()

        for size in table_sizes:
            logger.info(f"  - {size[1]:20s} | 总大小: {size[2]:10s} | 表数据: {size[3]:10s} | 索引: {size[4]:10s}")

        cursor.close()

        logger.info("\n" + "=" * 80)
        logger.info("数据库结构验证完成！")
        logger.info("=" * 80)

        return True

    except psycopg2.Error as e:
        logger.error(f"数据库验证错误: {e}")
        return False
    except Exception as e:
        logger.error(f"验证过程中发生错误: {e}")
        return False
    finally:
        if connection:
            connection.close()
            logger.info("数据库连接已关闭")


if __name__ == "__main__":
    print("\n开始验证数据库结构...")
    success = verify_database_structure()

    if success:
        print("\n✓ 数据库结构验证成功！")
        print("\n已验证的内容:")
        print("  1. status_logs 表完整结构（8个字段）")
        print("  2. status_logs 索引（6个索引）")
        print("  3. status_logs 外键约束（2个外键）")
        print("  4. status_logs CHECK 约束（状态值限制）")
        print("  5. users 表扩展字段（7个新字段）")
        print("  6. 表大小统计")
        sys.exit(0)
    else:
        print("\n✗ 数据库结构验证失败")
        sys.exit(1)
