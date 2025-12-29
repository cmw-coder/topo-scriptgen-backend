from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class PythonFileInfo(BaseModel):
    """Python文件信息模型"""
    file_path: str = Field(..., description="文件路径")
    file_name: str = Field(..., description="文件名")
    modified_time: datetime = Field(..., description="文件修改时间")
    size: int = Field(..., description="文件大小（字节）")
    relative_path: Optional[str] = Field(None, description="相对于项目根目录的路径")

class CommandLineInfo(BaseModel):
    """命令行信息模型"""
    id: int = Field(..., description="命令ID，按执行顺序递增")
    command: str = Field(..., description="命令行内容")
    line_number: int = Field(..., description="在文件中的行号")
    context: Optional[str] = Field(None, description="命令行的上下文信息")
    function_name: Optional[str] = Field(None, description="命令行所在的函数名")
    dut_device: Optional[str] = Field(None, description="DUT设备标识，如DUT1, DUT2等")
    command_type: Optional[str] = Field(None, description="命令类型，如CheckCommand, send等")
    parameters: Optional[Dict[str, Any]] = Field(None, description="命令参数解析结果")
    description: Optional[str] = Field(None, description="命令描述信息")

class PythonFilesResponse(BaseModel):
    """Python文件列表响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[List[PythonFileInfo]] = Field(None, description="Python文件列表")
    total_count: int = Field(0, description="文件总数")

class CommandLinesResponse(BaseModel):
    """命令行列表响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[List[CommandLineInfo]] = Field(None, description="命令行列表")
    file_path: str = Field(..., description="分析的文件路径")
    total_commands: int = Field(0, description="命令总数")
    clear_buffer_count: int = Field(0, description="clear_buffer调用次数")
    clear_buffer_locations: Optional[List[Dict[str, Any]]] = Field(None, description="clear_buffer调用位置列表")

class FilePathRequest(BaseModel):
    """文件路径请求模型"""
    file_path: str = Field(..., description="文件路径")

__all__ = [
    "PythonFileInfo",
    "CommandLineInfo",
    "PythonFilesResponse",
    "CommandLinesResponse",
    "FilePathRequest"
]
