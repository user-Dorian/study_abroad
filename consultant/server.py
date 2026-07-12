"""规划师端Web服务入口 - 企业内部留学智能检索系统（独立端口8001）

与客户端端共享LLM客户端、嵌入模型等基础设施，
但使用独立的配置、提示词、Milvus集合和前端页面。
"""

# ====== 首先确保项目根目录在 Python 路径中 ======
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ====== 必须在最前面设置 SSL 和环境变量 ======
import os
import ssl

from dotenv import load_dotenv
load_dotenv()

# Windows SSL 兼容模式
if os.getenv("SSL_VERIFY", "true").lower() != "true":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["CURL_CA_BUNDLE"] = ""
    os.environ["REQUESTS_CA_BUNDLE"] = ""
    os.environ["SSL_CERT_FILE"] = ""

    def _patched_create_default_context(purpose=ssl.Purpose.SERVER_AUTH):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    ssl.create_default_context = _patched_create_default_context
    ssl._create_default_https_context = _patched_create_default_context

    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====== 正常导入 ======
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from consultant.api.routes import router as query_router, init_query_handler
from consultant.api.auth_routes import router as auth_router
from consultant.api.status_routes import router as status_router
from consultant.api.quota_routes import router as quota_router
from consultant.config.settings import ConsultantConfig
from common.utils.logger import logger
from common.friendship.routes import router as friendship_router
from common.contact_chat.routes import router as contact_chat_router
from common.contact_chat.websocket_routes import router as websocket_router
from common.unread_messages.routes import router as unread_messages_router
from common.account.routes import router as account_router
from common.profile.routes import router as profile_router

# 会话管理模块（可选导入）
conversation_router = None
init_conversation_module = None

try:
    from consultant.api.conversation_routes import router as conversation_router, init_conversation_module
    logger.info("[规划师端] 会话管理模块导入成功")
except ImportError as e:
    logger.warning(f"[规划师端] 会话管理模块导入失败，将跳过 ({e})")

app = FastAPI(title="企业留学通 - 规划师端", version="1.0.0")

app.include_router(query_router, prefix="")
app.include_router(auth_router, prefix="")
app.include_router(status_router, prefix="")
app.include_router(quota_router, prefix="")
if conversation_router:
    app.include_router(conversation_router, prefix="")
app.include_router(friendship_router)
app.include_router(contact_chat_router)
app.include_router(unread_messages_router)
app.include_router(account_router)
app.include_router(profile_router)

