@echo off
REM 客户端服务器启动脚本
REM 确保使用conda的rag_env环境启动

echo ========================================
echo 启动客户端服务器 (端口 8002)
echo ========================================

REM 设置端口
set PORT=8002

REM 使用conda环境启动
D:\miniconda3\Scripts\conda.exe run -n rag_env python backend/client/server.py

pause