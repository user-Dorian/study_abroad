"""多线程分段下载 bge-reranker-v2-m3 的 model.safetensors"""
import os
import sys
import time
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings()

# 使用相对路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET_DIR = os.path.join(BASE_DIR, "models", "bge-reranker-v2-m3")
MODEL_ID = "BAAI/bge-reranker-v2-m3"
CHUNK_SIZE = 1024 * 1024  # 1MB

# 候选镜像：ModelScope 优先，hf-mirror 备选
CANDIDATES = [
    {
        "name": "ModelScope",
        "url": "https://modelscope.cn/models/BAAI/bge-reranker-v2-m3/resolve/master/model.safetensors",
    },
    {
        "name": "hf-mirror",
        "url": "https://hf-mirror.com/BAAI/bge-reranker-v2-m3/resolve/main/model.safetensors",
    },
]

def get_file_size(url):
    """获取远程文件大小，返回 (size, supports_range)"""
    try:
        r = requests.head(url, allow_redirects=True, verify=False, timeout=15)
        if r.status_code != 200:
            return None, False
        size = int(r.headers.get("Content-Length", 0))
        supports_range = "bytes" in r.headers.get("Accept-Ranges", "")
        return size, supports_range
    except Exception:
        return None, False

def download_chunk(url, start, end, idx, total, retries=3):
    """下载指定字节范围"""
    headers = {"Range": f"bytes={start}-{end}"}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, verify=False, timeout=120)
            if r.status_code in (206, 200):
                return idx, r.content
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return idx, None

def select_mirror():
    """选择最快的镜像"""
    print("正在检测可用镜像...")
    fastest = None
    fastest_time = float("inf")
    for c in CANDIDATES:
        try:
            t0 = time.time()
            r = requests.head(c["url"], allow_redirects=True, verify=False, timeout=10)
            elapsed = time.time() - t0
            if r.status_code == 200:
                size = int(r.headers.get("Content-Length", 0))
                print(f"  ✓ {c['name']}: 可用, 文件大小 {size/1024/1024:.1f}MB, 延迟 {elapsed:.1f}s")
                if elapsed < fastest_time:
                    fastest_time = elapsed
                    fastest = c
            else:
                print(f"  ✗ {c['name']}: HTTP {r.status_code}")
        except Exception as e:
            print(f"  ✗ {c['name']}: {e}")
    return fastest

def download():
    """多线程分段下载"""
    mirror = select_mirror()
    if not mirror:
        print("所有镜像均不可用!")
        sys.exit(1)

    url = mirror["url"]
    print(f"\n使用镜像: {mirror['name']}")

    size, supports_range = get_file_size(url)
    if not size:
        print("无法获取文件大小!")
        sys.exit(1)

    print(f"文件大小: {size/1024/1024:.1f}MB")

    os.makedirs(TARGET_DIR, exist_ok=True)
    target_file = os.path.join(TARGET_DIR, "model.safetensors")

    if os.path.exists(target_file) and os.path.getsize(target_file) == size:
        print("文件已存在且完整，跳过下载")
        return

    NUM_THREADS = 8
    chunk_size = max(CHUNK_SIZE, size // NUM_THREADS + 1)

    ranges = []
    for i in range(NUM_THREADS):
        start = i * chunk_size
        end = min(start + chunk_size - 1, size - 1) if i < NUM_THREADS - 1 else size - 1
        if start > end:
            break
        ranges.append((start, end))

    print(f"启动 {len(ranges)} 个线程下载...")
    results = {}
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = {
            executor.submit(download_chunk, url, start, end, i, len(ranges)): i
            for i, (start, end) in enumerate(ranges)
        }
        for future in as_completed(futures):
            idx, data = future.result()
            if data is None:
                print(f"  线程 {idx} 下载失败!")
                sys.exit(1)
            results[idx] = data
            progress = len(results) / len(ranges) * 100
            print(f"  进度: {progress:.0f}% ({len(results)}/{len(ranges)})")

    # 合并文件
    print("合并文件...")
    with open(target_file, "wb") as f:
        for i in range(len(ranges)):
            f.write(results[i])

    actual_size = os.path.getsize(target_file)
    if actual_size == size:
        print(f"下载完成: {target_file} ({actual_size/1024/1024:.1f}MB)")
    else:
        print(f"文件大小不匹配: 期望 {size}, 实际 {actual_size}")
        os.remove(target_file)


if __name__ == "__main__":
    download()
