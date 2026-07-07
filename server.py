"""Web服务入口 - 提供前端页面和API接口"""

# ====== 必须在最前面设置 SSL 和环境变量，防止 aiohttp/huggingface_hub 提前初始化 ======
import os
import ssl

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# Windows SSL 兼容模式 - 必须在任何库导入前设置
if os.getenv("SSL_VERIFY", "true").lower() != "true":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""
    os.environ["SSL_CERT_FILE"] = ""

    # 替换 ssl.create_default_context 避免 aiohttp 在模块导入时调用 ssl.create_default_context 报错
    # Windows证书存储可能有损坏的证书，导致 ASN1 解析失败
    # 直接返回不验证的上下文，完全跳过 Windows 证书加载
    def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ssl.create_default_context = _patched_create_default_context
    ssl._create_default_https_context = _patched_create_default_context

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====== 以下是正常导入 ======
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
from api.routes import router as query_router, init_query_handler
from utils.logger import logger

conversation_router = None
init_conversation_module = None

try:
    from api.conversation_routes import router as conversation_router, init_conversation_module
    logger.info("会话管理模块导入成功")
except ImportError as e:
    logger.warning(f"会话管理模块导入失败，将跳过 ({e})")

app = FastAPI(title="RAG智能检索系统", version="1.0.0")

app.include_router(query_router, prefix="")
if conversation_router:
    app.include_router(conversation_router, prefix="")

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

