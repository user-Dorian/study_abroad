"""RAG测试脚本 - 测试完整检索流程"""
import json
import sys
import time
import requests


def test_rag_retrieval():
    """测试RAG检索流程"""
    question = "留学需要做哪些准备？"
    url = "http://localhost:8000/api/query"
    
    print(f"发送问题: {question}")
    print(f"请求URL: {url}")
    
    try:
        response = requests.post(
            url,
            json={"question": question},
            stream=True,
            headers={"Accept": "text/event-stream"}
        )
        
        print(f"\nHTTP状态码: {response.status_code}")
        print("=" * 80)
        
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith("data: "):
                data = line[6:]
                try:
                    parsed = json.loads(data)
                    
                    if parsed.get("type") == "result":
                        print("\n✅ 最终结果:")
                        print(parsed.get("answer", ""))
                    else:
                        step = parsed.get("step", "?")
                        name = parsed.get("name", "")
                        status = parsed.get("status", "")
                        detail = parsed.get("detail", "")
                        
                        print(f"\n[步骤{step}] {name} [{status}]")
                        print(f"  详情: {detail}")
                        
                except json.JSONDecodeError:
                    print(f"原始数据: {data[:200]}")
        
        print("\n" + "=" * 80)
        print("测试完成!")
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = test_rag_retrieval()
    sys.exit(0 if success else 1)
