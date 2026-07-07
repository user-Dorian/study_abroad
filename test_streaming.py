"""流式输出测试脚本"""
import json
import time
import sys

try:
    import requests
except ImportError:
    print("缺少requests库，尝试用urllib实现")
    requests = None

def test_streaming(endpoint="http://127.0.0.1:8000/api/query", question="你好"):
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {"question": question}
    print(f"\n[测试] POST {endpoint}")
    print(f"[测试] 问题: {question}\n")
    start = time.time()
    first_event_time = None
    event_count = 0
    chunk_count = 0
    answer_chunks = []

    if requests:
        resp = requests.post(endpoint, json=payload, headers=headers, stream=True, timeout=60)
        print(f"[测试] 状态码: {resp.status_code}")
        print(f"[测试] Content-Type: {resp.headers.get('Content-Type')}\n")
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            line = line.decode("utf-8") if isinstance(line, bytes) else line
            if line.startswith("data: "):
                data = line[6:]
                event_count += 1
                if first_event_time is None:
                    first_event_time = time.time() - start
                try:
                    obj = json.loads(data)
                    print(f"[{event_count:03d}] +{time.time()-start:.3f}s {obj.get('type') or obj.get('name')} | {json.dumps(obj, ensure_ascii=False)[:200]}")
                    if obj.get("type") == "answer_chunk":
                        chunk_count += 1
                        answer_chunks.append(obj.get("content", ""))
                except json.JSONDecodeError:
                    print(f"[{event_count:03d}] +{time.time()-start:.3f}s (非JSON) {data[:200]}")
    else:
        import urllib.request
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"[测试] 状态码: {resp.status}")
            print(f"[测试] Content-Type: {resp.headers.get('Content-Type')}\n")
            for raw in resp:
                line = raw.decode("utf-8").rstrip("\n")
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                event_count += 1
                if first_event_time is None:
                    first_event_time = time.time() - start
                try:
                    obj = json.loads(data)
                    print(f"[{event_count:03d}] +{time.time()-start:.3f}s {obj.get('type') or obj.get('name')} | {json.dumps(obj, ensure_ascii=False)[:200]}")
                    if obj.get("type") == "answer_chunk":
                        chunk_count += 1
                        answer_chunks.append(obj.get("content", ""))
                except json.JSONDecodeError:
                    print(f"[{event_count:03d}] +{time.time()-start:.3f}s (非JSON) {data[:200]}")

    total = time.time() - start
    print(f"\n[测试] 首事件延迟: {first_event_time:.3f}s" if first_event_time else "\n[测试] 无事件")
    print(f"[测试] 总事件数: {event_count}, 流式块数: {chunk_count}")
    print(f"[测试] 回答总长度: {len(''.join(answer_chunks))}")
    print(f"[测试] 总耗时: {total:.3f}s")
    return event_count, chunk_count

if __name__ == "__main__":
    question = sys.argv[1] if len(sys.argv) > 1 else "你好"
    test_streaming(question=question)
