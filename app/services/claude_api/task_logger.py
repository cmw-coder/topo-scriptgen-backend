"""
任务日志管理服务

负责任务日志文件的创建、写入和管理
"""
import os
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path


class TaskLogger:
    """任务日志管理器"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # 缓存 task_id 到日志文件名的映射，确保同一任务的日志写入同一文件
        self._log_file_cache: dict[str, str] = {}
        # 启动时加载已有日志文件的缓存
        self._load_cache()

    def _load_cache(self):
        """
        启动时从已有日志文件中加载缓存
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

            # 扫描所有 .log 文件
            pattern = str(task_logs_dir / "*.log")
            log_files = glob.glob(pattern)

            loaded_count = 0
            for log_file_path in log_files:
                filename = os.path.basename(log_file_path)
                # 解析文件名：年月日时分秒_taskId.log
                # 提取 task_id（去掉前14位时间戳和下划线，去掉 .log 后缀）
                if filename.endswith('.log'):
                    # 文件名格式：20260122194648_taskId.log
                    # 第14位是下划线，所以从第15位开始到 .log 之前是 task_id
                    parts = filename.split('_', 1)
                    if len(parts) == 2:
                        task_id_from_file = parts[1].removesuffix('.log')
                        # 缓存文件名（带时间戳前缀）
                        self._log_file_cache[task_id_from_file] = filename
                        loaded_count += 1

            if loaded_count > 0:
                self.logger.info(f"TaskLogger: 加载了 {loaded_count} 个日志文件缓存")

        except Exception as e:
            self.logger.warning(f"TaskLogger: 加载日志缓存失败: {str(e)}")

    def get_log_file_path(self, task_id: str) -> str:
        """
        获取任务日志文件路径
        文件名格式：年月日时分秒_taskId.log
        例如：20250122143025_abc123-def456.log

        Args:
            task_id: 任务ID

        Returns:
            日志文件的完整路径
        """
        from app.core.path_manager import path_manager

        logs_dir = path_manager.get_logs_dir()
        # 创建任务日志子目录
        task_logs_dir = logs_dir / "tasks"
        task_logs_dir.mkdir(parents=True, exist_ok=True)

        # 如果缓存中存在，直接返回
        if task_id in self._log_file_cache:
            return str(task_logs_dir / self._log_file_cache[task_id])

        # 首次调用，生成文件名并缓存
        # 文件名格式：年月日时分秒_taskId.log
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
