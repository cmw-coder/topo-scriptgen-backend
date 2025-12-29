import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, AsyncGenerator
import subprocess
import os

from app.core.path_manager import path_manager
from app.core.config import settings
from app.models.claude import (
    ClaudeCommandRequest,
    ClaudeCommandResponse,
    ClaudeLogEntry,
    ClaudeLogQuery,
    ClaudeCommandType,
)

logger = logging.getLogger(__name__)


class ClaudeService:
    """Claude Code服务，封装命令行调用功能"""

    def __init__(self):
        self.path_manager = path_manager
        self.running_tasks: Dict[str, ClaudeCommandResponse] = {}
        self.websocket_connections: Dict[str, List] = (
            {}
        )  # task_id -> list of websockets

    def _get_command(
        self,
        command_type: str,
        custom_command: Optional[str] = None,
        parameters: Optional[Dict] = None,
    ) -> str:
        """根据命令类型生成具体的Claude Code命令"""
        parameters = parameters or {}

        if command_type == ClaudeCommandType.CREATE_CONFTEST:
            return "claude --help"  # 示例：创建conftest的命令
        elif command_type == ClaudeCommandType.GENERATE_TEST_SCRIPT:
            # 根据设备命令生成测试脚本
            device_commands = parameters.get("device_commands", [])
            if device_commands:
                return f"claude \"根据以下设备命令生成测试脚本: {', '.join(device_commands)}\""
            else:
                return 'claude "请提供设备命令以生成测试脚本"'
        elif command_type == ClaudeCommandType.CUSTOM and custom_command:
            return f"claude {custom_command}"
        else:
            return "claude --help"

    async def execute_command(
        self, request: ClaudeCommandRequest
    ) -> ClaudeCommandResponse:
        """执行Claude Code命令"""
        task_id = str(uuid.uuid4())
        start_time = datetime.now()

        try:
            # 生成具体命令
            command = self._get_command(
                request.command_type, request.command, request.parameters
            )

            # 创建任务响应对象
            task_response = ClaudeCommandResponse(
                task_id=task_id,
                command=command,
                status="running",
                start_time=start_time,
            )

            # 添加到运行任务列表
            self.running_tasks[task_id] = task_response

            logger.info(f"开始执行Claude命令任务: {task_id}, 命令: {command}")

            # 在后台执行命令
            asyncio.create_task(
                self._execute_command_background(task_id, command, request)
            )

            return task_response

        except Exception as e:
            logger.error(f"创建Claude命令任务失败: {str(e)}")
            return ClaudeCommandResponse(
                task_id=task_id,
                command=request.command or "",
                status="failed",
                start_time=start_time,
                end_time=datetime.now(),
                error=f"任务创建失败: {str(e)}",
            )

    async def _execute_command_background(
        self, task_id: str, command: str, request: ClaudeCommandRequest
    ):
        """后台执行Claude命令"""
        try:
            # 设置工作目录
            working_dir = None
            if request.working_directory:
                working_dir = self.path_manager.resolve_path(request.working_directory)
                if not working_dir.exists():
                    await self._update_task_status(
                        task_id, "failed", error=f"工作目录不存在: {working_dir}"
                    )
                    return

            # 准备执行环境
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"

            # 执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env,
            )

            output_lines = []
            error_lines = []

            # 读取输出
            async def read_output(stream, is_error=False):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    line_str = line.decode("utf-8", errors="ignore").rstrip()

                    if is_error:
                        error_lines.append(line_str)
                    else:
                        output_lines.append(line_str)

                    # 实时发送到WebSocket
                    await self._send_to_websocket(
                        task_id,
                        {
                            "type": "output",
                            "content": line_str,
                            "is_error": is_error,
                            "timestamp": datetime.now().isoformat(),
                        },
                    )

            # 并行读取stdout和stderr
            stdout_task = asyncio.create_task(read_output(process.stdout, False))
            stderr_task = asyncio.create_task(read_output(process.stderr, True))

            # 等待进程完成
            try:
                exit_code = await asyncio.wait_for(
                    process.wait(),
                    timeout=request.timeout or settings.CLAUDE_CODE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                await self._update_task_status(task_id, "timeout", error="命令执行超时")
                return

            # 等待输出读取完成
            await stdout_task
            await stderr_task

            # 更新任务状态
            combined_output = "\n".join(output_lines)
            combined_error = "\n".join(error_lines)

            if exit_code == 0:
                await self._update_task_status(
                    task_id, "completed", output=combined_output
                )
            else:
                error_msg = combined_error or f"命令执行失败，退出码: {exit_code}"
                await self._update_task_status(
                    task_id, "failed", error=error_msg, output=combined_output
                )

            # 记录日志
            await self._log_execution(
                task_id, command, exit_code, combined_output, combined_error
            )

        except Exception as e:
            logger.error(f"执行Claude命令失败: {task_id}, 错误: {str(e)}")
            await self._update_task_status(
                task_id, "failed", error=f"执行失败: {str(e)}"
            )

    async def _update_task_status(
        self,
        task_id: str,
        status: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """更新任务状态"""
        if task_id in self.running_tasks:
            task = self.running_tasks[task_id]
            task.status = status
            task.end_time = datetime.now()
            if output is not None:
                task.output = output
            if error is not None:
                task.error = error
            task.exit_code = 0 if status == "completed" else 1

            # 通知WebSocket连接
            await self._send_to_websocket(
                task_id,
                {
                    "type": "status",
                    "status": status,
                    "task_id": task_id,
                    "timestamp": task.end_time.isoformat(),
                },
            )

    async def _send_to_websocket(self, task_id: str, message: dict):
        """发送消息到WebSocket连接"""
        if task_id in self.websocket_connections:
            connections = self.websocket_connections[task_id]
            # 发送消息到所有连接的WebSocket
            for websocket in connections[:]:  # 复制列表以避免迭代时修改
                try:
                    await websocket.send_text(json.dumps(message, ensure_ascii=False))
                except Exception as e:
                    logger.warning(f"WebSocket发送消息失败: {str(e)}")
                    connections.remove(websocket)

    async def _log_execution(
        self, task_id: str, command: str, exit_code: int, output: str, error: str
    ):
        """记录执行日志"""
        try:
            log_entry = ClaudeLogEntry(
                task_id=task_id,
                timestamp=datetime.now(),
                level="INFO" if exit_code == 0 else "ERROR",
                message=f"Claude命令执行完成: {command}",
                data={
                    "command": command,
                    "exit_code": exit_code,
                    "output_length": len(output),
                    "error_length": len(error) if error else 0,
                },
            )

            # 保存到日志文件
            await self._save_log_entry(log_entry)

        except Exception as e:
            logger.error(f"记录执行日志失败: {str(e)}")

    async def _save_log_entry(self, log_entry: ClaudeLogEntry):
        """保存日志条目到文件"""
        try:
            logs_dir = self.path_manager.get_logs_dir()
            log_file = logs_dir / "claude_commands.log"

            # 确保日志目录存在
            logs_dir.mkdir(parents=True, exist_ok=True)

            # 追加日志
            log_line = (
                json.dumps(log_entry.model_dump(), ensure_ascii=False, default=str)
                + "\n"
            )
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_line)

        except Exception as e:
            logger.error(f"保存日志条目失败: {str(e)}")

    async def get_task_status(self, task_id: str) -> Optional[ClaudeCommandResponse]:
        """获取任务状态"""
        return self.running_tasks.get(task_id)

    async def get_all_tasks(self) -> List[ClaudeCommandResponse]:
        """获取所有任务状态"""
        return list(self.running_tasks.values())

    async def query_logs(self, query: ClaudeLogQuery) -> List[ClaudeLogEntry]:
        """查询日志"""
        try:
            logs_dir = self.path_manager.get_logs_dir()
            log_file = logs_dir / "claude_commands.log"

            if not log_file.exists():
                return []

            log_entries = []

            # 读取日志文件
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        log_data = json.loads(line.strip())
                        log_entry = ClaudeLogEntry(**log_data)

                        # 应用过滤条件
                        if query.task_id and log_entry.task_id != query.task_id:
                            continue
                        if query.start_time and log_entry.timestamp < query.start_time:
                            continue
                        if query.end_time and log_entry.timestamp > query.end_time:
                            continue
                        if query.level and log_entry.level != query.level:
                            continue

                        log_entries.append(log_entry)

                    except (json.JSONDecodeError, ValueError):
                        continue

            # 排序（最新的在前）
            log_entries.sort(key=lambda x: x.timestamp, reverse=True)

            # 应用分页
            offset = query.offset
            limit = query.limit
            return log_entries[offset : offset + limit]

        except Exception as e:
            logger.error(f"查询日志失败: {str(e)}")
            return []

    def register_websocket(self, task_id: str, websocket):
        """注册WebSocket连接"""
        if task_id not in self.websocket_connections:
            self.websocket_connections[task_id] = []
        self.websocket_connections[task_id].append(websocket)

    def unregister_websocket(self, task_id: str, websocket):
        """取消注册WebSocket连接"""
        if task_id in self.websocket_connections:
            try:
                self.websocket_connections[task_id].remove(websocket)
                if not self.websocket_connections[task_id]:
                    del self.websocket_connections[task_id]
            except ValueError:
                pass


# 创建Claude服务实例
claude_service = ClaudeService()
