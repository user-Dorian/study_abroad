"""系统启动引导模块 - SSL配置、环境检查、启动信息打印"""

import os
import sys
import ssl
import subprocess
import time
from typing import Optional, List


class BootstrapManager:
    """启动引导管理器"""

    @staticmethod
    def patch_ssl():
        """
        修复SSL证书问题
        解决国内访问huggingface、aiohttp、httpx等时的SSL证书验证失败问题
        """
        try:
            # 方案1：设置环境变量禁用SSL验证（不推荐生产环境）
            os.environ['CURL_CA_BUNDLE'] = ''
            os.environ['SSL_CERT_FILE'] = ''
            os.environ['REQUESTS_CA_BUNDLE'] = ''

            # 方案2：设置Python ssl模块不验证证书（仅用于开发环境）
            if hasattr(ssl, '_create_unverified_context'):
                ssl._create_default_https_context = ssl._create_unverified_context

            # 方案3：覆盖ssl.create_default_context，让httpx/httpcore也跳过验证
            _original_create_default_context = ssl.create_default_context

            def _patched_create_default_context(*args, **kwargs):
                ctx = _original_create_default_context(*args, **kwargs)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                return ctx

            ssl.create_default_context = _patched_create_default_context

            # 方案4：针对httpx/httpcore的SSL配置
            try:
                import httpx
                _original_httpx_create = httpx.create_default_context
                httpx.create_default_context = _patched_create_default_context
            except ImportError:
                pass

        except Exception as e:
            print(f"[WARNING] SSL patch failed: {e}")

    @staticmethod
    def print_header(service_name: str, port: int = None):
        """
        打印服务启动标题
        Args:
            service_name: 服务名称
            port: 服务端口（可选）
        """
        print("\n" + "=" * 70)
        print(f"  {service_name}")
        if port:
            print(f"  Port: {port} | PID: {os.getpid()}")
        else:
            print(f"  PID: {os.getpid()}")
        print("=" * 70 + "\n")

    @staticmethod
    def print_step_loading(step_name: str, emoji: str = "⏳"):
        """
        打印加载步骤（带进度提示）
        Args:
            step_name: 步骤名称
            emoji: 进度图标
        """
        print(f"{emoji} {step_name}...", end="", flush=True)

    @staticmethod
    def print_step_done(index_or_success, message: str = None, status: str = None):
        """
        打印步骤完成
        Args:
            index_or_success: 如果是int，表示步骤索引；如果是bool，表示成功状态
            message: 完成消息
            status: 状态（success/warn/error）
        """
        if isinstance(index_or_success, int):
            # 模式1：print_step_done(1, "消息", "success")
            print(f" {index_or_success}... {message}")
        else:
            # 模式2：print_step_done(True, "done") 或 print_step_done(success=True, message="done")
            success = index_or_success if isinstance(index_or_success, bool) else True
            msg = message or "done"
            if success:
                print(f" ✓ {msg}")
            else:
                print(f" ✗ {msg}")

    @staticmethod
    def check_docker_running() -> bool:
        """检查Docker是否运行"""
        try:
            result = subprocess.run(
                ["docker", "ps"],
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def check_container_running(container_name: str) -> bool:
        """检查指定容器是否运行"""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )
            return container_name in result.stdout
        except Exception:
            return False

    @staticmethod
    def start_container(container_name: str, image_name: Optional[str] = None) -> bool:
        """
        启动Docker容器
        Args:
            container_name: 容器名称
            image_name: 镜像名称（如果容器不存在则创建）
        Returns:
            是否成功启动
        """
        try:
            # 检查容器是否存在
            check_result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            if container_name in check_result.stdout:
                # 容器存在，启动它
                subprocess.run(
                    ["docker", "start", container_name],
                    capture_output=True,
                    timeout=30,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
            elif image_name:
                # 容器不存在，创建并启动
                subprocess.run(
                    ["docker", "run", "-d", "--name", container_name, image_name],
                    capture_output=True,
                    timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
            else:
                return False

            time.sleep(2)  # 等待容器启动
            return True
        except Exception as e:
            print(f"[ERROR] Failed to start container {container_name}: {e}")
            return False

    def ensure_docker_environments(
        self,
        required_containers: Optional[List[str]] = None,
        redis_config: Optional[dict] = None,
        postgres_config: Optional[dict] = None,
        milvus_config: Optional[dict] = None
    ):
        """
        确保Docker环境和必需容器运行
        Args:
            required_containers: 需要的容器列表，如 ['redis', 'milvus', 'postgres']
            redis_config: Redis配置字典（用于日志记录）
            postgres_config: PostgreSQL配置字典（用于日志记录）
            milvus_config: Milvus配置字典（用于日志记录）
        """
        if required_containers is None:
            required_containers = ['redis', 'milvus', 'postgres']

        # 检查Docker是否运行
        if not self.check_docker_running():
            print("\n" + "!" * 70)
            print("  WARNING: Docker is not running!")
            print("  Please start Docker Desktop and restart the service.")
            print("!" * 70 + "\n")
            return

        # 检查并启动容器
        for container in required_containers:
            self.print_step_loading(f"Checking {container}")

            if self.check_container_running(container):
                self.print_step_done(True, "running")
            else:
                self.print_step_done(False, "not running, starting...")
                if self.start_container(container):
                    self.print_step_done(True, "started")
                else:
                    self.print_step_done(False, "failed to start")


# 全局实例
bootstrap_manager = BootstrapManager()


# 模块级便捷函数
def patch_ssl():
    """修复SSL证书问题"""
    bootstrap_manager.patch_ssl()


def print_header(service_name: str, port: int = None):
    """打印服务启动标题"""
    bootstrap_manager.print_header(service_name, port)


def print_step_loading(step_name: str, emoji: str = "⏳"):
    """打印加载步骤"""
    bootstrap_manager.print_step_loading(step_name, emoji)


def print_step_done(index_or_success, message: str = None, status: str = None):
    """打印步骤完成"""
    bootstrap_manager.print_step_done(index_or_success, message, status)


def ensure_docker_environments(
    required_containers: Optional[List[str]] = None,
    redis_config: Optional[dict] = None,
    postgres_config: Optional[dict] = None,
    milvus_config: Optional[dict] = None
):
    """确保Docker环境和必需容器运行"""
    bootstrap_manager.ensure_docker_environments(
        required_containers,
        redis_config,
        postgres_config,
        milvus_config
    )
