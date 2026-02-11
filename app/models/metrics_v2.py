"""
基于脚本的度量数据模型 v2

核心设计理念：
1. 以脚本为核心度量单位
2. 支持多次部署、多次调试、多次ITC run
3. 每个脚本记录完整的生命周期活动
4. 自动追踪全局最新活跃脚本
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ActivityType(str, Enum):
    """活动类型枚举"""
    COMMAND_DEBUG = "command_debug"      # 命令行调试
    WRITE_SCRIPT = "write_script"        # 写脚本（AI回写）
    ITC_RUN = "itc_run"                  # ITC 执行
    KEEP_ALIVE = "keep_alive"            # Web活跃时间


class ScriptType(str, Enum):
    """脚本类型枚举"""
    CONFTEST = "conftest"                # conftest.py
    TEST_SCRIPT = "test_script"          # 测试脚本 (test_*.py)
    OTHER_PYTHON = "other_python"        # 其他 Python 脚本


class DeployRecord(BaseModel):
    """单次部署记录"""

    # 部署唯一标识
    deploy_id: str = Field(description="部署ID（UUID）")

    # 时间信息
    deploy_call_time: datetime = Field(description="调用部署接口的时间")
    deploy_complete_time: Optional[datetime] = Field(None, description="部署完成的时间")
    deploy_duration: Optional[float] = Field(None, description="部署耗时（秒）")

    # 部署元数据
    username: str = Field(description="用户名")
    workspace: str = Field(description="工作目录")
    topox_file: str = Field(description="使用的 topox 文件路径")
    version_path: Optional[str] = Field(None, description="版本路径")
    device_type: str = Field(description="设备类型")

    # 部署状态
    status: str = Field(default="pending", description="部署状态: pending | deploying | deployed | failed")

    # 执行机信息（部署成功后填充）
    executor_ip: Optional[str] = Field(None, description="执行机IP地址")
    device_list: Optional[List[Dict[str, Any]]] = Field(None, description="设备列表")

    # ========== 新增：活跃文件信息 ==========
    # 部署时的活跃文件信息（记录部署时刻的活跃脚本）
    active_file_at_deploy: Optional[str] = Field(None, description="部署时的活跃文件路径")
    active_file_name_at_deploy: Optional[str] = Field(None, description="部署时的活跃文件名")
    active_ai_fingerprint_at_deploy: Optional[str] = Field(None, description="部署时的活跃AI指纹ID")
    active_script_uuid_at_deploy: Optional[str] = Field(None, description="部署时的活跃脚本内部UUID")

    # ========== 新增：关联脚本信息 ==========
    # 部署记录关联的脚本AI指纹（部署结束后第一个生成的脚本文件关联）
    associated_script_ai_fingerprint: Optional[str] = Field(
        None,
        description="关联的脚本AI指纹ID（部署结束后第一个生成的脚本文件关联，只能关联一次）"
    )
    # =======================================

    # 创建时间
    created_at: datetime = Field(default_factory=datetime.now, description="记录创建时间")


class ActivityRecord(BaseModel):
    """单次活动记录"""

    # 活动唯一标识
    activity_id: str = Field(description="活动ID（UUID）")

    # 活动类型
    activity_type: ActivityType = Field(description="活动类型")

    # 时间信息
    start_time: datetime = Field(description="活动开始时间")
    end_time: Optional[datetime] = Field(None, description="活动结束时间")
    duration: Optional[float] = Field(None, description="活动耗时（秒）")

    # 相关文件（某些活动类型需要）
    related_file: Optional[str] = Field(None, description="相关文件路径")

    # 额外信息（用于存储扩展数据）
    extra_info: Optional[Dict[str, Any]] = Field(None, description="额外信息")

    # 创建时间
    created_at: datetime = Field(default_factory=datetime.now, description="记录创建时间")


class DurationRecord(BaseModel):
    """耗时记录"""
    timestamp: datetime = Field(description="记录时间戳")
    duration: float = Field(description="耗时（秒）")
    extra_info: Optional[Dict[str, Any]] = Field(None, description="额外信息（如返回码等）")


class ScriptMetrics(BaseModel):
    """单个脚本的度量指标"""

    # 脚本唯一标识
    script_uuid: str = Field(description="脚本唯一标识（UUID）")

    # 脚本基本信息
    script_path: str = Field(description="脚本文件路径")
    script_name: str = Field(description="脚本文件名")
    script_type: ScriptType = Field(description="脚本类型")

    # 生成信息
    created_at: datetime = Field(default_factory=datetime.now, description="脚本生成时间")

    # 该脚本关联的所有部署记录（按时间倒序）- 已弃用，保留用于向后兼容
    deploy_records: List[DeployRecord] = Field(
        default_factory=list,
        description="该脚本生命周期中的所有部署记录（已弃用，不再使用）"
    )

    # 该脚本的所有活动记录（按时间倒序）
    activity_records: List[ActivityRecord] = Field(
        default_factory=list,
        description="该脚本的所有活动记录"
    )

    # 生成耗时
    generation_duration: Optional[float] = Field(None, description="脚本生成耗时（秒）")

    # ========== 新增：回写耗时和ITC run耗时记录 ==========
    # 回写耗时记录（按时间倒序）
    write_back_durations: List[DurationRecord] = Field(
        default_factory=list,
        description="该脚本的回写耗时记录"
    )

    # ITC run耗时记录（按时间倒序）
    itc_run_durations: List[DurationRecord] = Field(
        default_factory=list,
        description="该脚本的ITC run耗时记录"
    )
    # =========================================

    # ========== 新增：command_debug 和 write_script 总耗时 ==========
    # 命令行调试总耗时（秒）- 累计所有 command_debug 活动的耗时
    command_debug_duration: float = Field(default=0.0, description="命令行调试总耗时（秒）")

    # 写脚本总耗时（秒）- 累计所有 write_script 活动的耗时
    write_script_duration: float = Field(default=0.0, description="写脚本总耗时（秒）")
    # =========================================

    # ========== 新增：aigc.json 相关信息 ==========
    # 内部项目名称（来自 aigc.json，格式：proj_YYMMDDHH_uuid）
    aigc_project_name: Optional[str] = Field(None, description="内部项目名称")

    # NVIDIA项目ID（来自 aigc.json，格式：NV202509090001）
    nvid: Optional[str] = Field(None, description="NVIDIA项目ID")

    # 会话ID（来自 aigc.json）
    sessionId: Optional[str] = Field(None, description="会话ID")
    # =============================================

    # Web活跃时间总长（秒）
    keep_alive_duration: float = Field(default=0.0, description="Web活跃时间总长（秒）")

    # 最后活跃时间
    last_active_time: Optional[datetime] = Field(None, description="最后一次活跃时间")

    # AI 指纹 UUID
    ai_fingerprint_uuid: Optional[str] = Field(None, description="AI指纹UUID")

    # 状态
    status: str = Field(default="active", description="状态: active | archived | deleted")

    class Config:
        use_enum_values = True

class MetricsPushRequest(BaseModel):
    """指标推送请求模型（兼容旧版 /push 接口）"""

    # 类型
    type: str = Field(..., description="指标类型: command_debug(命令行调试) | keep_alive(Web使用时间) | write_script(写脚本时间)")

    # 文件名（command_debug 和 write_script 类型需要）
    file_name: Optional[str] = Field(None, description="脚本文件名（command_debug 和 write_script 类型必需）")

    # 操作耗时（秒）
    interval: Optional[float] = Field(None, description="用户操作耗时（秒）（所有类型都必需）", gt=0)
