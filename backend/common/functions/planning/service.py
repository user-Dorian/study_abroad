"""留学规划业务逻辑层 - 调用 PlanningWorkflow 生成规划方案

负责：
1. 调用 workflows_standalone/planning/workflow.py 中的 PlanningWorkflow
2. 异步执行规划生成任务（通过 asyncio.to_thread 包装同步调用）
3. 处理任务状态（processing/completed/failed）
4. 缓存结果到Redis（TTL=3600）
"""
import json
import asyncio
from typing import Optional

from backend.common.functions.planning.repository import get_planning_repo
from backend.common.basics.utils.logger import logger

# Redis 缓存 TTL（秒）
PLANNING_CACHE_TTL = 3600


def _build_workflow_input(request_data: dict) -> dict:
    """将前端请求数据转换为 PlanningWorkflow 所需的输入格式

    前端请求格式（参考后端API缺失模块实现计划.md）：
    {
        "basic_info": {"current_school", "current_major", "gpa", "gpa_scale", "education_level"},
        "target_info": {"target_countries", "target_major"},
        "scores": {"toefl", "ielts", "gre"},
        "budget": {"min", "max"},
        "additional": {"research_experience", "awards", "work_experience"}
    }

    PlanningWorkflow.generate_plan 期望的输入（参考 ProfileParser.parse）：
    扁平字典，包含 gpa, gpa_scale, current_school, current_major, academic_level,
    toefl, ielts, gre, gmat, target_countries, target_majors, target_level,
    budget_min, budget_max, intended_start_date, work_experience, research_experience, awards
    """
    basic_info = request_data.get("basic_info", {})
    target_info = request_data.get("target_info", {})
    scores = request_data.get("scores", {})
    budget = request_data.get("budget", {})
    additional = request_data.get("additional", {})

    workflow_input = {
        # basic_info
        "current_school": basic_info.get("current_school", ""),
        "current_major": basic_info.get("current_major", ""),
        "gpa": basic_info.get("gpa"),
        "gpa_scale": basic_info.get("gpa_scale", "4.0"),
        "academic_level": basic_info.get("education_level", "undergraduate"),
        # scores
        "toefl": scores.get("toefl"),
        "ielts": scores.get("ielts"),
        "gre": scores.get("gre"),
        "gmat": scores.get("gmat"),
        # target_info
        "target_countries": target_info.get("target_countries", []),
        "target_majors": [target_info["target_major"]] if target_info.get("target_major") else target_info.get("target_majors", []),
        "target_level": target_info.get("target_level", "master"),
        # budget
        "budget_min": budget.get("min"),
        "budget_max": budget.get("max"),
        # additional
        "work_experience": additional.get("work_experience"),
        "research_experience": additional.get("research_experience"),
        "awards": additional.get("awards", []),
        # timeline
        "intended_start_date": request_data.get("intended_start_date"),
    }
    return workflow_input


def _format_plan_result(plan: dict) -> dict:
    """将 PlanningWorkflow 的输出转换为前端期望的响应格式

    前端期望：
    {
        "stats": {"matched_schools", "highest_match_rate", "budget_assessment"},
        "plans": [...],
        "timeline": [...],
        "advice": [...]
    }
    """
    schools = plan.get("schools", [])
    schools_by_chance = plan.get("schools_by_chance", {})
    budget_analysis = plan.get("budget_analysis", {})
    timeline = plan.get("timeline", [])
    recommendations = plan.get("recommendations", [])
    application_strategy = plan.get("application_strategy", {})

    # 计算统计数据
    matched_count = len(schools)
    highest_match = 0
    for school in schools:
        score = school.get("match_score", 0)
        if isinstance(score, str):
            try:
                score = float(score.replace("%", ""))
            except (ValueError, TypeError):
                score = 0
        if score > highest_match:
            highest_match = score

    # 预算评估
    budget_assessment = "充足"
    if budget_analysis:
        total_min = sum(
            float(v.get("total_cost_min", 0) or 0) if isinstance(v, dict) else 0
            for v in budget_analysis.values()
        )
        if total_min > 50:
            budget_assessment = "紧张"
        elif total_min > 30:
            budget_assessment = "适中"

    stats = {
        "matched_schools": matched_count,
        "highest_match_rate": f"{int(highest_match)}%",
        "budget_assessment": budget_assessment,
    }

    # 格式化院校方案
    plans = []
    for school in schools:
        plans.append({
            "school_name": school.get("school_name", ""),
            "country": school.get("country", ""),
            "ranking": school.get("ranking", ""),
            "program": school.get("program", ""),
            "match_score": school.get("match_score", 0),
            "chances": school.get("chances", ""),
            "tuition_range": school.get("tuition_range", ""),
            "requirements": school.get("requirements", {}),
        })

    # 建议列表
    advice = recommendations if recommendations else []

    return {
        "stats": stats,
        "plans": plans,
        "timeline": timeline,
        "advice": advice,
        "application_strategy": application_strategy,
        "budget_analysis": budget_analysis,
        "schools_by_chance": {
            k: len(v) for k, v in schools_by_chance.items()
        },
        "generated_at": plan.get("generated_at", ""),
    }


