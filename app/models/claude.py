from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class ClaudeCommandType(BaseModel):
    """Claude命令类型枚举"""

    CREATE_CONFTEST: str = "创建conftest"
    GENERATE_TEST_SCRIPT: str = "根据对设备下方的命令行生成测试脚本"
    CUSTOM: str = "自定义命令"


class ClaudeCommandRequest(BaseModel):
    """Claude命令请求模型"""

    command_type: str = Field(description="命令类型")
    command: Optional[str] = Field(None, description="自定义命令")
    working_directory: Optional[str] = Field(None, description="工作目录")
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="命令参数"
    )
    timeout: Optional[int] = Field(default=300, description="超时时间(秒)")


class ClaudeCommandResponse(BaseModel):
    """Claude命令响应模型"""

    task_id: str = Field(description="任务ID")
    command: str = Field(description="执行的命令")
    status: str = Field(description="任务状态: running/completed/failed/timeout")
    start_time: datetime = Field(description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    output: Optional[str] = Field(None, description="命令输出")
    error: Optional[str] = Field(None, description="错误信息")
    exit_code: Optional[int] = Field(None, description="退出码")


class ClaudeLogEntry(BaseModel):
    """Claude日志条目模型"""

    task_id: str = Field(description="任务ID")
    timestamp: datetime = Field(description="时间戳")
    level: str = Field(description="日志级别: INFO/WARNING/ERROR")
    message: str = Field(description="日志消息")
    data: Optional[Dict[str, Any]] = Field(None, description="附加数据")


class ClaudeLogQuery(BaseModel):
    """Claude日志查询模型"""

    task_id: Optional[str] = Field(None, description="任务ID")
    start_time: Optional[datetime] = Field(None, description="开始时间")
    end_time: Optional[datetime] = Field(None, description="结束时间")
    level: Optional[str] = Field(None, description="日志级别")
    limit: int = Field(default=100, description="返回条数限制")
    offset: int = Field(default=0, description="偏移量")
