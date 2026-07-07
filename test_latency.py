"""测量请求各环节延迟"""
import json
import time
import urllib.request

endpoint = "http://localhost:8000/api/query"
payload = json.dumps({"question": "你好"}).encode("utf-8")
headers = {
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
}
req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
start = time.time()
with urllib.request.urlopen(req, timeout=60) as resp:
    status_time = time.time() - start
    print(f"[测试] 状态码: {resp.status}, 首字节时间(TTFB): {status_time:.3f}s")
    first_data_time = None
    for i, raw in enumerate(resp):
        if first_data_time is None:
            first_data_time = time.time() - start
            print(f"[测试] 首条数据时间: {first_data_time:.3f}s")
        if i < 3:
            print(f"[测试] 数据 {i+1}: {raw.decode('utf-8').strip()[:120]}")
        else:
            break
