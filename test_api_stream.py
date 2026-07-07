import requests

r = requests.post('http://localhost:8000/api/query', json={'question': 'curl测试'}, stream=True, headers={'Accept': 'text/event-stream'})
print('Status:', r.status_code)
print('Headers:', dict(r.headers))
for chunk in r.iter_lines():
    if chunk:
        print(chunk.decode()[:150])
