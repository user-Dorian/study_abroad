"""规划师端Web服务入口 - 企业内部留学智能检索系统（独立端口8001）

与客户端端共享LLM客户端、嵌入模型等基础设施，
但使用独立的配置、提示词、Milvus集合和前端页面。
"""

# ====== 首先确保项目根目录在 Python 路径中 ======
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ====== 必须在最前面设置 SSL 和环境变量 ======
import os
from dotenv import load_dotenv
load_dotenv()

from backend.common.basics.bootstrap import patch_ssl
patch_ssl()

from backend.common.basics.bootstrap import (
    print_header, print_step_loading, print_step_done,
    ensure_docker_environments,
)

# ====== 正常导入 ======
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn
from backend.common.basics.utils.logger import logger

try:
    from backend.consultant.api.routes import router as query_router, init_query_handler
    logger.info("[规划师端] 查询路由模块导入成功")
except ImportError as e:
    query_router = None; init_query_handler = None
    logger.warning(f"[规划师端] 查询路由模块导入失败: {e}")

try:
    from backend.consultant.api.auth_routes import router as auth_router
    logger.info("[规划师端] 认证路由模块导入成功")
except ImportError as e:
    auth_router = None
    logger.warning(f"[规划师端] 认证路由模块导入失败: {e}")

try:
    from backend.consultant.api.status_routes import router as status_router
    logger.info("[规划师端] 状态路由模块导入成功")
except ImportError as e:
    status_router = None
    logger.warning(f"[规划师端] 状态路由模块导入失败: {e}")

try:
    from backend.consultant.api.quota_routes import router as quota_router
    logger.info("[规划师端] 配额路由模块导入成功")
except ImportError as e:
    quota_router = None
    logger.warning(f"[规划师端] 配额路由模块导入失败: {e}")

try:
    from backend.consultant.basics.config.settings import Config as ConsultantConfig
    logger.info("[规划师端] 配置模块导入成功")
except ImportError as e:
    ConsultantConfig = None
    logger.warning(f"[规划师端] 配置模块导入失败: {e}")
from backend.common.functions.friendship.routes import router as friendship_router
from backend.common.functions.contact_chat.routes import router as contact_chat_router
from backend.common.functions.contact_chat.websocket_routes import router as websocket_router
from backend.common.functions.unread_messages.routes import router as unread_messages_router
from backend.common.functions.account.routes import router as account_router
from backend.common.functions.profile.routes import router as profile_router
from backend.common.functions.settings.routes import router as settings_router

# F-1/F-2: 申请时间线
try:
    from backend.common.functions.application_timeline.routes import router as application_timeline_router
    logger.info("申请时间线模块导入成功")
except ImportError as e:
    application_timeline_router = None
    logger.warning(f"申请时间线模块导入失败: {e}")

# F-3: 收藏夹
try:
    from backend.common.functions.favorites.routes import router as favorites_router
    logger.info("收藏夹模块导入成功")
except ImportError as e:
    favorites_router = None
    logger.warning(f"收藏夹模块导入失败: {e}")

# F-5: 消息分类
try:
    from backend.common.functions.message_classify.routes import router as message_classify_router
    logger.info("消息分类模块导入成功")
except ImportError as e:
    message_classify_router = None
    logger.warning(f"消息分类模块导入失败: {e}")

# F-6: 模拟面试
try:
    from backend.common.functions.mock_interview.routes import router as mock_interview_router
    logger.info("模拟面试模块导入成功")
except ImportError as e:
    mock_interview_router = None
    logger.warning(f"模拟面试模块导入失败: {e}")

# 会话管理模块（可选导入）
conversation_router = None
init_conversation_module = None

try:
    from backend.consultant.api.conversation_routes import router as conversation_router, init_conversation_module
    logger.info("[规划师端] 会话管理模块导入成功")
except ImportError as e:
    logger.warning(f"[规划师端] 会话管理模块导入失败，将跳过 ({e})")

# 工作台模块（可选导入）
workspace_router = None
try:
    from backend.consultant.api.workspace_routes import router as workspace_router
    logger.info("[规划师端] 工作台模块导入成功")
except ImportError as e:
    logger.warning(f"[规划师端] 会话管理模块导入失败，将跳过 ({e})")

# 学生派单信息模块（可选导入）
dispatch_router = None
try:
    from backend.consultant.api.dispatch_routes import router as dispatch_router
    logger.info("[规划师端] 学生派单信息模块导入成功")
