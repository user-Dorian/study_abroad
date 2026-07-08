"""会话配置 - 采用面向对象管理"""
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


class ConversationConfig:
    """会话管理配置类
    
    管理对话历史、标题生成、消息分页等相关配置项。
    所有配置项均通过环境变量读取，支持灵活的环境配置。
    """
    
    # ==================== 对话历史配置 ====================
    
    # 最多加载的对话历史轮数
    # 用于控制上下文窗口大小，避免token超限
    # 环境变量: CONVERSATION_MAX_HISTORY_TURNS
    MAX_HISTORY_TURNS = int(os.getenv("CONVERSATION_MAX_HISTORY_TURNS", "10"))
    
    # ==================== 标题生成配置 ====================
    
    # 是否自动提取会话标题
    # 启用后，系统会根据对话内容自动生成会话标题
    # 环境变量: CONVERSATION_AUTO_TITLE_ENABLED
    AUTO_TITLE_ENABLED = os.getenv("CONVERSATION_AUTO_TITLE_ENABLED", "true").lower() == "true"
    
    # 标题最大长度
    # 限制自动生成的标题长度，避免过长
    # 环境变量: CONVERSATION_TITLE_MAX_LENGTH
    TITLE_MAX_LENGTH = int(os.getenv("CONVERSATION_TITLE_MAX_LENGTH", "20"))
    
    # 默认会话标题
    # 当无法自动生成标题时使用的默认值
    # 环境变量: CONVERSATION_DEFAULT_TITLE
    DEFAULT_TITLE = os.getenv("CONVERSATION_DEFAULT_TITLE", "新对话")
    
    # ==================== 上下文压缩配置 ====================
    
    # 是否启用上下文压缩
    # 环境变量: CONVERSATION_COMPRESSION_ENABLED
    COMPRESSION_ENABLED = os.getenv("CONVERSATION_COMPRESSION_ENABLED", "true").lower() == "true"
    
    # 上下文压缩阈值（token数）
    # 当对话历史的token占用量超过此值时，触发上下文压缩
    # 基于token计数更精确，避免上下文溢出
    # 环境变量: CONVERSATION_COMPRESSION_TOKEN_LIMIT
    COMPRESSION_TOKEN_LIMIT = int(os.getenv("CONVERSATION_COMPRESSION_TOKEN_LIMIT", "8192"))
    
    # 压缩后保留的目标token数
    # 压缩后，保留的对话历史token数不超过此值
    # 环境变量: CONVERSATION_COMPRESSION_TARGET_TOKENS
    COMPRESSION_TARGET_TOKENS = int(os.getenv("CONVERSATION_COMPRESSION_TARGET_TOKENS", "4096"))
    
    # 压缩时保留的最近完整轮数（保底）
    # 即使token数没超，也至少保留最近N轮完整消息
    # 环境变量: CONVERSATION_COMPRESSION_KEEP_TURNS
    COMPRESSION_KEEP_TURNS = int(os.getenv("CONVERSATION_COMPRESSION_KEEP_TURNS", "3"))
    
    # 上下文安全缓冲区（token数）
    # 在计算token限制时预留的安全空间
    # 环境变量: CONVERSATION_CONTEXT_BUFFER_TOKENS
    CONTEXT_BUFFER_TOKENS = int(os.getenv("CONVERSATION_CONTEXT_BUFFER_TOKENS", "1024"))
    
    # 中文token换算系数（1中文≈1.5token）
    # 环境变量: CONVERSATION_CHINESE_TOKEN_RATIO
    CHINESE_TOKEN_RATIO = float(os.getenv("CONVERSATION_CHINESE_TOKEN_RATIO", "1.5"))
    
    # ==================== 消息分页配置 ====================
    
    # 消息列表分页大小
    # 用于控制每次加载的消息数量，优化性能
    # 环境变量: CONVERSATION_MESSAGES_PAGE_SIZE
    MESSAGES_PAGE_SIZE = int(os.getenv("CONVERSATION_MESSAGES_PAGE_SIZE", "50"))
    
    @classmethod
    def get_config_info(cls) -> dict:
        """获取会话配置信息摘要
        
        Returns:
            dict: 包含所有配置项的字典，便于日志记录和调试
        """
        return {
            "max_history_turns": cls.MAX_HISTORY_TURNS,
            "auto_title_enabled": cls.AUTO_TITLE_ENABLED,
            "title_max_length": cls.TITLE_MAX_LENGTH,
            "default_title": cls.DEFAULT_TITLE,
            "messages_page_size": cls.MESSAGES_PAGE_SIZE,
            "compression_enabled": cls.COMPRESSION_ENABLED,
            "compression_token_limit": cls.COMPRESSION_TOKEN_LIMIT,
            "compression_target_tokens": cls.COMPRESSION_TARGET_TOKENS,
            "compression_keep_turns": cls.COMPRESSION_KEEP_TURNS,
            "context_buffer_tokens": cls.CONTEXT_BUFFER_TOKENS,
            "chinese_token_ratio": cls.CHINESE_TOKEN_RATIO,
        }
    
    @classmethod
    def validate(cls) -> bool:
        """验证会话配置是否有效
        
        检查关键配置项是否在合理范围内，确保系统稳定运行。
        
        Returns:
            bool: 配置是否有效
        """
        from common.utils.logger import logger
        
        is_valid = True
        
        # 验证历史轮数
        if cls.MAX_HISTORY_TURNS < 1:
            logger.error(f"MAX_HISTORY_TURNS 配置无效: {cls.MAX_HISTORY_TURNS}，必须大于0")
            is_valid = False
        
        # 验证标题长度
        if cls.TITLE_MAX_LENGTH < 1:
            logger.error(f"TITLE_MAX_LENGTH 配置无效: {cls.TITLE_MAX_LENGTH}，必须大于0")
            is_valid = False
        
        # 验证分页大小
        if cls.MESSAGES_PAGE_SIZE < 1:
            logger.error(f"MESSAGES_PAGE_SIZE 配置无效: {cls.MESSAGES_PAGE_SIZE}，必须大于0")
            is_valid = False
        
        # 验证默认标题
        if not cls.DEFAULT_TITLE or not cls.DEFAULT_TITLE.strip():
            logger.error("DEFAULT_TITLE 不能为空")
            is_valid = False
        
        # 验证token压缩阈值
        if cls.COMPRESSION_TOKEN_LIMIT < 1024:
            logger.error(f"COMPRESSION_TOKEN_LIMIT 配置无效: {cls.COMPRESSION_TOKEN_LIMIT}，必须大于等于1024")
            is_valid = False
        
        # 验证目标token数
        if cls.COMPRESSION_TARGET_TOKENS < 512:
            logger.error(f"COMPRESSION_TARGET_TOKENS 配置无效: {cls.COMPRESSION_TARGET_TOKENS}，必须大于等于512")
            is_valid = False
        
        # 验证目标token数不超过阈值
        if cls.COMPRESSION_TARGET_TOKENS >= cls.COMPRESSION_TOKEN_LIMIT:
            logger.error(f"COMPRESSION_TARGET_TOKENS({cls.COMPRESSION_TARGET_TOKENS}) 必须小于 COMPRESSION_TOKEN_LIMIT({cls.COMPRESSION_TOKEN_LIMIT})")
            is_valid = False
        
        # 验证保底轮数
        if cls.COMPRESSION_KEEP_TURNS < 1:
            logger.error(f"COMPRESSION_KEEP_TURNS 配置无效: {cls.COMPRESSION_KEEP_TURNS}，必须大于0")
            is_valid = False
        
        # 验证中文token系数
        if cls.CHINESE_TOKEN_RATIO <= 0:
            logger.error(f"CHINESE_TOKEN_RATIO 配置无效: {cls.CHINESE_TOKEN_RATIO}，必须大于0")
            is_valid = False
        
        if is_valid:
            logger.debug("会话配置验证通过")
        else:
            logger.error("会话配置验证失败，请检查环境变量")
        
        return is_valid
    
    @classmethod
    def log_config(cls):
        """记录会话配置信息到日志
        
        在应用启动时调用，便于追踪当前使用的配置。
        """
        from common.utils.logger import logger
        
        config_info = cls.get_config_info()
        logger.info("=" * 50)
        logger.info("会话配置信息:")
        for key, value in config_info.items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 50)
