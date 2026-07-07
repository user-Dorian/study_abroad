"""基于 LangGraph 的对话图实现 - 使用 checkpointer 持久化对话状态"""
from typing import TypedDict, Optional, Dict, Any, Annotated
from operator import add
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import asyncio

from conversation.manager import ConversationManager
from conversation.config import ConversationConfig
from handlers.query_handler import QueryHandler
from rag.models.llm_client import llm_client
from rag.prompts.prompt_template import prompt_manager
from config.database import DatabaseConfig
from utils.logger import logger


class ConversationState(TypedDict):
    """对话状态定义 - 包含完整的对话上下文
    
    LangGraph 的 checkpointer 会自动持久化这个状态，
    每次查询时会自动恢复之前的状态，实现对话记忆。
    
    使用 Annotated[list, add] 可以让 LangGraph 自动合并历史消息，
    而不是每次都覆盖。
    """
    # 使用 Annotated 实现消息累加，而不是每次覆盖
    messages: Annotated[list[dict], add]  # 对话消息列表（自动累加）
    conversation_id: str  # 会话ID（用于 thread_id）
    question: str  # 当前用户问题
    answer: str  # 生成的回答
    answer_source: str  # 回答来源（redis/bm25/rag/llm）
    execution_path: Annotated[list[dict], add]  # 执行路径（自动累加）
    should_generate: bool  # 是否需要 LLM 生成