except ImportError as e:
    logger.warning(f"[规划师端] 学生派单信息模块导入失败，将跳过 ({e})")

app = FastAPI(title="企业留学通 - 规划师端", version="1.0.0")

if query_router:
    app.include_router(query_router, prefix="")
if auth_router:
    app.include_router(auth_router, prefix="")
if status_router:
    app.include_router(status_router, prefix="")
if quota_router:
    app.include_router(quota_router, prefix="")
if conversation_router:
    app.include_router(conversation_router, prefix="")
app.include_router(friendship_router)
app.include_router(contact_chat_router)
app.include_router(unread_messages_router)
app.include_router(account_router)
app.include_router(profile_router)
app.include_router(settings_router)
if application_timeline_router:
    app.include_router(application_timeline_router)
if favorites_router:
    app.include_router(favorites_router)
if message_classify_router:
    app.include_router(message_classify_router)
if mock_interview_router:
    app.include_router(mock_interview_router)
if workspace_router:
    app.include_router(workspace_router, prefix="")
if dispatch_router:
    app.include_router(dispatch_router)

# WebSocket路由必须在静态文件挂载之前直接注册，避免被mount覆盖
# 直接注册WebSocket端点，确保/ws路径优先匹配
from backend.common.functions.contact_chat.websocket_routes import websocket_chat_endpoint
app.websocket("/ws/chat/{user_id}")(websocket_chat_endpoint)

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ========== 并行初始化子任务 ==========

def _init_redis():
    """初始化Redis连接"""
    try:
        import redis
        from backend.consultant.basics.config.redis_config import ConsultantRedisConfig
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
        from backend.consultant.basics.config.database import ConsultantDatabaseConfig

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
                from backend.consultant.api.quota_routes import _create_quota_tables_if_not_exists
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
        from backend.consultant.retrieval.bm25_index_builder import ConsultantBM25IndexBuilder

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
        from backend.common.functions.rag.data_loader.chunk_and_embed import MilvusManager
        from backend.consultant.rag.rag_config import ConsultantRAGConfig

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
        from backend.common.functions.rag.models.llm_client import llm_client
        return "[规划师端] LLM客户端初始化成功", "success"
    except Exception as e:
        return f"[规划师端] LLM客户端初始化失败 ({e})", "warn"


def _init_conversation():
    """初始化会话管理模块"""
    if init_conversation_module is None:
        return "[规划师端] 会话管理模块未导入（依赖缺失）", "skip"

    try:
        from backend.common.basics.scripts.create_conversation_tables import create_conversation_tables
        from backend.common.functions.conversation.config import ConversationConfig

        success = create_conversation_tables()
        if success:
            from backend.common.functions.conversation.repository import init_pool
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
        from backend.common.functions.rag.retrieval.rag_retriever import rag_retriever
        from backend.consultant.rag.rag_config import ConsultantRAGConfig

        if ConsultantRAGConfig.ENABLE_MODEL_WARMUP:
            rag_retriever.initialize()
            rag_retriever.warmup()
            return "[规划师端] RAG检索器与模型预热成功", "success"
        else:
            return "[规划师端] 模型预热已禁用", "skip"
    except Exception as e:
        logger.error(f"[规划师端] RAG检索器或模型预热失败: {e}")
        return f"[规划师端] RAG检索器或模型预热失败 ({e})", "warn"



