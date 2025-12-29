from fastapi import APIRouter, HTTPException, Query
import os
import xml.etree.ElementTree as ET
from typing import List, Optional

from app.services.file_service import file_service
from app.services.python_analysis_service import python_analysis_service
from app.services.script_command_extract import (
    refresh_static_variables,
    filename_command_mapping
)
from app.services.topo_service import topo_service
from app.core.config import settings
from app.core.path_manager import path_manager
from app.models.common import BaseResponse, FileOperationRequest, FileOperationResponse, DirectoryItem
from app.models.python_analysis import PythonFilesResponse, FilePathRequest

router = APIRouter(prefix="/files", tags=["文件操作"])

@router.get("/read", response_model=BaseResponse)
async def read_file_or_directory(
    path: str = Query(..., description="文件或目录路径"),
    encoding: str = Query(default="utf-8", description="文件编码")
):
    """读取文件或目录内容
AI_FingerPrint_UUID: 20251224-TXpcoB1x
"""
    try:
        # 判断是文件还是目录
        resolved_path = file_service.path_manager.resolve_path(path)

        if resolved_path.is_dir():
            # 读取目录
            result = await file_service.read_directory(path)
        else:
            # 读取文件
            result = await file_service.read_file(path, encoding)

        if result.success:
            return BaseResponse(
                status="ok",
                message=result.message,
                content=result.content if hasattr(result, 'content') else None,
                data={
                    "path": result.path,
                    "operation": result.operation,
                    "size": result.size,
                    "content": result.content if hasattr(result, 'content') else None
                }
            )
        else:
            raise HTTPException(status_code=400, detail=result.message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {str(e)}")

@router.post("/write", response_model=BaseResponse)
async def write_file(request: FileOperationRequest):
    """写入文件内容"""
    try:
        if not request.content:
            raise HTTPException(status_code=400, detail="文件内容不能为空")

        result = await file_service.write_file(
            request.path,
            request.content,
            request.encoding
        )

        if result.success:
            return BaseResponse(
                status="ok",
                message=result.message,
                data={
                    "path": result.path,
                    "operation": result.operation,
                    "size": result.size
                }
            )
        else:
            raise HTTPException(status_code=400, detail=result.message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {str(e)}")

@router.delete("/delete", response_model=BaseResponse)
async def delete_file_or_directory(
    path: str = Query(..., description="文件或目录路径")
):
    """删除文件或目录"""
    try:
        result = await file_service.delete_file(path)

        if result.success:
            return BaseResponse(
                status="ok",
                message=result.message,
                data={
                    "path": result.path,
                    "operation": result.operation,
                    "size": result.size
                }
            )
        else:
            raise HTTPException(status_code=400, detail=result.message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

@router.get("/tree", response_model=BaseResponse)
async def get_directory_tree(
    path: str = Query(default="", description="目录路径，为空时返回项目根目录")
):
    """获取目录树结构"""
    try:
        tree_items = await file_service.get_directory_tree(path)

        # 转换为字典格式
        def item_to_dict(item):
            # 确保路径使用正斜杠格式
            path = item.path.replace("\\", "/") if item.path else item.path

            # 格式化时间为年月日时分秒
            formatted_time = None
            if item.modified_time:
                formatted_time = item.modified_time.strftime("%Y-%m-%d %H:%M:%S")

            return {
                "label": item.label,
                "path": path,
                "children": [item_to_dict(child) for child in item.children] if item.children else None,
                "is_file": item.is_file,
                "size": item.size,
                "modified_time": formatted_time
            }

        tree_data = [item_to_dict(item) for item in tree_items]

        return BaseResponse(
            status="ok",
            message=f"成功获取目录树，共 {len(tree_data)} 个顶级项目",
            data=tree_data
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取目录树失败: {str(e)}")

@router.get("/list", response_model=BaseResponse)
async def list_directory(
    path: str = Query(..., description="目录路径")
):
    """列出目录内容（扁平结构）"""
    try:
        result = await file_service.read_directory(path)

        if result.success:
            # 解析返回的JSON内容
            import json
            if result.content:
                directory_items = json.loads(result.content)
            else:
                directory_items = []

            return BaseResponse(
                status="ok",
                message=result.message,
                data=directory_items
            )
        else:
            raise HTTPException(status_code=400, detail=result.message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"列出目录失败: {str(e)}")

@router.get("/python-files", response_model=PythonFilesResponse)
async def get_all_python_files(
    base_path: Optional[str] = Query(None, description="基础路径，为空时搜索整个项目")
):
    """获取项目中所有Python文件列表"""
    try:
        python_files = await python_analysis_service.find_all_python_files(base_path)
        
        return PythonFilesResponse(
            status="ok",
            message=f"找到 {len(python_files)} 个Python文件",
            data=python_files,
            total_count=len(python_files)
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取Python文件列表失败: {str(e)}")

@router.post("/executed-command-lines", response_model=BaseResponse)
async def extract_executed_command_lines(request: FilePathRequest):
    """根据Python执行后的日志提取命令行"""
    try:
        import logging
        logger = logging.getLogger(__name__)

        # Get the filename from the request path
        file_path = request.file_path
        filename = os.path.basename(file_path)

        logger.info(f"=== 命令行提取调试信息 ===")
        logger.info(f"请求的文件路径: {file_path}")
        logger.info(f"提取的文件名: {filename}")
        logger.info(f"开始实时解析日志目录（将删除并重建 local 临时目录）...")

        # 实时解析日志文件，不使用缓存
        # 每次解析前会删除并重建 local 目录，确保使用最新的解码文件
        from app.services.script_command_extract.agent_helper import ExtractCommandAgent
        agent = ExtractCommandAgent(settings.get_script_command_log_path())
        log_command_mapping = agent.get_log_command_info()

        logger.info(f"日志解析完成，获取到 {len(log_command_mapping)} 个文件映射")
        logger.info(f"映射键列表: {list(log_command_mapping.keys())}")

        # Match the file path with the mapping
        command_lines = ""

        # Try exact filename match first
        if filename in log_command_mapping:
            command_lines = log_command_mapping[filename]
            logger.info(f"精确匹配成功: {filename}")
        else:
            # Try to find a partial match
            logger.info(f"精确匹配失败，尝试部分匹配...")
            for key, value in log_command_mapping.items():
                if filename in key or key in filename:
                    command_lines = value
                    logger.info(f"部分匹配成功: 请求文件名='{filename}', 映射键='{key}'")
                    break
            else:
                logger.warning(f"未找到匹配的命令行映射")

        # If no match found, use empty string
        if not command_lines:
            logger.warning(f"命令行为空，返回空字符串")
            command_lines = ""

        # 从 topox 文件获取设备列表
        device_list = await _get_device_list_from_topox()

        # 将 IP 地址转换为域名
        device_list = settings.convert_ip_to_domain(device_list)

        return BaseResponse(
            status="ok",
            message="成功提取命令行",
            data={
                "commandLines": command_lines,
                "deviceList": device_list
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提取命令行失败: {str(e)}")


async def _get_device_list_from_topox():
    """
    从 topox 文件获取设备列表，并根据部署状态补充连接信息

    Returns:
        list: 设备列表，如果已部署则包含连接信息
    """
    try:
        # 1. 从 topox 文件读取设备列表
        topox_response = await topo_service.load_topox("default.topox")

        if not topox_response.network or not topox_response.network.device_list:
            # 如果 topox 文件为空或不存在，返回空列表
            return []

        # 转换为字典格式的设备列表
        device_list = []
        for device in topox_response.network.device_list:
            device_list.append({
                "name": device.name,
                "location": device.location,
                "title": device.name  # 添加 title 属性，默认使用设备名
            })

        # 2. 获取部署状态和已部署的设备信息
        deploy_status = settings.get_deploy_status()
        deployed_device_list = settings.get_deploy_device_list()

        # 3. 如果已部署且有设备信息，补充连接信息
        if deploy_status == "deployed" and deployed_device_list:
            # 创建设备名到连接信息的映射
            device_connection_map = {}
            for device_info in deployed_device_list:
                device_name = device_info.get("name")
                if device_name:
                    device_connection_map[device_name] = {
                        "host": device_info.get("host"),
                        "port": device_info.get("port"),
                        "type": device_info.get("type"),
                        "executorip": device_info.get("executorip"),
                        "userip": device_info.get("userip"),
                        "title": device_info.get("title")  # 添加 title，从 deploy 返回的值获取
                    }

            # 为设备列表中的每个设备添加连接信息
            for device in device_list:
                device_name = device.get("name")
                if device_name in device_connection_map:
                    device.update(device_connection_map[device_name])

        return device_list

    except Exception as e:
        # 如果读取失败，记录错误并返回空列表
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"从 topox 文件获取设备列表失败: {str(e)}")
        return []
