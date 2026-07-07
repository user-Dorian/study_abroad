"""
下载 BAAI/bge-reranker-v2-m3 到本地 models 目录
关键：禁用 Xet 协议，使用标准 HTTP 下载防止 CAS 桥超时
"""
import os
import sys
import time

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# === 关键环境变量 ===
os.environ["HF_HUB_DISABLE_XET"] = "1"         # 禁用 Xet CAS 协议，用标准 HTTP
os.environ["HF_HUB_DOWNLOAD_TIMEOUT"] = "600"   # 单文件下载超时 600 秒
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

MODEL_DIR = os.path.join(os.getcwd(), "models", "bge-reranker-v2-m3")
MODEL_NAME = "BAAI/bge-reranker-v2-m3"


def download():
    """使用 hf_hub_download 逐个下载文件"""
    from huggingface_hub import hf_hub_download, HfApi
    
    # 清理旧目录
    if os.path.exists(MODEL_DIR):
        import shutil
        shutil.rmtree(MODEL_DIR)
    os.makedirs(MODEL_DIR, exist_ok=True)
    
    print(f"下载目标: {MODEL_DIR}")
    
    # 获取文件列表
    try:
        api = HfApi()
        files = [f.rfilename for f in api.list_repo_tree(MODEL_NAME, recursive=True)]
        print(f"仓库文件 ({len(files)} 个):")
        for f in files:
            print(f"  - {f}")
    except Exception as e:
        print(f"获取文件列表失败: {e}")
        files = [
            "config.json", "model.safetensors",
            "tokenizer.json", "tokenizer_config.json",
            "special_tokens_map.json", "sentencepiece.bpe.model",
            "README.md", ".gitattributes",
        ]
    
    # 先下载小文件，最后下载大的 model.safetensors
    big_files = {"model.safetensors"}
    small_files = [f for f in files if f not in big_files]
    big_files_list = [f for f in files if f in big_files]
    ordered = small_files + big_files_list
    
    total = len(ordered)
    downloaded = 0
    start = time.time()
    
    for i, filepath in enumerate(ordered):
        try:
            print(f"\n[{i+1}/{total}] 下载 {filepath}...")
            local_path = hf_hub_download(
                repo_id=MODEL_NAME,
                filename=filepath,
                local_dir=MODEL_DIR,
                local_dir_use_symlinks=False,
                resume_download=True,
            )
            size_mb = os.path.getsize(local_path) / 1024 / 1024
            print(f"  ✅ {size_mb:.1f} MB")
            downloaded += 1
        except Exception as e:
            print(f"  ❌ {e}")
    
    elapsed = time.time() - start
    print(f"\n下载完成 {downloaded}/{total} 文件，耗时: {elapsed:.0f} 秒")
    return downloaded == total


def verify():
    """校验文件完整性"""
    print("\n===== 校验文件 =====")
    required = ["config.json", "model.safetensors", "tokenizer.json",
                 "tokenizer_config.json", "sentencepiece.bpe.model",
                 "special_tokens_map.json"]
    
    all_ok = True
    for f in required:
        fp = os.path.join(MODEL_DIR, f)
        if not os.path.exists(fp):
            print(f"❌ 缺少: {f}")
            all_ok = False
        else:
            size = os.path.getsize(fp)
            print(f"✅ {f}: {size/1024/1024:.1f} MB")
    
    if all_ok:
        print("\n🎉 所有文件完整！")
    return all_ok


if __name__ == "__main__":
    ok = download()
    if ok:
        verify()
    sys.exit(0 if ok else 1)
