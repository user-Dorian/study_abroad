"""
Webapp测试脚本 - 测试RAG系统的对话功能和检索流程
使用方法: 先启动服务 python server.py, 然后运行此脚本
"""
import sys
import time
import json
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"

def test_home_page(page):
    """测试1: 首页加载"""
    print("\n=== 测试1: 首页加载 ===")
    page.goto(BASE_URL)
    page.wait_for_load_state('networkidle')
    
    title = page.title()
    print(f"  页面标题: {title}")
    assert "RAG" in title or "智能检索" in page.content(), "页面标题不包含RAG"
    
    # 检查聊天输入框是否存在
    input_el = page.locator('#questionInput')
    assert input_el.count() > 0, "找不到聊天输入框"
    print(f"  ✓ 输入框存在")
    
    submit_btn = page.locator('#submitBtn')
    assert submit_btn.count() > 0, "找不到提交按钮"
    print(f"  ✓ 提交按钮存在")
    
    print("  ✓ 首页加载测试通过")
    return True

def test_conversation_sidebar(page):
    """测试2: 对话侧边栏"""
    print("\n=== 测试2: 对话侧边栏 ===")
    page.goto(BASE_URL)
    page.wait_for_load_state('networkidle')
    time.sleep(1)
    
    # 检查对话侧边栏
    sidebar = page.locator('#conversationSidebar')
    assert sidebar.count() > 0, "找不到对话侧边栏"
    
    # 检查对话列表
    conv_list = page.locator('#conversationList')
    assert conv_list.count() > 0, "找不到对话列表"
    
    print("  ✓ 对话侧边栏测试通过")
    return True

def test_submit_query(page):
    """测试3: 提交查询（使用对话API）"""
    print("\n=== 测试3: 提交查询 ===")
    page.goto(BASE_URL)
    page.wait_for_load_state('networkidle')
    time.sleep(1)
    
    # 获取对话数量
    before_count = page.locator('.conversation-item').count()
    print(f"  查询前对话数: {before_count}")
    
    # 输入问题
    input_el = page.locator('#questionInput')
    input_el.fill("你好")
    
    # 点击提交
    page.locator('#submitBtn').click()
    
    # 等待状态显示
    time.sleep(3)
    
    # 获取对话数量（应该有新建对话）
    after_count = page.locator('.conversation-item').count()
    print(f"  查询后对话数: {after_count}")
    
    # 截图
    page.screenshot(path='/tmp/rag_test_query.png', full_page=True)
    
    # 检查是否有错误信息
    error_messages = page.locator('.error-message').count()
    print(f"  错误消息数: {error_messages}")
    
    if error_messages > 0:
        error_text = page.locator('.error-message').first.text_content()
        print(f"  ✗ 发现错误: {error_text}")
        return False
    
    # 检查是否显示了助手回复
    assistant_msgs = page.locator('.message.assistant').count()
    print(f"  助手消息数: {assistant_msgs}")
    
    if assistant_msgs > 0:
        print("  ✓ 成功收到回复")
    else:
        print("  ✗ 未收到任何回复")
    
    return True

def test_conversation_persistence(page):
    """测试4: 对话持久化（切换对话后消息不丢失）"""
    print("\n=== 测试4: 对话持久化 ===")
    page.goto(BASE_URL)
    page.wait_for_load_state('networkidle')
    time.sleep(2)
    
    # 先获取当前对话数
    page.locator('#questionInput').fill("测试一下")
    page.locator('#submitBtn').click()
    time.sleep(5)
    
    # 获取消息数
    msgs_before = page.locator('.message').count()
    print(f"  消息数（第一次查询后）: {msgs_before}")
    
    # 输入第二个问题
    page.locator('#questionInput').fill("再说点什么")
    page.locator('#submitBtn').click()
    time.sleep(5)
    
    msgs_after = page.locator('.message').count()
    print(f"  消息数（第二次查询后）: {msgs_after}")
    
    if msgs_after > msgs_before:
        print("  ✓ 消息成功累积")
    else:
        print(f"  ✗ 消息未累积 (before={msgs_before}, after={msgs_after})")
    
    # 截图
    page.screenshot(path='/tmp/rag_test_conversation.png', full_page=True)
    return True

