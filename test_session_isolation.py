"""会话隔离测试脚本

验证：同时向两个不同会话发送不同问题，返回结果不会串扰。
"""
import json
import threading
import urllib.request

BASE = "http://127.0.0.1:8000"


def create_conversation(title: str) -> str:
    req = urllib.request.Request(
        f"{BASE}/api/conversations",
        data=json.dumps({"title": title}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["id"]


def query_conversation(conversation_id: str, question: str, results: dict, key: str):
    req = urllib.request.Request(
        f"{BASE}/api/conversations/{conversation_id}/query",
        data=json.dumps({"question": question}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if line.startswith("data: "):
                    try:
                        obj = json.loads(line[6:])
                        if obj.get("type") in ("answer_chunk", "result"):
                            chunks.append(obj)
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        results[key] = f"ERROR: {e}"
        return
    results[key] = chunks


def main():
    conv_a = create_conversation("会话A")
    conv_b = create_conversation("会话B")
    print(f"创建会话A: {conv_a}")
    print(f"创建会话B: {conv_b}")

    results = {}
    t_a = threading.Thread(target=query_conversation, args=(conv_a, "美国硕士申请条件", results, "A"))
    t_b = threading.Thread(target=query_conversation, args=(conv_b, "你好", results, "B"))

    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    answer_a = "".join(c.get("content", "") for c in results.get("A", []) if c.get("type") == "answer_chunk")
    answer_b = "".join(c.get("content", "") for c in results.get("B", []) if c.get("type") == "answer_chunk")

    print("\n=== 会话A回答 ===")
    print(answer_a[:300])
    print("\n=== 会话B回答 ===")
    print(answer_b[:300])

    # 简单校验：A的回答应包含美国/硕士，B的回答应包含问候
    a_ok = "美国" in answer_a or "硕士" in answer_a
    b_ok = "你好" in answer_b or "留学通" in answer_b

    print(f"\n会话A是否相关: {a_ok}")
    print(f"会话B是否相关: {b_ok}")
    if a_ok and b_ok:
        print("会话隔离测试通过")
    else:
        print("会话隔离测试失败：可能出现串扰")


if __name__ == "__main__":
    main()
