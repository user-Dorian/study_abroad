# PowerShell下载bge-m3模型
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = {$true}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$targetDir = "D:\Heima\AI-31期-就业班\小组项目\RAG\models\bge-m3"
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

$baseUrl = "https://hf-mirror.com/BAAI/bge-m3/resolve/main"

$files = @("pytorch_model.bin","config.json","tokenizer.json","tokenizer_config.json","sentencepiece.bpe.model","special_tokens_map.json","colbert_linear.pt","sparse_linear.pt","modules.json","config_sentence_transformers.json","sentence_bert_config.json")

Write-Host "下载 bge-m3 模型..." -ForegroundColor Green
Write-Host "镜像: hf-mirror.com" -ForegroundColor Cyan
Write-Host "目标: $targetDir" -ForegroundColor Cyan

$wc = New-Object System.Net.WebClient

foreach ($fname in $files) {
    $fpath = Join-Path $targetDir $fname
    $url = "$baseUrl/$fname"
    
    if (Test-Path $fpath) {
        $size = (Get-Item $fpath).Length
        if ($fname -eq "pytorch_model.bin" -and $size -gt 2GB) {
            Write-Host "[跳过] $fname ($([math]::Round($size/1GB,2)) GB)" -ForegroundColor Green
            continue
        } elseif ($size -gt 1KB) {
            Write-Host "[跳过] $fname ($([math]::Round($size/1MB,1)) MB)" -ForegroundColor Green
            continue
        }
    }
    
    Write-Host "[下载] $fname ..." -ForegroundColor Yellow
    
    try {
        $wc.DownloadFile($url, $fpath)
        $size = (Get-Item $fpath).Length
        if ($size -gt 1MB) {
            Write-Host "[完成] $fname ($([math]::Round($size/1MB,1)) MB)" -ForegroundColor Green
        } else {
            Write-Host "[完成] $fname ($([math]::Round($size/1KB,1)) KB)" -ForegroundColor Green
        }
    } catch {
        Write-Host "[失败] $fname`: $($_.Exception.Message)" -ForegroundColor Red
        if ($fname -eq "pytorch_model.bin") { exit 1 }
    }
}

# 子目录
$subDir = Join-Path $targetDir "1_Pooling"
New-Item -ItemType Directory -Path $subDir -Force | Out-Null
$subFile = Join-Path $subDir "config.json"
if (-not (Test-Path $subFile)) {
    Write-Host "[下载] 1_Pooling/config.json ..." -ForegroundColor Yellow
    $wc.DownloadFile("$baseUrl/1_Pooling/config.json", $subFile)
    Write-Host "[完成] 1_Pooling/config.json" -ForegroundColor Green
}

Write-Host "`n下载完成!" -ForegroundColor Green
Write-Host "`n文件列表:" -ForegroundColor Cyan
Get-ChildItem $targetDir -Recurse -File | Sort-Object Length -Descending | ForEach-Object {
    $s = if($_.Length -gt 1MB){"$([math]::Round($_.Length/1MB,1)) MB"}else{"$([math]::Round($_.Length/1KB,1)) KB"}
    Write-Host "  $($_.Name): $s"
}
