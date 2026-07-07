import json, requests
q = "留学需要做哪些准备？"
print(f"测试: {q}\n")
resp = requests.post("http://localhost:8000/api/query", json={"question": q}, stream=True, headers={"Accept": "text/event-stream"})
for line in resp.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        d = json.loads(line[6:])
        if d.get("type") == "result":
            a = d.get("answer","")
            print(f"最终回答 ({len(a)}字符): {a[:200]}...")
        else:
            s, n, st = d.get("step","?"), d.get("name",""), d.get("status","")
            print(f"  [{s}] {n}: {st}")
print("\n完成!")