class ConversationGraph:
    """对话图类，封装 LangGraph 的执行流程
    
    使用 AsyncPostgresSaver 作为 checkpointer 来持久化对话状态：
    - 每个 conversation_id 对应一个 thread_id
    - 查询时自动恢复之前的对话状态
    - 新消息自动追加到 messages 列表中
    """
    
    _checkpointer: AsyncPostgresSaver = None
    _initialized: bool = False
    
    def __init__(self, conversation_manager: ConversationManager):
        """
        初始化对话图
        
        Args:
            conversation_manager: 会话管理器实例
        """
        self.conversation_manager = conversation_manager
        self.graph = None
        logger.info("ConversationGraph 初始化中...")
    
    @classmethod
    async def _init_checkpointer(cls) -> AsyncPostgresSaver:
        """
        初始化 AsyncPostgresSaver checkpointer
        
        LangGraph 的 checkpointer 需要 async context manager 来管理连接。
        使用 psycopg 异步驱动连接 PostgreSQL。
        
        Returns:
            AsyncPostgresSaver: 已初始化的 checkpointer 实例
        """
        if cls._checkpointer is not None and cls._initialized:
            return cls._checkpointer
        
        try:
            # 构建 PostgreSQL 连接字符串（使用 psycopg 异步驱动）
            conn_string = (
                f"postgresql://{DatabaseConfig.DB_USER}:{DatabaseConfig.DB_PASSWORD}"
                f"@{DatabaseConfig.DB_HOST}:{DatabaseConfig.DB_PORT}/{DatabaseConfig.DB_NAME}"
            )
            
            logger.info(f"初始化 AsyncPostgresSaver: {DatabaseConfig.DB_HOST}:{DatabaseConfig.DB_PORT}/{DatabaseConfig.DB_NAME}")
            
            # 创建 AsyncPostgresSaver 实例
            cls._checkpointer = AsyncPostgresSaver.from_conn_string(conn_string)
            
            # 异步 setup 创建 checkpoint 表
            await cls._checkpointer.setup()
            
            cls._initialized = True
            logger.info("AsyncPostgresSaver 初始化成功，checkpoint 表已创建")
            
            return cls._checkpointer
            
        except Exception as e:
            logger.error(f"AsyncPostgresSaver 初始化失败: {e}")
            cls._initialized = False
            raise
    
    def _build_graph(self, checkpointer: AsyncPostgresSaver):
        """
        构建 LangGraph 状态图
        
        Args:
            checkpointer: 用于持久化状态的 checkpointer 实例
            
        Returns:
            编译后的 LangGraph 图
        """
        workflow = StateGraph(ConversationState)
        
        # 添加节点
        workflow.add_node("retrieve", self.retrieve)
        workflow.add_node("generate", self.generate)
        workflow.add_node("save_messages", self.save_messages)
        
        # 添加边
        workflow.add_edge(START, "retrieve")
        
        # 条件边：根据检索结果决定是否需要 LLM 生成
        workflow.add_conditional_edges(
            "retrieve",
            lambda state: "generate" if state.get("should_generate", True) else "save_messages"
        )
        
        workflow.add_edge("generate", "save_messages")
        workflow.add_edge("save_messages", END)
        
        # 编译图，传入 checkpointer
        # checkpointer 会自动保存和恢复对话状态
        compiled_graph = workflow.compile(checkpointer=checkpointer)
        
        logger.info("LangGraph 状态图编译完成，已启用 checkpointer")
        
        return compiled_graph
    
    def retrieve(self, state: ConversationState) -> dict:
        """
        执行多级检索
        
        注意：使用 checkpointer 后，state["messages"] 会包含之前的对话历史，
        我们可以直接从状态中获取历史消息，而不需要单独查询数据库。
        
        Args:
            state: 当前对话状态
            
        Returns:
            dict: 更新的状态片段
        """
        question = state["question"]
        messages = state.get("messages", [])
        
        logger.info(f"开始检索: {question[:50]}...")
        logger.info(f"当前对话历史: {len(messages)} 条消息")
        
        execution_path = []
        
        try:
            from api.routes import get_query_handler
            query_handler = get_query_handler()
            
            # Redis 精确匹配
            answer = query_handler.redis_exact_match(question)
            if answer:
                logger.info("检索成功: Redis精确匹配")
                execution_path.append({
                    "step": "retrieve",
                    "status": "success",
                    "source": "redis",
                    "detail": "Redis缓存命中"
                })
                return {
                    "answer": answer,
                    "answer_source": "redis",
                    "execution_path": execution_path,
                    "should_generate": False
                }
            
            # BM25 匹配
            matched_question, prob = query_handler.bm25_match_with_softmax(question)
            if prob >= 0.7 and matched_question:
                answer = query_handler.redis_exact_match(matched_question)
                if not answer:
                    answer = query_handler.query_database(matched_question)
                if answer:
                    logger.info("检索成功: BM25匹配")
                    execution_path.append({
                        "step": "retrieve",
                        "status": "success",
                        "source": "bm25",
                        "detail": f"BM25匹配成功，概率={prob:.4f}"
                    })
                    return {
                        "answer": answer,
                        "answer_source": "bm25",
                        "execution_path": execution_path,
                        "should_generate": False
                    }
            
            # RAG 向量检索
            answer = query_handler.rag_retrieve(question)
            if answer:
                logger.info("检索成功: RAG向量检索")
                execution_path.append({
                    "step": "retrieve",
                    "status": "success",
                    "source": "rag",
                    "detail": "RAG向量检索成功"
                })
                return {
                    "answer": answer,
                    "answer_source": "rag",
                    "execution_path": execution_path,
                    "should_generate": False
                }
            
            # 检索未命中，需要 LLM 生成
            logger.info("检索未命中，需要 LLM 生成")
            execution_path.append({
                "step": "retrieve",
                "status": "miss",
                "detail": "检索未命中，需要LLM生成"
            })
            return {
                "execution_path": execution_path,
                "should_generate": True
            }
        
        except Exception as e:
            logger.error(f"检索失败: {e}")
            execution_path.append({
                "step": "retrieve",
                "status": "error",
                "detail": f"检索异常: {str(e)}"
            })
            return {
                "execution_path": execution_path,
                "should_generate": True
            }
    
    def generate(self, state: ConversationState) -> dict:
        """
        LLM 生成回答（带对话上下文）
        
        使用 checkpointer 后，state["messages"] 会包含完整的对话历史，
        我们直接使用这些消息作为上下文来生成回答。
        
        Args:
            state: 当前对话状态
            
        Returns:
            dict: 更新的状态片段
        """
        messages = state.get("messages", [])
        question = state["question"]
        
        logger.info(f"开始 LLM 生成: 对话历史 {len(messages)} 条")
        
        execution_path = []
        
        try:
            # 构建系统提示
            system_prompt = prompt_manager.build_messages("fallback_answer", question=question)
            
            # 构建完整的消息列表
            llm_messages = []
            if system_prompt:
                llm_messages.extend(system_prompt)
            
            # 添加对话历史（排除当前问题）
            # messages 包含了所有历史消息，包括刚才添加的当前问题
            for msg in messages:
                # 只添加历史消息，不重复添加当前问题
                if msg.get("role") in ["user", "assistant"]:
                    llm_messages.append({"role": msg["role"], "content": msg["content"]})
            
            # 如果 messages 为空（首次对话），添加当前问题
            if not messages:
                llm_messages.append({"role": "user", "content": question})
            
            logger.info(f"LLM 输入消息: {len(llm_messages)} 条")
            
            # 调用 LLM
            answer = llm_client.chat(messages=llm_messages)
            
            if answer:
                logger.info(f"LLM 生成成功: {len(answer)} 字符")
                execution_path.append({
                    "step": "generate",
                    "status": "success",
                    "detail": f"LLM生成成功，长度: {len(answer)}"
                })
                return {
                    "answer": answer,
                    "answer_source": "llm",
                    "execution_path": execution_path
                }
            else:
                logger.warning("LLM 生成返回空")
                execution_path.append({
                    "step": "generate",
                    "status": "error",
                    "detail": "LLM生成返回空"
                })
                return {"execution_path": execution_path}
                
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            execution_path.append({
                "step": "generate",
                "status": "error",
                "detail": f"生成异常: {str(e)}"
            })
            return {"execution_path": execution_path}
    
    def save_messages(self, state: ConversationState) -> dict:
        """
        保存消息到状态和数据库
        
        使用 checkpointer 后，LangGraph 会自动将新消息追加到 state["messages"]，
        我们只需要：
        1. 返回新消息让它追加到状态
        2. 同步保存到数据库（用于跨会话查询）
        
        Args:
            state: 当前对话状态
            
        Returns:
            dict: 新消息（会被自动追加到 messages）
        """
        question = state["question"]
        answer = state.get("answer", "")
        
        execution_path = []
        
        try:
            # 返回新消息，LangGraph 会自动追加到 messages
            new_messages = []
            
            # 用户消息
            new_messages.append({"role": "user", "content": question})
            
            # assistant 消息（如果有回答）
            if answer:
                new_messages.append({
                    "role": "assistant",
                    "content": answer,
                    "source": state.get("answer_source", "unknown")
                })
            
            # 同步保存到数据库（用于跨会话查询和持久化）
            conversation_id = state["conversation_id"]
            self.conversation_manager.add_message(
                conversation_id=conversation_id,
                role="user",
                content=question
            )
            
            if answer:
                self.conversation_manager.add_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                    metadata={"source": state.get("answer_source", "unknown")}
                )
            
            execution_path.append({
                "step": "save_messages",
                "status": "success",
                "detail": "消息保存成功"
            })
            
            logger.info(f"消息保存成功: conversation_id={conversation_id}")
            
            return {
                "messages": new_messages,  # LangGraph 会自动追加
                "execution_path": execution_path
            }
            
        except Exception as e:
            logger.error(f"保存消息失败: {e}")
            execution_path.append({
                "step": "save_messages",
                "status": "error",
                "detail": f"保存异常: {str(e)}"
            })
            return {"execution_path": execution_path}
    
    async def query_async(self, conversation_id: str, question: str) -> dict:
        """
        执行异步对话查询
        
        使用 thread_id 来区分不同对话：
        - 每个 conversation_id 对应一个 thread_id
        - LangGraph 会自动恢复该 thread 的历史状态
        - 新消息会被追加到历史消息中
        
        Args:
            conversation_id: 会话ID（用作 thread_id）
            question: 用户问题
            
        Returns:
            dict: 包含 answer 和 execution_path
        """
        logger.info(f"开始异步对话查询: conversation_id={conversation_id}, question={question[:50]}...")
        
        try:
            # 初始化 checkpointer（如果尚未初始化）
            checkpointer = await self._init_checkpointer()
            
            # 编译图（如果尚未编译）
            if self.graph is None:
                self.graph = self._build_graph(checkpointer)
            
            # 配置 thread_id，LangGraph 会自动恢复该对话的历史状态
            config = {
                "configurable": {
                    "thread_id": conversation_id  # 使用 conversation_id 作为 thread_id
                }
            }
            
            # 构建输入状态
            # 注意：不需要手动加载历史，LangGraph 会自动从 checkpoint 恢复
            input_state = {
                "conversation_id": conversation_id,
                "question": question,
                "answer": "",
                "answer_source": "",
                "should_generate": True
            }
            
            # 执行图，LangGraph 会：
            # 1. 从 checkpoint 恢复历史状态（包括之前的 messages）
            # 2. 执行各个节点
            # 3. 将新状态保存到 checkpoint
            final_state = await self.graph.ainvoke(input_state, config)
            
            logger.info(f"对话查询完成: answer_length={len(final_state.get('answer', ''))}")
            logger.info(f"对话消息总数: {len(final_state.get('messages', []))}")
            
            return {
                "answer": final_state.get("answer", ""),
                "execution_path": final_state.get("execution_path", []),
                "messages": final_state.get("messages", [])
            }
            
        except Exception as e:
            logger.error(f"异步对话查询失败: {e}")
            return {
                "answer": "抱歉，处理您的问题时出现错误。",
                "execution_path": [{"step": "error", "detail": str(e)}],
                "messages": []
            }
    
    def query(self, conversation_id: str, question: str) -> dict:
        """
        执行同步对话查询（包装异步方法）
        
        Args:
            conversation_id: 会话ID
            question: 用户问题
            
        Returns:
            dict: 包含 answer 和 execution_path
        """
        try:
            # 使用 asyncio 运行异步查询
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在异步上下文中，创建新的 task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.query_async(conversation_id, question)
                    )
                    return future.result()
            else:
                # 如果不在异步上下文中，直接运行
                return asyncio.run(self.query_async(conversation_id, question))
                
        except Exception as e:
            logger.error(f"同步对话查询失败: {e}")
            return {
                "answer": "抱歉，处理您的问题时出现错误。",
                "execution_path": [{"step": "error", "detail": str(e)}],
                "messages": []
            }
    
    @classmethod
    async def get_state_async(cls, conversation_id: str) -> Optional[dict]:
        """
        获取指定对话的当前状态
        
        用于检查对话是否有历史记录，或者调试对话状态。
        
        Args:
            conversation_id: 会话ID
            
        Returns:
            dict | None: 对话状态，不存在时返回 None
        """
        try:
            checkpointer = await cls._init_checkpointer()
            
            config = {
                "configurable": {
                    "thread_id": conversation_id
                }
            }
            
            # 从 checkpointer 获取状态
            state_snapshot = await checkpointer.aget_tuple(config)
            
            if state_snapshot:
                return state_snapshot.checkpoint
            return None
            
        except Exception as e:
            logger.error(f"获取对话状态失败: {e}")
            return None