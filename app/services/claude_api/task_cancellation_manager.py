"""
任务取消管理器

负责任务的取消操作，支持取消正在进行的 Claude Code SDK 调用

使用方式：
1. 在启动异步任务时，通过 create_task() 创建并注册任务
2. 通过 cancel_task() 取消指定的任务
3. 任务内部可以通过 is_cancelled() 检查是否被取消
"""
import asyncio
import logging
from threading import Lock
from typing import Dict, Any, Optional, Set, Coroutine


class TaskCancellationManager:
    """任务取消管理器"""

    def __init__(self):
        # 存储 task_id 到 asyncio.Task 的映射
        self._running_tasks: Dict[str, asyncio.Task] = {}
        # 存储已取消的任务 ID
        self._cancelled_tasks: Set[str] = set()
        # 使用锁确保线程安全
        self._lock = Lock()
        self.logger = logging.getLogger(__name__)

    def create_task(
        self,
        task_id: str,
        coro: Coroutine,
        *,
        name: Optional[str] = None
    ) -> asyncio.Task:
        """
        创建并注册一个新的 asyncio 任务

        这是推荐的使用方式，可以确保任务被正确注册以支持取消

        Args:
            task_id: 任务ID
            coro: 要执行的协程
            name: 任务名称（可选）

        Returns:
            创建的 asyncio.Task 对象
        """
        task = asyncio.create_task(coro, name=name or task_id)
        self.register_task(task_id, task)
        # 添加完成回调，任务完成后自动清理
        task.add_done_callback(lambda t: self._on_task_done(task_id))
        return task

    def _on_task_done(self, task_id: str) -> None:
        """
        任务完成时的回调函数

        当任务完成（成功、失败或被取消）时自动调用，
        从运行任务列表中移除该任务。

        Args:
            task_id: 任务ID
        """
        self.unregister_task(task_id)

    def register_task(self, task_id: str, task: asyncio.Task):
        """
        注册正在运行的任务

        Args:
            task_id: 任务ID
            task: asyncio Task 对象
        """
        with self._lock:
            # 如果该任务ID之前已被标记为取消，清除标记
            if task_id in self._cancelled_tasks:
                self._cancelled_tasks.remove(task_id)
            self._running_tasks[task_id] = task
        self.logger.info(f"注册任务: task_id={task_id}")

    def unregister_task(self, task_id: str):
        """
        注销任务（任务完成或失败时调用）

        Args:
            task_id: 任务ID
        """
        with self._lock:
            self._running_tasks.pop(task_id, None)
            self._cancelled_tasks.discard(task_id)
        self.logger.info(f"注销任务: task_id={task_id}")

    async def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        取消指定的任务

        Args:
            task_id: 任务ID

        Returns:
            包含取消结果的字典
        """
        with self._lock:
            # 检查任务是否在运行
            task = self._running_tasks.get(task_id)

            if task is None:
                # 检查是否已经被取消
                if task_id in self._cancelled_tasks:
                    return {
                        "success": False,
                        "message": "任务已经被取消",
                        "task_id": task_id,
                        "status": "already_cancelled"
                    }
                return {
                    "success": False,
                    "message": "任务不存在或已完成",
                    "task_id": task_id,
                    "status": "not_found"
                }

            # 标记为已取消
            self._cancelled_tasks.add(task_id)

        # 尝试取消任务
        try:
            # asyncio.Task.cancel() 会向任务发送 CancelledError
            cancelled = task.cancel()

            if cancelled:
                self.logger.info(f"任务取消请求已发送: task_id={task_id}")
                return {
                    "success": True,
                    "message": "任务取消请求已发送",
                    "task_id": task_id,
                    "status": "cancelling"
                }
            else:
                # 任务可能已经完成
                with self._lock:
                    self._cancelled_tasks.discard(task_id)
                return {
                    "success": False,
                    "message": "任务已完成，无法取消",
                    "task_id": task_id,
                    "status": "already_completed"
                }

        except Exception as e:
            self.logger.error(f"取消任务失败: task_id={task_id}, error={str(e)}")
            with self._lock:
                self._cancelled_tasks.discard(task_id)
            return {
                "success": False,
                "message": f"取消任务失败: {str(e)}",
                "task_id": task_id,
                "status": "error"
            }

    def is_cancelled(self, task_id: str) -> bool:
        """
        检查任务是否已被标记为取消

        Args:
            task_id: 任务ID

        Returns:
            是否被取消
        """
        with self._lock:
            return task_id in self._cancelled_tasks

    def get_running_task_count(self) -> int:
        """
        获取正在运行的任务数量

        Returns:
            正在运行的任务数量
        """
        with self._lock:
            return len(self._running_tasks)

    def get_all_running_tasks(self) -> Dict[str, str]:
        """
        获取所有正在运行的任务信息

        Returns:
            任务ID到任务状态的映射
        """
        with self._lock:
            result = {}
            for task_id, task in self._running_tasks.items():
                if not task.done():
                    result[task_id] = "running"
                else:
                    result[task_id] = "done"
            return result

    async def wait_for_cancel(self, task_id: str, timeout: float = 5.0):
        """
        等待任务被取消完成

        Args:
            task_id: 任务ID
            timeout: 超时时间（秒）
        """
        with self._lock:
            task = self._running_tasks.get(task_id)

        if task is None:
            return

        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.CancelledError:
            # 预期的取消异常
            self.logger.info(f"任务已被取消: task_id={task_id}")
        except asyncio.TimeoutError:
            self.logger.warning(f"等待任务取消超时: task_id={task_id}")


# 创建全局单例
task_cancellation_manager = TaskCancellationManager()
