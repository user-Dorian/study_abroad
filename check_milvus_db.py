"""检查Milvus数据库状态"""
from pymilvus import MilvusClient, connections, utility

# 连接到Milvus
client = MilvusClient(uri="http://localhost:19530")

# 列出所有数据库
databases = client.list_databases()
print(f"Milvus数据库列表: {databases}")

# 检查每个数据库中的集合
for db_name in databases:
    print(f"\n=== 数据库: {db_name} ===")
    # 切换到该数据库
    client.using_database(db_name)
    
    # 使用旧API获取集合列表
    connections.connect(
        alias="default",
        host="localhost",
        port="19530",
        db_name=db_name
    )
    
    collections = utility.list_collections()
    print(f"集合列表: {collections}")
    
    # 显示每个集合的记录数
    for coll_name in collections:
        try:
            from pymilvus import Collection
            coll = Collection(coll_name)
            count = coll.num_entities
            print(f"  - {coll_name}: {count} 条记录")
        except Exception as e:
            print(f"  - {coll_name}: 无法获取记录数 ({e})")

print("\n" + "="*60)
print("检查完成")
