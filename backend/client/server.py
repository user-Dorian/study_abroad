"""Web服务入口 - 提供前端页面和API接口"""

# ====== 首先确保项目根目录在 Python 路径中 ======
import sys
from pathlib import Path
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ====== 必须在最前面设置 SSL 和环境变量，防止 aiohttp/huggingface_hub 提前初始化 ======
import os
from dotenv import load_dotenv
load_dotenv()

from backend.common.basics.bootstrap import patch_ssl
patch_ssl()

from backend.common.basics.bootstrap import (
    print_header, print_step_loading, print_step_done,
    ensure_docker_environments,
)

# ====== 以下是正常导入 ======
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
from backend.client.basics.api.routes import router as query_router, init_query_handler
from backend.client.basics.api.auth_routes import router as auth_router
from backend.client.basics.api.status_routes import router as status_router
from backend.client.basics.config.settings import Config
from backend.common.basics.utils.logger import logger
from backend.common.functions.friendship.routes import router as friendship_router
from backend.common.functions.contact_chat.routes import router as contact_chat_router
from backend.common.functions.contact_chat.websocket_routes import router as websocket_router
from backend.common.functions.unread_messages.routes import router as unread_messages_router
from backend.common.functions.account.routes import router as account_router
from backend.common.functions.profile.routes import router as profile_router
try:
    from backend.common.functions.profile.routes import student_profile_router
    logger.info("学生资料独立路由导入成功")
except ImportError as e:
    student_profile_router = None
    logger.warning(f"学生资料独立路由导入失败: {e}")
from backend.common.functions.settings.routes import router as settings_router

# F-1/F-2: 申请时间线
try:
    from backend.common.functions.application_timeline.routes import router as application_timeline_router
    logger.info("申请时间线模块导入成功")
except ImportError as e:
    application_timeline_router = None
    logger.warning(f"申请时间线模块导入失败: {e}")

# F-3: 知识库智能推荐/收藏夹
try:
    from backend.common.functions.favorites.routes import router as favorites_router
    logger.info("收藏夹模块导入成功")
except ImportError as e:
    favorites_router = None
    logger.warning(f"收藏夹模块导入失败: {e}")

# F-5: 智能消息分类
try:
    from backend.common.functions.message_classify.routes import router as message_classify_router
    logger.info("消息分类模块导入成功")
except ImportError as e:
    message_classify_router = None
    logger.warning(f"消息分类模块导入失败: {e}")

# F-6: AI 模拟面试官
try:
    from backend.common.functions.mock_interview.routes import router as mock_interview_router
    logger.info("模拟面试模块导入成功")
except ImportError as e:
    mock_interview_router = None
    logger.warning(f"模拟面试模块导入失败: {e}")

# F-7: 场景模拟
try:
    from backend.common.functions.scenario.routes import router as scenario_router
    logger.info("场景模拟模块导入成功")
except ImportError as e:
    scenario_router = None
    logger.warning(f"场景模拟模块导入失败: {e}")

# F-8: 留学规划
try:
    from backend.common.functions.planning.routes import router as planning_router
    logger.info("留学规划模块导入成功")
except ImportError as e:
    planning_router = None
    logger.warning(f"留学规划模块导入失败: {e}")

# 信息收集模块
try:
    from backend.common.functions.info_collect.routes import router as info_collect_router
    logger.info("信息收集模块导入成功")
except ImportError as e:
    info_collect_router = None
    logger.warning(f"信息收集模块导入失败: {e}")

conversation_router = None
init_conversation_module = None
try:
    from backend.client.basics.api.conversation_routes import router as conversation_router, init_conversation_module
    logger.info("会话管理模块导入成功")
except ImportError as e:
    logger.warning(f"会话管理模块导入失败，将跳过 ({e})")

app = FastAPI(title="RAG智能检索系统", version="1.0.0")

app.include_router(query_router, prefix="")
app.include_router(auth_router, prefix="")
app.include_router(status_router, prefix="")
if conversation_router:
    app.include_router(conversation_router, prefix="")
app.include_router(friendship_router)
app.include_router(contact_chat_router)
app.include_router(unread_messages_router)
app.include_router(account_router)
app.include_router(profile_router)
if student_profile_router:
    app.include_router(student_profile_router)
app.include_router(settings_router)
if application_timeline_router:
    app.include_router(application_timeline_router)
if favorites_router:
    app.include_router(favorites_router)
if message_classify_router:
    app.include_router(message_classify_router)
if mock_interview_router:
    app.include_router(mock_interview_router)
if scenario_router:
    app.include_router(scenario_router)
if planning_router:
    app.include_router(planning_router)
if info_collect_router:
    app.include_router(info_collect_router)


# ====== Health Check端点 ======

@app.get("/api/health")
async def api_health_check():
    """
    API健康检查端点 - 用于监控和负载均衡

    返回简单的健康状态信息
    """
    import time
    from datetime import datetime
    from backend.client.basics.api.status_routes import START_TIME

    return {
        "status": "ok",
        "service": "client",
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "uptime_seconds": round(time.time() - START_TIME, 2)
    }