def _print_header(text: str):
    """打印分隔标题"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")

def _print_step(step: int, text: str, status: str = "success"):
    """打印步骤状态"""
    icon = {"success": "[✓]", "warn": "[!]", "skip": "[-]", "error": "[×]"}.get(status, "[?]")
    print(f"  {icon} {step}. {text}")

def _print_step_loading(step: int, text: str):
    """打印正在加载的步骤"""
    print(f"  [...] {step}. {text}", end="", flush=True)

def _print_step_done(step: int, text: str, status: str = "success"):
    """完成加载步骤的打印"""
    icon = {"success": "[✓]", "warn": "[!]", "skip": "[-]", "error": "[×]"}.get(status, "[?]")
    # 先清除当前行的 [...] 内容，再打印结果
    print(f"\r  {icon} {step}. {text}")


# ========== 并行初始化子任务 ==========

def _init_redis():
    """初始化Redis连接，返回 (redis_client_or_None, status_text, status)"""
    try:
        import redis
        from config.redis_config import RedisConfig
        if RedisConfig.validate():
            r = redis.Redis(**RedisConfig.get_connection_params())
            r.ping()
            return r, "Redis连接成功", "success"
        else:
            return None, "Redis配置不完整，将降级使用", "warn"
    except Exception as e:
        return None, f"Redis连接失败 ({e})", "warn"


def _init_database():
    """验证数据库连接，返回 (db_available_bool, status_text, status)"""
    try:
        import psycopg2
        from config.database import DatabaseConfig
        if DatabaseConfig.validate():
            conn = psycopg2.connect(**DatabaseConfig.get_connection_params())
            conn.close()
            return True, "数据库连接成功", "success"
        else:
            return False, "数据库配置不完整", "warn"
    except Exception as e:
        return False, f"数据库连接失败 ({e})", "warn"


def _init_bm25():
    """加载BM25索引（优先缓存），返回 (bm25_retriever_or_None, status_text, status)"""
    try:
        from retrieval.bm25_index_builder import BM25IndexBuilder
        builder = BM25IndexBuilder()
        bm25 = builder.initialize()
        count = len(bm25.questions) if bm25 and bm25.is_loaded else 0
        return bm25, f"BM25索引加载成功 ({count} 个问题)", "success"
    except Exception as e:
        return None, f"BM25索引加载失败 ({e})", "error"


def _init_milvus():
    """连接Milvus向量数据库，返回 (status_text, status)"""
    try:
        from rag.data_loader.chunk_and_embed import MilvusManager
        milvus = MilvusManager()
        count = milvus.get_count()
        if count > 0:
            return f"Milvus连接成功 ({count} 条向量数据)", "success"
        else:
            return "Milvus已连接，但无向量数据 (请先运行数据构建)", "warn"
    except Exception as e:
        return f"Milvus连接失败 ({e})", "warn"


def _init_llm():
    """初始化LLM客户端，返回 (status_text, status)"""
    try:
        from rag.models.llm_client import llm_client
        return "LLM客户端初始化成功", "success"
    except Exception as e:
        return f"LLM客户端初始化失败 ({e})", "warn"


def _init_conversation():
    """初始化会话管理模块，返回 (status_text, status)"""
    if init_conversation_module is None:
        return "会话管理模块未导入（依赖缺失）", "skip"
    
    try:
        from scripts.create_conversation_tables import create_conversation_tables
        from conversation.config import ConversationConfig
        
        success = create_conversation_tables()
        if success:
            # 预热数据库连接池，避免首次请求卡住
            from conversation.repository import init_pool
            init_pool()
            
            ConversationConfig.log_config()
            init_conversation_module()
            return "会话管理模块初始化成功", "success"
        else:
            return "会话管理模块初始化失败", "error"
    except Exception as e:
        return f"会话管理模块初始化失败 ({e})", "warn"


def _ensure_docker_environments():
    """确保Docker依赖环境可用（Redis/PostgreSQL/Milvus）"""
    try:
        from utils.docker_env_manager import DockerEnvManager
        from config.redis_config import RedisConfig
        from config.database import DatabaseConfig
        from rag.rag_config import RAGConfig

        auto_start = os.getenv("AUTO_START_DOCKER_ENV", "true").lower() == "true"
        if not auto_start:
            logger.info("AUTO_START_DOCKER_ENV=false，跳过Docker环境自动检测")
            return

        logger.info("开始检测Docker依赖环境...")
        manager = DockerEnvManager()

        # 检查磁盘空间
        ok, free_gb = manager.check_disk_space()
        if not ok:
            logger.warning(f"磁盘空间不足（剩余 {free_gb:.1f}GB），跳过自动启动Docker环境")
            return
        logger.info(f"磁盘空间检查通过（剩余 {free_gb:.1f}GB）")

        results = manager.ensure_all(
            redis_config={
                "host": RedisConfig.HOST,
                "port": RedisConfig.PORT,
                "password": RedisConfig.PASSWORD,
            },
            postgres_config={
                "host": DatabaseConfig.DB_HOST,
                "port": DatabaseConfig.DB_PORT,
                "user": DatabaseConfig.DB_USER,
                "password": DatabaseConfig.DB_PASSWORD,
                "database": DatabaseConfig.DB_NAME,
            },
            milvus_config={
                "host": RAGConfig.MILVUS_HOST,
                "port": RAGConfig.MILVUS_PORT,
            }
        )

        for service, (success, message) in results.items():
            if success:
                logger.info(f"[✓] {service}: {message}")
            else:
                logger.warning(f"[!] {service}: {message}")

    except Exception as e:
        logger.warning(f"Docker环境自动检测/启动失败: {e}")


def preload_all_modules():
    """预加载所有模块，使用并行初始化优化启动速度"""
    _print_header("正在初始化系统组件...")

    # ========== 第零阶段：确保Docker依赖环境可用 ==========
    _ensure_docker_environments()

    # ========== 第一阶段：Redis + 数据库并行连接验证 ==========
    _print_step_loading(1, "Redis连接")
    _print_step_loading(2, "数据库连接")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_redis = executor.submit(_init_redis)
        future_db = executor.submit(_init_database)

        redis_client, redis_text, redis_status = future_redis.result()
        db_available, db_text, db_status = future_db.result()

    _print_step_done(1, redis_text, redis_status)
    _print_step_done(2, db_text, db_status)

    # ========== 第二阶段：BM25 + Milvus + LLM 并行初始化 ==========
    _print_step_loading(3, "BM25索引加载")
    _print_step_loading(4, "LLM客户端初始化")
    _print_step_loading(5, "Milvus向量数据库")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_bm25 = executor.submit(_init_bm25)
        future_llm = executor.submit(_init_llm)
        future_milvus = executor.submit(_init_milvus)

        bm25_retriever, bm25_text, bm25_status = future_bm25.result()
        llm_text, llm_status = future_llm.result()
        milvus_text, milvus_status = future_milvus.result()

    _print_step_done(3, bm25_text, bm25_status)
    _print_step_done(4, llm_text, llm_status)
    _print_step_done(5, milvus_text, milvus_status)

    # ========== 第三阶段：QueryHandler（复用已初始化组件） ==========
    _print_step_loading(6, "QueryHandler初始化")
    try:
        init_query_handler(
            redis_client=redis_client,
            bm25_retriever=bm25_retriever if bm25_retriever and bm25_retriever.is_loaded else None,
            db_available=db_available,
        )
        _print_step_done(6, "QueryHandler初始化成功", "success")
    except Exception as e:
        _print_step_done(6, f"QueryHandler初始化失败 ({e})", "error")

    # ========== 第四阶段：RAG检索器与模型预热 + 会话管理模块 ==========
    _print_step_loading(7, "RAG检索器与模型预热")
    _print_step_loading(8, "会话管理模块")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_rag = executor.submit(_init_rag)
        future_conv = executor.submit(_init_conversation)

        rag_text, rag_status = future_rag.result()
        conv_text, conv_status = future_conv.result()

    _print_step_done(7, rag_text, rag_status)
    _print_step_done(8, conv_text, conv_status)

    print()


def _init_rag():
    """初始化RAG检索器与模型预热，返回 (status_text, status)"""
    try:
        from rag.retrieval.rag_retriever import rag_retriever
        from rag.rag_config import RAGConfig

        if RAGConfig.ENABLE_MODEL_WARMUP:
            rag_retriever.initialize()
            rag_retriever.warmup()
            return "RAG检索器与模型预热成功", "success"
        else:
            return "模型预热已禁用", "skip"
    except Exception as e:
        logger.error(f"RAG检索器或模型预热失败: {e}")
        return f"RAG检索器或模型预热失败 ({e})", "warn"

@app.on_event("startup")
async def startup_event():
    """服务启动事件"""
    pass  # 已在main()中预加载完成

@app.get("/")
async def serve_index():
    """提供前端页面"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        })
    return {"error": "前端页面不存在"}

def main():
    """启动Web服务"""
    # 先预加载所有模块
    preload_all_modules()
    
    _print_header("启动Web服务")
    print(f"\n  访问地址: http://localhost:8000")
    print(f"  按 Ctrl+C 停止服务\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
