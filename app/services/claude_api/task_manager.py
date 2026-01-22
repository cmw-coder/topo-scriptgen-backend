"""
任务状态管理服务

负责任务的创建、状态更新、消息存储和查询
替换原来的 conftest_tasks 全局变量
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from threading import Lock


class TaskManager:
    """任务状态管理器"""

    def __init__(self):
        # 使用字典存储任务信息，key 为 task_id
        self._tasks: Dict[str, Dict[str, Any]] = {}
        # 使用锁确保线程安全
        self._lock = Lock()
        self.logger = logging.getLogger(__name__)

    def create_task(
        self,
        task_id: str,
        script_path: str = "",
        script_filename: str = "",
        device_commands: str = "",
        test_point: str = "",
        workspace: str = "",
    ) -> Dict[str, Any]:
        """
        创建新任务

        Args:
            task_id: 任务ID
            script_path: 脚本完整路径
            script_filename: 脚本文件名
            device_commands: 设备命令
            test_point: 测试点
            workspace: 工作目录

        Returns:
            创建的任务信息字典
        """
        task_info = {
            "task_id": task_id,
            "script_path": script_path,
            "script_filename": script_filename,
            "device_commands": device_commands,
            "test_point": test_point,
            "workspace": workspace,
            "status": "pending",
            "stage": "pending",
            "messages": [],
            "created_at": datetime.now().isoformat(),
        }

        with self._lock:
            self._tasks[task_id] = task_info

        self.logger.info(f"创建任务: task_id={task_id}")
        return task_info

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务信息

        Args:
            task_id: 任务ID

        Returns:
            任务信息字典，如果不存在则返回 None
        """
        with self._lock:
            return self._tasks.get(task_id)

    def update_status(self, task_id: str, status: str, stage: str = ""):
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态 (pending/running/completed/failed)
            stage: 当前阶段
        """
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]["status"] = status
                if stage:
                    self._tasks[task_id]["stage"] = stage

    def get_status(self, task_id: str) -> str:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            任务状态，如果任务不存在则返回 "unknown"
        """
        task_info = self.get_task(task_id)
        return task_info["status"] if task_info else "unknown"

    def add_message(self, task_id: str, message_type: str, data: str, status: str = "processing"):
        """
        添加任务消息

        Args:
            task_id: 任务ID
            message_type: 消息类型 (info/warning/error/success)
            data: 消息数据
            status: 消息状态 (processing/end)
        """
        with self._lock:
            if task_id in self._tasks:
                ws_message = {
                    "status": status,
                    "type": message_type,
                    "data": data,
                    "timestamp": datetime.now().isoformat()
                }
                self._tasks[task_id].setdefault("messages", []).append(ws_message)
                self.logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

    def get_messages(self, task_id: str) -> List[Dict[str, Any]]:
        """
        获取任务的所有消息

        Args:
            task_id: 任务ID

        Returns:
            消息列表
        """
        task_info = self.get_task(task_id)
        return task_info.get("messages", []) if task_info else []

    def task_exists(self, task_id: str) -> bool:
        """
        检查任务是否存在

        Args:
            task_id: 任务ID

        Returns:
            任务是否存在
        """
        with self._lock:
            return task_id in self._tasks

    def delete_task(self, task_id: str) -> bool:
        """
        删除任务

        Args:
            task_id: 任务ID

        Returns:
            是否成功删除
        """
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self.logger.info(f"删除任务: task_id={task_id}")
                return True
            return False

    def get_all_tasks(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有任务

        Returns:
            所有任务的字典
        """
        with self._lock:
            return self._tasks.copy()

    def clear_completed_tasks(self, older_than_hours: int = 24):
        """
        清理已完成的旧任务

        Args:
            older_than_hours: 清理多少小时前的任务
        """
        from datetime import timedelta

        cutoff_time = datetime.now() - timedelta(hours=older_than_hours)
        tasks_to_delete = []

        with self._lock:
            for task_id, task_info in self._tasks.items():
                if task_info["status"] in ["completed", "failed"]:
                    created_at = datetime.fromisoformat(task_info["created_at"])
                    if created_at < cutoff_time:
                        tasks_to_delete.append(task_id)

            for task_id in tasks_to_delete:
                del self._tasks[task_id]

        if tasks_to_delete:
            self.logger.info(f"清理了 {len(tasks_to_delete)} 个旧任务")


# 创建全局单例
task_manager = TaskManager()
