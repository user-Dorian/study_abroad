"""会话管理器 - 管理用户对话会话"""
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from backend.common.basics.utils.logger import logger
from .repository import get_conversation_repo


class ConversationManager:
    """会话管理器 - 管理用户对话会话
    
    特性：
    - 会话CRUD操作
    - 消息历史管理
    - 自动标题生成
    - 完善的错误处理
    """
    
    def create_conversation(
        self,
        title: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建新会话
        
        Args:
            title: 会话标题
            user_id: 用户ID
            
        Returns:
            Dict: 会话信息
        """
        try:
            conv_id = str(uuid.uuid4())
            title = title or "新对话"
            
            repo = get_conversation_repo()
            repo.create_conversation(
                conversation_id=conv_id,
                user_id=user_id,
                title=title
            )
            
            logger.info(f"创建会话成功: conv_id={conv_id}, user_id={user_id}")
            
            return {
                "id": conv_id,
                "user_id": user_id,
                "title": title,
                "created_at": datetime.utcnow().isoformat(),
                "message_count": 0,
            }
            
        except Exception as e:
            logger.error(f"创建会话失败: {e}", exc_info=True)
            raise
    
    def get_conversation(
        self,
        conversation_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取会话信息
        
        Args:
            conversation_id: 会话ID
            user_id: 用户ID
            
        Returns:
            Dict: 会话信息
        """
        try:
            repo = get_conversation_repo()
            conv = repo.get_conversation(conversation_id, user_id)
            return conv
        except Exception as e:
            logger.error(f"获取会话失败: {e}", exc_info=True)
            return None
    
    def list_conversations(
        self,
        user_id: Optional[str] = None,
        dialogue_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取会话列表
        
        Args:
            user_id: 用户ID
            dialogue_type: 对话类型（ai_chat/contact_chat）
            
        Returns:
            List[Dict]: 会话列表
        """
        try:
            repo = get_conversation_repo()
            convs = repo.list_conversations(user_id, dialogue_type)
            return convs
        except Exception as e:
            logger.error(f"获取会话列表失败: {e}", exc_info=True)
            return []
    
    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        """重命名会话

        Args:
            conversation_id: 会话ID
            title: 新标题

        Returns:
            bool: 是否成功
        """
        try:
            repo = get_conversation_repo()
            success = repo.update_conversation_title(conversation_id, title)

            if success:
                logger.info(f"重命名会话成功: conv_id={conversation_id}, title={title}")
            return success

        except Exception as e:
            logger.error(f"重命名会话失败: {e}", exc_info=True)
            return False

    def update_conversation_title(self, conversation_id: str, title: str) -> bool:
        """更新会话标题（rename_conversation的别名，用于API一致性）

        Args:
            conversation_id: 会话ID
            title: 新标题

        Returns:
            bool: 是否成功
        """
        return self.rename_conversation(conversation_id, title)
    
    def delete_conversation(
        self,
        conversation_id: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """删除会话
        
        Args:
            conversation_id: 会话ID
            user_id: 用户ID
            
        Returns:
            bool: 是否成功
        """
        try:
            repo = get_conversation_repo()
            success = repo.delete_conversation(conversation_id, user_id)
            
            if success:
                logger.info(f"删除会话成功: conv_id={conversation_id}")
            return success
            
        except Exception as e:
            logger.error(f"删除会话失败: {e}", exc_info=True)
            return False
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """添加消息到会话
        
        Args:
            conversation_id: 会话ID
            role: 角色（user/assistant）
            content: 消息内容
            metadata: 元数据
            
        Returns:
            Dict: 消息信息
        """
        try:
            message_id = str(uuid.uuid4())
            repo = get_conversation_repo()
            
            repo.add_message(
                message_id=message_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata=metadata
            )
            
            return {
                "id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "metadata": metadata,
                "created_at": datetime.utcnow().isoformat(),
            }
            
        except Exception as e:
            logger.error(f"添加消息失败: {e}", exc_info=True)
            raise
    
    def get_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取会话消息列表
        
        Args:
            conversation_id: 会话ID
            limit: 返回数量限制
            
        Returns:
            List[Dict]: 消息列表
        """
        try:
            repo = get_conversation_repo()
            messages = repo.get_messages(conversation_id, limit)
            return messages
        except Exception as e:
            logger.error(f"获取消息列表失败: {e}", exc_info=True)
            return []
    
    def get_history_for_llm(self, conversation_id: str) -> List[Dict[str, str]]:
        """获取用于LLM的对话历史（格式化）
        
        Args:
            conversation_id: 会话ID
            
        Returns:
            List[Dict]: 格式化的对话历史
        """
        try:
            repo = get_conversation_repo()
            messages = repo.get_messages(conversation_id, limit=20)
            
            # 格式化为LLM格式
            formatted = []
            for msg in messages:
                formatted.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
            
            return formatted
            
        except Exception as e:
            logger.error(f"获取对话历史失败: {e}", exc_info=True)
            return []
    
    def find_empty_conversation(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """查找用户的空对话
        
        Args:
            user_id: 用户ID
            
        Returns:
            Dict: 空对话信息
        """
        try:
            repo = get_conversation_repo()
            conv = repo.find_empty_conversation(user_id)
            return conv
        except Exception as e:
            logger.error(f"查找空对话失败: {e}", exc_info=True)
            return None