# WebSocket路由必须在静态文件挂载之前直接注册，避免被mount覆盖
from backend.common.functions.contact_chat.websocket_routes import websocket_chat_endpoint
app.websocket("/ws/chat/{user_id}")(websocket_chat_endpoint)

# 静态文件目录
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# ========== 并行初始化子任务 ==========

def _init_redis():
    """初始化Redis连接，返回 (redis_client_or_None, status_text, status)"""
    try:
        import redis
        from backend.client.basics.config.redis_config import ClientRedisConfig
        if ClientRedisConfig.validate():
            r = redis.Redis(**ClientRedisConfig.get_connection_params())
            r.ping()
            return r, "Redis连接成功", "success"
        else:
            return None, "Redis配置不完整，将降级使用", "warn"
    except Exception as e:
        return None, f"Redis连接失败 ({e})", "warn"


def _init_database():
    """验证数据库连接并创建必要的表，返回 (db_available_bool, status_text, status)"""
    try:
        import psycopg2
        from backend.client.basics.config.database import ClientDatabaseConfig
        if ClientDatabaseConfig.validate():
            conn = psycopg2.connect(**ClientDatabaseConfig.get_connection_params())
            # 创建用户资料表
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        nickname VARCHAR(50),
                        occupation VARCHAR(100),
                        industry VARCHAR(50),
                        experience_years VARCHAR(20),
                        skills TEXT[],
                        bio TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id)
                    );
                    CREATE TABLE IF NOT EXISTS user_documents (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        filename VARCHAR(255) NOT NULL,
                        file_type VARCHAR(20),
                        file_size INTEGER,
                        file_content BYTEA,
                        parsed_text TEXT,
                        parse_status VARCHAR(20) DEFAULT 'completed',
                        upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id);
                    CREATE INDEX IF NOT EXISTS idx_user_documents_user_id ON user_documents(user_id);

                    CREATE TABLE IF NOT EXISTS student_profiles (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id VARCHAR(64) NOT NULL,
                        real_name VARCHAR(50),
                        age INTEGER,
                        gender VARCHAR(10),
                        phone VARCHAR(20),
                        wechat VARCHAR(50),
                        target_country VARCHAR(50),
                        target_level VARCHAR(20),
                        target_major VARCHAR(100),
                        current_school VARCHAR(100),
                        current_major VARCHAR(100),
                        gpa FLOAT,
                        language_type VARCHAR(20),
                        language_score FLOAT,
                        budget VARCHAR(50),
                        entry_time VARCHAR(20),
                        notes TEXT,
                        gpa_system VARCHAR(10),
                        current_grade VARCHAR(10),
                        internship VARCHAR(5),
                        internship_duration VARCHAR(10),
                        work_experience VARCHAR(5),
                        work_years VARCHAR(10),
                        completion_rate INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_student_profiles_user_id ON student_profiles(user_id);
                """)
                # 为已有数据库添加新字段（兼容旧表）
                try:
                    cur.execute("""
                        ALTER TABLE user_documents
                        ADD COLUMN IF NOT EXISTS file_content BYTEA;
                    """)
                except Exception:
                    pass
                try:
                    cur.execute("""
                        ALTER TABLE user_documents
                        ADD COLUMN IF NOT EXISTS parse_status VARCHAR(20) DEFAULT 'completed';
                    """)
                except Exception:
                    pass
                conn.commit()
            conn.close()

            # ====== P0-C 修复：自动创建 user_settings / login_history 表 ======
            settings_status = _ensure_settings_tables()

            if settings_status:
                return True, "数据库连接成功（用户资料表、用户设置表已创建）", "success"
            else:
                return True, "数据库连接成功（用户设置表创建失败，将在运行时重试）", "warn"
        else:
            return False, "数据库配置不完整", "warn"
    except Exception as e:
        return False, f"数据库连接失败 ({e})", "warn"


def _ensure_settings_tables() -> bool:
    """P0-C：启动时确保 user_settings / login_history 表存在且 user_id = UUID

    Returns:
        bool: 建表成功返回 True，失败返回 False（不阻塞服务启动）
    """
    try:
        from backend.common.basics.scripts.create_settings_tables import create_settings_tables
        import asyncio
        return asyncio.run(create_settings_tables())
    except Exception as e:
        logger.error(f"[P0-C] 建表失败: {e}")
        return False


def _init_bm25():
    """加载BM25索引（优先缓存），返回 (bm25_retriever_or_None, status_text, status)"""
    try:
        from backend.common.functions.retrieval.bm25_index_builder import BM25IndexBuilder
        builder = BM25IndexBuilder()
        bm25 = builder.initialize()
        count = len(bm25.questions) if bm25 and bm25.is_loaded else 0
        return bm25, f"BM25索引加载成功 ({count} 个问题)", "success"
    except Exception as e:
        return None, f"BM25索引加载失败 ({e})", "error"


def _init_milvus():
    """连接Milvus向量数据库，返回 (status_text, status)"""
    try:
        from backend.common.functions.rag.data_loader.chunk_and_embed import MilvusManager
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
        from backend.common.functions.rag.models.llm_client import llm_client
        return "LLM客户端初始化成功", "success"
    except Exception as e:
        return f"LLM客户端初始化失败 ({e})", "warn"


def _init_conversation():
    """初始化会话管理模块，返回 (status_text, status)"""
    if init_conversation_module is None:
        return "会话管理模块未导入（依赖缺失）", "skip"
    
    try:
        from backend.common.basics.scripts.create_conversation_tables import create_conversation_tables
        from backend.common.functions.conversation.config import ConversationConfig
        
        success = create_conversation_tables()
        if success:
            # 预热数据库连接池，避免首次请求卡住
            from backend.common.functions.conversation.repository import init_pool
            init_pool()
            
            ConversationConfig.log_config()
            init_conversation_module()
            return "会话管理模块初始化成功", "success"
        else:
            return "会话管理模块初始化失败", "error"
    except Exception as e:
        return f"会话管理模块初始化失败 ({e})", "warn"



def preload_all_modules():
    """预加载所有模块，使用并行初始化优化启动速度"""
    print_header("正在初始化系统组件...")

    # ========== 第零阶段：确保Docker依赖环境可用 ==========
    from backend.client.basics.config.redis_config import ClientRedisConfig
    from backend.client.basics.config.database import ClientDatabaseConfig
    from backend.common.functions.rag.rag_config import RAGConfig
    ensure_docker_environments(
        redis_config={"host": ClientRedisConfig.HOST, "port": ClientRedisConfig.PORT, "password": ClientRedisConfig.PASSWORD},
        postgres_config={"host": ClientDatabaseConfig.DB_HOST, "port": ClientDatabaseConfig.DB_PORT, "user": ClientDatabaseConfig.DB_USER, "password": ClientDatabaseConfig.DB_PASSWORD, "database": ClientDatabaseConfig.DB_NAME},
        milvus_config={"host": RAGConfig.MILVUS_HOST, "port": RAGConfig.MILVUS_PORT},
    )

    # ========== 第一阶段：Redis + 数据库并行连接验证 ==========
    print_step_loading(1, "Redis连接")
    print_step_loading(2, "数据库连接")

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_redis = executor.submit(_init_redis)
        future_db = executor.submit(_init_database)

        redis_client, redis_text, redis_status = future_redis.result()
        db_available, db_text, db_status = future_db.result()

    print_step_done(1, redis_text, redis_status)
    print_step_done(2, db_text, db_status)

    # ========== 第二阶段：BM25 + Milvus + LLM 并行初始化 ==========
    print_step_loading(3, "BM25索引加载")
    print_step_loading(4, "LLM客户端初始化")
    print_step_loading(5, "Milvus向量数据库")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_bm25 = executor.submit(_init_bm25)
        future_llm = executor.submit(_init_llm)
        future_milvus = executor.submit(_init_milvus)

        bm25_retriever, bm25_text, bm25_status = future_bm25.result()
        llm_text, llm_status = future_llm.result()
        milvus_text, milvus_status = future_milvus.result()

    print_step_done(3, bm25_text, bm25_status)
    print_step_done(4, llm_text, llm_status)
    print_step_done(5, milvus_text, milvus_status)

    # ========== 第三阶段：QueryHandler（复用已初始化组件） ==========
    print_step_loading(6, "QueryHandler初始化")
    try:
        init_query_handler(
            redis_client=redis_client,
            bm25_retriever=bm25_retriever if bm25_retriever and bm25_retriever.is_loaded else None,
            db_available=db_available,
        )
        print_step_done(6, "QueryHandler初始化成功", "success")
    except Exception as e:
        print_step_done(6, f"QueryHandler初始化失败 ({e})", "error")

    # ========== 第四阶段：RAG检索器与模型预热 + 会话管理模块 ==========
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


def _init_rag():
    """初始化RAG检索器与模型预热，返回 (status_text, status)"""
    try:
        from backend.common.functions.rag.retrieval.rag_retriever import rag_retriever
        from backend.common.functions.rag.rag_config import RAGConfig

        if RAGConfig.ENABLE_MODEL_WARMUP:
            rag_retriever.initialize()
            rag_retriever.warmup()
            return "RAG检索器与模型预热成功", "success"
        else:
            return "模型预热已禁用", "skip"
    except Exception as e:
        logger.error(f"RAG检索器或模型预热失败: {e}")
        return f"RAG检索器或模型预热失败 ({e})", "warn"


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

# 挂载静态文件目录 - 提供前端页面（html=True 支持自动查找 index.html）
# 注意：mount 必须在 API 路由之后，避免覆盖 API 路由
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def main():
    """启动Web服务"""
    # 先预加载所有模块
    preload_all_modules()
    
    print_header("启动Web服务")
    print(f"\n  访问地址: http://localhost:{Config.PORT}")
    print(f"  按 Ctrl+C 停止服务\n")

    uvicorn.run(app, host=Config.HOST, port=Config.PORT)


if __name__ == "__main__":
    main()
