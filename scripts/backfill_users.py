"""回填 enterprise_users 到 users 表（满足 conversations 外键约束）"""
import psycopg2

conn = psycopg2.connect(
    host='localhost', port=5433,
    user='eduagent_user', password='123456',
    database='studyabroad'
)
cur = conn.cursor()

# 获取所有企业用户
cur.execute('SELECT id, username, email, password_hash, role FROM enterprise_users')
enterprise_users = cur.fetchall()
print(f'Found {len(enterprise_users)} enterprise users')

for eu in enterprise_users:
    eu_id, eu_username, eu_email, eu_pwd_hash, eu_role = eu
    # 检查是否已存在于 users 表（相同ID）
    cur.execute('SELECT id FROM users WHERE id = %s', (eu_id,))
    if cur.fetchone():
        print(f'  [skip] User {eu_username} (id={eu_id}) already exists in users table')
        continue

    # 检查用户名是否冲突
    cur.execute('SELECT id, username FROM users WHERE username = %s', (eu_username,))
    conflict = cur.fetchone()
    if conflict:
        conflict_id, conflict_username = conflict
        print(f'  [conflict] Username "{eu_username}" already used by user {conflict_id}')
        # 使用 "username_enterprise" 作为 users 表的用户名
        new_username = f'{eu_username}_enterprise'
        cur.execute(
            """INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
               ON CONFLICT (id) DO NOTHING""",
            (eu_id, new_username, eu_email or '', eu_pwd_hash, eu_role or 'consultant')
        )
        conn.commit()
        print(f'  [insert] Inserted as {new_username}')
    else:
        # 插入新记录
        cur.execute(
            """INSERT INTO users (id, username, email, password_hash, role, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
               ON CONFLICT (id) DO NOTHING""",
            (eu_id, eu_username, eu_email or '', eu_pwd_hash, eu_role or 'consultant')
        )
        conn.commit()
        print(f'  [insert] Inserted enterprise user {eu_username}')

# 验证
cur.execute('SELECT id, username, role FROM users ORDER BY created_at DESC LIMIT 10')
print('\nCurrent users table (last 10):')
for r in cur.fetchall():
    print(f'  {r[0]} | {r[1]} | {r[2]}')

cur.execute('SELECT id, username FROM enterprise_users')
print('\nEnterprise users:')
for r in cur.fetchall():
    print(f'  {r[0]} | {r[1]}')

conn.close()
print('\nDone!')