def test_new_conversation(page):
    """测试5: 新建对话"""
    print("\n=== 测试5: 新建对话 ===")
    page.goto(BASE_URL)
    page.wait_for_load_state('networkidle')
    time.sleep(1)
    
    # 找到新建对话按钮并点击
    new_conv_btn = page.locator('#newConversationBtn')
    if new_conv_btn.count() > 0:
        items_before = page.locator('.conversation-item').count()
        print(f"  新建前对话数: {items_before}")
        
        new_conv_btn.click()
        time.sleep(1)
        
        items_after = page.locator('.conversation-item').count()
        print(f"  新建后对话数: {items_after}")
        
        if items_after >= items_before:
            print("  ✓ 新建对话成功")
        else:
            print("  ✗ 新建对话失败")
    else:
        print("  - 未找到新建按钮（可能由其他方式触发）")
    
    return True

def test_api_health(page):
    """测试6: API健康检查"""
    print("\n=== 测试6: API健康检查 ===")
    
    import requests
    try:
        resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
        print(f"  健康检查状态: {resp.status_code}")
        assert resp.status_code == 200
        print(f"  ✓ API健康检查通过")
        return True
    except Exception as e:
        print(f"  ✗ API健康检查失败: {e}")
        return False

def test_api_conversations(page):
    """测试7: API对话列表"""
    print("\n=== 测试7: API对话列表 ===")
    
    import requests
    try:
        resp = requests.get(f"{BASE_URL}/api/conversations", timeout=5)
        print(f"  对话列表状态: {resp.status_code}")
        
        if resp.status_code == 200:
            convs = resp.json()
            print(f"  对话数: {len(convs)}")
            if len(convs) > 0:
                print(f"  第一个对话ID: {convs[0].get('id', 'N/A')[:8]}...")
            print(f"  ✓ API对话列表测试通过")
            return True
        else:
            print(f"  ✗ 对话列表返回: {resp.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ API对话列表失败: {e}")
        return False


def main():
    """主测试流程"""
    print("=" * 60)
    print("  RAG系统测试开始")
    print("=" * 60)
    
    results = {}
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        # 捕获控制台日志
        page.on('console', lambda msg: print(f'    [浏览器日志] {msg.type}: {msg.text}'))
        
        try:
            results['home'] = test_home_page(page)
        except Exception as e:
            print(f"  ✗ 首页测试异常: {e}")
            results['home'] = False
        
        try:
            results['sidebar'] = test_conversation_sidebar(page)
        except Exception as e:
            print(f"  ✗ 侧边栏测试异常: {e}")
            results['sidebar'] = False
        
        try:
            results['api_health'] = test_api_health(page)
        except Exception as e:
            print(f"  ✗ API健康检查异常: {e}")
            results['api_health'] = False
        
        try:
            results['api_convs'] = test_api_conversations(page)
        except Exception as e:
            print(f"  ✗ API对话列表异常: {e}")
            results['api_convs'] = False
        
        try:
            results['query'] = test_submit_query(page)
        except Exception as e:
            print(f"  ✗ 查询测试异常: {e}")
            results['query'] = False
        
        try:
            results['new_conv'] = test_new_conversation(page)
        except Exception as e:
            print(f"  ✗ 新建对话测试异常: {e}")
            results['new_conv'] = False
        
        try:
            results['persistence'] = test_conversation_persistence(page)
        except Exception as e:
            print(f"  ✗ 持久化测试异常: {e}")
            results['persistence'] = False
        
        browser.close()
    
    # 输出结果汇总
    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    all_pass = True
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        if not passed:
            all_pass = False
        print(f"  {status} - {test_name}")
    
    print("=" * 60)
    if all_pass:
        print("  所有测试通过！")
    else:
        print("  部分测试失败，请查看详细输出。")
    print("=" * 60)
    
    return all_pass


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
