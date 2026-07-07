"""逐个下载bge-m3关键文件 - 跳过snapshot_download的缓存API"""
import os, sys

# ====== SSL patch ======
import ssl as _ssl
def _no_verify_ctx(purpose=_ssl.Purpose.SERVER_AUTH):
    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    return ctx
_ssl.create_default_context = _no_verify_ctx
_ssl._create_default_https_context = _no_verify_ctx
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["SSL_CERT_FILE"] = ""

# ====== 镜像 ======
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import urllib3
urllib3.disable_warnings()

from huggingface_hub import hf_hub_download

target_dir = os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3")
os.makedirs(target_dir, exist_ok=True)

# 只下载PyTorch必需文件
files = [
    "pytorch_model.bin",       # 2.12 GB
    "config.json",             # 小
    "tokenizer.json",          # 16 MB
    "tokenizer_config.json",   # 小
    "sentencepiece.bpe.model", # 5 MB
    "special_tokens_map.json", # 小
    "colbert_linear.pt",       # 2 MB
    "sparse_linear.pt",        # 小
    "modules.json",            # 小
    "config_sentence_transformers.json",  # 小
    "sentence_bert_config.json",  # 小
    "1_Pooling/config.json",      # 小
]

print("下载 bge-m3 关键文件...")
print(f"镜像: hf-mirror.com")
print(f"目标: {target_dir}")
print("=" * 60)

total_downloaded = 0
for fname in files:
    fpath = os.path.join(target_dir, fname)
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    
    if os.path.exists(fpath) and os.path.getsize(fpath) > 1000:
        size = os.path.getsize(fpath)
        total_downloaded += size
        print(f"  ✓ {fname}: {size/(1024*1024):.1f} MB (已存在)")
        continue

    print(f"\n>>> 下载 {fname} ...")
    sys.stdout.flush()
    
    try:
        path = hf_hub_download(
            repo_id="BAAI/bge-m3",
            filename=fname,
            local_dir=target_dir,
            resume_download=True,
            token=None,  # 不认证，避免resolve-cache API
        )
        size = os.path.getsize(path)
        total_downloaded += size
        print(f"  ✓ {fname}: {size/(1024*1024):.1f} MB")
    except Exception as e:
        print(f"  ✗ {fname}: {e}")
        # 小文件失败不影响继续
        if fname == "pytorch_model.bin":
            print("  致命: pytorch_model.bin 下载失败，终止")
            sys.exit(1)

print(f"\n{'='*60}")
print(f"下载完成! 总大小: {total_downloaded/(1024*1024):.1f} MB")
print(f"目录: {target_dir}")
