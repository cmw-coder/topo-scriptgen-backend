#!/usr/bin/env python3
"""
数据模型模块
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class TopoxDeployRequest:
    """Topox 部署请求（表单数据）"""

    # 这些字段从 multipart/form-data 中提取
    # topox_file: UploadFile
    # version_path: Optional[str]
    # device_type: Optional[str]


class ScriptsRunRequest:
    """脚本运行请求（表单数据）"""

    # 这些字段从 multipart/form-data 中提取
    # script_files: List[UploadFile]
    # executor_ip: str


class BaseResponse(BaseModel):
    """基础响应模型"""
    status: str = Field(..., description="响应状态: ok/error")
    message: str = Field(..., description="响应消息")
    data: Optional[Dict[str, Any]] = Field(None, description="响应数据")


class DeployResponse(BaseResponse):
    """部署响应模型"""
    data: Optional[Dict[str, Any]] = Field(
        None,
        description="部署结果数据，包含 executorip 和 terminalinfo"
    )


class RunResponse(BaseResponse):
    """脚本运行响应模型"""
    data: Optional[Dict[str, Any]] = Field(
        None,
        description="运行结果数据，包含 return_code, return_info, result"
    )


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "ok"
    project: str
    version: str


__all__ = [
    "BaseResponse",
    "DeployResponse",
    "RunResponse",
    "HealthResponse",
]
