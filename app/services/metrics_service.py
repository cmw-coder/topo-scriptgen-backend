"""
统计度量服务

负责记录和管理部署流程的统计数据
"""
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.models.metrics import WorkflowMetrics
from app.core.config import settings
from app.core.path_manager import path_manager

logger = logging.getLogger(__name__)


class MetricsService:
    """统计度量服务类"""

    def __init__(self):
        # 内存缓存：key为flow_id，value为WorkflowMetrics
        self._flows: dict[str, WorkflowMetrics] = {}
        # 当前活动的流程ID（每个用户一次只能有一个活动流程）
        self._current_flow_ids: dict[str, str] = {}  # key为username, value为flow_id

        # 部署耗时内存变量（用于在流程创建前暂存部署时间信息）
        # key为username, value为 {"call_time": datetime, "complete_time": datetime}
        self._deploy_times_cache: dict[str, dict] = {}

    def _get_metrics_dir(self) -> Path:
        """获取统计文件存储目录（保存到共享目录）"""
        import getpass
        import platform

        username = getpass.getuser()

        # 根据操作系统选择共享目录路径
        if platform.system() == "Windows":
            # Windows 网络共享路径
            base_dir = Path(f"\\\\10.144.41.149\\webide\\aigc_tool\\{username}\\metrics")
        else:
            # Linux 共享目录路径
            base_dir = Path(f"/opt/coder/statistics/build/aigc_tool/{username}/metrics")

        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            return base_dir
        except Exception as e:
            logger.warning(f"无法访问共享目录 {base_dir}，回退到本地目录: {e}")
            # 回退到本地 .metrics 目录
            work_dir = path_manager.get_project_root()
            fallback_dir = work_dir / ".metrics" / "flows"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return fallback_dir

    def _get_flow_file_path(self, flow_id: str) -> Path:
        """获取流程统计文件的路径"""
        metrics_dir = self._get_metrics_dir()
        return metrics_dir / f"{flow_id}.json"

    def _get_username(self) -> str:
        """获取当前用户名"""
        import getpass
        return getpass.getuser()

    def get_current_flow_id(self, username: str) -> Optional[str]:
        """
        获取指定用户的当前活动流程ID

        Args:
            username: 用户名

        Returns:
            流程ID，如果不存在则返回None
        """
        return self._current_flow_ids.get(username)

    def get_or_create_flow_id(self, username: str) -> str:
        """
        获取或创建指定用户的当前流程ID
        如果流程不存在，则自动创建一个默认流程

        Args:
            username: 用户名

        Returns:
            流程ID
        """
        # 检查是否已有活动流程
        if username in self._current_flow_ids:
            flow_id = self._current_flow_ids[username]
            if flow_id in self._flows:
                return flow_id

        # 不存在则创建默认流程
        flow_id = str(uuid.uuid4())
        flow = WorkflowMetrics(
            flow_id=flow_id,
            username=username,
            workspace="",
            user_prompt="",
            status="pending"
        )

        # 保存到内存缓存
        self._flows[flow_id] = flow
        self._current_flow_ids[username] = flow_id

        logger.info(f"自动创建默认流程: flow_id={flow_id}, username={username}")
        return flow_id

    def create_flow(self, user_prompt: str, workspace: str) -> str:
        """
        创建新的流程统计记录

        Args:
            user_prompt: 用户输入的测试点/prompt
            workspace: 工作目录路径

        Returns:
            flow_id: 流程ID
        """
        username = self._get_username()

        # 创建新的流程记录
        flow_id = str(uuid.uuid4())
        flow = WorkflowMetrics(
            flow_id=flow_id,
            username=username,
            workspace=workspace,
            user_prompt=user_prompt,
            status="pending"
        )

        # 保存到内存缓存
        self._flows[flow_id] = flow
        self._current_flow_ids[username] = flow_id

        # 检查是否有缓存的部署时间信息，如果有则写入到流程中
        if username in self._deploy_times_cache:
            deploy_times = self._deploy_times_cache[username]
            call_time = deploy_times.get("call_time")
            complete_time = deploy_times.get("complete_time")

            if call_time:
                flow.deploy_call_time = call_time
            if complete_time:
                flow.deploy_complete_time = complete_time

            # 计算部署耗时
            if call_time and complete_time:
                duration = (complete_time - call_time).total_seconds()
                flow.deploy_duration = round(duration, 2)
                logger.info(f"从缓存恢复部署耗时: flow_id={flow_id}, deploy_duration={duration:.2f}秒")

            # 清空缓存
            del self._deploy_times_cache[username]
            logger.info(f"已清空用户 {username} 的部署时间缓存")

        logger.info(f"创建流程统计记录: flow_id={flow_id}, username={username}, prompt={user_prompt[:50]}...")
        return flow_id

    def get_or_create_current_flow(self, user_prompt: str, workspace: str) -> str:
        """
        获取或创建当前流程统计记录

        Args:
            user_prompt: 用户输入的测试点/prompt
            workspace: 工作目录路径

        Returns:
            flow_id: 流程ID
        """
        username = self._get_username()

        # 检查当前用户是否已有活动流程
        if username in self._current_flow_ids:
            flow_id = self._current_flow_ids[username]
            if flow_id in self._flows:
                # 更新prompt（可能用户修改了输入）
                self._flows[flow_id].user_prompt = user_prompt
                return flow_id

        # 创建新流程
        return self.create_flow(user_prompt, workspace)

    def get_flow(self, flow_id: str) -> Optional[WorkflowMetrics]:
        """
        获取流程统计记录

        Args:
            flow_id: 流程ID

        Returns:
            WorkflowMetrics对象，如果不存在则返回None
        """
        return self._flows.get(flow_id)

    def record_topo_save(self) -> None:
        """记录第一次保存topo时间"""
        username = self._get_username()

        if username not in self._current_flow_ids:
            logger.warning(f"用户 {username} 没有活动流程，跳过记录topo保存时间")
            return

        flow_id = self._current_flow_ids[username]
        flow = self._flows.get(flow_id)

        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，跳过记录topo保存时间")
            return

        # 只记录第一次保存时间
        if flow.first_topo_save_time is None:
            flow.first_topo_save_time = datetime.now()
            logger.info(f"记录topo保存时间: flow_id={flow_id}, time={flow.first_topo_save_time}")
        else:
            logger.debug(f"topo保存时间已存在，跳过重复记录: flow_id={flow_id}")

    def record_deploy_call(self, call_time: datetime) -> None:
        """
        记录调用deploy时间

        如果有活动流程则直接记录，否则保存到内存缓存中等待流程创建

        Args:
            call_time: 调用deploy的时间
        """
        username = self._get_username()

        if username not in self._current_flow_ids:
            # 没有活动流程，保存到内存缓存
            if username not in self._deploy_times_cache:
                self._deploy_times_cache[username] = {}
            self._deploy_times_cache[username]["call_time"] = call_time
            logger.info(f"缓存deploy调用时间（无活动流程）: username={username}, time={call_time}")
            return

        flow_id = self._current_flow_ids[username]
        flow = self._flows.get(flow_id)

        if not flow:
            # 流程不存在，保存到内存缓存
            if username not in self._deploy_times_cache:
                self._deploy_times_cache[username] = {}
            self._deploy_times_cache[username]["call_time"] = call_time
            logger.info(f"缓存deploy调用时间（流程不存在）: username={username}, time={call_time}")
            return

        # 有活动流程，直接记录
        flow.deploy_call_time = call_time

        # 如果有topo保存时间，计算时间差
        if flow.first_topo_save_time:
            duration = (call_time - flow.first_topo_save_time).total_seconds()
            flow.topo_save_to_deploy_call_duration = round(duration, 2)
            logger.info(f"记录deploy调用时间: flow_id={flow_id}, topo_save_to_deploy_duration={duration:.2f}秒")
        else:
            logger.info(f"记录deploy调用时间: flow_id={flow_id}, time={call_time}")

    def record_deploy_complete(self, complete_time: datetime) -> None:
        """
        记录部署完成时间

        如果有活动流程则直接记录，否则保存到内存缓存中等待流程创建

        Args:
            complete_time: 部署完成的时间
        """
        username = self._get_username()

        if username not in self._current_flow_ids:
            # 没有活动流程，保存到内存缓存
            if username not in self._deploy_times_cache:
                self._deploy_times_cache[username] = {}
            self._deploy_times_cache[username]["complete_time"] = complete_time

            # 尝试计算缓存中的部署耗时
            call_time = self._deploy_times_cache[username].get("call_time")
            if call_time:
                duration = (complete_time - call_time).total_seconds()
                logger.info(f"缓存deploy完成时间（无活动流程）: username={username}, complete_time={complete_time}, duration={duration:.2f}秒")
            else:
                logger.info(f"缓存deploy完成时间（无活动流程）: username={username}, complete_time={complete_time}")
            return

        flow_id = self._current_flow_ids[username]
        flow = self._flows.get(flow_id)

        if not flow:
            # 流程不存在，保存到内存缓存
            if username not in self._deploy_times_cache:
                self._deploy_times_cache[username] = {}
            self._deploy_times_cache[username]["complete_time"] = complete_time

            # 尝试计算缓存中的部署耗时
            call_time = self._deploy_times_cache[username].get("call_time")
            if call_time:
                duration = (complete_time - call_time).total_seconds()
                logger.info(f"缓存deploy完成时间（流程不存在）: username={username}, complete_time={complete_time}, duration={duration:.2f}秒")
            else:
                logger.info(f"缓存deploy完成时间（流程不存在）: username={username}, complete_time={complete_time}")
            return

        # 有活动流程，直接记录
        flow.deploy_complete_time = complete_time

        # 计算部署耗时
        if flow.deploy_call_time:
            duration = (complete_time - flow.deploy_call_time).total_seconds()
            flow.deploy_duration = round(duration, 2)
            logger.info(f"记录部署完成时间: flow_id={flow_id}, deploy_duration={duration:.2f}秒")
        else:
            logger.warning(f"没有deploy调用时间，无法计算部署耗时: flow_id={flow_id}")

        # 更新状态为deploying
        flow.status = "deploying"

    def record_conftest_duration(self, flow_id: str, start: datetime, end: datetime) -> None:
        """
        记录生成conftest耗时

        Args:
            flow_id: 流程ID
            start: 开始时间
            end: 结束时间
        """
        flow = self._flows.get(flow_id)
        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，跳过记录conftest耗时")
            return

        duration = (end - start).total_seconds()
        flow.generate_conftest_duration = round(duration, 2)
        logger.info(f"记录conftest生成耗时: flow_id={flow_id}, duration={duration:.2f}秒")

    def record_script_duration(self, flow_id: str, start: datetime, end: datetime) -> None:
        """
        记录生成脚本耗时

        Args:
            flow_id: 流程ID
            start: 开始时间
            end: 结束时间
        """
        flow = self._flows.get(flow_id)
        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，跳过记录脚本生成耗时")
            return

        duration = (end - start).total_seconds()
        flow.generate_script_duration = round(duration, 2)
        logger.info(f"记录脚本生成耗时: flow_id={flow_id}, duration={duration:.2f}秒")

    def record_itc_run_duration(self, flow_id: str, start: datetime, end: datetime) -> None:
        """
        记录ITC run耗时

        Args:
            flow_id: 流程ID
            start: 开始时间
            end: 结束时间
        """
        flow = self._flows.get(flow_id)
        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，跳过记录ITC run耗时")
            return

        duration = (end - start).total_seconds()
        flow.itc_run_duration = round(duration, 2)
        logger.info(f"记录ITC run耗时: flow_id={flow_id}, duration={duration:.2f}秒")

    async def record_claude_analysis_metrics(self, flow_id: str, username: str) -> bool:
        """
        记录 Claude SDK 分析指标（调用 process_single_subfolder）

        Args:
            flow_id: 流程ID
            username: 用户名

        Returns:
            是否记录成功
        """
        flow = self._flows.get(flow_id)
        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，跳过记录Claude分析指标")
            return False

        try:
            # 导入 process_single_subfolder 函数
            from app.services.metrics.todo_analysis_workflow import process_single_subfolder

            # 构造 Claude 项目日志目录路径
            # 路径格式: /home/{username}/.claude/projects/-home-{username}-project
            folder_path = f"/home/{username}/.claude/projects/-home-{username}-project"
            folder_name = f"-home-{username}-project"

            logger.info(f"开始分析 Claude SDK 日志: flow_id={flow_id}, path={folder_path}")

            # 调用 process_single_subfolder 进行分析
            result = await process_single_subfolder(folder_path, folder_name)

            if result is False:
                logger.warning(f"Claude SDK 分析失败: flow_id={flow_id}")
                return False

            if isinstance(result, dict):
                # 保存分析结果到流程
                flow.claude_analysis_metrics = result
                logger.info(f"记录Claude分析指标成功: flow_id={flow_id}, metrics={result}")
                return True
            else:
                logger.info(f"Claude SDK 分析完成但无Agent分析结果: flow_id={flow_id}")
                return True

        except Exception as e:
            logger.error(f"记录Claude分析指标失败: flow_id={flow_id}, error={e}")
            return False

    def save_flow(self, flow_id: str, status: str = "completed") -> bool:
        """
        保存流程到JSON文件

        Args:
            flow_id: 流程ID
            status: 流程状态

        Returns:
            是否保存成功
        """
        flow = self._flows.get(flow_id)
        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，无法保存")
            return False

        # 更新状态和完成时间
        flow.status = status
        if status in ("completed", "failed"):
            flow.completed_at = datetime.now()

        # 保存到文件
        file_path = self._get_flow_file_path(flow_id)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(
                    flow.model_dump(mode='json'),
                    f,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                )

            logger.info(f"保存流程统计成功: flow_id={flow_id}, file={file_path}")

            # 从活动流程中移除
            username = flow.username
            if username in self._current_flow_ids and self._current_flow_ids[username] == flow_id:
                del self._current_flow_ids[username]

            # 从缓存中移除
            del self._flows[flow_id]

            return True

        except Exception as e:
            logger.error(f"保存流程统计失败: flow_id={flow_id}, error={e}")
            return False

    def save_current_flow(self, status: str = "completed") -> bool:
        """
        保存当前用户的流程

        Args:
            status: 流程状态

        Returns:
            是否保存成功
        """
        username = self._get_username()

        if username not in self._current_flow_ids:
            logger.warning(f"用户 {username} 没有活动流程，无法保存")
            return False

        flow_id = self._current_flow_ids[username]
        return self.save_flow(flow_id, status)

    def update_flow_file(self, flow_id: str) -> bool:
        """
        更新流程文件（不改变状态，不从缓存移除）

        用于实时更新流程数据（如命令行调试指标）

        Args:
            flow_id: 流程ID

        Returns:
            是否保存成功
        """
        flow = self._flows.get(flow_id)
        if not flow:
            logger.warning(f"流程 {flow_id} 不存在，无法更新文件")
            return False

        # 保存到文件（不改变状态，不从缓存移除）
        file_path = self._get_flow_file_path(flow_id)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(
                    flow.model_dump(mode='json'),
                    f,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                )

            logger.debug(f"更新流程文件成功: flow_id={flow_id}, file={file_path}")
            return True

        except Exception as e:
            logger.error(f"更新流程文件失败: flow_id={flow_id}, error={e}")
            return False

    def _recalculate_total_debug_duration(self, flow: WorkflowMetrics) -> float:
        """
        重新计算 total_debug_duration（所有 command_debug 和 write_script 的总和）

        Args:
            flow: 流程对象

        Returns:
            总调试时长（秒）
        """
        total = 0.0

        # 累加 command_debug_metrics
        if flow.command_debug_metrics:
            for file_metrics in flow.command_debug_metrics.values():
                total += file_metrics.get("total_duration", 0.0)

        # 累加 write_script_metrics
        if flow.write_script_metrics:
            for file_metrics in flow.write_script_metrics.values():
                total += file_metrics.get("total_duration", 0.0)

        return round(total, 2)

    def push_metrics(self, metrics_type: str, file_name: str | None, interval: float) -> dict:
        """
        推送指标数据

        Args:
            metrics_type: 指标类型 (command_debug | keep_alive | write_script)
            file_name: 文件名（command_debug 和 write_script 类型必需）
            interval: 操作耗时（秒）

        Returns:
            包含更新后指标数据的字典

        Raises:
            ValueError: 参数不合法时抛出
        """
        username = self._get_username()

        # 获取或自动创建当前用户的最新流程
        flow_id = self.get_or_create_flow_id(username)
        flow = self._flows.get(flow_id)

        if not flow:
            raise ValueError(f"流程不存在: {flow_id}")

        now = datetime.now()

        if metrics_type == "command_debug":
            # 命令行调试指标（按文件记录）
            if not file_name:
                raise ValueError("command_debug 类型需要 file_name 参数")

            if flow.command_debug_metrics is None:
                flow.command_debug_metrics = {}

            file_metrics = flow.command_debug_metrics.get(file_name, {})
            current_duration = file_metrics.get("total_duration", 0.0)
            new_duration = round(current_duration + interval, 2)

            flow.command_debug_metrics[file_name] = {
                "total_duration": new_duration,
                "last_updated": now.isoformat()
            }

            # 重新计算 total_debug_duration
            flow.total_debug_duration = self._recalculate_total_debug_duration(flow)

            self.update_flow_file(flow_id)

            logger.info(
                f"记录command_debug指标: flow_id={flow_id}, username={username}, "
                f"file={file_name}, interval={interval}秒, "
                f"file_duration={new_duration}秒, total_debug_duration={flow.total_debug_duration}秒"
            )

            return {
                "flow_id": flow_id,
                "type": metrics_type,
                "file_name": file_name,
                "interval": interval,
                "file_duration": new_duration,
                "total_debug_duration": flow.total_debug_duration
            }

        elif metrics_type == "write_script":
            # 写脚本时间指标（按文件记录）
            if not file_name:
                raise ValueError("write_script 类型需要 file_name 参数")

            if flow.write_script_metrics is None:
                flow.write_script_metrics = {}

            file_metrics = flow.write_script_metrics.get(file_name, {})
            current_duration = file_metrics.get("total_duration", 0.0)
            new_duration = round(current_duration + interval, 2)

            flow.write_script_metrics[file_name] = {
                "total_duration": new_duration,
                "last_updated": now.isoformat()
            }

            # 重新计算 total_debug_duration
            flow.total_debug_duration = self._recalculate_total_debug_duration(flow)

            self.update_flow_file(flow_id)

            logger.info(
                f"记录write_script指标: flow_id={flow_id}, username={username}, "
                f"file={file_name}, interval={interval}秒, "
                f"file_duration={new_duration}秒, total_debug_duration={flow.total_debug_duration}秒"
            )

            return {
                "flow_id": flow_id,
                "type": metrics_type,
                "file_name": file_name,
                "interval": interval,
                "file_duration": new_duration,
                "total_debug_duration": flow.total_debug_duration
            }

        elif metrics_type == "keep_alive":
            # Web使用时间（全局，不按文件）
            current_duration = flow.keep_alive_duration or 0.0
            new_duration = round(current_duration + interval, 2)
            flow.keep_alive_duration = new_duration

            self.update_flow_file(flow_id)

            logger.info(
                f"记录keep_alive指标: flow_id={flow_id}, username={username}, "
                f"interval={interval}秒, total_duration={new_duration}秒"
            )

            return {
                "flow_id": flow_id,
                "type": metrics_type,
                "interval": interval,
                "total_duration": new_duration
            }

        else:
            raise ValueError(
                f"不支持的指标类型: {metrics_type}，支持的类型: command_debug, keep_alive, write_script"
            )


# 创建全局实例
metrics_service = MetricsService()