def preload_all_modules():
    """预加载所有模块，使用并行初始化优化启动速度"""
    print_header("正在初始化规划师端系统组件...")

    # 第零阶段：Docker环境
    from backend.consultant.basics.config.redis_config import ConsultantRedisConfig
    from backend.consultant.basics.config.database import ConsultantDatabaseConfig
    from backend.consultant.rag.rag_config import ConsultantRAGConfig
    ensure_docker_environments(
        redis_config={"host": ConsultantRedisConfig.HOST, "port": ConsultantRedisConfig.PORT, "password": ConsultantRedisConfig.PASSWORD},
        postgres_config={"host": ConsultantDatabaseConfig.DB_HOST, "port": ConsultantDatabaseConfig.DB_PORT, "user": ConsultantDatabaseConfig.DB_USER, "password": ConsultantDatabaseConfig.DB_PASSWORD, "database": ConsultantDatabaseConfig.DB_NAME},
        milvus_config={"host": ConsultantRAGConfig.MILVUS_HOST, "port": ConsultantRAGConfig.MILVUS_PORT}
    )

    # 第一阶段：Redis + 数据库并行
    print_step_loading(1, "Redis连接")
    print_step_loading(2, "数据库连接")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_redis = executor.submit(_init_redis)
        future_db = executor.submit(_init_database)

        redis_client, redis_text, redis_status = future_redis.result()
        db_available, db_text, db_status = future_db.result()

    print_step_done(1, redis_text, redis_status)
    print_step_done(2, db_text, db_status)

    # 第二阶段：BM25 + LLM + Milvus 并行
    print_step_loading(3, "企业BM25索引加载")
    print_step_loading(4, "LLM客户端初始化")
    print_step_loading(5, "Milvus向量数据库")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_bm25 = executor.submit(_init_bm25_for_enterprise)
        future_llm = executor.submit(_init_llm)
        future_milvus = executor.submit(_init_milvus)

        bm25_retriever, bm25_text, bm25_status = future_bm25.result()
        llm_text, llm_status = future_llm.result()
        milvus_text, milvus_status = future_milvus.result()

    print_step_done(3, bm25_text, bm25_status)
    print_step_done(4, llm_text, llm_status)
    print_step_done(5, milvus_text, milvus_status)

    # 第三阶段：QueryHandler初始化
    print_step_loading(6, "规划师端QueryHandler初始化")
    try:
        init_query_handler(
            redis_client=redis_client,
            bm25_retriever=bm25_retriever if bm25_retriever and bm25_retriever.is_loaded else None,
            db_available=db_available,
        )
        print_step_done(6, "[规划师端] QueryHandler初始化成功", "success")
    except Exception as e:
        print_step_done(6, f"[规划师端] QueryHandler初始化失败 ({e})", "error")

    # 第四阶段：RAG检索器预热 + 会话管理
    print_step_loading(7, "RAG检索器与模型预热")
    print_step_loading(8, "会话管理模块")
    print_step_loading(9, "F-1/F-3/F-6 业务表")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_rag = executor.submit(_init_rag)
        future_conv = executor.submit(_init_conversation)
        future_f1f3f6 = executor.submit(_init_f1_f3_f6_tables)

        rag_text, rag_status = future_rag.result()
        conv_text, conv_status = future_conv.result()
        f1f3f6_text, f1f3f6_status = future_f1f3f6.result()

    print_step_done(7, rag_text, rag_status)
    print_step_done(8, conv_text, conv_status)
    print_step_done(9, f1f3f6_text, f1f3f6_status)

    print()


def _init_f1_f3_f6_tables():
    """创建 F-1/F-3/F-6 业务表，返回 (status_text, status)"""
    try:
        from backend.common.basics.scripts.create_f1_f3_f6_tables import create_f1_f3_f6_tables
        success = create_f1_f3_f6_tables()
        if success:
            return "F-1/F-3/F-6 业务表创建成功", "success"
        return "F-1/F-3/F-6 业务表部分创建失败", "warn"
    except Exception as e:
        logger.error(f"F-1/F-3/F-6 业务表创建失败: {e}")
        return f"F-1/F-3/F-6 业务表失败 ({e})", "warn"


@app.on_event("startup")
async def startup_event():
    """服务启动事件"""
    pass  # 已在main()中预加载完成


# 挂载共享静态文件目录（在根挂载之前，避免被覆盖）
COMMON_STATIC_DIR = os.path.join(_project_root, "backend", "common", "static")
if os.path.exists(COMMON_STATIC_DIR):
    app.mount("/common", StaticFiles(directory=COMMON_STATIC_DIR), name="common_static")

# 挂载前端共享资源目录（包含Service Worker、压缩CSS等）
FRONTEND_DIR = os.path.join(_project_root, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

# 挂载静态文件目录
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main():
    """启动规划师端Web服务"""
    if ConsultantConfig is None:
        logger.error("规划师端配置模块未加载，无法启动服务")
        return

    # 验证配置
    ConsultantConfig.validate()

    # 预加载所有模块
    preload_all_modules()

    print_header("启动规划师端Web服务")
    print(f"\n  访问地址: http://localhost:{ConsultantConfig.PORT}")
    print(f"  按 Ctrl+C 停止服务\n")

    uvicorn.run(app, host=ConsultantConfig.HOST, port=ConsultantConfig.PORT)


if __name__ == "__main__":
    main()
