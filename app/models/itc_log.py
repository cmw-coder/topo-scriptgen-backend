"""ITC日志相关的数据模型
AI_FingerPrint_UUID: 20250108-WX7kN2pZ
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ItcLogFileInfo(BaseModel):
    """ITC日志文件信息模型"""
    filename: str = Field(description="文件名")
    size: int = Field(description="文件大小(字节)")
    modified_time: str = Field(description="最后修改时间(格式: YYYY-MM-DD HH:MM:SS)")


class ItcLogFileListResponse(BaseModel):
    """ITC日志文件列表响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[List[ItcLogFileInfo]] = Field(None, description="ITC日志文件列表")
    total_count: Optional[int] = Field(None, description="文件总数")


class ItcLogFileContentRequest(BaseModel):
    """ITC日志文件内容请求模型"""
    filename: str = Field(description="ITC日志文件名")


class ItcLogFileContentResponse(BaseModel):
    """ITC日志文件内容响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[dict] = Field(None, description="文件信息及内容")
