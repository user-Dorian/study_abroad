"""测试Docker环境管理器"""
import sys
sys.path.insert(0, "d:\\Heima\\AI-31期-就业班\\小组项目\\RAG")

from utils.docker_env_manager import DockerEnvManager

print("=== 测试Docker环境管理器 ===")
manager = DockerEnvManager()
print(f"Docker可用: {manager.docker_available}")

ok, free_gb = manager.check_disk_space()
print(f"磁盘空间: {free_gb:.1f}GB, 充足: {ok}")

# 测试Redis
print("\n=== 测试Redis ===")
success, msg = manager.ensure_redis("localhost", 6379, "1234")
print(f"Redis: {success} - {msg}")

# 测试PostgreSQL
print("\n=== 测试PostgreSQL ===")
success, msg = manager.ensure_postgres("localhost", 5433, "eduagent_user", "123456", "studyabroad")
print(f"PostgreSQL: {success} - {msg}")

# 测试Milvus
print("\n=== 测试Milvus ===")
success, msg = manager.ensure_milvus("localhost", 19530)
print(f"Milvus: {success} - {msg}")

print("\n测试完成！")