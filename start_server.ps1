# Client Server Startup Script
# Ensures using conda rag_env environment

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Starting Client Server (Port 8002)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$env:PORT = "8002"
D:\miniconda3\Scripts\conda.exe run -n rag_env python backend/client/server.py