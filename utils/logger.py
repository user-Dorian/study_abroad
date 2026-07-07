"""日志管理模块 - 支持控制台和文件双输出"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

# 日志目录
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 默认日志级别设置
DEFAULT_LOG_LEVEL = "DEBUG"  # 文件日志级别
CONSOLE_LOG_LEVEL = "INFO"   # 控制台日志级别


class LogFormatter(logging.Formatter):
    """自定义日志格式化器，支持彩色输出"""

    # ANSI颜色代码
    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def __init__(self, fmt=None, datefmt=None, use_color=True):
        super().__init__(fmt, datefmt)
        self.use_color = use_color

    def format(self, record):
        if self.use_color:
            color = self.COLORS.get(record.levelname, self.RESET)
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logger(
    name: str = "rag",
    console_level: str = None,
    file_level: str = None,
    log_to_file: bool = True,
    log_to_console: bool = True,
) -> logging.Logger:
    """
    设置并返回配置好的日志记录器

    Args:
        name: 日志记录器名称
        console_level: 控制台日志级别，默认INFO
        file_level: 文件日志级别，默认DEBUG
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到控制台

    Returns:
        logging.Logger: 配置好的日志记录器
    """
    # 设置日志级别
    if console_level is None:
        console_level = CONSOLE_LOG_LEVEL
    if file_level is None:
        file_level = DEFAULT_LOG_LEVEL

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # 最低级别，由handler控制实际输出

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 日志格式
    detailed_fmt = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
    simple_fmt = "%(asctime)s - %(levelname)s - %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # 控制台日志
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, console_level.upper()))
        console_formatter = LogFormatter(
            fmt=simple_fmt, datefmt=datefmt, use_color=True
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # 文件日志
    if log_to_file:
        # 按日期创建日志文件
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"{name}_{today}.log"

        # 按大小轮转的文件处理器(最大10MB,保留5个备份)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, file_level.upper()))
        file_formatter = LogFormatter(
            fmt=detailed_fmt, datefmt=datefmt, use_color=False
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 错误日志单独记录
        error_log_file = LOG_DIR / f"{name}_error_{today}.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)

    return logger


# 创建默认日志记录器
logger = setup_logger()
