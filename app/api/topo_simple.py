import json
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from xml.etree.ElementTree import ParseError

from app.core.path_manager import path_manager
from app.models.topox import TopoxRequest
from app.services.topo_service import topo_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["拓扑管理"])


# 完全保留main2.py的API端点，只修改路径适配
@router.get("/api/v1/topox")
async def get_topox() -> JSONResponse:
    logger.info("GET /api/v1/topox received")
    # 修改为使用新的路径管理系统，但保持原有的路径结构逻辑
    # 原来是: Path.home() / "project" / "test_scripts" / "default.topox"
    # 现在使用配置中的路径
    topox_path = path_manager.get_topox_dir() / "default.topox"

    if topox_path.exists():
        try:
            data = topox_path.read_text(encoding="utf-8")
            # topo_service returns a Network pydantic model; convert to dict for JSON response
            network = topo_service.parse_topox_xml(data).model_dump()
        except OSError:
            logger.exception("Failed to read %s", topox_path)
            return JSONResponse(
                content={
                    "status": "error",
                    "message": "Failed to read topox file.",
                    "data": "",
                },
                status_code=500,
            )
        except ParseError:
            return JSONResponse(
                content={
                    "status": "error",
                    "message": "Invalid topox XML.",
                    "data": "",
                },
                status_code=500,
            )
    else:
        logger.info("%s not found; returning empty data", topox_path)
        network = {"device_list": [], "link_list": []}

    # 定义mock设备属性信息
    mock_device_attrs = {
        "DUT1": {"host": "55.97.64.23", "port": 23, "type": "telnet"},
        "DUT2": {"host": "55.97.64.32", "port": 23, "type": "telnet"},
        "DUT3": {"host": "55.97.64.27", "port": 23, "type": "telnet"},
    }

    # 为设备列表中的每个设备添加新属性，不修改返回结构
    for device in network["device_list"]:
        device_name = device["name"]
        if device_name in mock_device_attrs:
            device.update(mock_device_attrs[device_name])

    return JSONResponse(content={"status": "ok", "data": network}, status_code=200)


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
        "POST /api/v1/topox payload: %s",
        json.dumps(request.model_dump(), ensure_ascii=False),
    )

    try:
        # 使用 topo_service 保存文件（会自动触发复制到 AIGC 目标目录）
        response = await topo_service.save_topox(request, "default.topox")

        logger.info(f"成功保存 topox 文件: {response.file_path}")

        return JSONResponse(
            content={
                "status": "ok",
                "message": "Topox 文件保存成功",
                "data": response.xml_content,
                "file_path": response.file_path,
            },
            status_code=200,
        )

    except Exception as e:
        logger.exception("保存 topox 文件失败")
        return JSONResponse(
            content={"status": "error", "message": f"保存 topox 文件失败: {str(e)}"},
            status_code=500,
        )


@router.get("/api/v1/physical-devices")
async def get_physical_devices() -> JSONResponse:
    """获取带设备属性的拓扑信息，始终返回拓扑结构，并根据部署状态附加部署信息"""
    try:
        logger.info("GET /api/v1/physical-devices received")

        from app.core.config import settings

        # 获取部署状态
        deploy_status = settings.get_deploy_status()
        device_list = settings.get_deploy_device_list()

        logger.info(f"当前部署状态: {deploy_status}")

        # 第一步：始终读取并返回拓扑结构
        topox_path = path_manager.get_topox_dir() / "default.topox"
        if topox_path.exists():
            try:
                data = topox_path.read_text(encoding="utf-8")
                # topo_service returns a Network pydantic model; convert to dict for JSON response
                network = topo_service.parse_topox_xml(data).model_dump()
            except OSError:
                logger.exception("Failed to read %s", topox_path)
                network = {"device_list": [], "link_list": []}
            except ParseError:
                logger.exception("Failed to parse topox XML from %s", topox_path)
                network = {"device_list": [], "link_list": []}
            except Exception as e:
                logger.exception("Unexpected error reading topox file: %s", str(e))
                network = {"device_list": [], "link_list": []}
        else:
            logger.info("%s not found; returning empty data", topox_path)
            network = {"device_list": [], "link_list": []}

        if deploy_status == "deployed" and device_list:
            # 部署成功 - 添加设备连接信息（包括 title）
            device_attrs_map = {}
            for device_info in device_list:
                device_name = device_info.get("name")
                if device_name:
                    device_attrs_map[device_name] = {
                        "host": device_info.get("host"),
                        "port": device_info.get("port"),
                        "type": device_info.get("type"),
                        "executorip": device_info.get("executorip"),
                        "userip": device_info.get("userip"),
                        "title": device_info.get(
                            "title", device_name
                        ),  # 添加 title 属性，默认使用设备名
                    }

            # 为设备列表中的每个设备添加属性
            for device in network["device_list"]:
                device_name = device["name"]
                if device_name in device_attrs_map:
                    device.update(device_attrs_map[device_name])

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
            response_message = (
                error_message
                if error_message
                else "部署失败，请重置设备或者重新部署重试"
            )

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
                "deployStatus": deploy_status,  # 额外返回部署状态
            },
            status_code=200,
        )

    except Exception as e:
        # 捕获所有未处理的异常
        import traceback

        logger.exception(
            "Unexpected error in get_physical_devices: %s\n%s",
            str(e),
            traceback.format_exc(),
        )
        return JSONResponse(
            content={
                "status": "error",
                "message": f"服务器内部错误: {str(e)}",
                "data": {"device_list": [], "link_list": []},
            },
            status_code=500,
        )
