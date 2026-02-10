"""
Claude Code API 路由层

提供脚本生成、回写、ITC执行等API接口
业务逻辑已移至 app.services.claude_api 模块
"""
import uuid
import os
from typing import List
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.common import BaseResponse
from app.services.claude_api.task_manager import task_manager
from app.services.claude_api.task_cancellation_manager import task_cancellation_manager
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
    request: GenerateScriptRequest
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

        # 使用 task_cancellation_manager 创建后台任务（支持取消）
        task_cancellation_manager.create_task(
            task_id=task_id,
            coro=script_generation_service.execute_full_pipeline(
                task_id, script_full_path, script_filename, device_commands
            )
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
    prompt: str = Query(..., description="claude用户输入")
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

        # 使用 task_cancellation_manager 创建后台任务（支持取消）
        task_cancellation_manager.create_task(
            task_id=task_id,
            coro=script_generation_service.execute_prompt_pipeline(
                task_id, prompt, workspace
            )
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


@router.post("/claude-chat", response_model=BaseResponse)
async def claude_chat(
    request: dict
):
    """
    直接调用 Claude Code SDK 处理用户输入

    请求参数（JSON Body）：
    - **prompt**: 用户输入的prompt

    不预设prompt模板，直接将用户输入传递给Claude Code SDK处理

    返回taskId，前端可以通过 GET /api/v1/claude/task-log/{task_id} 获取执行日志
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 从请求中获取prompt
        prompt = request.get("prompt", "")
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt参数不能为空")

        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 获取工作目录
        workspace = settings.get_work_directory()

        # 使用 task_manager 创建任务
        task_manager.create_task(
            task_id=task_id,
            test_point=prompt,
            workspace=workspace
        )

        logger.info(f"创建claude-chat任务: task_id={task_id}, prompt={prompt[:50]}...")

        # 使用 task_cancellation_manager 创建后台任务（支持取消）
        task_cancellation_manager.create_task(
            task_id=task_id,
            coro=script_generation_service.execute_claude_chat_pipeline(
                task_id, prompt, workspace
            )
        )

        return BaseResponse(
            status="ok",
            message="Claude Chat 任务已启动",
            data={
                "task_id": task_id,
                "log_url": f"/api/v1/claude/task-log/{task_id}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"创建claude-chat任务失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"创建claude-chat任务失败: {str(e)}")


@router.post("/generate-netconf-script", response_model=BaseResponse)
async def generate_netconf_script(
    files: List[UploadFile] = File(..., description="YANG 文件列表（支持多个文件上传）")
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
        yang_files_dir = os.path.join(workspace,  "yang_files")
        project_dir = os.path.join(workspace)
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

        # 使用 task_cancellation_manager 创建后台任务（支持取消）
        task_cancellation_manager.create_task(
            task_id=task_id,
            coro=script_generation_service.execute_netconf_script_pipeline(
                task_id, workspace, saved_files
            )
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


@router.post("/cancel-task/{task_id}", response_model=BaseResponse)
async def cancel_task(task_id: str):
    """
    取消正在进行的任务

    参数：
    - **task_id**: 任务ID（即log_id）

    返回取消操作的结果，并同步刷新任务日志

    支持取消的任务类型：
    - /claude/prompt 创建的自动化测试流程任务
    - /claude/claude-chat 创建的 Claude Chat 任务
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"收到取消任务请求: task_id={task_id}")

        # 调用取消管理器取消任务
        result = await task_cancellation_manager.cancel_task(task_id)

        # 获取当前任务状态
        task_info = task_manager.get_task(task_id)

        response_data = {
            "task_id": task_id,
            **result
        }

        # 如果取消成功，记录日志
        if result.get("success"):
            # 更新任务管理器中的状态
            if task_info:
                task_manager.update_status(task_id, "cancelled")

            # 写入取消日志到日志文件
            from app.services.claude_api.task_logger import task_logger
            task_logger.write_log(task_id, "⚠️ 用户请求取消任务")
            task_logger.write_end_log(task_id, "cancelled")

            return BaseResponse(
                status="ok",
                message=result.get("message", "任务取消成功"),
                data=response_data
            )
        else:
            # 取消失败（任务不存在或已完成）
            status_code = 404 if result.get("status") == "not_found" else 400
            return BaseResponse(
                status="error",
                message=result.get("message", "任务取消失败"),
                data=response_data
            )

    except Exception as e:
        import traceback
        logger = logging.getLogger(__name__)
        logger.error(f"取消任务失败: task_id={task_id}, error={str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")


@router.get("/task-status/{task_id}", response_model=BaseResponse)
async def get_task_status(task_id: str):
    """
    获取任务状态信息

    参数：
    - **task_id**: 任务ID

    返回任务的当前状态和运行信息
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 从任务管理器获取任务信息
        task_info = task_manager.get_task(task_id)

        if task_info is None:
            raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

        # 检查任务是否在取消管理器中
        running_tasks = task_cancellation_manager.get_all_running_tasks()
        is_running = task_id in running_tasks

        return BaseResponse(
            status="ok",
            message="成功获取任务状态",
            data={
                "task_id": task_id,
                "status": task_info.get("status", "unknown"),
                "stage": task_info.get("stage", ""),
                "is_running": is_running,
                "created_at": task_info.get("created_at", ""),
                "messages_count": len(task_info.get("messages", []))
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logging.getLogger(__name__).error(f"获取任务状态失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")
