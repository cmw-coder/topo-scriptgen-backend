"""
命令行调试指标统计服务

统计用户调试脚本的时间：
- 记录用户每次调用接口的时间
- 如果前后两次调用间隔 < 5分钟，认为是调试时间
- 如果间隔 >= 5分钟，则不算调试时间（新的一段调试）
- 对于连续的调试调用（间隔都 < 5分钟），取最大间隔作为该段调试时间
- 总调试耗时是所有调试段的最大间隔之和
- 调试指标保存到当前用户的最新流程文件中
"""
import logging
import getpass
from datetime import datetime
from typing import List

from app.services.metrics_service import metrics_service

logger = logging.getLogger(__name__)

# 调试超时阈值（秒）
DEBUG_TIMEOUT_SECONDS = 5 * 60  # 5分钟


class CommandDebugService:
    """命令行调试指标服务类"""

    def _get_username(self) -> str:
        """获取当前用户名"""
        return getpass.getuser()

    def _calculate_debug_duration(self, call_times: List[datetime]) -> float:
        """
        计算调试耗时

        规则：
        1. 如果前后两次调用间隔 < 5分钟，认为是调试时间
        2. 如果间隔 >= 5分钟，则不算调试时间（分割成多段调试）
        3. 对于连续的调试调用（间隔都 < 5分钟），取最大间隔作为该段调试时间
        4. 总调试耗时是所有调试段的最大间隔之和

        Args:
            call_times: 调用时间列表（已按时间排序）

        Returns:
            总调试耗时（秒）
        """
        if len(call_times) < 2:
            return 0.0

        total_duration = 0.0

        # 分割成多段调试
        debug_segments = []
        current_segment = [call_times[0]]

        for i in range(1, len(call_times)):
            prev_time = current_segment[-1]
            curr_time = call_times[i]
            interval = (curr_time - prev_time).total_seconds()

            if interval < DEBUG_TIMEOUT_SECONDS:
                # 间隔 < 5分钟，认为是同一段调试
                current_segment.append(curr_time)
            else:
                # 间隔 >= 5分钟，新的一段调试
                if len(current_segment) >= 2:
                    debug_segments.append(current_segment)
                current_segment = [curr_time]

        # 添加最后一段
        if len(current_segment) >= 2:
            debug_segments.append(current_segment)

        # 计算每段调试的最大间隔，然后求和
        for segment in debug_segments:
            if len(segment) < 2:
                continue

            # 计算该段内所有相邻调用的时间间隔，取最大值
            max_interval = 0.0
            for i in range(1, len(segment)):
                interval = (segment[i] - segment[i - 1]).total_seconds()
                if interval > max_interval:
                    max_interval = interval

            total_duration += max_interval

        return round(total_duration, 2)

    def push_command_debug(self, file_name: str) -> dict:
        """
        推送命令行调试指标

        Args:
            file_name: 调试的脚本文件名

        Returns:
            更新后的调试指标数据
        """
        username = self._get_username()
        now = datetime.now()

        # 获取当前用户的最新流程
        flow_id = metrics_service.get_current_flow_id(username)

        if flow_id is None:
            logger.warning(f"用户 {username} 没有活动流程，跳过记录命令行调试指标")
            return {
                "file_name": file_name,
                "error": "no_active_flow",
                "message": "当前没有活动流程"
            }

        flow = metrics_service.get_flow(flow_id)
        if flow is None:
            logger.warning(f"流程 {flow_id} 不存在，跳过记录命令行调试指标")
            return {
                "file_name": file_name,
                "error": "flow_not_found",
                "message": "流程不存在"
            }

        # 初始化 command_debug_metrics（如果不存在）
        if flow.command_debug_metrics is None:
            flow.command_debug_metrics = {}

        # 获取或创建该文件的调试记录
        file_metrics = flow.command_debug_metrics.get(file_name, {})
        call_times_str = file_metrics.get("call_times", [])

        # 转换字符串时间为 datetime 对象
        call_times = []
        for t in call_times_str:
            if isinstance(t, str):
                call_times.append(datetime.fromisoformat(t))
            elif isinstance(t, datetime):
                call_times.append(t)

        # 添加新的调用时间
        call_times.append(now)

        # 重新计算总调试耗时
        total_duration = self._calculate_debug_duration(call_times)

        # 更新流程的调试指标
        flow.command_debug_metrics[file_name] = {
            "call_times": [t.isoformat() for t in call_times],
            "total_debug_duration": total_duration,
            "call_count": len(call_times),
            "last_updated": now.isoformat()
        }

        # 保存流程到文件（不改变状态，不从缓存移除）
        metrics_service.update_flow_file(flow_id)

        logger.info(
            f"记录命令行调试指标: flow_id={flow_id}, username={username}, file={file_name}, "
            f"call_count={len(call_times)}, "
            f"total_duration={total_duration}秒"
        )

        return {
            "flow_id": flow_id,
            "file_name": file_name,
            "call_count": len(call_times),
            "total_debug_duration": total_duration,
            "last_updated": now.isoformat()
        }

    def get_debug_metrics(self, file_name: str) -> dict:
        """
        获取指定文件的调试指标

        Args:
            file_name: 调试的脚本文件名

        Returns:
            调试指标数据
        """
        username = self._get_username()

        # 获取当前用户的最新流程
        flow_id = metrics_service.get_current_flow_id(username)

        if flow_id is None:
            return {
                "file_name": file_name,
                "error": "no_active_flow",
                "message": "当前没有活动流程"
            }

        flow = metrics_service.get_flow(flow_id)
        if flow is None:
            return {
                "file_name": file_name,
                "error": "flow_not_found",
                "message": "流程不存在"
            }

        if flow.command_debug_metrics is None:
            return {
                "file_name": file_name,
                "error": "no_metrics",
                "message": "该文件没有调试记录"
            }

        file_metrics = flow.command_debug_metrics.get(file_name)
        if file_metrics is None:
            return {
                "file_name": file_name,
                "error": "no_metrics",
                "message": "该文件没有调试记录"
            }

        return {
            "flow_id": flow_id,
            "file_name": file_name,
            **file_metrics
        }


# 创建全局实例
command_debug_service = CommandDebugService()
