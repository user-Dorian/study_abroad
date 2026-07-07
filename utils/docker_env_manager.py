"""Docker环境自动管理模块

负责在服务启动时自动检测和启动必要的外部依赖环境：
- Redis
- PostgreSQL
- Milvus (standalone + etcd + minio)

实现原则：
1. 先尝试连接，连接成功则跳过
2. 连接失败时检查Docker是否可用
3. 优先启动已存在的容器 (docker start)
4. 不存在则创建新容器 (docker run)
5. 检查磁盘空间是否充足
6. 全部失败后降级并提示用户手动启动
"""
import os
import sys
import time
import shutil
import socket
import subprocess
from typing import Dict, List, Tuple, Optional
from pathlib import Path

from utils.logger import logger


class DockerEnvManager:
    """Docker环境管理器"""

    # 最小可用磁盘空间 (GB)
    MIN_FREE_SPACE_GB = 5
    # 创建容器前需要的最小空间 (GB)
    MIN_FREE_SPACE_FOR_CREATE_GB = 10

    def __init__(self):
        self.docker_available = False
        self.docker_compose_available = False
        self._check_docker()

    def _check_docker(self):
        """检查Docker是否可用"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10,
                encoding="utf-8"
            )
            self.docker_available = result.returncode == 0
            if self.docker_available:
                logger.info("Docker已可用")
            else:
                logger.warning(f"Docker不可用: {result.stderr.strip()}")
        except Exception as e:
            logger.warning(f"Docker检查失败: {e}")
            self.docker_available = False

    def _run_cmd(self, cmd: List[str], timeout: int = 60) -> Tuple[int, str, str]:
        """运行命令并返回结果"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8"
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return -1, "", "命令超时"
        except Exception as e:
            return -1, "", str(e)

    def check_disk_space(self, path: str = ".") -> Tuple[bool, float]:
        """检查磁盘空间是否充足"""
        try:
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024 ** 3)
            return free_gb >= self.MIN_FREE_SPACE_GB, free_gb
        except Exception as e:
            logger.warning(f"磁盘空间检查失败: {e}")
            return False, 0.0

    def check_port_open(self, host: str, port: int, timeout: int = 2) -> bool:
        """检查端口是否开放"""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    def _get_all_containers(self) -> List[Dict]:
        """获取所有容器（包括停止的）及其端口映射信息"""
        if not self.docker_available:
            return []
        rc, stdout, _ = self._run_cmd([
            "docker", "ps", "-a",
            "--format", "{{.Names}}|{{.Ports}}|{{.Status}}"
        ])
        if rc != 0:
            return []
        containers = []
        for line in stdout.strip().splitlines():
            parts = line.split("|")
            if len(parts) >= 3:
                containers.append({
                    "name": parts[0].strip(),
                    "ports": parts[1].strip(),
                    "status": parts[2].strip()
                })
        return containers

    def _find_container_by_port(self, port: int) -> Optional[str]:
        """根据端口映射查找容器名"""
        containers = self._get_all_containers()
        port_marker = f"0.0.0.0:{port}->"
        for c in containers:
            if port_marker in c["ports"] or f":{port}->" in c["ports"]:
                return c["name"]
        return None

    def container_exists(self, container_name: str) -> bool:
        """检查容器是否存在（包括停止的）"""
        if not self.docker_available:
            return False
        rc, stdout, _ = self._run_cmd(["docker", "ps", "-a", "--format", "{{.Names}}"])
        if rc != 0:
            return False
        return container_name in stdout.splitlines()

    def container_running(self, container_name: str) -> bool:
        """检查容器是否正在运行"""
        if not self.docker_available:
            return False
        rc, stdout, _ = self._run_cmd(["docker", "ps", "--format", "{{.Names}}"])
        if rc != 0:
            return False
        return container_name in stdout.splitlines()

    def start_container(self, container_name: str) -> bool:
        """启动已存在的容器"""
        logger.info(f"尝试启动已有容器: {container_name}")
        rc, stdout, stderr = self._run_cmd(["docker", "start", container_name], timeout=30)
        if rc == 0:
            logger.info(f"容器 {container_name} 启动成功")
            return True
        else:
            logger.error(f"容器 {container_name} 启动失败: {stderr}")
            return False

    def ensure_redis(self, host: str = "localhost", port: int = 6379, password: str = "") -> Tuple[bool, str]:
        """确保Redis可用"""
        # 1. 先测试连接
        if self._test_redis_connection(host, port, password):
            return True, "Redis已连接"

        # 2. 端口已开放但没有正确响应，说明不是Redis
        if self.check_port_open(host, port):
            return False, f"端口 {port} 已占用但不是Redis服务"

        # 3. 尝试Docker启动
        if not self.docker_available:
            return False, "Docker不可用，无法自动启动Redis"

        container_name = "redis"
        # 如果默认容器名不存在，尝试通过端口查找已有容器
        if not self.container_exists(container_name):
            found = self._find_container_by_port(port)
            if found:
                logger.info(f"通过端口 {port} 发现已有Redis容器: {found}")
                container_name = found

        if self.container_running(container_name):
            return False, f"Redis容器已在运行但连接失败，请检查密码/端口配置"

        if self.container_exists(container_name):
            if self.start_container(container_name):
                time.sleep(2)
                if self._test_redis_connection(host, port, password):
                    return True, "Redis容器启动并连接成功"
                return False, "Redis容器启动后仍无法连接"
            return False, "Redis容器启动失败"

        # 4. 创建新容器
        can_create, reason = self._can_create_container()
        if not can_create:
            return False, reason

        logger.info(f"创建Redis容器: {container_name}")
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", f"{port}:6379",
            "--restart", "unless-stopped"
        ]
        if password:
            cmd.extend(["redis:7-alpine", "redis-server", "--requirepass", password])
        else:
            cmd.append("redis:7-alpine")

        rc, _, stderr = self._run_cmd(cmd, timeout=60)
        if rc != 0:
            return False, f"创建Redis容器失败: {stderr}"

        time.sleep(2)
        if self._test_redis_connection(host, port, password):
            return True, "Redis容器创建并连接成功"
        return False, "Redis容器创建后仍无法连接"

    def _test_redis_connection(self, host: str, port: int, password: str) -> bool:
        """测试Redis连接"""
        try:
            import redis
            params = {"host": host, "port": port, "socket_connect_timeout": 2}
            if password:
                params["password"] = password
            r = redis.Redis(**params)
            return r.ping()
        except Exception:
            return False

    def ensure_postgres(
        self,
        host: str = "localhost",
        port: int = 5432,
        user: str = "postgres",
        password: str = "postgres",
        db_name: str = "postgres"
    ) -> Tuple[bool, str]:
        """确保PostgreSQL可用"""
        # 1. 先测试连接
        if self._test_postgres_connection(host, port, user, password, db_name):
            return True, "PostgreSQL已连接"

        # 2. 端口已开放但没有正确响应
        if self.check_port_open(host, port):
            return False, f"端口 {port} 已占用但不是PostgreSQL服务"

        # 3. 尝试Docker启动
        if not self.docker_available:
            return False, "Docker不可用，无法自动启动PostgreSQL"

        container_name = "postgres"
        # 如果默认容器名不存在，尝试通过端口查找已有容器
        if not self.container_exists(container_name):
            found = self._find_container_by_port(port)
            if found:
                logger.info(f"通过端口 {port} 发现已有PostgreSQL容器: {found}")
                container_name = found

        if self.container_running(container_name):
            return False, "PostgreSQL容器已在运行但连接失败，请检查用户名/密码/数据库名配置"

        if self.container_exists(container_name):
            if self.start_container(container_name):
                time.sleep(3)
                if self._test_postgres_connection(host, port, user, password, db_name):
                    return True, "PostgreSQL容器启动并连接成功"
                return False, "PostgreSQL容器启动后仍无法连接"
            return False, "PostgreSQL容器启动失败"

        # 4. 创建新容器
        can_create, reason = self._can_create_container()
        if not can_create:
            return False, reason

        logger.info(f"创建PostgreSQL容器: {container_name}")
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", f"{port}:5432",
            "-e", f"POSTGRES_USER={user}",
            "-e", f"POSTGRES_PASSWORD={password}",
            "-e", f"POSTGRES_DB={db_name}",
            "--restart", "unless-stopped",
            "postgres:15"
        ]

        rc, _, stderr = self._run_cmd(cmd, timeout=90)
        if rc != 0:
            return False, f"创建PostgreSQL容器失败: {stderr}"

        # 等待PostgreSQL启动
        for _ in range(30):
            time.sleep(1)
            if self._test_postgres_connection(host, port, user, password, db_name):
                return True, "PostgreSQL容器创建并连接成功"

        return False, "PostgreSQL容器创建后仍无法连接"

    def _test_postgres_connection(self, host: str, port: int, user: str, password: str, db_name: str) -> bool:
        """测试PostgreSQL连接"""
        try:
            import psycopg2
            conn = psycopg2.connect(
                host=host, port=port, user=user, password=password, database=db_name,
                connect_timeout=2
            )
            conn.close()
            return True
        except Exception:
            return False

    def ensure_milvus(self, host: str = "localhost", port: int = 19530) -> Tuple[bool, str]:
        """确保Milvus可用
        
        尝试启动 standalone Milvus 容器
        """
        # 1. 先测试连接
        if self._test_milvus_connection(host, port):
            return True, "Milvus已连接"

        # 2. 端口已开放但没有正确响应
        if self.check_port_open(host, port):
            return False, f"端口 {port} 已占用但不是Milvus服务"

        # 3. 尝试Docker启动
        if not self.docker_available:
            return False, "Docker不可用，无法自动启动Milvus"

        container_name = "milvus-standalone"
        # 如果默认容器名不存在，尝试通过端口查找已有容器
        if not self.container_exists(container_name):
            found = self._find_container_by_port(port)
            if found:
                logger.info(f"通过端口 {port} 发现已有Milvus容器: {found}")
                container_name = found

        if self.container_running(container_name):
            return False, "Milvus容器已在运行但连接失败"

        if self.container_exists(container_name):
            if self.start_container(container_name):
                time.sleep(5)
                if self._test_milvus_connection(host, port):
                    return True, "Milvus容器启动并连接成功"
                return False, "Milvus容器启动后仍无法连接"
            return False, "Milvus容器启动失败"

        # 4. 创建新容器 (Milvus standalone 简化版)
        can_create, reason = self._can_create_container(min_gb=15)
        if not can_create:
            return False, reason

        logger.info(f"创建Milvus standalone容器: {container_name}")
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", f"{port}:19530",
            "-p", "9091:9091",
            "--restart", "unless-stopped",
            "milvusdb/milvus:v2.4.1",
            "milvus", "run", "standalone"
        ]

        rc, _, stderr = self._run_cmd(cmd, timeout=120)
        if rc != 0:
            return False, f"创建Milvus容器失败: {stderr}"

        # 等待Milvus启动
        for i in range(60):
            time.sleep(2)
            if i % 10 == 0:
                logger.info(f"等待Milvus启动... {i*2}s")
            if self._test_milvus_connection(host, port):
                return True, "Milvus容器创建并连接成功"

        return False, "Milvus容器创建后仍无法连接"

    def _test_milvus_connection(self, host: str, port: int) -> bool:
        """测试Milvus连接"""
        try:
            from pymilvus import connections, utility
            connections.connect(alias="docker_test", host=host, port=port, timeout=2)
            # 简单ping
            utility.list_databases(using="docker_test")
            connections.disconnect("docker_test")
            return True
        except Exception:
            return False

    def _can_create_container(self, min_gb: Optional[int] = None) -> Tuple[bool, str]:
        """检查是否可以创建新容器"""
        required_gb = min_gb or self.MIN_FREE_SPACE_FOR_CREATE_GB
        ok, free_gb = self.check_disk_space()
        if not ok:
            return False, f"磁盘空间不足，剩余 {free_gb:.1f}GB（需要至少 {self.MIN_FREE_SPACE_GB}GB）"
        if free_gb < required_gb:
            return False, f"磁盘空间不足，无法创建新容器。剩余 {free_gb:.1f}GB（建议至少 {required_gb}GB）"
        return True, f"磁盘空间充足，剩余 {free_gb:.1f}GB"

    def ensure_all(
        self,
        redis_config: Optional[Dict] = None,
        postgres_config: Optional[Dict] = None,
        milvus_config: Optional[Dict] = None
    ) -> Dict[str, Tuple[bool, str]]:
        """确保所有依赖环境可用"""
        results = {}

        # Redis
        if redis_config:
            results["redis"] = self.ensure_redis(
                redis_config.get("host", "localhost"),
                redis_config.get("port", 6379),
                redis_config.get("password", "")
            )

        # PostgreSQL
        if postgres_config:
            results["postgres"] = self.ensure_postgres(
                postgres_config.get("host", "localhost"),
                postgres_config.get("port", 5432),
                postgres_config.get("user", "postgres"),
                postgres_config.get("password", "postgres"),
                postgres_config.get("database", "postgres")
            )

        # Milvus
        if milvus_config:
            results["milvus"] = self.ensure_milvus(
                milvus_config.get("host", "localhost"),
                milvus_config.get("port", 19530)
            )

        return results
