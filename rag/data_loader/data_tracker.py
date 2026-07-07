"""数据变更跟踪器 - 使用MD5哈希检测文件和分块变更"""
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from rag.rag_config import RAGConfig
from utils.logger import logger


class DataTracker:
    """数据变更跟踪器，记录文件状态和分块哈希"""

    def __init__(self, state_dir: Optional[Path] = None):
        state_dir = state_dir or RAGConfig.DATA_DIR
        self.state_file = state_dir / ".data_state.json"
        self.state = self._load()

    def _load(self) -> dict:
        data = {"files": {}}
        if self.state_file.exists():
            try:
                raw = json.loads(self.state_file.read_text(encoding="utf-8"))
                # 标准化所有文件路径的盘符为小写
                normalized = {}
                for key, val in raw.get("files", {}).items():
                    norm_key = self._do_normalize_key(key)
                    normalized[norm_key] = val
                data["files"] = normalized
            except Exception as e:
                logger.warning(f"加载数据状态文件失败: {e}")
        return data

    @staticmethod
    def _do_normalize_key(key: str) -> str:
        """统一文件路径字符串的盘符为小写"""
        if len(key) > 1 and key[1] == ":":
            key = key[0].lower() + key[1:]
        return key

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @staticmethod
    def compute_file_hash(file_path: Path) -> str:
        """计算文件内容MD5"""
        md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5.update(chunk)
        return md5.hexdigest()

    @staticmethod
    def compute_text_hash(text: str) -> str:
        """计算文本MD5（用于分块对比）"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_key(file_path: Path) -> str:
        """统一文件路径的盘符为小写，避免Windows大小写不一致"""
        return DataTracker._do_normalize_key(str(file_path))

    def get_file_state(self, file_path: Path) -> Optional[dict]:
        return self.state["files"].get(self._normalize_key(file_path))

    def has_file_changed(self, file_path: Path) -> bool:
        """检查文件是否新增或内容发生变化（对比mtime+内容哈希）"""
        file_key = self._normalize_key(file_path)
        if file_key not in self.state["files"]:
            return True  # 新文件

        old = self.state["files"][file_key]
        mtime = file_path.stat().st_mtime
        if abs(old.get("mtime", 0) - mtime) > 0.01:
            return True  # 修改时间变了

        return False

    def scan_changes(self) -> dict:
        """
        扫描数据目录，返回变更信息

        Returns:
            {"new": [], "modified": [], "deleted": [], "all_current": []}
        """
        data_dir = RAGConfig.DATA_DIR
        if not data_dir.exists():
            return {"new": [], "modified": [], "deleted": [], "all_current": []}

        current_files = []
        for ext in RAGConfig.SUPPORTED_FILE_TYPES:
            for f in data_dir.rglob(f"*{ext}"):
                if f.is_file():
                    current_files.append(f)

        new_files = []
        modified_files = []
        deleted_files = []

        # 检查新增/修改
        for f in current_files:
            if self.has_file_changed(f):
                file_key = self._normalize_key(f)
                old_state = self.state["files"].get(file_key)
                if old_state is None:
                    new_files.append(f)
                else:
                    modified_files.append(f)

        # 检查删除
        tracked_keys = set(self.state["files"].keys())
        current_keys = set(self._normalize_key(f) for f in current_files)
        for key in tracked_keys - current_keys:
            deleted_files.append(Path(key))

        return {
            "new": new_files,
            "modified": modified_files,
            "deleted": deleted_files,
            "all_current": current_files,
        }

    def update_file_state(self, file_path: Path, chunk_infos: List[dict]):
        """
        更新文件状态和分块哈希信息

        Args:
            file_path: 文件路径
            chunk_infos: [{"child_id": str, "text_hash": str, "parent_id": str}, ...]
        """
        file_key = self._normalize_key(file_path)
        try:
            content_hash = self.compute_file_hash(file_path)
        except Exception as e:
            logger.warning(f"无法计算文件哈希 {file_path}: {e}")
            content_hash = ""
        self.state["files"][file_key] = {
            "mtime": file_path.stat().st_mtime,
            "content_hash": content_hash,
            "chunks": chunk_infos,
        }

    def remove_file(self, file_path: Path):
        """删除文件跟踪记录"""
        self.state["files"].pop(self._normalize_key(file_path), None)

    def get_child_ids(self, file_path: Path) -> List[str]:
        """获取文件关联的所有子分块ID"""
        info = self.state["files"].get(self._normalize_key(file_path))
        if not info:
            return []
        return [c["child_id"] for c in info.get("chunks", [])]

    def get_chunk_text_hashes(self, file_path: Path) -> set:
        """获取文件的所有分块文本哈希集合"""
        info = self.state["files"].get(self._normalize_key(file_path))
        if not info:
            return set()
        return set(c["text_hash"] for c in info.get("chunks", []))