# WebSocket路由必须在静态文件挂载之前直接注册，避免被mount覆盖
# 直接注册WebSocket端点，确保/ws路径优先匹配
from common.contact_chat.websocket_routes import websocket_chat_endpoint
app.websocket("/ws/chat/{user_id}")(websocket_chat_endpoint)

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _print_header(text: str):
    """打印分隔标题"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def _print_step_loading(step: int, text: str):
    """打印正在加载的步骤"""
    print(f"  [...] {step}. {text}", end="", flush=True)


def _print_step_done(step: int, text: str, status: str = "success"):
    """完成加载步骤的打印"""
    icon = {"success": "[✓]", "warn": "[!]", "skip": "[-]", "error": "[×]"}.get(status, "[?]")
    print(f"\r  {icon} {step}. {text}")


# ========== 并行初始化子任务 ==========

def _init_redis():
    """初始化Redis连接"""
    try:
        import redis
        from consultant.config.redis_config import ConsultantRedisConfig
        if ConsultantRedisConfig.validate():
            r = redis.Redis(**ConsultantRedisConfig.get_connection_params())
            r.ping()
            return r, "[规划师端] Redis连接成功", "success"
        else:
            return None, "[规划师端] Redis配置不完整，将降级使用", "warn"
    except Exception as e:
        return None, f"[规划师端] Redis连接失败 ({e})", "warn"


def _init_database():
    """验证数据库连接并初始化企业数据表"""
    try:
        import psycopg2
        from consultant.config.database import ConsultantDatabaseConfig

        if ConsultantDatabaseConfig.validate():
            conn = psycopg2.connect(**ConsultantDatabaseConfig.get_connection_params())

            # 创建规划师端所需的企业数据表
            with conn.cursor() as cur:
                # 创建企业QA对表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS enterprise_qa_pairs (
                        id SERIAL PRIMARY KEY,
                        question TEXT NOT NULL,
                        answer TEXT NOT NULL,
                        category VARCHAR(100),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
            conn.close()

            # 创建名额管理相关表（enterprise_quota / enterprise_quota_usage）
            try:
                from consultant.api.quota_routes import _create_quota_tables_if_not_exists
                _create_quota_tables_if_not_exists()
            except Exception as qe:
                logger.warning(f"[规划师端] 名额管理表创建失败（不影响主流程）: {qe}")

            return True, "[规划师端] 数据库连接成功（企业数据表已就绪）", "success"
        else:
            return False, "[规划师端] 数据库配置不完整", "warn"
    except Exception as e:
        return False, f"[规划师端] 数据库连接失败 ({e})", "warn"


def _init_bm25_for_enterprise():
    """初始化企业数据的BM25索引"""
    try:
        from consultant.retrieval.bm25_index_builder import ConsultantBM25IndexBuilder

        builder = ConsultantBM25IndexBuilder()
        # 优先从缓存加载
        if builder.load_from_cache():
            bm25 = builder.retriever
        else:
            # 缓存不存在则重建
            bm25 = builder.initialize()
        count = len(bm25.questions) if bm25 and bm25.is_loaded else 0
        return bm25, f"[规划师端] 企业BM25索引加载成功 ({count} 个问题)", "success"
    except Exception as e:
        return None, f"[规划师端] 企业BM25索引加载失败 ({e})", "warn"


def _init_milvus():
    """连接Milvus向量数据库（企业数据集合）"""
    try:
        from common.rag.data_loader.chunk_and_embed import MilvusManager
        from consultant.rag.rag_config import ConsultantRAGConfig

        milvus = MilvusManager(
            collection_name=ConsultantRAGConfig.MILVUS_COLLECTION_NAME,
            database_name=ConsultantRAGConfig.MILVUS_DATABASE_NAME,
        )
        count = milvus.get_count() if hasattr(milvus, 'get_count') else 0
        if count > 0:
            return f"[规划师端] Milvus连接成功 ({count} 条企业向量数据)", "success"
        else:
            return "[规划师端] Milvus已连接，但无企业向量数据（请先运行数据构建）", "warn"
    except Exception as e:
        return f"[规划师端] Milvus连接失败 ({e})", "warn"


def _init_llm():
    """初始化LLM客户端（共享）"""
    try:
        from common.rag.models.llm_client import llm_client
        return "[规划师端] LLM客户端初始化成功", "success"
    except Exception as e:
        return f"[规划师端] LLM客户端初始化失败 ({e})", "warn"


def _init_conversation():
    """初始化会话管理模块"""
    if init_conversation_module is None:
        return "[规划师端] 会话管理模块未导入（依赖缺失）", "skip"

    try:
        from common.scripts.create_conversation_tables import create_conversation_tables
        from common.conversation.config import ConversationConfig

        success = create_conversation_tables()
        if success:
            from common.conversation.repository import init_pool
            init_pool()

            ConversationConfig.log_config()
            init_conversation_module()
            return "[规划师端] 会话管理模块初始化成功", "success"
        else:
            return "[规划师端] 会话管理模块初始化失败", "error"
    except Exception as e:
        return f"[规划师端] 会话管理模块初始化失败 ({e})", "warn"


def _init_rag():
    """初始化RAG检索器与模型预热"""
    try:
        from common.rag.retrieval.rag_retriever import rag_retriever
        from consultant.rag.rag_config import ConsultantRAGConfig

        if ConsultantRAGConfig.ENABLE_MODEL_WARMUP:
            rag_retriever.initialize()
            rag_retriever.warmup()
            return "[规划师端] RAG检索器与模型预热成功", "success"
        else:
            return "[规划师端] 模型预热已禁用", "skip"
    except Exception as e:
        logger.error(f"[规划师端] RAG检索器或模型预热失败: {e}")
        return f"[规划师端] RAG检索器或模型预热失败 ({e})", "warn"


def _ensure_docker_environments():
    """确保Docker依赖环境可用"""
    try:
        from common.utils.docker_env_manager import DockerEnvManager
        from consultant.config.redis_config import ConsultantRedisConfig
        from consultant.config.database import ConsultantDatabaseConfig
        from consultant.rag.rag_config import ConsultantRAGConfig

        auto_start = os.getenv("AUTO_START_DOCKER_ENV", "true").lower() == "true"
        if not auto_start:
            logger.info("[规划师端] AUTO_START_DOCKER_ENV=false，跳过Docker环境自动检测")
            return

        logger.info("[规划师端] 开始检测Docker依赖环境...")
        manager = DockerEnvManager()

        results = manager.ensure_all(
            redis_config={
                "host": ConsultantRedisConfig.HOST,
                "port": ConsultantRedisConfig.PORT,
                "password": ConsultantRedisConfig.PASSWORD,
            },
            postgres_config={
                "host": ConsultantDatabaseConfig.DB_HOST,
                "port": ConsultantDatabaseConfig.DB_PORT,
                "user": ConsultantDatabaseConfig.DB_USER,
                "password": ConsultantDatabaseConfig.DB_PASSWORD,
                "database": ConsultantDatabaseConfig.DB_NAME,
            },
            milvus_config={
                "host": ConsultantRAGConfig.MILVUS_HOST,
                "port": ConsultantRAGConfig.MILVUS_PORT,
            }
        )

        for service, (success, message) in results.items():
            if success:
                logger.info(f"[✓] {service}: {message}")
            else:
                logger.warning(f"[!] {service}: {message}")

    except Exception as e:
        logger.warning(f"[规划师端] Docker环境自动检测/启动失败: {e}")


def preload_all_modules():
    """预加载所有模块，使用并行初始化优化启动速度"""
    _print_header("正在初始化规划师端系统组件...")

    # 第零阶段：Docker环境
    _ensure_docker_environments()

    # 第一阶段：Redis + 数据库并行
    _print_step_loading(1, "Redis连接")
    _print_step_loading(2, "数据库连接")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_redis = executor.submit(_init_redis)
        future_db = executor.submit(_init_database)

        redis_client, redis_text, redis_status = future_redis.result()
        db_available, db_text, db_status = future_db.result()

    _print_step_done(1, redis_text, redis_status)
    _print_step_done(2, db_text, db_status)

    # 第二阶段：BM25 + LLM + Milvus 并行
    _print_step_loading(3, "企业BM25索引加载")
    _print_step_loading(4, "LLM客户端初始化")
    _print_step_loading(5, "Milvus向量数据库")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_bm25 = executor.submit(_init_bm25_for_enterprise)
        future_llm = executor.submit(_init_llm)
        future_milvus = executor.submit(_init_milvus)

        bm25_retriever, bm25_text, bm25_status = future_bm25.result()
        llm_text, llm_status = future_llm.result()
        milvus_text, milvus_status = future_milvus.result()

    _print_step_done(3, bm25_text, bm25_status)
    _print_step_done(4, llm_text, llm_status)
    _print_step_done(5, milvus_text, milvus_status)

    # 第三阶段：QueryHandler初始化
    _print_step_loading(6, "规划师端QueryHandler初始化")
    try:
        init_query_handler(
            redis_client=redis_client,
            bm25_retriever=bm25_retriever if bm25_retriever and bm25_retriever.is_loaded else None,
            db_available=db_available,
        )
        _print_step_done(6, "[规划师端] QueryHandler初始化成功", "success")
    except Exception as e:
        _print_step_done(6, f"[规划师端] QueryHandler初始化失败 ({e})", "error")

    # 第四阶段：RAG检索器预热 + 会话管理
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


@app.on_event("startup")
async def startup_event():
    """服务启动事件"""
    pass  # 已在main()中预加载完成


# 挂载静态文件目录
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main():
    """启动规划师端Web服务"""
    # 验证配置
    ConsultantConfig.validate()

    # 预加载所有模块
    preload_all_modules()

    _print_header("启动规划师端Web服务")
    print(f"\n  访问地址: http://localhost:{ConsultantConfig.PORT}")
    print(f"  按 Ctrl+C 停止服务\n")

    uvicorn.run(app, host=ConsultantConfig.HOST, port=ConsultantConfig.PORT)


if __name__ == "__main__":
    main()
