"""通信限制中间件 - 架构重构：移除绑定关系通信限制

根据最新架构设计，绑定关系（付费）与好友关系（社交）完全分离。
所有用户之间可以直接通信，无需绑定关系。
- 用户可以直接搜索规划师并发起聊天
- 规划师可以直接搜索用户并发起聊天
- 绑定关系仅用于付费服务场景，不影响通信

保留本模块仅用于兼容性查询，不再阻止通信。
"""
from typing import Optional

from common.consultant.repository import get_consultant_relation_repo
from common.utils.logger import logger


async def verify_user_planner_binding(user_id: str, planner_id: str) -> dict:
    """验证用户是否绑定了指定规划师
    
    架构调整：不再阻止通信，仅返回绑定关系信息供参考。
    绑定关系仅用于付费服务场景识别。
    
    Args:
        user_id: 用户ID
        planner_id: 规划师ID
        
    Returns:
        dict: 绑定关系信息，不存在则返回空字典
    """
    repo = get_consultant_relation_repo()
    relation = await repo.get_active_relation_by_user(user_id)
    
    if relation and relation["consultant_id"] == planner_id:
        logger.info(
            f"用户{user_id}与规划师{planner_id}存在绑定关系（付费服务）"
        )
        return relation
    
    logger.info(
        f"用户{user_id}与规划师{planner_id}无绑定关系，允许自由通信"
    )
    return {}


async def verify_planner_user_binding(planner_id: str, user_id: str) -> bool:
    """验证规划师是否绑定了指定用户
    
    架构调整：不再阻止通信，仅返回绑定关系状态供参考。
    
    Args:
        planner_id: 规划师ID
        user_id: 用户ID
        
    Returns:
        bool: 绑定关系存在返回True，否则返回False（不阻止通信）
    """
    repo = get_consultant_relation_repo()
    exists = await repo.check_relation_exists(planner_id, user_id)
    
    if exists:
        logger.info(f"规划师{planner_id}与用户{user_id}存在绑定关系（付费服务）")
    else:
        logger.info(f"规划师{planner_id}与用户{user_id}无绑定关系，允许自由通信")
    
    return exists


async def get_user_bound_planner_id(user_id: str) -> Optional[str]:
    """获取用户绑定的规划师ID
    
    Args:
        user_id: 用户ID
        
    Returns:
        Optional[str]: 绑定的规划师ID，未绑定则返回None
    """
    repo = get_consultant_relation_repo()
    relation = await repo.get_active_relation_by_user(user_id)
    
    if relation:
        return relation["consultant_id"]
    return None


async def filter_conversations_for_planner(
    planner_id: str,
    conversations: list
) -> list:
    """为规划师过滤对话列表
    
    架构调整：不再过滤，返回所有对话（自由通信模式）。
    
    Args:
        planner_id: 规划师ID
        conversations: 对话列表
        
    Returns:
        list: 全部对话列表（不做过滤）
    """
    return conversations