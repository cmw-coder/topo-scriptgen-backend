from pydantic import BaseModel, Field
from typing import List, Optional


class Device(BaseModel):
    """设备模型"""

    name: str = Field(description="设备名称")
    location: str = Field(description="设备位置")


class Link(BaseModel):
    """链路模型"""

    start_device: str = Field(description="起始设备名称")
    start_port: str = Field(description="起始端口名称")
    end_device: str = Field(description="结束设备名称")
    end_port: str = Field(description="结束端口名称")


class Network(BaseModel):
    """网络拓扑模型"""

    device_list: List[Device] = Field(default_factory=list, description="设备列表")
    link_list: List[Link] = Field(default_factory=list, description="链路列表")


class TopoxRequest(BaseModel):
    """Topox请求模型"""

    network: Network = Field(description="网络拓扑数据")


class TopoxResponse(BaseModel):
    """Topox响应模型"""

    network: Optional[Network] = Field(None, description="网络拓扑数据")
    xml_content: Optional[str] = Field(None, description="XML格式内容")
    file_path: Optional[str] = Field(None, description="保存的文件路径")
