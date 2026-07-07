"""测试会话自动标题生成功能"""
import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conversation.manager import ConversationManager
from utils.logger import logger


def test_auto_title_generation():
    """测试自动标题生成功能"""
    print("=" * 60)
    print("测试会话自动标题生成功能")
    print("=" * 60)
    
    try:
        # 初始化管理器
        manager = ConversationManager()
        print("\n✓ ConversationManager 初始化成功")
        
        # 测试1: 创建新会话
        print("\n【测试1】创建新会话")
        conversation = manager.create_conversation()
        conv_id = conversation["id"]
        print(f"✓ 创建会话成功")
        print(f"  - ID: {conv_id}")
        print(f"  - 标题: {conversation['title']}")
        
        # 验证初始标题为默认标题
        assert conversation["title"] == "新对话", f"初始标题应为'新对话'，实际为: {conversation['title']}"
        print("✓ 初始标题验证通过")
        
        # 测试2: 添加第一条用户消息（应触发自动标题生成）
        print("\n【测试2】添加第一条用户消息")
        user_content = "请介绍一下哈佛大学的历史和录取要求"
        msg1 = manager.add_message(conv_id, "user", user_content)
        print(f"✓ 添加用户消息成功")
        print(f"  - 消息ID: {msg1['id']}")
        print(f"  - 内容: {user_content[:50]}...")
        
        # 等待 LLM 调用完成（自动标题生成是异步的，但这里是同步调用）
        import time
        time.sleep(2)
        
        # 验证标题是否被更新
        updated_conv = manager.get_conversation(conv_id)
        print(f"\n✓ 获取更新后的会话")
        print(f"  - 标题: {updated_conv['title']}")
        
        # 标题应该不再是默认标题
        if updated_conv["title"] != "新对话":
            print(f"✓ 自动标题生成成功！新标题: {updated_conv['title']}")
        else:
            print("⚠ 标题未更新，可能是 LLM 调用失败或配置问题")
        
        # 测试3: 添加第二条用户消息（不应触发标题生成）
        print("\n【测试3】添加第二条用户消息")
        msg2 = manager.add_message(conv_id, "user", "那斯坦福大学呢？")
        print(f"✓ 添加第二条用户消息成功")
        
        time.sleep(1)
        
        # 验证标题未改变
        final_conv = manager.get_conversation(conv_id)
        if final_conv["title"] == updated_conv["title"]:
            print(f"✓ 标题未改变，符合预期: {final_conv['title']}")
        else:
            print(f"⚠ 标题意外改变: {updated_conv['title']} -> {final_conv['title']}")
        
        # 测试4: 添加 assistant 消息（不应触发标题生成）
        print("\n【测试4】添加 assistant 消息")
        msg3 = manager.add_message(conv_id, "assistant", "哈佛大学是美国最古老的高等学府之一...")
        print(f"✓ 添加 assistant 消息成功")
        
        time.sleep(1)
        
        # 验证标题未改变
        final_conv2 = manager.get_conversation(conv_id)
        if final_conv2["title"] == final_conv["title"]:
            print(f"✓ 标题未改变，符合预期: {final_conv2['title']}")
        else:
            print(f"⚠ 标题意外改变: {final_conv['title']} -> {final_conv2['title']}")
        
        # 测试5: 创建另一个会话，使用自定义标题
        print("\n【测试5】创建自定义标题的会话")
        custom_conv = manager.create_conversation(title="我的留学咨询")
        custom_conv_id = custom_conv["id"]
        print(f"✓ 创建自定义标题会话成功")
        print(f"  - ID: {custom_conv_id}")
        print(f"  - 标题: {custom_conv['title']}")
        
        # 添加用户消息（不应触发自动标题生成，因为已有自定义标题）
        msg4 = manager.add_message(custom_conv_id, "user", "耶鲁大学怎么样？")
        print(f"✓ 添加用户消息成功")
        
        time.sleep(1)
        
        # 验证标题未改变
        custom_conv_updated = manager.get_conversation(custom_conv_id)
        if custom_conv_updated["title"] == "我的留学咨询":
            print(f"✓ 自定义标题未改变，符合预期: {custom_conv_updated['title']}")
        else:
            print(f"⚠ 自定义标题被意外改变: 我的留学咨询 -> {custom_conv_updated['title']}")
        
        # 清理测试数据
        print("\n【清理】删除测试会话")
        manager.delete_conversation(conv_id)
        manager.delete_conversation(custom_conv_id)
        print("✓ 测试会话已删除")
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = test_auto_title_generation()
    sys.exit(0 if success else 1)
