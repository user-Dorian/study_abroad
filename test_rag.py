"""测试RAG模块"""
import requests
import json

url = "http://localhost:8000/api/query"

test_questions = [
    "留学英国需要注意哪些安全事项",
    "你好",
    "澳洲留学签证最新政策",
]

for question in test_questions:
    data = {"question": question}
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    print(f"{'='*60}")

    try:
        response = requests.post(url, json=data, stream=True, timeout=60)
        
        if response.status_code != 200:
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text[:500]}")
            continue
        
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = json.loads(line[6:])
                    if data.get('type') == 'result':
                        print(f"\n最终答案: {data['answer'][:300]}...")
                        print(f"\n执行路径:")
                        for step in data['execution_path']:
                            print(f"  [{step['status']}] {step['name']}: {step['detail']}")
                    else:
                        print(f"  [{data['status']}] {data['name']}: {data['detail']}")
    except Exception as e:
        print(f"请求失败: {e}")
