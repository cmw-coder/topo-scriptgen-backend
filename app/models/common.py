from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class BaseResponse(BaseModel):
    """基础响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[Any] = Field(None, description="响应数据")

class DirectoryItem(BaseModel):
    """目录项模型"""
    label: str = Field(description="文件或目录名")
    path: str = Field(description="完整路径")
    children: Optional[List['DirectoryItem']] = Field(default=None, description="子目录项")
    is_file: bool = Field(description="是否为文件")
    size: Optional[int] = Field(None, description="文件大小(字节)")
    modified_time: Optional[datetime] = Field(None, description="最后修改时间")

# 解决前向引用
DirectoryItem.model_rebuild()

class FileOperationRequest(BaseModel):
    """文件操作请求模型"""
    path: str = Field(description="文件或目录路径")
    content: Optional[str] = Field(None, description="文件内容(用于写操作)")
    encoding: str = Field(default="utf-8", description="文件编码")

class FileOperationResponse(BaseModel):
    """文件操作响应模型"""
    path: str = Field(description="操作路径")
    operation: str = Field(description="操作类型: read/write/delete")
    success: bool = Field(description="操作是否成功")
    content: Optional[str] = Field(None, description="文件内容(读操作返回)")
    size: Optional[int] = Field(None, description="文件大小")
    message: Optional[str] = Field(None, description="操作消息")