class PlanningService:
    """留学规划业务服务"""

    def __init__(self):
        self._repo = get_planning_repo()

    async def generate_planning(self, user_id: str, request_data: dict) -> dict:
        """生成留学规划（异步任务）

        流程：
        1. 创建规划任务（status=processing）
        2. 在后台线程中调用 PlanningWorkflow.generate_plan
        3. 更新任务状态和结果
        4. 缓存结果到Redis

        Args:
            user_id: 用户ID
            request_data: 前端请求数据

        Returns:
            dict: {"task_id": "...", "status": "processing"}
        """
        # 1. 创建任务记录
        task = await self._repo.create_task(user_id, request_data)
        task_id = task["id"]
        logger.info(f"[PlanningService] 任务已创建: task_id={task_id}")

        # 2. 启动后台异步任务
        asyncio.create_task(self._execute_planning(task_id, request_data))

        return {"task_id": task_id, "status": "processing"}

    async def _execute_planning(self, task_id: str, request_data: dict):
        """后台执行规划生成（在线程池中运行同步的 PlanningWorkflow）"""
        try:
            # 转换输入格式
            workflow_input = _build_workflow_input(request_data)

            # 在线程池中执行同步的 PlanningWorkflow
            loop = asyncio.get_event_loop()
            plan = await loop.run_in_executor(
                None,
                self._run_workflow,
                workflow_input,
            )

            if "error" in plan:
                error_msg = plan.get("error", "规划生成失败")
                errors = plan.get("errors", [])
                if errors:
                    error_msg += ": " + "; ".join(errors)
                await self._repo.update_task_failed(task_id, error_msg)
                logger.warning(f"[PlanningService] 规划生成失败: task_id={task_id}, error={error_msg}")
                return

            # 格式化结果
            result = _format_plan_result(plan)

            # 更新任务状态
            await self._repo.update_task_completed(task_id, result)
            logger.info(f"[PlanningService] 规划生成成功: task_id={task_id}")

            # 缓存到Redis
            await self._cache_result(task_id, result)

        except Exception as e:
            logger.error(f"[PlanningService] 规划执行异常: task_id={task_id}, error={e}", exc_info=True)
            await self._repo.update_task_failed(task_id, str(e))

    @staticmethod
    def _run_workflow(workflow_input: dict) -> dict:
        """在线程池中运行 PlanningWorkflow（同步方法）"""
        from workflows_standalone.planning.workflow import PlanningWorkflow
        workflow = PlanningWorkflow()
        return workflow.generate_plan(workflow_input)

    async def get_result(self, task_id: str, user_id: str) -> Optional[dict]:
        """获取规划结果

        优先从Redis缓存读取，缓存未命中则从数据库读取。

        Args:
            task_id: 任务ID
            user_id: 用户ID（用于权限校验）

        Returns:
            dict | None: 规划结果，不存在或无权限时返回 None
        """
        # 优先从缓存读取
        cached = await self._get_cached_result(task_id)
        if cached is not None:
            return cached

        # 从数据库读取
        task = await self._repo.get_task(task_id)
        if task is None:
            return None

        # 权限校验
        if task["user_id"] != user_id:
            logger.warning(f"[PlanningService] 无权访问: task_id={task_id}, user_id={user_id}")
            return None

        result = {
            "task_id": task["id"],
            "status": task["status"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }

        if task["status"] == "completed" and task.get("result"):
            result["result"] = task["result"]
            # 回填缓存
            await self._cache_result(task_id, task["result"])
        elif task["status"] == "failed":
            result["error_message"] = task.get("error_message", "未知错误")

        return result

    async def _cache_result(self, task_id: str, result: dict):
        """缓存规划结果到Redis"""
        try:
            from common.config.async_redis import AsyncRedisPool
            client = await AsyncRedisPool.get_client()
            cache_key = f"planning_result:{task_id}"
            await client.setex(cache_key, PLANNING_CACHE_TTL, json.dumps(result, ensure_ascii=False))
            logger.info(f"[PlanningService] 结果已缓存: task_id={task_id}, TTL={PLANNING_CACHE_TTL}s")
        except Exception as e:
            logger.warning(f"[PlanningService] 缓存结果失败（非阻塞）: task_id={task_id}, error={e}")

    async def _get_cached_result(self, task_id: str) -> Optional[dict]:
        """从Redis缓存获取规划结果"""
        try:
            from common.config.async_redis import AsyncRedisPool
            client = await AsyncRedisPool.get_client()
            cache_key = f"planning_result:{task_id}"
            cached = await client.get(cache_key)
            if cached:
                data = json.loads(cached)
                logger.info(f"[PlanningService] 缓存命中: task_id={task_id}")
                return data
        except Exception as e:
            logger.warning(f"[PlanningService] 读取缓存失败（非阻塞）: task_id={task_id}, error={e}")
        return None
