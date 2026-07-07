# 留学知识库 RAG 智能检索系统

基于 RAG（Retrieval-Augmented Generation）技术的留学知识智能问答系统，支持多轮对话、多级检索与流式输出。

## 环境要求

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐使用 Conda 管理环境 |
| PostgreSQL | 15+ | 端口 5432，用于存储会话和用户数据 |
| Redis | 7+ | 端口 6379，密码：1234，用于会话缓存 |
| Milvus | 2.4+ | 端口 19530，用于向量存储和相似性检索 |

## 模型依赖

本项目需要以下嵌入和重排序模型，请先运行下载脚本：

| 模型 | 路径 | 下载脚本 |
|------|------|---------|
| BAAI/bge-m3 | `models/bge-m3/` | `python scripts/download_model_modelscope.py` |
| BAAI/bge-reranker-v2-m3 | `models/bge-reranker-v2-m3/` | `python scripts/download_reranker_v3.py` |

模型文件较大（总计约 3GB），已配置在 `.gitignore` 中不会上传至仓库，请在各环境单独下载。

## Git 忽略说明

以下内容已在 `.gitignore` 中配置，不会上传至仓库，但本地保留：

| 类型 | 说明 |
|------|------|
| `models/` | 模型文件（~3GB），仅 `.gitkeep` 占位 |
| `logs/` | 运行时日志 |
| `bm25_index/` | BM25 索引（可通过脚本重建），仅 `.gitkeep` 占位 |
| `.env` | 敏感配置（API Key、数据库密码等） |
| `test_*.py` | 测试脚本（本地保留，不上传） |
| `__pycache__/` | Python 缓存 |
| `*.log` | 日志文件 |

## 环境配置

1. 复制环境变量模板：
   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env` 文件，配置以下关键参数：
   - `DASHSCOPE_API_KEY` - 阿里云 DashScope API 密钥
   - `DEEPSEEK_API_KEY` - DeepSeek API 密钥
   - `POSTGRES_USER` / `POSTGRES_PASSWORD` - 数据库连接信息
   - `MILVUS_HOST` / `MILVUS_PORT` - Milvus 连接信息
   - `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` - Redis 连接信息

## 启动服务

### 1. 启动基础设施

```bash
# 启动 PostgreSQL（如使用 Docker）
docker run -d --name postgres -e POSTGRES_USER=... -e POSTGRES_PASSWORD=... -p 5432:5432 postgres:15

# 启动 Redis
docker run -d --name redis -p 6379:6379 redis:7 redis-server --requirepass 1234

# 启动 Milvus
docker compose -f milvus-docker-compose.yml up -d
```

### 2. 创建数据库表

```bash
python scripts/create_conversation_tables.py
python scripts/create_tokenized_table.py
```

### 3. 构建知识库索引

```bash
python rag/data_loader/build_index.py
```

### 4. 启动 Web 服务

```bash
python server.py
```

服务启动后，访问 `http://localhost:8000/static/index.html` 即可使用。

## 项目结构

```
├── api/              # API 路由层（会话管理、查询接口）
├── config/           # 面向对象配置管理
├── conversation/     # 会话管理模块
├── handlers/         # 查询处理器（多级检索编排）
├── rag/              # RAG 核心模块
│   ├── data_loader/  # 数据加载、分块、嵌入
│   ├── models/       # LLM 客户端、意图分类、策略选择
│   ├── prompts/      # 提示词模板
│   └── retrieval/    # 检索与重排序
├── retrieval/        # BM25 检索模块
├── utils/            # 工具模块（日志、Docker 环境管理）
├── scripts/          # 工具脚本（模型下载、建表）
├── data/             # 留学知识库原始数据
├── static/           # 前端静态页面
├── server.py         # Web 服务入口
├── main.py           # CLI 交互入口
├── check_config.py   # 配置检查
├── check_milvus_db.py# Milvus 数据库检查
├── .env.example      # 环境变量模板
├── .gitignore        # Git 忽略规则
└── requirements.txt  # Python 依赖清单
```

## 相关脚本

| 脚本 | 用途 |
|------|------|
| `scripts/download_model_modelscope.py` | 通过 ModelScope 下载 bge-m3 嵌入模型 |
| `scripts/download_reranker_v3.py` | 通过 HuggingFace 镜像下载重排序模型 |
| `scripts/download_final.py` | 通过 HuggingFace 镜像下载 bge-m3（备选方案） |
| `scripts/download_model_multithread.py` | 多线程分段下载模型（备用） |
| `scripts/create_conversation_tables.py` | 创建会话数据库表 |
| `scripts/create_tokenized_table.py` | 创建分词数据库表 |
| `check_config.py` | 检查项目配置是否正确 |
| `check_milvus_db.py` | 检查 Milvus 数据库连接和索引状态 |
