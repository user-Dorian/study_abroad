"""SSE流式响应工具函数（阶段6：SSE流式响应优化）"""
import json


def sse_event(data: dict) -> str:
    """格式化SSE事件

    Args:
        data: 要序列化为JSON的事件数据字典

    Returns:
        格式化后的SSE事件字符串，格式为 "data: {json}\n\n"
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
