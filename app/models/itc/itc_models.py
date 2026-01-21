from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

class DeployRequest(BaseModel):
    """部署环境请求模型"""
    topofile: Optional[str] = Field(None, description="topox文件目录，一般是svn目录")
    verisonPath: Optional[str] = Field(None, description="版本目录，可选，运行脚本需要的版本目录")
    deviceType: Optional[str] = Field("simware9cen", description="设备类型，支持simware9cen、simware9dis、simware7dis，默认simware9cen")

class NewDeployRequest(BaseModel):
    """新部署环境请求模型（简化版）

    支持的参数：
    - versionPath: 版本目录（兼容旧接口拼写，与 versionpath 二选一）
    - versionpath: 版本目录（正确拼写，与 verisonPath 二选一）
    - devicetype: 设备类型
    """
    versionPath: Optional[str] = Field(None, description="版本目录（兼容旧接口拼写），可选，运行脚本需要的版本目录")
    versionpath: Optional[str] = Field(None, description="版本目录（正确拼写），可选，运行脚本需要的版本目录")
    devicetype: Optional[str] = Field("simware9cen", description="设备类型，支持simware9cen、simware9dis、simware7dis，默认simware9cen")

    def get_version_path(self) -> Optional[str]:
        """获取版本路径（优先使用正确拼写的 versionpath，否则使用 versionPath）"""
        return self.versionpath or self.versionPath

class RunScriptRequest(BaseModel):
    """运行脚本请求模型"""
    scriptspath: str = Field(..., description="脚本文件目录，一般是svn目录")
    executorip: str = Field(..., description="执行机IP，运行脚本的执行机IP地址")

class RunSingleScriptRequest(BaseModel):
    """运行单个脚本请求模型"""
    script_path: str = Field(..., description="要运行的脚本文件名（如 conftest.py）")

class ExecutorRequest(BaseModel):
    """执行机操作请求模型（用于undeploy、restoreconfiguration、suspend、resume）"""
    executorip: str = Field(..., description="执行机IP，运行脚本的执行机IP地址")

class TerminalInfo(BaseModel):
    """终端连接信息"""
    ip: str = Field(..., description="设备IP")
    port: str = Field(..., description="端口号")
    protocol: str = Field(..., description="连接协议")

class DeployResult(BaseModel):
    """部署结果"""
    executorip: str = Field(..., description="执行机IP")
    terminalinfo: Dict[str, List[str]] = Field(..., description="终端连接信息")

class ITCResponse(BaseModel):
    """ITC API 通用响应模型"""
    return_code: str = Field(..., description="返回码")
    return_info: Optional[Union[str, Dict[str, Any]]] = Field(None, description="返回信息（可能是字符串或字典）")
    result: Optional[Dict[str, Any]] = Field(None, description="返回结果")

# 特定响应类型
class DeployResponse(ITCResponse):
    """部署环境响应"""
    result: Optional[DeployResult] = Field(None, description="部署结果")

class RunScriptResponse(ITCResponse):
    """运行脚本响应"""
    result: Optional[str] = Field(None, description="脚本日志内容")

class SimpleResponse(ITCResponse):
    """简单操作响应（用于undeploy、restoreconfiguration、suspend、resume）"""
    result: Optional[Any] = Field(None, description="返回结果")

# ========== ITC日志相关模型 ==========

class ItcLogFileInfo(BaseModel):
    """ITC日志文件信息模型"""
    filename: str = Field(description="文件名")
    size: int = Field(description="文件大小(字节)")
    modified_time: str = Field(description="最后修改时间(格式: YYYY-MM-DD HH:MM:SS)")
    Result: Optional[str] = Field(None, description="测试结果（仅.pytestlog.json文件）")
    elapsed_time: Optional[str] = Field(None, description="耗时（仅.pytestlog.json文件）")


class ItcLogStatistics(BaseModel):
    """ITC日志统计信息"""
    result_counts: Optional[Dict[str, int]] = Field(None, description="每个Result类型的个数统计")
    total_elapsed_time: Optional[str] = Field(None, description="所有elapsed_time的总和（原始格式）")


class ItcLogFileListResponse(BaseModel):
    """ITC日志文件列表响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[List[ItcLogFileInfo]] = Field(None, description="ITC日志文件列表")
    total_count: Optional[int] = Field(None, description="文件总数")
    statistics: Optional[ItcLogStatistics] = Field(None, description="统计信息（仅.pytestlog.json文件）")


class ItcLogFileContentRequest(BaseModel):
    """ITC日志文件内容请求模型"""
    filename: str = Field(description="ITC日志文件名")


class ItcLogFileContentResponse(BaseModel):
    """ITC日志文件内容响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[dict] = Field(None, description="文件信息及内容")


class AllPytestJsonFilesResponse(BaseModel):
    """所有 pytest.json 文件内容响应模型"""
    status: str = Field(description="响应状态: ok/error")
    message: Optional[str] = Field(None, description="响应消息")
    data: Optional[List[Dict[str, Any]]] = Field(None, description="所有 pytest.json 文件内容的列表")
    total_count: Optional[int] = Field(None, description="文件总数")


class ItcResultData(BaseModel):
    """ITC运行结果数据模型"""
    status: str = Field(description="运行状态: ok/error")
    message: Optional[str] = Field(None, description="结果消息或错误信息")


class ItcResultResponse(BaseModel):
    """ITC运行结果响应模型"""
    data: ItcResultData = Field(description="ITC运行结果数据")


__all__ = [
    "DeployRequest",
    "RunScriptRequest",
    "RunSingleScriptRequest",
    "ExecutorRequest",
    "TerminalInfo",
    "DeployResult",
    "ITCResponse",
    "DeployResponse",
    "RunScriptResponse",
    "SimpleResponse",
    # ITC日志相关模型
    "ItcLogFileInfo",
    "ItcLogStatistics",
    "ItcLogFileListResponse",
    "ItcLogFileContentRequest",
    "ItcLogFileContentResponse",
    "AllPytestJsonFilesResponse",
    "ItcResultData",
    "ItcResultResponse"
]