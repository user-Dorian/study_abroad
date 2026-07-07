"""测试对话历史记忆修复"""
import sys
sys.path.insert(0, ".")

from conversation.config import ConversationConfig
from conversation.manager import ConversationManager

print("=" * 60)
print("测试1: 模块导入")
print("=" * 60)
try:
    from conversation.config import ConversationConfig
    from conversation.manager import ConversationManager
    print("✓ 模块导入成功")
except Exception as e:
    print(f"✗ 模块导入失败: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("测试2: 配置验证")
print("=" * 60)
config_info = ConversationConfig.get_config_info()
print(f"配置信息:")
for key, value in config_info.items():
    print(f"  {key}: {value}")

is_valid = ConversationConfig.validate()
print(f"\n配置验证结果: {'✓ 通过' if is_valid else '✗ 失败'}")

print("\n" + "=" * 60)
print("测试3: Token计算")
print("=" * 60)
manager = ConversationManager()

test_texts = [
    "你好",
    "Hello world",
    "你好，请问香港留学的学费大概是多少？",
    "根据最新数据，香港大学的学费大约是每年15万港币左右。",
]

for text in test_texts:
    tokens = manager._count_tokens(text)
    print(f"文本: '{text}' → Token数: {tokens}")

print("\n" + "=" * 60)
print("测试4: 历史消息Token计算")
print("=" * 60)
test_history = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！很高兴认识你。"},
    {"role": "user", "content": "香港留学怎么样？"},
    {"role": "assistant", "content": "香港留学非常热门，拥有多所世界知名高校。"},
]

total_tokens = manager._calculate_history_tokens(test_history)
print(f"历史消息({len(test_history)}条) → Token数: {total_tokens}")

print("\n" + "=" * 60)
print("测试5: 检查RAG路由是否传递history_messages")
print("=" * 60)
with open("api/conversation_routes.py", "r", encoding="utf-8") as f:
    content = f.read()

if "history_messages=history" in content:
    print("✓ RAG路由已传递history_messages参数")
else:
    print("✗ RAG路由未传递history_messages参数")

if "skip_cache=True" in content:
    print("✓ 对话API已设置skip_cache=True")
else:
    print("✗ 对话API未设置skip_cache=True")

print("\n" + "=" * 60)
print("测试完成！")
print("=" * 60)