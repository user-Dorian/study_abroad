"""LLM客户端 - 统一管理大语言模型调用

特性：
- 统一的API调用接口
- 支持流式和非流式输出
- 支持JSON结构化输出
- 完善的错误处理和重试机制
- 兜底策略：超时、重试、降级
"""
import os
import json
import asyncio
import time
from typing import List, Dict, Any, Optional, AsyncIterator, Callable
from backend.common.basics.utils.logger import logger
from ..rag_config import RAGConfig


class LLMClient:
    """LLM客户端 - 支持Qwen和DeepSeek模型

    特性：
    - 统一的API调用接口
    - 支持流式和非流式输出
    - 支持JSON结构化输出
    - 完善的错误处理和重试机制
    - 兜底策略：超时重试、降级回答
    """

    # 重试配置
    MAX_RETRIES = 2
    RETRY_DELAYS = [1, 2]  # 指数退避：1s, 2s
    REQUEST_TIMEOUT = 10.0  # 单次请求超时10s

    def __init__(self):
        """初始化LLM客户端"""
        self._qwen_client = None
        self._deepseek_client = None
        self._initialized = False
        self._available_providers = []  # 可用的provider列表，用于降级

    def _ensure_initialized(self):
        """确保客户端已初始化"""
        if self._initialized:
            return

        # 禁用SSL验证（避免证书验证失败导致连接错误）
        # 同时配置httpx信任系统证书
        import httpx
        try:
            ssl_context = httpx.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = 0  # ssl.CERT_NONE
            http_client = httpx.AsyncClient(
                timeout=self.REQUEST_TIMEOUT,
                verify=False,  # 禁用SSL证书验证
            )
        except Exception as e:
            logger.warning(f"创建httpx客户端失败，使用默认配置: {e}")
            http_client = None

        # 初始化Qwen客户端
        if RAGConfig.DASHSCOPE_API_KEY:
            try:
                from openai import AsyncOpenAI
                client_kwargs = {
                    "api_key": RAGConfig.DASHSCOPE_API_KEY,
                    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "timeout": self.REQUEST_TIMEOUT,
                }
                if http_client:
                    client_kwargs["http_client"] = http_client
                self._qwen_client = AsyncOpenAI(**client_kwargs)
                self._available_providers.append("qwen")
                logger.info("Qwen客户端初始化成功 (SSL验证已禁用)")
            except Exception as e:
                logger.warning(f"Qwen客户端初始化失败: {e}")

        # 初始化DeepSeek客户端
        if RAGConfig.DEEPSEEK_API_KEY:
            try:
                from openai import AsyncOpenAI
                client_kwargs = {
                    "api_key": RAGConfig.DEEPSEEK_API_KEY,
                    "base_url": "https://api.deepseek.com/v1",
                    "timeout": self.REQUEST_TIMEOUT,
                }
                if http_client:
                    client_kwargs["http_client"] = http_client
                self._deepseek_client = AsyncOpenAI(**client_kwargs)
                self._available_providers.append("deepseek")
                logger.info("DeepSeek客户端初始化成功 (SSL验证已禁用)")
            except Exception as e:
                logger.warning(f"DeepSeek客户端初始化失败: {e}")

        if not self._available_providers:
            logger.warning("⚠ 没有可用的LLM provider，将使用兜底回答模式")

        self._initialized = True

    def _get_client(self, model: str, exclude_providers: List[str] = None):
        """根据模型名称选择客户端

        Args:
            model: 模型名称
            exclude_providers: 排除的provider列表（用于故障转移）

        Returns:
            tuple: (client, provider_name, actual_model) 或 (None, None, None)
        """
        self._ensure_initialized()
        exclude_providers = exclude_providers or []

        # 如果指定了deepseek模型，优先使用deepseek
        if 'deepseek' in model.lower() and "deepseek" not in exclude_providers:
            if self._deepseek_client:
                # 使用deepseek-chat作为默认模型
                actual_model = model if model.lower() != 'deepseek' else 'deepseek-chat'
                return self._deepseek_client, "deepseek", actual_model

        # 默认使用Qwen（如果不被排除）
        if "qwen" not in exclude_providers and self._qwen_client:
            return self._qwen_client, "qwen", model

        # 降级：尝试任何可用的provider（除了被排除的）
        for provider in self._available_providers:
            if provider in exclude_providers:
                continue
            if provider == "qwen" and self._qwen_client:
                return self._qwen_client, "qwen", model
            elif provider == "deepseek" and self._deepseek_client:
                # deepseek使用自己的模型名
                actual_model = 'deepseek-chat' if 'qwen' in model.lower() or 'deepseek' in model.lower() else model
                return self._deepseek_client, "deepseek", actual_model

        return None, None, None

    def _get_fallback_model(self, provider: str, original_model: str) -> str:
        """获取provider对应的模型名（用于fallback）

        Args:
            provider: provider名称
            original_model: 原始模型名

        Returns:
            str: 实际使用的模型名
        """
        if provider == "deepseek":
            # DeepSeek使用自己的模型名
            return "deepseek-chat"
        elif provider == "qwen":
            # Qwen使用原始模型名或默认qwen-plus
            return original_model if original_model and 'qwen' in original_model.lower() else "qwen-plus"
        return original_model

    # 不可恢复的错误（不需要重试）
    NON_RETRYABLE_KEYWORDS = [
        "403", "PermissionDenied", "quota", "exhausted",
        "authentication", "api key", "invalid", "unauthorized"
    ]

    async def async_chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
        fallback_response: str = None,
    ) -> str:
        """异步调用LLM（非流式）- 带重试、provider故障转移和兜底

        改进的故障转移策略：
        1. 使用指定provider调用
        2. 遇到不可恢复错误（403/quota）时，自动切换到备用provider
        3. 所有provider都失败后，返回兜底回答

        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            fallback_response: 兜底回答（None时使用默认）

        Returns:
            str: 生成的文本
        """
        model = model or RAGConfig.GENERATION_MODEL_NAME
        temperature = temperature if temperature is not None else RAGConfig.LLM_TEMPERATURE
        max_tokens = max_tokens or RAGConfig.LLM_MAX_TOKENS

        start_time = time.time()
        last_error = None
        tried_providers = []  # 已尝试过的provider列表（用于故障转移）

        # 最多尝试 len(available_providers) 次（每个provider一次）
        max_provider_attempts = max(len(self._available_providers), 1)

        for provider_attempt in range(max_provider_attempts):
            try:
                client, provider, actual_model = self._get_client(
                    model, exclude_providers=tried_providers
                )
                if client is None:
                    logger.warning(f"[LLM] 没有更多可用provider（已尝试: {tried_providers}）")
                    break

                tried_providers.append(provider)
                logger.info(
                    f"[LLM] 尝试 provider={provider}, model={actual_model} "
                    f"(第{provider_attempt+1}/{max_provider_attempts}次)"
                )

                # 单个provider内部重试（最多1次，避免quota问题重试浪费）
                for retry_attempt in range(1):
                    try:
                        response = await client.chat.completions.create(
                            model=actual_model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )

                        result = response.choices[0].message.content.strip()
                        elapsed = time.time() - start_time
                        logger.info(
                            f"[LLM] 响应成功({provider}, {elapsed:.2f}s): "
                            f"{result[:80]}..."
                        )
                        return result

                    except asyncio.TimeoutError:
                        last_error = "请求超时"
                        logger.warning(
                            f"[LLM] {provider}调用超时(重试{retry_attempt+1})"
                        )
                    except Exception as e:
                        last_error = str(e)
                        error_str = str(e).lower()
                        logger.warning(
                            f"[LLM] {provider}调用失败: {type(e).__name__}: {e}"
                        )

                        # 不可恢复的错误（403/quota），切换到下一个provider
                        if any(kw.lower() in error_str for kw in self.NON_RETRYABLE_KEYWORDS):
                            logger.warning(
                                f"[LLM] {provider}不可恢复错误，切换到下一个provider"
                            )
                            break  # 跳出内部重试，外层循环会尝试下一个provider

                        # 可恢复错误（网络/超时），等待后重试
                        if retry_attempt == 0:
                            delay = self.RETRY_DELAYS[0]
                            logger.info(f"[LLM] 等待{delay}s后重试...")
                            await asyncio.sleep(delay)

            except Exception as e:
                last_error = str(e)
                logger.warning(f"[LLM] provider切换异常: {e}")
                continue

        # 所有provider都失败，返回兜底回答
        elapsed = time.time() - start_time
        logger.error(
            f"[LLM] 所有provider调用失败({elapsed:.2f}s, "
            f"已尝试: {tried_providers}): {last_error}，使用兜底回答"
        )

        if fallback_response is not None:
            return fallback_response

        # 默认兜底回答
        return self._get_default_fallback(messages)

    def _get_default_fallback(self, messages: List[Dict[str, str]]) -> str:
        """根据消息内容生成默认兜底回答

        Args:
            messages: 对话消息

        Returns:
            str: 兜底回答
        """
        # 提取用户问题
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break

        if not user_msg:
            return "您好，我是留学通，有什么可以帮助您的吗？"

        # 简单的关键词匹配兜底
        if any(kw in user_msg for kw in ["你好", "hello", "hi", "您好"]):
            return "您好！我是留学通，专业的留学咨询顾问。有什么留学相关的问题都可以问我。"

        if any(kw in user_msg for kw in ["谢谢", "感谢", "thanks"]):
            return "不客气，还有什么其他问题吗？"

        if any(kw in user_msg for kw in ["再见", "bye", "拜拜"]):
            return "再见！祝您留学顺利！"

        # 默认兜底
        return (
            "抱歉，系统暂时遇到了一些问题，无法为您生成回答。"
            "请稍后再试，或者直接咨询专业的留学顾问。"
        )

    async def async_chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
    ) -> AsyncIterator[str]:
        """异步调用LLM（流式输出）- 带provider故障转移和兜底

        改进策略：
        1. 优先使用Qwen流式输出
        2. Qwen失败（403/quota）时，自动切换到DeepSeek
        3. 所有provider流式都失败时，降级为非流式调用
        4. 非流式也失败时，返回兜底回答

        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数

        Yields:
            str: 生成的文本片段
        """
        model = model or RAGConfig.GENERATION_MODEL_NAME
        temperature = temperature if temperature is not None else RAGConfig.LLM_TEMPERATURE
        max_tokens = max_tokens or RAGConfig.LLM_MAX_TOKENS

        tried_providers = []
        last_error = None
        max_provider_attempts = max(len(self._available_providers), 1)

        for provider_attempt in range(max_provider_attempts):
            try:
                client, provider, actual_model = self._get_client(
                    model, exclude_providers=tried_providers
                )
                if client is None:
                    break

                tried_providers.append(provider)
                logger.info(
                    f"[LLM-Stream] 尝试 provider={provider}, model={actual_model} "
                    f"(第{provider_attempt+1}/{max_provider_attempts}次)"
                )

                stream = await client.chat.completions.create(
                    model=actual_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )

                has_yielded = False
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                        has_yielded = True

                # 如果已经输出过内容，直接返回（不能切换provider）
                if has_yielded:
                    return

                # 没有输出任何内容，可能是空响应，尝试下一个provider
                logger.warning(
                    f"[LLM-Stream] {provider}返回空响应，尝试下一个provider"
                )

            except Exception as e:
                last_error = str(e)
                error_str = str(e).lower()
                logger.warning(
                    f"[LLM-Stream] {provider}流式调用失败: {type(e).__name__}: {e}"
                )

                # 不可恢复错误，切换到下一个provider
                if any(kw.lower() in error_str for kw in self.NON_RETRYABLE_KEYWORDS):
                    logger.warning(
                        f"[LLM-Stream] {provider}不可恢复错误，切换到下一个provider"
                    )
                    continue
                # 其他错误也尝试下一个provider
                continue

        # 所有provider流式都失败，降级为非流式调用
        logger.warning(
            f"[LLM-Stream] 所有provider流式失败(已尝试: {tried_providers})，"
            f"降级为非流式调用"
        )
        try:
            fallback = await self.async_chat(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            yield fallback
        except Exception as e:
            logger.error(f"[LLM-Stream] 非流式降级也失败: {e}", exc_info=True)
            yield self._get_default_fallback(messages)

    async def async_chat_json(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = 0.0,
        default_value: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """异步调用LLM并返回JSON结构化输出 - 带兜底

        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 温度参数（默认0，提高稳定性）
            default_value: 解析失败时的默认值

        Returns:
            Dict: 解析后的JSON对象
        """
        model = model or RAGConfig.INTENT_MODEL_NAME
        default_value = default_value or {}

        try:
            response_text = await self.async_chat(
                messages=messages,
                model=model,
                temperature=temperature,
                fallback_response=json.dumps(default_value),
            )

            # 尝试解析JSON
            # 提取JSON块（处理可能的Markdown代码块）
            if '```json' in response_text:
                response_text = response_text.split('```json')[1].split('```')[0]
            elif '```' in response_text:
                response_text = response_text.split('```')[1].split('```')[0]

            response_text = response_text.strip()
            result = json.loads(response_text)
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}, 原始响应: {response_text[:200]}")
            return default_value

        except Exception as e:
            logger.error(f"LLM JSON调用失败: {e}", exc_info=True)
            return default_value

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
        max_tokens: int = None,
    ) -> str:
        """同步调用LLM（非流式）"""
        return asyncio.run(self.async_chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        ))

    def warmup(self):
        """预热模型（避免首次调用卡顿）"""
        try:
            logger.info("开始预热LLM模型...")
            test_messages = [{"role": "user", "content": "测试"}]
            response = self.chat(
                messages=test_messages,
                model=RAGConfig.INTENT_MODEL_NAME,
                max_tokens=10
            )
            logger.info(f"LLM模型预热完成: {response[:50]}")
        except Exception as e:
            logger.warning(f"LLM模型预热失败: {e}（不影响使用，首次调用可能稍慢）")

    def is_available(self) -> bool:
        """检查LLM是否可用"""
        self._ensure_initialized()
        return len(self._available_providers) > 0


# 全局单例
llm_client = LLMClient()
