@echo off
REM 修复Windows SSL证书问题的启动脚本
REM 在Python启动前设置环境变量

REM 获取certifi证书路径
for /f "delims=" %%i in ('conda run -n rag_env python -c "import certifi; print(certifi.where())"') do set SSL_CERT_FILE=%%i

echo SSL_CERT_FILE=%SSL_CERT_FILE%

REM 设置SSL环境变量
set SSL_CERT_FILE=%SSL_CERT_FILE%
set CURL_CA_BUNDLE=%SSL_CERT_FILE%
set REQUESTS_CA_BUNDLE=%SSL_CERT_FILE%

REM 运行RAG数据构建
conda run -n rag_env python %*
