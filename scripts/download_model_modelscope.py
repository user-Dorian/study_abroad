"""使用ModelScope下载bge-m3 - 跳过onnx"""
import os, sys

os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["SSL_CERT_FILE"] = ""

import ssl as _ssl
_ssl._create_default_https_context = _ssl._create_unverified_context

target_dir = os.path.join(os.path.dirname(__file__), "..", "models", "bge-m3")
os.makedirs(target_dir, exist_ok=True)

print("开始下载 bge-m3 (跳过onnx文件)...")
print(f"目标: {target_dir}")
print("=" * 60)

from modelscope.hub.snapshot_download import snapshot_download

try:
    path = snapshot_download(
        'BAAI/bge-m3',
        local_dir=target_dir,
        ignore_file_pattern=['onnx/*'],   # 跳过onnx (省2.1GB)
        max_workers=3,                     # 3线程并行
    )
    print(f"\n下载完成: {path}")
    
    # 验证
    print("\n文件检查:")
    total_size = 0
    for f in sorted(os.listdir(target_dir)):
        fp = os.path.join(target_dir, f)
        if os.path.isfile(fp):
            s = os.path.getsize(fp)
            total_size += s
            if s > 1024*1024:
                print(f"  ✓ {f}: {s/(1024*1024):.1f} MB")
    
    print(f"\n总大小: {total_size/(1024*1024):.1f} MB")
    
    # 检查pytorch_model.bin
    bin_path = os.path.join(target_dir, "pytorch_model.bin")
    if os.path.exists(bin_path):
        bin_size = os.path.getsize(bin_path)
        print(f"\n✓ pytorch_model.bin: {bin_size/(1024*1024):.1f} MB")
        if bin_size < 2000 * 1024 * 1024:
            print("⚠ 文件大小不足2GB，可能未完整下载")
    else:
        print("\n✗ pytorch_model.bin 不存在!")
        
except Exception as e:
    print(f"下载失败: {e}")
    import traceback; traceback.print_exc()
    sys.exit(1)

print("\n完成!")
