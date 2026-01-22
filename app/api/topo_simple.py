import json
import logging
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, TypedDict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.path_manager import path_manager
from app.models.topo import Network, Device, Link, TopoxRequest, TopoxResponse
from app.services.topo_service import topo_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["拓扑管理"])

class Device(TypedDict):
    name: str
    location: str

class Link(TypedDict):
    start_device: str
    start_port: str
    end_device: str
    end_port: str

class Network(TypedDict):
    device_list: List[Device]
    link_list: List[Link]

class RequestBody(TypedDict):
    network: Network

def _indent(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print XML by indenting in-place."""
    indent_str = "  "
    i = "\n" + level * indent_str
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + indent_str
        for child in elem:
            _indent(child, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

def build_topox(payload: RequestBody) -> str:
    """Convert request payload to topox XML string."""
    network_elem = ET.Element("NETWORK")

    network_section = payload.get("network", {})
    device_list = []
    link_list = []

    if isinstance(network_section, dict):
        device_list = network_section.get("device_list", []) or []
        link_list = network_section.get("link_list", []) or []

    device_list_elem = ET.SubElement(network_elem, "DEVICE_LIST")
    for device in device_list:
        device_elem = ET.SubElement(device_list_elem, "DEVICE")
        prop_elem = ET.SubElement(device_elem, "PROPERTY")
        ET.SubElement(prop_elem, "NAME").text = device.get("name", "")
        ET.SubElement(prop_elem, "TYPE").text = "Simware9"
        ET.SubElement(prop_elem, "ENABLE").text = "TRUE"
        ET.SubElement(prop_elem, "IS_DOUBLE_MCU").text = "FALSE"
        ET.SubElement(prop_elem, "IS_SINGLE_MCU").text = "FALSE"
        ET.SubElement(prop_elem, "IS_SAME_DUT_TYPE").text = "FALSE"
        ET.SubElement(prop_elem, "MAP_PRIORITY").text = "0"
        ET.SubElement(prop_elem, "IS_DUT").text = "true"
        ET.SubElement(prop_elem, "LOCATION").text = device.get("location", "")

    link_list_elem = ET.SubElement(network_elem, "LINK_LIST")
    for link in link_list:
        link_elem = ET.SubElement(link_list_elem, "LINK")
        start_device = link.get("start_device", "")
        end_device = link.get("end_device", "")
        start_port = link.get("start_port", "")
        end_port = link.get("end_port", "")
        for device_name, port_name in (
            (start_device, start_port),
            (end_device, end_port),
        ):
            node_elem = ET.SubElement(link_elem, "NODE")
            ET.SubElement(node_elem, "DEVICE").text = device_name
            port_elem = ET.SubElement(node_elem, "PORT")
            ET.SubElement(port_elem, "NAME").text = port_name
            ET.SubElement(port_elem, "TYPE").text = ""
            ET.SubElement(port_elem, "IPAddr").text = ""
            ET.SubElement(port_elem, "IPv6Addr").text = ""
            ET.SubElement(port_elem, "SLOT_TYPE").text = ""
            ET.SubElement(port_elem, "TAG").text = ""

    _indent(network_elem)
    xml_bytes = ET.tostring(network_elem, encoding="utf-8", xml_declaration=True)
    return xml_bytes.decode("utf-8")

def parse_topox(xml_text: str) -> Network:
    """Parse topox XML into Network dict."""
    network: Network = {"device_list": [], "link_list": []}

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.exception("Failed to parse topox XML")
        raise

    device_list_elem = root.find("DEVICE_LIST")
    if device_list_elem is not None:
        for device_elem in device_list_elem.findall("DEVICE"):
            prop_elem = device_elem.find("PROPERTY")
            device_name = ""
            device_location = ""
            if prop_elem is not None:
                name_elem = prop_elem.find("NAME")
                location_elem = prop_elem.find("LOCATION")
                device_name = name_elem.text if name_elem is not None else ""
                device_location = (
                    location_elem.text if location_elem is not None else ""
                )
            network["device_list"].append(
                {"name": device_name or "", "location": device_location or ""}
            )

    link_list_elem = root.find("LINK_LIST")
    if link_list_elem is not None:
        for link_elem in link_list_elem.findall("LINK"):
            nodes = link_elem.findall("NODE")
            if len(nodes) < 2:
                continue

            def _node_details(node: ET.Element) -> tuple[str, str]:
                device_elem = node.find("DEVICE")
                port_name_elem = node.find("PORT/NAME")
                device_name = device_elem.text if device_elem is not None else ""
                port_name = port_name_elem.text if port_name_elem is not None else ""
                return device_name or "", port_name or ""

            start_device, start_port = _node_details(nodes[0])
            end_device, end_port = _node_details(nodes[1])

            network["link_list"].append(
                {
                    "start_device": start_device,
                    "start_port": start_port,
                    "end_device": end_device,
                    "end_port": end_port,
                }
            )

    return network

@router.post("/api/v1/topox")
async def post_topox(request: TopoxRequest) -> JSONResponse:
    """
    保存 topox 文件

    请求体格式:
    {
        "network": {
            "device_list": [
                {"name": "设备名称", "location": "设备位置"}
            ],
            "link_list": [
                {
                    "start_device": "起始设备",
                    "start_port": "起始端口",
                    "end_device": "结束设备",
                    "end_port": "结束端口"
                }
            ]
        }
    }
    """
    logger.info(
        "POST /api/v1/topox payload: %s", json.dumps(request.model_dump(), ensure_ascii=False)
    )

    try:
        # 使用 topo_service 保存文件（会自动触发复制到 AIGC 目标目录）
        response = await topo_service.save_topox(request, "default.topox")

        # 保存设备列表到 aigc.json（包含 text 和 portlist）
        topo_service.save_device_list_to_aigc_json(request.network)

        # ========== 统计：记录第一次保存topo时间 ==========
        try:
            from app.services.metrics_service import metrics_service
            metrics_service.record_topo_save()
        except Exception as metrics_error:
            logger.warning(f"记录topo保存时间失败: {metrics_error}")
        # ================================================

        logger.info(f"成功保存 topox 文件: {response.file_path}")

        return JSONResponse(
            content={
                "status": "ok",
                "message": "Topox 文件保存成功",
                "data": response.xml_content,
                "file_path": response.file_path
            },
            status_code=200
        )

    except Exception as e:
        logger.exception("保存 topox 文件失败")
        return JSONResponse(
            content={
                "status": "error",
                "message": f"保存 topox 文件失败: {str(e)}"
            },
            status_code=500,
        )

@router.get("/api/v1/physical-devices")
async def get_physical_devices() -> JSONResponse:
    """获取带设备属性的拓扑信息，从 aigc.json 读取 device_list 和 link_list，并根据部署状态附加部署信息"""
    try:
        logger.info("GET /api/v1/physical-devices received")

        from app.core.config import settings

        # 获取部署状态
        deploy_status = settings.get_deploy_status()
        device_list = settings.get_deploy_device_list()

        logger.info(f"当前部署状态: {deploy_status}")

        # 第一步：从 aigc.json 读取 device_list 和 link_list
        work_dir = path_manager.get_project_root()
        aigc_json_path = work_dir / ".aigc_tool" / "aigc.json"

        network = {"device_list": [], "link_list": []}

        if aigc_json_path.exists():
            try:
                with open(aigc_json_path, 'r', encoding='utf-8') as f:
                    aigc_config = json.load(f)
                    network["device_list"] = aigc_config.get("device_list", [])
                    network["link_list"] = aigc_config.get("link_list", [])
                logger.info(f"从 aigc.json 读取到 {len(network['device_list'])} 个设备和 {len(network['link_list'])} 条链路")
            except Exception as e:
                logger.warning(f"读取 aigc.json 失败: {str(e)}，返回空数据")
        else:
            logger.info(f"aigc.json 不存在: {aigc_json_path}")

        # 第二步：根据部署状态确定响应消息和是否添加设备连接信息
        response_status = "ok"
        response_message = "获取成功"

        if deploy_status == "deployed" and device_list:
            # 已部署
            response_status = "ok"
            response_message = "部署成功"

        elif deploy_status == "deploying":
            # 部署中 - 不添加设备连接信息
            response_status = "processing"
            response_message = "正在部署中，请稍后刷新"

        elif deploy_status == "failed":
            # 部署失败 - 不添加设备连接信息，返回错误详情
            error_message = settings.get_deploy_error_message()
            response_status = "error"
            response_message = error_message if error_message else "部署失败，请重置设备或者重新部署重试"

        else:  # not_deployed
            # 未部署 - 不添加设备连接信息
            response_status = "idle"
            response_message = "未部署，请先部署环境"

        # 构造响应，包含部署状态
        return JSONResponse(
            content={
                "status": response_status,
                "message": response_message,
                "data": network,
                "deployStatus": deploy_status  # 额外返回部署状态
            },
            status_code=200
        )

    except Exception as e:
        # 捕获所有未处理的异常
        import traceback
        logger.exception("Unexpected error in get_physical_devices: %s\n%s", str(e), traceback.format_exc())
        return JSONResponse(
            content={
                "status": "error",
                "message": f"服务器内部错误: {str(e)}",
                "data": {"device_list": [], "link_list": []}
            },
            status_code=500
        )