"""LLM调用模块 - 支持DashScope和DeepSeek"""
import json
import ssl
import os
from typing import Optional
from dotenv import load_dotenv
import httpx
from openai import OpenAI
from common.rag.rag_config import RAGConfig
from common.utils.logger import logger

# 确保加载.env环境变量（防止在config之前被导入）
load_dotenv()


def _create_http_client():
    """创建HTTP客户端，处理SSL证书问题"""
    # Windows上SSL证书可能导致问题，使用verify=False作为临时方案
    ssl_verify = os.getenv("SSL_VERIFY", "true").lower() == "true"
    timeout = httpx.Timeout(timeout=30.0, connect=10.0)  # 异步改造：添加超时防止线程挂起
    if not ssl_verify:
        logger.info("SSL验证已禁用（Windows环境兼容模式）")
        return httpx.Client(verify=False, timeout=timeout)
    
    # 尝试使用系统证书
    try:
        return httpx.Client(timeout=timeout)
    except ssl.SSLError:
        logger.warning("SSL证书验证失败，使用不验证模式")
        return httpx.Client(verify=False, timeout=timeout)


class LLMClient:
    """大语言模型调用客户端"""
    
    def __init__(self):
        self.dashscope_client = None
        self.deepseek_client = None
        # 阶段4异步改造：异步客户端延迟初始化（首次调用 async_* 方法时创建），避免启动时阻塞
        self._async_dashscope_client = None
        self._async_deepseek_client = None
        self._init_clients()
    
    def _init_clients(self):
        """初始化客户端"""
        dashscope_key = RAGConfig.get_dashscope_api_key()
        deepseek_key = RAGConfig.get_deepseek_api_key()
        
        http_client = _create_http_client()
        
        if dashscope_key:
            self.dashscope_client = OpenAI(
                api_key=dashscope_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                http_client=http_client
            )
            logger.info("DashScope客户端初始化成功")
        
        if deepseek_key:
            self.deepseek_client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com",
                http_client=http_client
            )
            logger.info("DeepSeek客户端初始化成功")
    
    def chat(self, prompt: str = "", messages: list = None, model: Optional[str] = None, temperature: float = 0.1) -> str:
        """
        发送对话请求
        
        Args:
            prompt: 用户输入（兼容旧接口，当messages为空时使用）
            messages: 完整的消息列表，支持system/user/assistant角色
                     格式: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            model: 使用的模型名称，None则自动选择
            temperature: 温度参数
            
        Returns:
            模型回答文本
        """
        if not model:
            model = "deepseek-chat" if self.deepseek_client else "qwen-plus"
        
        # 构建消息列表
        if messages:
            msgs = messages
        else:
            msgs = [{"role": "user", "content": prompt}]
        
        # 优先使用DeepSeek
        if self.deepseek_client and "deepseek" in model.lower():
            return self._call_deepseek(msgs, model, temperature)
        elif self.dashscope_client:
            return self._call_dashscope(msgs, model, temperature)
        else:
            raise RuntimeError("未配置任何LLM客户端")
    
    def _call_deepseek(self, messages: list, model: str, temperature: float) -> str:
        """调用DeepSeek"""
        try:
            response = self.deepseek_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=2048,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"DeepSeek调用失败: {e}")
            raise
    
    def _call_dashscope(self, messages: list, model: str, temperature: float) -> str:
        """调用DashScope"""
        try:
            response = self.dashscope_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=2048,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"DashScope调用失败: {e}")
            raise

    def chat_stream(self, prompt: str = "", messages: list = None, model: Optional[str] = None, temperature: float = 0.1):
        """
        发送对话请求（流式）

        Args:
            prompt: 用户输入（兼容旧接口，当messages为空时使用）
            messages: 完整的消息列表，支持system/user/assistant角色
                     格式: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
            model: 使用的模型名称，None则自动选择
            temperature: 温度参数

        Yields:
            模型回答的每个token/chunk
        """
        if not model:
            model = "deepseek-chat" if self.deepseek_client else "qwen-plus"

        # 构建消息列表
        if messages:
            msgs = messages
        else:
            msgs = [{"role": "user", "content": prompt}]

        # 优先使用DeepSeek
        if self.deepseek_client and "deepseek" in model.lower():
            yield from self._call_deepseek_stream(msgs, model, temperature)
        elif self.dashscope_client:
            yield from self._call_dashscope_stream(msgs, model, temperature)
        else:
            raise RuntimeError("未配置任何LLM客户端")

    def _call_deepseek_stream(self, messages: list, model: str, temperature: float):
        """调用DeepSeek（流式）"""
        try:
            response = self.deepseek_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=2048,
                stream=True
            )
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"DeepSeek流式调用失败: {e}")
            raise

    def _call_dashscope_stream(self, messages: list, model: str, temperature: float):
        """调用DashScope（流式）"""
        try:
            response = self.dashscope_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=2048,
                stream=True
            )
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"DashScope流式调用失败: {e}")
            raise

    def chat_json(self, prompt: str = "", messages: list = None, model: Optional[str] = None) -> dict:
        """发送对话并解析JSON结果"""
        text = self.chat(prompt=prompt, messages=messages, model=model, temperature=0.1)
        # 尝试提取JSON
        try:
            # 如果返回的是纯JSON
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试从markdown代码块中提取
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            else:
                logger.warning(f"LLM返回非JSON格式: {text[:200]}")
                raise ValueError(f"无法解析JSON: {text[:100]}")

    # ============================================================
    # 阶段4异步改造：以下为异步方法，使用 AsyncOpenAI + httpx.AsyncClient
    # 异步客户端延迟初始化（首次调用时创建），避免启动时阻塞
    # 同步方法保留不变，向后兼容
    # ============================================================

    def _create_async_http_client(self):
        """创建异步HTTP客户端，处理SSL证书问题（与同步版逻辑保持一致）"""
        # Windows上SSL证书可能导致问题，使用verify=False作为临时方案
        ssl_verify = os.getenv("SSL_VERIFY", "true").lower() == "true"
        timeout = httpx.Timeout(timeout=30.0, connect=10.0)  # 异步改造：添加超时防止协程挂起
        if not ssl_verify:
            logger.info("异步客户端SSL验证已禁用（Windows环境兼容模式）")
            return httpx.AsyncClient(verify=False, timeout=timeout)

        # 尝试使用系统证书
        try:
            return httpx.AsyncClient(timeout=timeout)
        except ssl.SSLError:
            logger.warning("异步客户端SSL证书验证失败，使用不验证模式")
            return httpx.AsyncClient(verify=False, timeout=timeout)

    def _get_async_client(self, model: Optional[str] = None):
        """
        获取异步客户端（延迟初始化）

        根据模型名称选择对应的 AsyncOpenAI 客户端，首次调用时创建并缓存。

        Args:
            model: 模型名称，None则自动选择默认模型

        Returns:
            AsyncOpenAI: 异步客户端实例
        """
        from openai import AsyncOpenAI
        if not model:
            model = "deepseek-chat" if self.deepseek_client else "qwen-plus"

        # 根据模型选择客户端
        if self.deepseek_client and "deepseek" in model.lower():
            if self._async_deepseek_client is None:
                self._async_deepseek_client = AsyncOpenAI(
                    api_key=RAGConfig.get_deepseek_api_key(),
                    base_url="https://api.deepseek.com",
                    http_client=self._create_async_http_client()
                )
                logger.info("AsyncDeepSeek客户端初始化成功")
            return self._async_deepseek_client
        elif self.dashscope_client:
            if self._async_dashscope_client is None:
                self._async_dashscope_client = AsyncOpenAI(
                    api_key=RAGConfig.get_dashscope_api_key(),
                    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    http_client=self._create_async_http_client()
                )
                logger.info("AsyncDashScope客户端初始化成功")
            return self._async_dashscope_client
        else:
            raise RuntimeError("未配置任何LLM客户端")

    async def async_chat(self, prompt: str = "", messages: list = None, model: Optional[str] = None, temperature: float = 0.1) -> str:
        """
        异步发送对话请求（阶段4异步改造）

        Args:
            prompt: 用户输入（兼容旧接口，当messages为空时使用）
            messages: 完整的消息列表，支持system/user/assistant角色
            model: 使用的模型名称，None则自动选择
            temperature: 温度参数

        Returns:
            模型回答文本
        """
        if not model:
            model = "deepseek-chat" if self.deepseek_client else "qwen-plus"

        # 构建消息列表
        if messages:
            msgs = messages
        else:
            msgs = [{"role": "user", "content": prompt}]

        client = self._get_async_client(model)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=msgs,
                temperature=temperature,
                max_tokens=2048,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"异步LLM调用失败: {e}")
            raise

    async def async_chat_stream(self, prompt: str = "", messages: list = None, model: Optional[str] = None, temperature: float = 0.1):
        """
        异步流式对话（阶段4异步改造）

        使用 async for + yield 实现异步生成器，避免阻塞事件循环。

        Args:
            prompt: 用户输入（兼容旧接口，当messages为空时使用）
            messages: 完整的消息列表，支持system/user/assistant角色
            model: 使用的模型名称，None则自动选择
            temperature: 温度参数

        Yields:
            模型回答的每个token/chunk
        """
        if not model:
            model = "deepseek-chat" if self.deepseek_client else "qwen-plus"

        # 构建消息列表
        if messages:
            msgs = messages
        else:
            msgs = [{"role": "user", "content": prompt}]

        client = self._get_async_client(model)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=msgs,
                temperature=temperature,
                max_tokens=2048,
                stream=True,
            )
            async for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"异步LLM流式调用失败: {e}")
            raise

    async def async_chat_json(self, prompt: str = "", messages: list = None, model: Optional[str] = None) -> dict:
        """
        异步发送对话并解析JSON结果（阶段4异步改造）

        Args:
            prompt: 用户输入（兼容旧接口，当messages为空时使用）
            messages: 完整的消息列表
            model: 使用的模型名称，None则自动选择

        Returns:
            dict: 解析后的JSON字典
        """
        text = await self.async_chat(prompt=prompt, messages=messages, model=model, temperature=0.1)
        # 尝试提取JSON
        try:
            # 如果返回的是纯JSON
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试从markdown代码块中提取
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            else:
                logger.warning(f"异步LLM返回非JSON格式: {text[:200]}")
                raise ValueError(f"无法解析JSON: {text[:100]}")


llm_client = LLMClient()
