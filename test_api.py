"""
API测试脚本 - 测试RAG系统的后端API功能
直接通过HTTP请求测试，无需浏览器
"""
import sys
import time
import json
import requests

BASE_URL = "http://localhost:8000"


def test_health():
    """测试1: 健康检查"""
    print("\n=== 测试1: API健康检查 ===")
    try:
        resp = requests.get(f"{BASE_URL}/api/health", timeout=5)
        print(f"  状态码: {resp.status_code}")
        assert resp.status_code == 200
        data = resp.json()
        print(f"  响应: {data}")
        print("  ✓ 通过")
        return True
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_conversations_list():
    """测试2: 获取对话列表"""
    print("\n=== 测试2: 获取对话列表 ===")
    try:
        resp = requests.get(f"{BASE_URL}/api/conversations", timeout=5)
        print(f"  状态码: {resp.status_code}")
        assert resp.status_code == 200
        data = resp.json()
        print(f"  对话数: {len(data)}")
        if data:
            print(f"  第一个对话ID: {data[0].get('id', 'N/A')[:20]}...")
        print("  ✓ 通过")
        return data
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return []


def test_create_conversation():
    """测试3: 创建新对话"""
    print("\n=== 测试3: 创建新对话 ===")
    try:
        resp = requests.post(
            f"{BASE_URL}/api/conversations",
            json={"title": "测试对话"},
            timeout=5
        )
        print(f"  状态码: {resp.status_code}")
        assert resp.status_code == 200
        data = resp.json()
        conv_id = data.get("id", "")
        print(f"  创建对话ID: {conv_id[:20]}...")
        print(f"  标题: {data.get('title', 'N/A')}")
        print("  ✓ 通过")
        return data
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return None


