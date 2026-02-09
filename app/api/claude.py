"""
Claude Code API 路由层

提供脚本生成、回写、ITC执行等API接口
业务逻辑已移至 app.services.claude_api 模块
"""
import uuid
import os
from typing import List
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, UploadFile, File
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.common import BaseResponse
from app.services.claude_api.task_manager import task_manager
from app.services.claude_api.script_generation_service import script_generation_service

router = APIRouter(prefix="/claude", tags=["Claude Code"])


# ==================== 请求/响应模型 ====================

class GenerateScriptRequest(BaseModel):
    """生成测试脚本请求模型"""
    device_commands: str = Field(..., description="设备命令列表（新命令）")
    script_path: str = Field(..., description="脚本文件的相对路径")


# ==================== API 路由 ====================

@router.post("/generate-script", response_model=BaseResponse)
async def generate_test_script(
    request: GenerateScriptRequest,
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    根据设备命令生成测试脚本的快捷接口

    请求参数（JSON Body）：
    - **device_commands**: 设备命令列表（新命令内容）
    - **script_path**: 脚本文件的相对路径

    返回taskId，前端可以通过 GET /api/v1/claude/task-log/{task_id} 获取执行日志
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 从请求对象中获取参数
        device_commands = request.device_commands
        script_path = request.script_path

        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 获取工作目录
        workspace = settings.get_work_directory()

        # 构建脚本的绝对路径
        script_full_path = os.path.join(workspace, script_path) if not os.path.isabs(script_path) else script_path

        # 检查脚本文件是否存在
        if not os.path.exists(script_full_path):
            raise HTTPException(status_code=404, detail=f"脚本文件不存在: {script_full_path}")

        # 获取文件名（用于从 filename_command_mapping 中查找旧命令）
        script_filename = os.path.basename(script_path)

        # 使用 task_manager 创建任务
        task_manager.create_task(
            task_id=task_id,
            script_path=script_full_path,
            script_filename=script_filename,
            device_commands=device_commands
        )

        logger.info(f"创建generate-script任务: task_id={task_id}, script={script_path}")

        # 添加后台任务执行完整流程（脚本回写 + 拷贝 + ITC run）
        background_tasks.add_task(
            script_generation_service.execute_full_pipeline,
            task_id,
            script_full_path,
            script_filename,
            device_commands
        )

        return BaseResponse(
            status="ok",
            message="脚本生成和回写任务已启动",
            data={
                "task_id": task_id,
                "log_url": f"/api/v1/claude/task-log/{task_id}",
                "script_path": script_path,
                "script_full_path": script_full_path
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"创建generate-script任务失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"创建generate-script任务失败: {str(e)}")


@router.post("/prompt", response_model=BaseResponse)
async def execute_custom_command(
    prompt: str = Query(..., description="claude用户输入"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    执行完整的自动化测试流程：
    1. 生成 conftest.py
    2. 生成测试脚本
    3. 调用 ITC run 接口执行脚本

    返回taskId，前端可以通过 GET /api/v1/claude/task-log/{task_id} 获取执行日志
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 使用默认工作目录
        workspace = settings.get_work_directory()

        # 使用 task_manager 创建任务
        task_manager.create_task(
            task_id=task_id,
            test_point=prompt,
            workspace=workspace
        )

        logger.info(f"创建prompt任务: task_id={task_id}, test_point={prompt[:50]}...")

        # 添加后台任务执行完整流程
        background_tasks.add_task(
            script_generation_service.execute_prompt_pipeline,
            task_id,
            prompt,
            workspace
        )

        return BaseResponse(
            status="ok",
            message="自动化测试流程任务已启动",
            data={
                "task_id": task_id,
                "log_url": f"/api/v1/claude/task-log/{task_id}",
                "stages": [
                    "conftest生成",
                    "测试脚本生成",
                    "ITC脚本执行"
                ]
            }
        )

    except Exception as e:
        import traceback
        logger.error(f"创建prompt任务失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"创建prompt任务失败: {str(e)}\n{traceback.format_exc()}")


@router.get("/task-log/{task_id}", response_model=BaseResponse)
async def get_task_log(task_id: str):
    """
    获取任务的完整日志内容

    参数：
    - **task_id**: 任务ID

    返回任务日志文件的所有内容
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 使用 service 层获取日志内容
        log_data = script_generation_service.get_task_log_content(task_id)

        if log_data is None:
            raise HTTPException(status_code=404, detail=f"任务日志文件不存在: {task_id}")

        # logger.info(f"读取任务日志: task_id={task_id}, 日志行数={log_data['log_lines']}")

        return BaseResponse(
            status="ok",
            message=f"成功获取任务日志，共 {log_data['log_lines']} 行",
            data=log_data
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logging.getLogger(__name__).error(f"获取任务日志失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取任务日志失败: {str(e)}")


@router.post("/generate-netconf-script", response_model=BaseResponse)
async def generate_netconf_script(
    files: List[UploadFile] = File(..., description="YANG 文件列表（支持多个文件上传）"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    根据上传的 YANG 文件生成 NETCONF 测试脚本

    请求参数（multipart/form-data）：
    - **files**: YANG 文件列表，支持同时上传多个文件

    处理流程：
    1. 保存上传的 YANG 文件到 /project/yang_files 目录
    2. 生成 NETCONF 测试脚本
    3. 生成对应的 log 文件
    4. 返回 log_id（task_id）

    返回taskId，前端可以通过 GET /api/v1/claude/task-log/{task_id} 获取执行日志
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 获取工作目录
        workspace = settings.get_work_directory()

        # 构建目录路径
        yang_files_dir = os.path.join(workspace, "project", "yang_files")
        project_dir = os.path.join(workspace, "project")
        os.makedirs(yang_files_dir, exist_ok=True)
        os.makedirs(project_dir, exist_ok=True)

        # 保存上传的文件
        saved_files = []
        yang_files = []
        other_files = []
        for file in files:
            filename = file.filename
            if not filename:
                logger.warning(f"Task {task_id}: 跳过空文件名")
                continue

            # 安全检查：防止路径穿越攻击
            if '..' in filename or '/' in filename or '\\' in filename:
                logger.warning(f"Task {task_id}: 检测到非法文件名: {filename}")
                continue

            # 根据文件后缀决定保存路径
            if filename.endswith('.yang'):
                file_path = os.path.join(yang_files_dir, filename)
                yang_files.append(filename)
            else:
                file_path = os.path.join(project_dir, filename)
                other_files.append(filename)

            # 保存文件
            try:
                with open(file_path, 'wb') as f:
                    content = await file.read()
                    f.write(content)
                saved_files.append(filename)
                logger.info(f"Task {task_id}: 已保存文件: {filename}")
            except Exception as e:
                logger.error(f"Task {task_id}: 保存文件 {filename} 失败: {str(e)}")

        if not saved_files:
            raise HTTPException(status_code=400, detail="未找到有效的文件")

        # 使用 task_manager 创建任务
        task_manager.create_task(
            task_id=task_id,
            test_point=f"生成 NETCONF 测试脚本，基于 {len(saved_files)} 个 YANG 文件",
            workspace=workspace
        )

        logger.info(f"创建generate-netconf-script任务: task_id={task_id}, files={saved_files}")

        # 添加后台任务执行完整流程
        background_tasks.add_task(
            script_generation_service.execute_netconf_script_pipeline,
            task_id,
            workspace,
            saved_files
        )

        return BaseResponse(
            status="ok",
            message="NETCONF 脚本生成任务已启动",
            data={
                "task_id": task_id,
                "log_id": task_id,
                "log_url": f"/api/v1/claude/task-log/{task_id}",
                "saved_files": saved_files,
                "yang_files": yang_files,
                "other_files": other_files,
                "yang_files_dir": yang_files_dir,
                "project_dir": project_dir
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"创建generate-netconf-script任务失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"创建 NETCONF 脚本生成任务失败: {str(e)}")
