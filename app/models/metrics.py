"""
统计度量数据模型

用于记录每次部署流程的指标数据
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class WorkflowMetrics(BaseModel):
    """单次部署流程统计指标"""

    # 唯一标识
    flow_id: str = Field(description="流程ID（UUID）")

    # 脚本开发人
    username: str = Field(description="当前用户名")

    # 工作区
    workspace: str = Field(description="工作目录路径")

    # 用户输入的prompt
    user_prompt: str = Field(description="用户输入的测试点/prompt")

    # 第一次保存topox时间
    first_topo_save_time: Optional[datetime] = Field(None, description="第一次保存topox的时间")

    # 调用deploy的时间
    deploy_call_time: Optional[datetime] = Field(None, description="调用部署接口的时间")

    # 部署完成时间
    deploy_complete_time: Optional[datetime] = Field(None, description="部署完成的时间")

    # 第一次保存topox到调用deploy的耗时（秒）
    topo_save_to_deploy_call_duration: Optional[float] = Field(None, description="从保存topox到调用deploy的时间间隔（秒）")

    # deploy部署耗时（秒）
    deploy_duration: Optional[float] = Field(None, description="部署操作耗时（秒）")

    # 调用agent生成conftest.py的总耗时（秒）
    generate_conftest_duration: Optional[float] = Field(None, description="生成conftest.py的耗时（秒）")

    # 调用生成脚本的总耗时（秒）
    generate_script_duration: Optional[float] = Field(None, description="生成测试脚本的耗时（秒）")

    # ITC调用run耗时（秒）
    itc_run_duration: Optional[float] = Field(None, description="ITC run_script接口调用耗时（秒）")

    # Claude SDK 分析指标（从 Claude 项目日志目录分析获取）
    claude_analysis_metrics: Optional[dict] = Field(None, description="Claude SDK分析的Todo指标数据")

    # 命令行调试指标（记录用户调试脚本的时间）
    command_debug_metrics: Optional[dict] = Field(None, description="命令行调试指标数据")

    # 流程创建时间
    created_at: datetime = Field(default_factory=datetime.now, description="流程创建时间")

    # 流程完成时间
    completed_at: Optional[datetime] = Field(None, description="流程完成时间")

    # 状态
    status: str = Field(default="pending", description="状态: pending/deploying/completed/failed")


class MetricsPushRequest(BaseModel):
    """指标推送请求模型"""

    # 类型
    type: str = Field(..., description="指标类型: command_debug")

    # 文件名
    file_name: str = Field(..., description="调试的脚本文件名")