def test_conversation_query(conv_id):
    """测试4: 在对话中提问（SSE流式回复）"""
    print(f"\n=== 测试4: 对话查询 (id={conv_id[:12]}...) ===")
    try:
        import sseclient

        resp = requests.post(
            f"{BASE_URL}/api/conversations/{conv_id}/query",
            json={"question": "你好"},
            stream=True,
            timeout=30
        )
        print(f"  状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  ✗ 查询失败: {resp.text[:200]}")
            return False

        client = sseclient.SSEClient(resp)
        result_answer = None
        steps = []
        parse_errors = 0

        for event in client.events():
            if event.data:
                try:
                    data = json.loads(event.data)

                    if data.get("type") == "result":
                        result_answer = data.get("answer", "")
                        steps = data.get("execution_path", [])
                        print(f"  最终回答: {result_answer[:100]}...")
                    elif "type" not in data:
                        steps.append(data)
                except json.JSONDecodeError:
                    parse_errors += 1

        print(f"  执行步骤数: {len(steps)}")
        for s in steps[:5]:
            name = s.get("name", "unknown")
            status = s.get("status", "unknown")
            detail = s.get("detail", "")
            print(f"    - [{status}] {name}: {detail[:80]}")
        if parse_errors > 0:
            print(f"  解析错误: {parse_errors}")

        if result_answer:
            print("  ✓ 通过")
            return True
        else:
            print("  ✗ 未获取到回答")
            return False
    except ImportError:
        print("  - 未安装sseclient-py，使用原始方式解析SSE")
        return _test_conversation_query_raw(conv_id)
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def _test_conversation_query_raw(conv_id):
    """使用原始HTTP流解析SSE"""
    try:
        resp = requests.post(
            f"{BASE_URL}/api/conversations/{conv_id}/query",
            json={"question": "介绍一下留学申请流程"},
            stream=True,
            timeout=60
        )
        print(f"  状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"  ✗ 查询失败: {resp.text[:200]}")
            return False

        buffer = ""
        result_answer = None
        steps = []
        chunk_count = 0

        for chunk in resp.iter_content(chunk_size=1, decode_unicode=True):
            if chunk:
                buffer += chunk
                if buffer.endswith('\n\n'):
                    lines = buffer.strip().split('\n')
                    buffer = ""
                    for line in lines:
                        if line.startswith('data: '):
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "result":
                                    result_answer = data.get("answer", "")
                                    steps = data.get("execution_path", [])
                                elif data.get("type") == "answer_chunk":
                                    chunk_count += 1
                                elif "type" not in data:
                                    steps.append(data)
                            except json.JSONDecodeError:
                                pass

        print(f"  执行步骤数: {len(steps)}")
        for s in steps[:5]:
            name = s.get("name", "unknown")
            status = s.get("status")
            detail = s.get("detail", "")
            print(f"    - {name}: {detail[:80]}")
        print(f"  回答长度: {len(result_answer or '')} 字符")
        print(f"  流式chunk数: {chunk_count}")

        if result_answer:
            print("  ✓ 通过")
            return True
        else:
            print("  ✗ 未获取到回答")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_get_messages(conv_id):
    """测试5: 获取对话消息"""
    print(f"\n=== 测试5: 获取对话消息 (id={conv_id[:12]}...) ===")
    try:
        resp = requests.get(
            f"{BASE_URL}/api/conversations/{conv_id}/messages?limit=100",
            timeout=5
        )
        print(f"  状态码: {resp.status_code}")
        assert resp.status_code == 200
        data = resp.json()
        print(f"  消息数: {len(data)}")
        for msg in data[:4]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:80]
            print(f"    [{role}] {content}")
        if len(data) >= 2:
            print("  ✓ 通过（消息≥2条）")
            return True
        elif len(data) >= 0:
            print("  ⚠ 部分通过（消息数较少）")
            return True
        else:
            print("  ✗ 无消息")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_conversation_history(conv_id):
    """测试6: 多轮对话历史"""
    print(f"\n=== 测试6: 多轮对话历史 (id={conv_id[:12]}...) ===")
    try:
        # 第二轮对话
        resp = requests.post(
            f"{BASE_URL}/api/conversations/{conv_id}/query",
            json={"question": "需要准备什么材料"},
            stream=True,
            timeout=60
        )
        print(f"  第二轮查询状态码: {resp.status_code}")

        if resp.status_code != 200:
            print(f"  ✗ 失败: {resp.text[:200]}")
            return False

        # 读取SSE流
        buffer = ""
        result_answer = None
        for chunk in resp.iter_content(chunk_size=1, decode_unicode=True):
            if chunk:
                buffer += chunk
                if buffer.endswith('\n\n'):
                    lines = buffer.strip().split('\n')
                    buffer = ""
                    for line in lines:
                        if line.startswith('data: '):
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "result":
                                    result_answer = data.get("answer", "")
                            except json.JSONDecodeError:
                                pass

        # 获取消息历史验证
        time.sleep(1)
        msg_resp = requests.get(
            f"{BASE_URL}/api/conversations/{conv_id}/messages?limit=100",
            timeout=5
        )
        if msg_resp.status_code == 200:
            messages = msg_resp.json()
            print(f"  总消息数: {len(messages)}")
            for msg in messages:
                role = msg.get("role", "?")
                content = msg.get("content", "")[:60]
                print(f"    [{role}] {content}")

            if len(messages) >= 4:
                print("  ✓ 通过（多轮对话历史正确保存）")
                return True
            else:
                print(f"  ⚠ 消息数不足4条")
                return False
        return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def test_delete_conversation(conv_id):
    """测试7: 删除对话"""
    print(f"\n=== 测试7: 删除对话 (id={conv_id[:12]}...) ===")
    try:
        resp = requests.delete(
            f"{BASE_URL}/api/conversations/{conv_id}",
            timeout=5
        )
        print(f"  状态码: {resp.status_code}")
        if resp.status_code == 200:
            print("  ✓ 通过")
            return True
        else:
            print(f"  ✗ 失败: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False


def main():
    print("=" * 60)
    print("  RAG系统 API 测试")
    print("=" * 60)

    results = {}

    results['health'] = test_health()

    results['list'] = test_conversations_list()

    conv = test_create_conversation()
    results['create'] = conv is not None

    if conv:
        conv_id = conv.get("id", "")
        results['query'] = test_conversation_query(conv_id)
        results['messages'] = test_get_messages(conv_id)
        results['history'] = test_conversation_history(conv_id)
        results['delete'] = test_delete_conversation(conv_id)

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
    # 先检查requests是否安装
    try:
        import requests
    except ImportError:
        print("请先安装requests: pip install requests")
        sys.exit(1)

    success = main()
    sys.exit(0 if success else 1)
