"""
测试数据清理脚本

【功能】
- 删除客户端和服务端的所有用户(以及相关数据)
- 保留白名单用户(用户自己注册的测试账号)

【数据来源】
配置: 用户提供的 username 白名单,默认保留 ['admin', 'planner1']

【安全机制】
- 优先 dry-run 模式,只显示不删除
- 必须显式 --confirm 才会执行
- 删除前打印影响范围
- 全部走事务,失败回滚

【用法】
  # 仅预览(默认)
  python common/scripts/cleanup_test_users.py

  # 实际删除(必须确认)
  python common/scripts/cleanup_test_users.py --confirm
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

import psycopg2
import argparse
from common.config.base_database import DatabaseConfig
from common.utils.logger import logger


# 白名单 - 不删除这些用户
WHITELIST_USERNAMES = {
    "admin",  # 管理员
    "planner1",  # 用户自己注册的规划师
    # 可添加其他需要保留的账号
}


def get_all_users(cursor, include_deleted=False):
    """获取所有用户"""
    if include_deleted:
        cursor.execute(
            "SELECT id, username, role, is_deleted, deleted_at FROM users ORDER BY created_at"
        )
    else:
        cursor.execute(
            "SELECT id, username, role, is_deleted, deleted_at FROM users WHERE is_deleted = FALSE ORDER BY created_at"
        )
    return cursor.fetchall()


def get_user_related_data_counts(cursor, user_ids):
    """获取用户相关数据统计"""
    counts = {}
    for table, col in [
        ("user_profiles", "user_id"),
        ("conversations", "user_id"),
        ("friend_requests", "sender_id"),
        ("friend_requests", "receiver_id"),
        ("friendships", "user_id"),
        ("friendships", "friend_id"),
        ("messages", "sender_id"),
        ("unread_messages", "user_id"),
        ("account_deletion_log", "user_id"),
        ("profile_change_log", "user_id"),
    ]:
        try:
            cursor.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ANY(%s::uuid[])",
                (list(user_ids),)
            )
            counts[table] = cursor.fetchone()[0]
        except Exception as e:
            counts[table] = f"err: {e}"
            # 一次失败的查询会让整个事务处于 aborted 状态，需要 ROLLBACK 才能继续
            try:
                connection.rollback()
            except Exception:
                pass
    return counts


def delete_user_data(cursor, user_ids):
    """删除用户相关数据(多表级联)"""
    user_id_list = list(user_ids)
    deleted_counts = {}

    # 1. 删除 profile_change_log
    cursor.execute(
        "DELETE FROM profile_change_log WHERE user_id = ANY(%s::uuid[])",
        (user_id_list,)
    )
    deleted_counts["profile_change_log"] = cursor.rowcount

    # 2. 删除 account_deletion_log
    cursor.execute(
        "DELETE FROM account_deletion_log WHERE user_id = ANY(%s::uuid[])",
        (user_id_list,)
    )
    deleted_counts["account_deletion_log"] = cursor.rowcount

    # 3. 删除 unread_messages
    cursor.execute(
        "DELETE FROM unread_messages WHERE user_id = ANY(%s::uuid[])",
        (user_id_list,)
    )
    deleted_counts["unread_messages"] = cursor.rowcount

    # 4. 删除消息
    cursor.execute(
        "DELETE FROM messages WHERE sender_id = ANY(%s::uuid[])",
        (user_id_list,)
    )
    deleted_counts["messages"] = cursor.rowcount

    # 5. 删除对话
    cursor.execute(
        "DELETE FROM conversations WHERE user_id = ANY(%s::uuid[]) OR other_user_id = ANY(%s::uuid[])",
        (user_id_list, user_id_list)
    )
    deleted_counts["conversations"] = cursor.rowcount

    # 6. 删除好友请求
    cursor.execute(
        "DELETE FROM friend_requests WHERE sender_id = ANY(%s::uuid[]) OR receiver_id = ANY(%s::uuid[])",
        (user_id_list, user_id_list)
    )
    deleted_counts["friend_requests"] = cursor.rowcount

    # 7. 删除好友关系
    cursor.execute(
        "DELETE FROM friendships WHERE user_id = ANY(%s::uuid[]) OR friend_id = ANY(%s::uuid[])",
        (user_id_list, user_id_list)
    )
    deleted_counts["friendships"] = cursor.rowcount

    # 8. 删除 user_profiles
    cursor.execute(
        "DELETE FROM user_profiles WHERE user_id = ANY(%s::uuid[])",
        (user_id_list,)
    )
    deleted_counts["user_profiles"] = cursor.rowcount

    # 9. 删除 users 表
    cursor.execute(
        "DELETE FROM users WHERE id = ANY(%s::uuid[])",
        (user_id_list,)
    )
    deleted_counts["users"] = cursor.rowcount

    return deleted_counts


def run_cleanup(confirm=False, dry_run=True, include_whitelist=False):
    """
    执行清理

    Args:
        confirm: 是否确认执行(必须为True才执行)
        dry_run: 仅预览不删除
        include_whitelist: 是否也删除白名单用户
    """
    connection = None
    try:
        if not DatabaseConfig.validate():
            logger.error("数据库配置验证失败")
            return False

        conn_params = DatabaseConfig.get_connection_params()
        connection = psycopg2.connect(**conn_params)
        cursor = connection.cursor()

        logger.info("=" * 60)
        logger.info("测试数据清理脚本")
        logger.info("=" * 60)

        # 1. 列出所有用户
        all_users = get_all_users(cursor, include_deleted=False)
        logger.info(f"\n当前用户总数: {len(all_users)}")

        # 2. 筛选要删除的用户
        users_to_delete = []
        users_to_keep = []
        for user in all_users:
            user_id, username, role, is_deleted, deleted_at = user
            if username in WHITELIST_USERNAMES and not include_whitelist:
                users_to_keep.append(user)
            else:
                users_to_delete.append(user)

        logger.info(f"  保留(白名单): {len(users_to_keep)} 个")
        for u in users_to_keep:
            logger.info(f"    - {u[1]} (role={u[2]})")

        logger.info(f"  将删除: {len(users_to_delete)} 个")
        for u in users_to_delete:
            logger.info(f"    - {u[1]} (role={u[2]})")

        if not users_to_delete:
            logger.info("\n[√] 没有需要删除的用户,退出")
            cursor.close()
            return True

        # 3. 统计影响范围
        user_ids = [str(u[0]) for u in users_to_delete]
        logger.info(f"\n数据影响范围统计:")
        counts = get_user_related_data_counts(cursor, user_ids)
        for table, count in counts.items():
            logger.info(f"  {table}: {count}")

        if dry_run:
            logger.info("\n[!] DRY-RUN 模式:未实际删除")
            logger.info("    要执行删除,请使用 --confirm 参数")
            cursor.close()
            return True

        # 4. 实际删除
        if not confirm:
            logger.error("\n[×] 必须显式 --confirm 才执行删除")
            cursor.close()
            return False

        # 再次提示
        logger.info(f"\n[!] 即将删除 {len(users_to_delete)} 个用户及其所有相关数据")
        logger.info("    5秒后开始执行...")
        import time
        time.sleep(2)

        logger.info("\n开始删除...")
        deleted_counts = delete_user_data(cursor, user_ids)

        connection.commit()

        logger.info("\n" + "=" * 60)
        logger.info("删除完成!")
        logger.info("=" * 60)
        for table, count in deleted_counts.items():
            logger.info(f"  {table}: 删除了 {count} 条")
        logger.info("=" * 60)

        cursor.close()
        return True

    except Exception as e:
        logger.error(f"清理失败: {e}")
        if connection:
            connection.rollback()
        return False
    finally:
        if connection:
            connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试数据清理脚本")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认执行删除(不传则dry-run)",
    )
    parser.add_argument(
        "--include-whitelist",
        action="store_true",
        help="也删除白名单用户(谨慎使用)",
    )

    args = parser.parse_args()

    success = run_cleanup(
        confirm=args.confirm,
        dry_run=not args.confirm,
        include_whitelist=args.include_whitelist,
    )
    sys.exit(0 if success else 1)
