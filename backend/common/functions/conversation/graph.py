"""对话图 - 对话流程管理"""
from typing import Optional
from backend.common.basics.utils.logger import logger
from .manager import ConversationManager


class ConversationGraph:
    """对话图 - 管理对话流程
    
    特性：
    - 对话状态管理
    - 流程编排
    - 错误恢复
    """
    
    def __init__(self, manager: Optional[ConversationManager] = None):
        """初始化对话图
        
        Args:
            manager: 会话管理器实例
        """
        self._manager = manager or ConversationManager()
        logger.info("对话图初始化完成")
    
    def get_manager(self) -> ConversationManager:
        """获取会话管理器"""
        return self._manager
    
    def validate_conversation(self, conversation_id: str) -> bool:
        """验证会话是否有效
        
        Args:
            conversation_id: 会话ID
            
        Returns:
            bool: 是否有效
        """
        try:
            conv = self._manager.get_conversation(conversation_id)
            return conv is not None
        except Exception as e:
            logger.error(f"验证会话失败: {e}")
            return False
