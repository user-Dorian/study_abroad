"""会话管理器 - 整合会话和消息的仓库层，提供业务逻辑封装"""
from typing import Optional, Dict
import threading

from common.conversation.repository import ConversationRepository, MessageRepository
from common.conversation.repository import AsyncConversationRepository, AsyncMessageRepository
from common.conversation.config import ConversationConfig
from common.utils.logger import logger


class ConversationManager:
    """会话管理器类
    
    整合 ConversationRepository 和 MessageRepository，提供完整的会话管理业务逻辑。
    包含会话的创建、查询、重命名、删除，以及消息的添加、查询和历史记录获取等功能。
    支持上下文压缩：长对话时自动压缩旧轮次，保留核心摘要。
    """
    
    def __init__(self):
        """初始化管理器，创建仓库实例"""
        self._conv_repo = ConversationRepository()
        self._msg_repo = MessageRepository()
        # 阶段2数据库异步化：异步仓库实例（延迟初始化，首次访问时创建）
        self._async_conv_repo = None
        self._async_msg_repo = None
        # 上下文压缩缓存 {conversation_id: {"summary": str, "count": int}}
        self._compression_cache: Dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        logger.info("ConversationManager 初始化成功")

    def _get_async_repos(self):
        """阶段2数据库异步化：延迟获取异步仓库实例"""
        if self._async_conv_repo is None:
            self._async_conv_repo = AsyncConversationRepository()
            self._async_msg_repo = AsyncMessageRepository()
        return self._async_conv_repo, self._async_msg_repo
    
    def create_conversation(self, title: str = None, user_id: Optional[str] = None) -> dict:
        """
        创建新会话
        
        Args:
            title: 会话标题，为 None 时使用默认标题
            user_id: 可选的用户ID
            
        Returns:
            dict: 包含 {id, title, created_at, updated_at} 的会话信息
        """
        try:
            # 如果标题为空，使用默认标题
            if title is None:
                title = ConversationConfig.DEFAULT_TITLE
                logger.debug(f"使用默认标题: {title}")
            
            # 调用仓库层创建会话
            result = self._conv_repo.create_conversation(title, user_id=user_id)
            logger.info(f"创建会话成功: id={result['id']}, title={title}")
            return result
            
        except Exception as e:
            logger.error(f"创建会话失败: title={title}, error={e}")
            raise
    
    def get_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """
        获取单个会话
        
        Args:
            conversation_id: 会话ID
            user_id: 可选的用户ID
            
        Returns:
            dict | None: 会话信息字典，不存在时返回 None
        """
        try:
            result = self._conv_repo.get_conversation(conversation_id, user_id=user_id)
            if result is None:
                logger.debug(f"会话不存在: id={conversation_id}")
            else:
                logger.debug(f"获取会话成功: id={conversation_id}")
            return result
            
        except Exception as e:
            logger.error(f"获取会话失败: id={conversation_id}, error={e}")
            raise
    
    def list_conversations(self, user_id: Optional[str] = None) -> list:
        """
        获取所有会话列表，按 updated_at 降序排列

        Args:
            user_id: 可选的用户ID

        Returns:
            list[dict]: 会话信息列表
        """
        try:
            result = self._conv_repo.list_conversations(user_id=user_id)
            logger.debug(f"获取会话列表成功: 共 {len(result)} 条")
            return result

        except Exception as e:
            logger.error(f"获取会话列表失败: error={e}")
            raise

    def find_empty_conversation(self, user_id: str) -> Optional[dict]:
        """
        查找用户的空对话（无消息），每人最多一个

        Args:
            user_id: 用户ID

        Returns:
            dict | None: 空对话信息
        """
        try:
            result = self._conv_repo.find_empty_conversation(user_id)
            return result
        except Exception as e:
            logger.error(f"查找空对话失败: user_id={user_id}, error={e}")
            raise

    def rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        """
        重命名会话
        
        Args:
            conversation_id: 会话ID
            new_title: 新标题
            
        Returns:
            bool: 重命名成功返回 True，会话不存在返回 False
        """
        try:
            result = self._conv_repo.update_title(conversation_id, new_title)
            if result:
                logger.info(f"重命名会话成功: id={conversation_id}, title={new_title}")
            else:
                logger.warning(f"重命名会话失败，会话不存在: id={conversation_id}")
            return result
            
        except Exception as e:
            logger.error(f"重命名会话失败: id={conversation_id}, error={e}")
            raise
    
    def delete_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """
        删除会话（级联删除关联消息）
        
        Args:
            conversation_id: 会话ID
            user_id: 可选的用户ID
            
        Returns:
            bool: 删除成功返回 True，会话不存在返回 False
        """
        try:
            result = self._conv_repo.delete_conversation(conversation_id, user_id=user_id)
            if result:
                logger.info(f"删除会话成功: id={conversation_id}")
            else:
                logger.warning(f"删除会话失败，会话不存在: id={conversation_id}")
            return result
            
        except Exception as e:
            logger.error(f"删除会话失败: id={conversation_id}, error={e}")
            raise
    
    def get_messages(self, conversation_id: str, limit: int = None) -> list:
        """
        获取消息列表，按 created_at 升序排列
        
        Args:
            conversation_id: 会话ID
            limit: 最大返回条数，为 None 时使用默认分页大小
            
        Returns:
            list[dict]: 消息列表
        """
        try:
            # 如果 limit 为空，使用默认分页大小
            if limit is None:
                limit = ConversationConfig.MESSAGES_PAGE_SIZE
                logger.debug(f"使用默认分页大小: {limit}")
            
            result = self._msg_repo.get_messages(conversation_id, limit)
            logger.debug(f"获取消息列表成功: conversation_id={conversation_id}, 共 {len(result)} 条")
            return result
            
        except Exception as e:
            logger.error(f"获取消息列表失败: conversation_id={conversation_id}, error={e}")
            raise
    
    def add_message(self, conversation_id: str, role: str, content: str, metadata: dict = None) -> dict:
        """
        添加消息并更新会话时间戳
        
        Args:
            conversation_id: 会话ID
            role: 消息角色（如 user / assistant / system）
            content: 消息内容
            metadata: 可选的元数据字典
            
        Returns:
            dict: 包含消息信息的字典
        """
        try:
            # 保存消息
            msg_result = self._msg_repo.save_message(conversation_id, role, content, metadata)
            logger.info(f"添加消息成功: id={msg_result['id']}, conversation_id={conversation_id}, role={role}")
            
            # 更新会话时间戳
            self._conv_repo.update_timestamp(conversation_id)
            logger.debug(f"更新会话时间戳成功: id={conversation_id}")
            
            # 自动标题生成：当添加的是 user 消息且会话标题为默认标题时，生成新标题
            if role == "user":
                self._auto_generate_title(conversation_id, content)
            
            return msg_result
            
        except Exception as e:
            logger.error(f"添加消息失败: conversation_id={conversation_id}, role={role}, error={e}")
            raise
    
    def _auto_generate_title(self, conversation_id: str, user_content: str) -> None:
        """
        自动根据用户第一条消息生成会话标题
        
        触发条件：
        1. 会话标题为默认标题
        2. 当前消息是用户消息（在 add_message 中已判断）
        
        Args:
            conversation_id: 会话ID
            user_content: 用户消息内容
        """
        try:
            # 获取当前会话信息
            conversation = self._conv_repo.get_conversation(conversation_id)
            if conversation is None:
                logger.warning(f"自动标题生成失败，会话不存在: id={conversation_id}")
                return
            
            # 检查是否为默认标题
            if conversation["title"] != ConversationConfig.DEFAULT_TITLE:
                logger.debug(f"会话已有自定义标题，跳过自动生成: id={conversation_id}, title={conversation['title']}")
                return
            
            # 检查是否为第一条用户消息
            messages = self._msg_repo.get_messages(conversation_id, limit=10)
            user_messages = [msg for msg in messages if msg["role"] == "user"]
            if len(user_messages) > 1:
                logger.debug(f"会话已有多条用户消息，跳过自动生成: id={conversation_id}")
                return
            
            # 调用 LLM 生成标题
            logger.info(f"开始自动生成会话标题: conversation_id={conversation_id}")
            new_title = self._generate_title_with_llm(user_content)
            
            if new_title:
                # 更新会话标题
                self._conv_repo.update_title(conversation_id, new_title)
                logger.info(f"自动标题生成成功: conversation_id={conversation_id}, title={new_title}")
            else:
                logger.warning(f"自动标题生成失败，LLM返回空结果: conversation_id={conversation_id}")
                
        except Exception as e:
            # 标题生成失败不应影响消息添加，只记录错误
            logger.error(f"自动标题生成异常: conversation_id={conversation_id}, error={e}")
    
    def _generate_title_with_llm(self, user_content: str) -> str:
        """
        调用 LLM 根据用户消息生成会话标题
        
        Args:
            user_content: 用户消息内容
            
        Returns:
            str: 生成的标题，失败返回 None
        """
        try:
            from common.rag.models.llm_client import llm_client
            
            # 构建生成标题的提示词
            prompt = f"""请根据以下用户消息，生成一个简洁的会话标题（不超过{ConversationConfig.TITLE_MAX_LENGTH}个字）。
要求：
1. 标题要能概括用户问题的核心内容
2. 标题要简洁明了，适合作为会话标题
3. 只返回标题文本，不要有其他内容

用户消息：{user_content}

请生成标题："""
            
            # 调用 LLM
            title = llm_client.chat(prompt=prompt, temperature=0.3)
            
            if title:
                # 清理标题，去除多余空白和引号
                title = title.strip().strip('"\'')
                # 限制长度
                if len(title) > ConversationConfig.TITLE_MAX_LENGTH:
                    title = title[:ConversationConfig.TITLE_MAX_LENGTH]
                return title
            
            return None
            
        except Exception as e:
            logger.error(f"LLM生成标题失败: error={e}")
            return None

    async def async_generate_title_with_llm(self, user_content: str) -> str:
        """
        异步调用 LLM 根据用户消息生成会话标题（阶段4异步改造）

        调用 await self.llm_client.async_chat(...)，避免阻塞事件循环。
        同步版 _generate_title_with_llm 保留不变，向后兼容。

        Args:
            user_content: 用户消息内容

        Returns:
            str: 生成的标题，失败返回 None
        """
        try:
            from common.rag.models.llm_client import llm_client

            # 构建生成标题的提示词（与同步版保持一致）
            prompt = f"""请根据以下用户消息，生成一个简洁的会话标题（不超过{ConversationConfig.TITLE_MAX_LENGTH}个字）。
要求：
1. 标题要能概括用户问题的核心内容
2. 标题要简洁明了，适合作为会话标题
3. 只返回标题文本，不要有其他内容

用户消息：{user_content}

请生成标题："""

            # 异步调用 LLM
            title = await llm_client.async_chat(prompt=prompt, temperature=0.3)

            if title:
                # 清理标题，去除多余空白和引号
                title = title.strip().strip('"\'')
                # 限制长度
                if len(title) > ConversationConfig.TITLE_MAX_LENGTH:
                    title = title[:ConversationConfig.TITLE_MAX_LENGTH]
                return title

            return None

        except Exception as e:
            logger.error(f"异步LLM生成标题失败: error={e}")
            return None
    
    def _count_tokens(self, text: str) -> int:
        """
        估算文本的token数量
        
        计算方法：
        - 英文字符和数字：1字符 ≈ 1 token
        - 中文字符：1字符 ≈ 1.5 token（中文通常更短但包含更多信息）
        - 空格、标点等：不计入或少量计入
        
        Args:
            text: 要计算的文本
            
        Returns:
            int: 估算的token数量
        """
        if not text:
            return 0
        
        import re
        
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_chars = len(re.findall(r'[a-zA-Z0-9]', text))
        other_chars = len(text) - chinese_chars - english_chars
        
        return int(chinese_chars * ConversationConfig.CHINESE_TOKEN_RATIO + english_chars + other_chars * 0.5)
    
    def _calculate_history_tokens(self, history: list) -> int:
        """
        计算对话历史的总token数
        
        Args:
            history: 对话历史消息列表
            
        Returns:
            int: 总token数
        """
        total_tokens = 0
        for msg in history:
            content = msg.get("content", "")
            total_tokens += self._count_tokens(content)
            total_tokens += 4  # 每条消息的role字段约4个token
        return total_tokens
    
    def get_history_for_llm(self, conversation_id: str, max_turns: int = None) -> list:
        """
        获取对话历史，格式为 [{"role": "user/assistant", "content": "..."}]
        
        支持基于token的上下文压缩：当对话历史的token占用量超过 COMPRESSION_TOKEN_LIMIT 时，
        旧轮次会被LLM汇总为一段精简摘要，保留最近的完整消息（基于token数）。
        
        Args:
            conversation_id: 会话ID
            max_turns: 最大轮数（备用限制），为 None 时使用配置中的默认值
            
        Returns:
            list[dict]: 对话历史列表
        """
        try:
            if max_turns is None:
                max_turns = ConversationConfig.MAX_HISTORY_TURNS
                logger.debug(f"使用默认历史轮数: {max_turns}")
            
            msg_limit = max_turns * 2
            messages = self._msg_repo.get_recent_messages(conversation_id, msg_limit)
            
            history = []
            for msg in messages:
                if msg["role"] in ["user", "assistant"]:
                    history.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
            
            actual_turns = len(history) // 2
            total_tokens = self._calculate_history_tokens(history)
            
            logger.debug(
                f"对话历史统计: conversation_id={conversation_id}, "
                f"轮数={actual_turns}, 消息数={len(history)}, token数={total_tokens}"
            )
            
            # 上下文压缩：当token数超过阈值时触发
            if (ConversationConfig.COMPRESSION_ENABLED
                    and total_tokens > ConversationConfig.COMPRESSION_TOKEN_LIMIT):
                history = self._compress_history_by_tokens(conversation_id, history, total_tokens)
            
            logger.debug(
                f"获取对话历史成功: conversation_id={conversation_id}, "
                f"轮数={actual_turns}, 最终消息数={len(history)}, token数={self._calculate_history_tokens(history)}"
            )
            return history
            
        except Exception as e:
            logger.error(f"获取对话历史失败: conversation_id={conversation_id}, error={e}")
            return []
    
    def _compress_history_by_tokens(self, conversation_id: str, history: list, total_tokens: int) -> list:
        """
        基于token的上下文压缩：当token数超过阈值时，将旧消息汇总为摘要
        
        策略：
        1. 计算需要释放的token数 = 当前token数 - 目标token数
        2. 从历史消息头部开始累加，找到需要压缩的消息范围
        3. 保留最近的完整消息（至少保留 COMPRESSION_KEEP_TURNS 轮）
        4. 将旧消息汇总为LLM摘要，如果LLM不可用则使用文本截断
        
        Args:
            conversation_id: 会话ID
            history: 原始历史消息列表
            total_tokens: 当前总token数
            
        Returns:
            list[dict]: 压缩后的历史消息列表
        """
        target_tokens = ConversationConfig.COMPRESSION_TARGET_TOKENS
        keep_turns = ConversationConfig.COMPRESSION_KEEP_TURNS
        
        # 计算需要保留的最近消息（保底）
        keep_msg_count = keep_turns * 2
        if len(history) <= keep_msg_count:
            logger.debug(f"消息数不足{keep_turns}轮，无需压缩: conversation_id={conversation_id}")
            return history
        
        recent_messages = history[-keep_msg_count:]
        recent_tokens = self._calculate_history_tokens(recent_messages)
        
        # 如果最近的消息已经超过目标token数，返回最近消息（不压缩）
        if recent_tokens >= target_tokens:
            logger.debug(f"最近{keep_turns}轮消息已达{recent_tokens}token，无需压缩旧消息")
            return recent_messages
        
        # 需要压缩的旧消息
        old_messages = history[:-keep_msg_count]
        
        # 检查缓存是否有效
        cache_key = f"{conversation_id}_compressed"
        old_msg_count = len(old_messages)
        
        with self._cache_lock:
            cached = self._compression_cache.get(cache_key)
            if cached and cached.get("count") == old_msg_count:
                logger.debug(f"使用缓存的上下文压缩摘要: conversation_id={conversation_id}")
                compressed_summary = cached["summary"]
            else:
                compressed_summary = self._generate_context_summary(old_messages)
                self._compression_cache[cache_key] = {
                    "summary": compressed_summary,
                    "count": old_msg_count
                }
                logger.info(f"基于token的上下文压缩完成: conversation_id={conversation_id}, "
                           f"压缩 {old_msg_count} 条消息 → 摘要, 保留 {keep_turns} 轮完整消息")
        
        compressed_history = [
            {
                "role": "user",
                "content": f"【以下是与用户之前的对话摘要】\n{compressed_summary}"
            }
        ]
        compressed_history.extend(recent_messages)
        
        return compressed_history
    
    def _compress_history(self, conversation_id: str, history: list, total_turns: int) -> list:
        """
        旧版压缩方法（基于轮数），保留向后兼容
        
        Args:
            conversation_id: 会话ID
            history: 原始历史消息列表
            total_turns: 总轮数
            
        Returns:
            list[dict]: 压缩后的历史消息列表
        """
        logger.warning(f"使用旧版基于轮数的压缩方法，请迁移到基于token的压缩")
        keep_turns = ConversationConfig.COMPRESSION_KEEP_TURNS
        old_turns_count = total_turns - keep_turns
        
        old_msgs_count = old_turns_count * 2
        old_messages = history[:old_msgs_count]
        recent_messages = history[old_msgs_count:]
        
        cache_key = f"{conversation_id}_compressed"
        with self._cache_lock:
            cached = self._compression_cache.get(cache_key)
            if cached and cached.get("count") == old_msgs_count:
                compressed_summary = cached["summary"]
            else:
                compressed_summary = self._generate_context_summary(old_messages)
                self._compression_cache[cache_key] = {
                    "summary": compressed_summary,
                    "count": old_msgs_count
                }
        
        compressed_history = [
            {
                "role": "user",
                "content": f"【以下是与用户之前的对话摘要】\n{compressed_summary}"
            }
        ]
        compressed_history.extend(recent_messages)
        
        return compressed_history
    
    # ====== 阶段2数据库异步化：异步 CRUD 方法（保留同步方法不变，新增 async 版本） ======

    async def async_create_conversation(self, title: str = None, user_id: Optional[str] = None) -> dict:
        """异步创建新会话"""
        async_conv_repo, _ = self._get_async_repos()
        if title is None:
            title = ConversationConfig.DEFAULT_TITLE
        return await async_conv_repo.create_conversation(title, user_id=user_id)

    async def async_get_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> Optional[dict]:
        """异步获取单个会话"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.get_conversation(conversation_id, user_id=user_id)

    async def async_list_conversations(self, user_id: Optional[str] = None) -> list:
        """异步获取会话列表"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.list_conversations(user_id=user_id)

    async def async_find_empty_conversation(self, user_id: str) -> Optional[dict]:
        """异步查找用户的空对话"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.find_empty_conversation(user_id)

    async def async_rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        """异步重命名会话"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.update_title(conversation_id, new_title)

    async def async_update_title(self, conversation_id: str, title: str, user_id: Optional[str] = None) -> bool:
        """异步更新会话标题"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.update_title(conversation_id, title, user_id=user_id)

    async def async_update_timestamp(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """异步更新会话时间戳"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.update_timestamp(conversation_id, user_id=user_id)

    async def async_delete_conversation(self, conversation_id: str, user_id: Optional[str] = None) -> bool:
        """异步删除会话"""
        async_conv_repo, _ = self._get_async_repos()
        return await async_conv_repo.delete_conversation(conversation_id, user_id=user_id)

    async def async_add_message(self, conversation_id: str, role: str, content: str, metadata: dict = None) -> dict:
        """异步添加消息并更新会话时间戳"""
        _, async_msg_repo = self._get_async_repos()
        msg_result = await async_msg_repo.save_message(conversation_id, role, content, metadata)
        await self.async_update_timestamp(conversation_id)
        if role == "user":
            await self.async_auto_generate_title(conversation_id, content)
        return msg_result

    async def async_auto_generate_title(self, conversation_id: str, user_content: str) -> None:
        """异步自动根据用户第一条消息生成会话标题（异步版）"""
        try:
            async_conv_repo, async_msg_repo = self._get_async_repos()
            conversation = await async_conv_repo.get_conversation(conversation_id)
            if conversation is None:
                return
            if conversation["title"] != ConversationConfig.DEFAULT_TITLE:
                return
            messages = await async_msg_repo.get_messages(conversation_id, limit=10)
            user_messages = [msg for msg in messages if msg["role"] == "user"]
            if len(user_messages) > 1:
                return
            new_title = await self.async_generate_title_with_llm(user_content)
            if new_title:
                await async_conv_repo.update_title(conversation_id, new_title)
        except Exception as e:
            logger.error(f"异步自动标题生成异常: conversation_id={conversation_id}, error={e}")

    async def async_get_messages(self, conversation_id: str, limit: int = None) -> list:
        """异步获取消息列表"""
        _, async_msg_repo = self._get_async_repos()
        if limit is None:
            limit = ConversationConfig.MESSAGES_PAGE_SIZE
        return await async_msg_repo.get_messages(conversation_id, limit)

    async def async_get_recent_messages(self, conversation_id: str, limit: int) -> list:
        """异步获取最近消息列表"""
        _, async_msg_repo = self._get_async_repos()
        return await async_msg_repo.get_recent_messages(conversation_id, limit)

    async def async_get_history_for_llm(self, conversation_id: str, max_turns: int = None) -> list:
        """异步获取对话历史，格式为 [{"role": "user/assistant", "content": "..."}]"""
        _, async_msg_repo = self._get_async_repos()
        if max_turns is None:
            max_turns = ConversationConfig.MAX_HISTORY_TURNS
        msg_limit = max_turns * 2
        messages = await async_msg_repo.get_recent_messages(conversation_id, msg_limit)
        history = []
        for msg in messages:
            if msg["role"] in ["user", "assistant"]:
                history.append({"role": msg["role"], "content": msg["content"]})
        total_tokens = self._calculate_history_tokens(history)
        if (ConversationConfig.COMPRESSION_ENABLED
                and total_tokens > ConversationConfig.COMPRESSION_TOKEN_LIMIT):
            history = self._compress_history_by_tokens(conversation_id, history, total_tokens)
        return history

    def _generate_context_summary(self, old_messages: list) -> str:
        """
        使用LLM将旧对话消息汇总为一段精简摘要
        
        如果LLM调用失败，使用备用方案：直接拼接消息内容。
        
        Args:
            old_messages: 需要压缩的旧消息列表
            
        Returns:
            str: 压缩后的摘要文本
        """
        try:
            from common.rag.models.llm_client import llm_client
            
            # 构建对话文本
            dialogue_text = ""
            for msg in old_messages:
                role = "用户" if msg["role"] == "user" else "留学通"
                dialogue_text += f"{role}：{msg['content']}\n"
            
            # 调用LLM生成摘要
            prompt = f"""请将以下对话内容压缩为一段简洁的摘要（200字以内），保留关键信息和上下文关联。

对话内容：
{dialogue_text}

摘要要求：
1. 保留用户的核心问题和已获得的关键信息
2. 保留对话的逻辑脉络
3. 用第三人称简述
4. 不超过200字

摘要："""
            
            summary = llm_client.chat(prompt=prompt, temperature=0.3)
            
            if summary:
                summary = summary.strip().strip('"\'')
                logger.debug(f"LLM上下文压缩摘要生成成功: {len(summary)} 字")
                return summary
            
        except Exception as e:
            logger.warning(f"LLM上下文压缩失败，使用文本截断方案: {e}")
        
        # 备用方案：拼接消息内容并截断
        summary_parts = []
        for msg in old_messages:
            role = "用户" if msg["role"] == "user" else "顾问"
            # 截取每条消息的前100字
            content = msg["content"][:100] if len(msg["content"]) > 100 else msg["content"]
            summary_parts.append(f"{role}: {content}")
        
        fallback_summary = " | ".join(summary_parts)
        if len(fallback_summary) > 500:
            fallback_summary = fallback_summary[:500] + "..."
        
        logger.debug(f"使用文本截断方案作为上下文摘要: {len(fallback_summary)} 字")
        return fallback_summary

    async def async_generate_context_summary(self, old_messages: list) -> str:
        """
        异步使用LLM将旧对话消息汇总为一段精简摘要（阶段4异步改造）

        调用 await llm_client.async_chat(...)，避免阻塞事件循环。
        如果LLM调用失败，使用备用方案：直接拼接消息内容（与同步版保持一致）。
        同步版 _generate_context_summary 保留不变，向后兼容。

        Args:
            old_messages: 需要压缩的旧消息列表

        Returns:
            str: 压缩后的摘要文本
        """
        try:
            from common.rag.models.llm_client import llm_client

            # 构建对话文本（与同步版保持一致）
            dialogue_text = ""
            for msg in old_messages:
                role = "用户" if msg["role"] == "user" else "留学通"
                dialogue_text += f"{role}：{msg['content']}\n"

            # 异步调用LLM生成摘要
            prompt = f"""请将以下对话内容压缩为一段简洁的摘要（200字以内），保留关键信息和上下文关联。

对话内容：
{dialogue_text}

摘要要求：
1. 保留用户的核心问题和已获得的关键信息
2. 保留对话的逻辑脉络
3. 用第三人称简述
4. 不超过200字

摘要："""

            summary = await llm_client.async_chat(prompt=prompt, temperature=0.3)

            if summary:
                summary = summary.strip().strip('"\'')
                logger.debug(f"异步LLM上下文压缩摘要生成成功: {len(summary)} 字")
                return summary

        except Exception as e:
            logger.warning(f"异步LLM上下文压缩失败，使用文本截断方案: {e}")

        # 备用方案：拼接消息内容并截断（与同步版保持一致）
        summary_parts = []
        for msg in old_messages:
            role = "用户" if msg["role"] == "user" else "顾问"
            # 截取每条消息的前100字
            content = msg["content"][:100] if len(msg["content"]) > 100 else msg["content"]
            summary_parts.append(f"{role}: {content}")

        fallback_summary = " | ".join(summary_parts)
        if len(fallback_summary) > 500:
            fallback_summary = fallback_summary[:500] + "..."

        logger.debug(f"异步上下文压缩使用文本截断方案: {len(fallback_summary)} 字")
        return fallback_summary
