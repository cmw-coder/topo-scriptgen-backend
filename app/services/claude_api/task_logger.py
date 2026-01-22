"""
任务日志管理服务

负责任务日志文件的创建、写入和管理

性能优化：
1. 启动时一次性加载所有已有文件的缓存
2. 缓存命中时直接返回，不做任何文件系统检查（O(1)）
3. 缓存未命中时才使用 glob 搜索（多进程场景下的慢速路径）
"""
import os
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path
from threading import Lock


class TaskLogger:
    """任务日志管理器"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # 缓存 task_id 到日志文件名的映射，确保同一任务的日志写入同一文件
        self._log_file_cache: dict[str, str] = {}
        # 线程锁，防止并发时重复创建文件
        self._lock = Lock()
        # 缓存 task_logs_dir 路径，避免重复获取
        self._task_logs_dir: Optional[Path] = None
        # 启动时加载已有日志文件的缓存
        self._load_cache()

    def _get_task_logs_dir(self) -> Path:
        """获取日志目录（带缓存）"""
        if self._task_logs_dir is None:
            from app.core.path_manager import path_manager
            logs_dir = path_manager.get_logs_dir()
            self._task_logs_dir = logs_dir / "tasks"
            self._task_logs_dir.mkdir(parents=True, exist_ok=True)
        return self._task_logs_dir

    def _load_cache(self):
        """
        启动时从已有日志文件中加载缓存（一次性操作）
        扫描日志目录，解析文件名格式：年月日时分秒_taskId.log
        恢复 task_id 到文件名的映射
        """
        import glob
        from app.core.path_manager import path_manager

        try:
            logs_dir = path_manager.get_logs_dir()
            task_logs_dir = logs_dir / "tasks"

            # 如果目录不存在，无需加载
            if not task_logs_dir.exists():
                return

            # 扫描所有 .log 文件（一次性操作）
            pattern = str(task_logs_dir / "*.log")
            log_files = glob.glob(pattern)

            loaded_count = 0
            new_cache = {}
            for log_file_path in log_files:
                filename = os.path.basename(log_file_path)
                if filename.endswith('.log'):
                    # 文件名格式：20260122194648_taskId.log
                    parts = filename.split('_', 1)
                    if len(parts) == 2:
                        task_id_from_file = parts[1].removesuffix('.log')
                        new_cache[task_id_from_file] = filename
                        loaded_count += 1

            # 一次性更新缓存（减少锁持有时间）
            with self._lock:
                self._log_file_cache = new_cache

            if loaded_count > 0:
                self.logger.info(f"TaskLogger: 加载了 {loaded_count} 个日志文件缓存")

        except Exception as e:
            self.logger.warning(f"TaskLogger: 加载日志缓存失败: {str(e)}")

    def get_log_file_path(self, task_id: str) -> str:
        """
        获取任务日志文件路径（性能优化版）

        文件名格式：年月日时分秒_taskId.log
        例如：20250122143025_abc123-def456.log

        性能：
        - 缓存命中：O(1)，无文件系统操作
        - 缓存未命中：glob 搜索（仅发生一次，之后被缓存）

        Args:
            task_id: 任务ID

        Returns:
            日志文件的完整路径
        """
        task_logs_dir = self._get_task_logs_dir()

        # 快速路径：缓存命中，直接返回（无锁，无文件系统检查）
        # 使用 try/except 避免 KeyError 异常的开销
        cached_filename = self._log_file_cache.get(task_id)
        if cached_filename is not None:
            return str(task_logs_dir / cached_filename)

        # 慢速路径：缓存未命中，需要搜索文件系统
        # 使用锁保护，防止并发时重复创建
        with self._lock:
            # 双重检查：可能在等待锁时已被其他线程设置
            cached_filename = self._log_file_cache.get(task_id)
            if cached_filename is not None:
                return str(task_logs_dir / cached_filename)

            # 从文件系统查找已有的日志文件（多进程场景：其他进程创建的文件）
            import glob
            pattern = str(task_logs_dir / f"*_{task_id}.log")
            existing_files = glob.glob(pattern)

            if existing_files:
                # 找到已有的日志文件，使用最新的（按文件名排序）
                existing_files.sort(reverse=True)
                existing_filename = os.path.basename(existing_files[0])
                self._log_file_cache[task_id] = existing_filename
                return str(existing_files[0])

            # 没有找到已有文件，创建新文件并缓存
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            log_filename = f"{timestamp}_{task_id}.log"
            self._log_file_cache[task_id] = log_filename

            return str(task_logs_dir / log_filename)

    def write_log(self, task_id: str, content: str):
        """
        写入任务日志文件
        格式：时:分:秒 log内容
        保持原始换行符，不转义为 \\n

        Args:
            task_id: 任务ID
            content: 日志内容
        """
        try:
            log_file = self.get_log_file_path(task_id)
            timestamp = datetime.now().strftime("%H:%M:%S")

            # 直接写入内容，保持原始的 \n 换行符
            # 将换行后的每一行都加上时间戳，但保持 \n 作为实际换行符
            lines = content.split('\n')
            log_lines = []
            for line in lines:
                # 为每行添加时间戳（包括空行，保持格式）
                log_lines.append(f"{timestamp} {line}")

            # 写入所有行，使用 \n 作为换行符（不转义）
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write('\n'.join(log_lines) + '\n')
        except Exception as e:
            self.logger.error(f"写入任务日志失败: {str(e)}")

    def write_start_log(self, task_id: str, task_name: str = "任务"):
        """
        写入任务开始标识
        统一格式：[任务开始] 任务名称
        与任务结束标识配对，便于程序解析

        Args:
            task_id: 任务ID
            task_name: 任务名称
        """
        start_message = f"[任务开始] {task_name}"
        self.write_log(task_id, start_message)

    def write_end_log(self, task_id: str, status: str = "completed"):
        """
        写入任务结束标识
        统一格式：[任务结束] 状态: completed/failed
        便于程序解析判断任务是否完成

        Args:
            task_id: 任务ID
            status: 任务状态 (completed/failed)
        """
        end_message = f"[任务结束] 状态: {status}"
        self.write_log(task_id, end_message)

    def write_info(self, task_id: str, message: str):
        """写入信息日志

        Args:
            task_id: 任务ID
            message: 日志消息
        """
        self.write_log(task_id, message)

    def write_warning(self, task_id: str, message: str):
        """写入警告日志

        Args:
            task_id: 任务ID
            message: 日志消息
        """
        self.write_log(task_id, f"⚠️ {message}")

    def write_error(self, task_id: str, message: str):
        """写入错误日志

        Args:
            task_id: 任务ID
            message: 日志消息
        """
        self.write_log(task_id, f"❌ {message}")

    def read_log(self, task_id: str) -> Optional[str]:
        """
        读取任务日志内容

        Args:
            task_id: 任务ID

        Returns:
            日志内容，如果文件不存在则返回 None
        """
        try:
            log_file = self.get_log_file_path(task_id)

            if not os.path.exists(log_file):
                return None

            with open(log_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            self.logger.error(f"读取任务日志失败: {str(e)}")
            return None

    def log_exists(self, task_id: str) -> bool:
        """
        检查任务日志文件是否存在

        Args:
            task_id: 任务ID

        Returns:
            日志文件是否存在
        """
        log_file = self.get_log_file_path(task_id)
        return os.path.exists(log_file)


# 创建全局单例
task_logger = TaskLogger()
