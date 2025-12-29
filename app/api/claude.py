import json
import asyncio
import uuid
import os
import shutil
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query, Depends, BackgroundTasks
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.services.claude_service import claude_service
from app.models.claude import (
    ClaudeCommandRequest, ClaudeCommandResponse, ClaudeLogQuery,
    ClaudeLogEntry, ClaudeCommandType
)
from app.models.common import BaseResponse
from app.core.config import settings

router = APIRouter(prefix="/claude", tags=["Claude Code"])


class ConftestRequest(BaseModel):
    """Conftest生成请求模型
AI_FingerPrint_UUID: 20251225-rxbt8O1c
"""
    test_point: str = Field(..., description="测试点描述")
    workspace: Optional[str] = Field(None, description="工作目录，默认使用项目工作目录")


class GenerateScriptRequest(BaseModel):
    """生成测试脚本请求模型
AI_FingerPrint_UUID: 20251225-Mk7LnQ3R
"""
    device_commands: str = Field(..., description="设备命令列表（新命令）")
    script_path: str = Field(..., description="脚本文件的相对路径")


# 任务管理器：存储task_id和WebSocket的映射
conftest_tasks = {}

@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket端点，用于实时输出Claude命令执行结果"""
    await websocket.accept()

    # 注册WebSocket连接
    claude_service.register_websocket(task_id, websocket)

    try:
        # 发送连接确认消息
        await websocket.send_text(json.dumps({
            "type": "connected",
            "task_id": task_id,
            "message": "WebSocket连接已建立",
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False))

        # 创建并启动定时发送测试数据的后台任务
        test_data_task = asyncio.create_task(send_test_data())

        # 保持连接活跃，处理客户端消息（用于心跳）
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    }, ensure_ascii=False))
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                # 忽略无效的JSON消息
                continue
            except Exception as e:
                # 发生错误时记录日志并断开连接
                print(f"WebSocket错误: {str(e)}")
                break

    except WebSocketDisconnect:
        pass
    finally:
        # 取消定时发送测试数据的任务
        test_data_task.cancel()
        try:
            await test_data_task
        except asyncio.CancelledError:
            pass
        # 取消注册WebSocket连接
        claude_service.unregister_websocket(task_id, websocket)

@router.post("/conftest", response_model=BaseResponse)
async def create_conftest(request: ConftestRequest, background_tasks: BackgroundTasks):
    """
    生成conftest.py文件

    - **test_point**: 测试点描述
    - **workspace**: 工作目录，可选，默认使用项目配置的工作目录

    返回taskId，前端通过WebSocket /ws/claude/conftest/{task_id} 接收实时进度
    """
    try:
        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 使用默认工作目录（如果未提供）
        workspace = request.workspace
        if not workspace:
            workspace = settings.get_work_directory()

        # 存储任务信息
        conftest_tasks[task_id] = {
            "test_point": request.test_point,
            "workspace": workspace,
            "status": "pending"
        }

        # 添加后台任务执行生成
        background_tasks.add_task(execute_conftest_generation, task_id, request.test_point, workspace)

        return BaseResponse(
            status="ok",
            message="conftest生成任务已启动",
            data={
                "task_id": task_id,
                "websocket_url": f"/ws/claude/conftest/{task_id}"
            }
        )

    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"创建conftest任务失败: {str(e)}\n{traceback.format_exc()}")


async def execute_conftest_generation(task_id: str, test_point: str, workspace: str):
    """后台执行conftest生成任务"""
    try:
        from app.services.cc_workflow import stream_generate_conftest_response
        import logging
        logger = logging.getLogger(__name__)

        # 更新任务状态
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = "running"

        # 调用生成函数
        async for message in stream_generate_conftest_response(test_point=test_point, workspace=workspace):
            # 判断消息类型并发送到WebSocket
            message_type = type(message).__name__

            # 提取消息内容
            message_content = ""
            if hasattr(message, 'content'):
                message_content = message.content
            elif hasattr(message, 'text'):
                message_content = message.text
            elif hasattr(message, 'model_response'):
                message_content = str(message.model_response)
            else:
                message_content = str(message)

            # 判断是否是错误消息
            is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False

            # 构造WebSocket消息
            ws_message = {
                "status": "processing",
                "type": message_type,
                "data": message_content,
                "timestamp": datetime.now().isoformat()
            }

            # 如果是ResultMessage（最终结果）或错误消息，标记为end状态
            if "Result" in message_type or "result" in message_type.lower() or is_error:
                ws_message["status"] = "end"

            logger.info(f"Task {task_id}: 收到消息 type={message_type}, status={ws_message['status']}")

            # 发送到消息队列
            if task_id in conftest_tasks:
                conftest_tasks[task_id].setdefault("messages", []).append(ws_message)

        # 更新任务状态为完成
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = "completed"
            logger.info(f"Task {task_id}: 完成")

    except Exception as e:
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        error_msg = f"生成conftest失败: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")

        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = "failed"
            conftest_tasks[task_id].setdefault("messages", []).append({
                "status": "end",
                "type": "error",
                "data": error_msg,
                "timestamp": datetime.now().isoformat()
            })


@router.websocket("/conftest/{task_id}")
async def websocket_conftest_endpoint(websocket: WebSocket, task_id: str):
    """conftest生成专用的WebSocket端点"""
    import logging
    logger = logging.getLogger(__name__)

    await websocket.accept()
    logger.info(f"WebSocket连接已建立: task_id={task_id}")

    try:
        # 发送连接确认
        await websocket.send_text(json.dumps({
            "status": "connected",
            "task_id": task_id,
            "message": "WebSocket连接已建立",
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False))

        # 如果任务已存在，发送已缓存的消息
        if task_id in conftest_tasks and "messages" in conftest_tasks[task_id]:
            cached_messages = conftest_tasks[task_id]["messages"]
            logger.info(f"发送 {len(cached_messages)} 条缓存消息")
            for msg in cached_messages:
                await websocket.send_text(json.dumps(msg, ensure_ascii=False))
        else:
            logger.info(f"任务 {task_id} 尚未开始或没有消息")

        # 保持连接，持续发送新消息
        last_sent_count = len(conftest_tasks.get(task_id, {}).get("messages", []))

        while True:
            try:
                # 检查是否有新消息
                if task_id in conftest_tasks:
                    messages = conftest_tasks[task_id].get("messages", [])
                    if len(messages) > last_sent_count:
                        # 发送新消息
                        new_messages = messages[last_sent_count:]
                        logger.info(f"发送 {len(new_messages)} 条新消息")
                        for msg in new_messages:
                            await websocket.send_text(json.dumps(msg, ensure_ascii=False))

                            # 如果是结束状态，关闭连接
                            if msg.get("status") == "end":
                                logger.info(f"收到结束状态消息，关闭连接")
                                await websocket.close()
                                return

                        last_sent_count = len(messages)

                    # 如果任务已完成且没有新消息，关闭连接
                    task_status = conftest_tasks[task_id].get("status")
                    if task_status in ["completed", "failed"] and len(messages) == last_sent_count:
                        logger.info(f"任务状态={task_status}，没有新消息，关闭连接")
                        await asyncio.sleep(0.5)  # 等待最后消息发送
                        await websocket.close()
                        return

                # 处理心跳（带超时）
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    message = json.loads(data)

                    if message.get("type") == "ping":
                        await websocket.send_text(json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }, ensure_ascii=False))
                except asyncio.TimeoutError:
                    # 超时继续循环，检查新消息
                    continue

            except WebSocketDisconnect:
                logger.info(f"WebSocket断开连接: task_id={task_id}")
                break
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"WebSocket错误: {str(e)}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket连接断开: task_id={task_id}")
    except Exception as e:
        logger.error(f"WebSocket端点异常: {str(e)}")
    finally:
        logger.info(f"WebSocket连接清理: task_id={task_id}")
        # 清理任务数据（可选，保留一段时间用于调试）
        # if task_id in conftest_tasks:
        #     del conftest_tasks[task_id]
        pass

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

    返回taskId，前端通过WebSocket /api/v1/claude/ws/{task_id} 接收实时进度
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

        # 存储任务信息
        conftest_tasks[task_id] = {
            "script_path": script_full_path,
            "script_filename": script_filename,
            "device_commands": device_commands,
            "status": "pending",
            "stage": "pending"
        }

        logger.info(f"创建generate-script任务: task_id={task_id}, script={script_path}")

        # 添加后台任务执行完整流程（脚本回写 + 拷贝 + ITC run）
        background_tasks.add_task(execute_full_pipeline, task_id, script_full_path, script_filename, device_commands)

        return BaseResponse(
            status="ok",
            message="脚本生成和回写任务已启动",
            data={
                "task_id": task_id,
                "websocket_url": f"/api/v1/claude/ws/{task_id}",
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

    返回taskId，前端通过WebSocket /ws/claude/prompt/{task_id} 接收实时进度
    """
    try:
        import logging
        logger = logging.getLogger(__name__)

        # 生成唯一任务ID
        task_id = str(uuid.uuid4())

        # 使用默认工作目录
        workspace = settings.get_work_directory()
        #prompt = "测试BGP IPv4地址族发送的静态路由 \n前置背景：\nDUT1和DUT2使用物理口地址建立直连IBGP邻居，DUT1建立静态路由\n测试步骤：\n1、DUT1 bgp发布静态路由，DUT2上检查BGP接收到对应路由"

        # 存储任务信息
        conftest_tasks[task_id] = {
            "test_point": prompt,
            "workspace": workspace,
            "status": "pending",
            "stage": "pending"  # 新增：记录当前阶段
        }

        logger.info(f"创建prompt任务: task_id={task_id}, test_point={prompt[:50]}...")

        # 添加后台任务执行完整流程
        background_tasks.add_task(execute_prompt_pipeline, task_id, prompt, workspace)

        return BaseResponse(
            status="ok",
            message="自动化测试流程任务已启动",
            data={
                "task_id": task_id,
                "websocket_url": f"/ws/claude/prompt/{task_id}",
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


async def execute_prompt_pipeline(task_id: str, test_point: str, workspace: str):
    """
    执行完整的自动化测试流程：
    1. 生成 conftest.py
    2. 生成测试脚本
    3. 调用 ITC run 接口执行脚本
    """
    import logging
    logger = logging.getLogger(__name__)

    def send_message(message_type: str, data: str, status: str = "processing", stage: str = ""):
        """发送消息到WebSocket消息队列"""
        try:
            ws_message = {
                "status": status,
                "type": message_type,
                "data": data,
                "stage": stage,
                "timestamp": datetime.now().isoformat()
            }

            if task_id in conftest_tasks:
                conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
                logger.info(f"Task {task_id} [{stage}]: {message_type} - {data[:100]}...")
            else:
                logger.warning(f"Task {task_id}: 任务不存在，无法发送消息")
        except Exception as e:
            # 发送消息失败不应该影响主流程
            logger.error(f"Task {task_id}: 发送消息失败: {str(e)}")

    def update_task_status(status: str, stage: str = ""):
        """更新任务状态"""
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = status
            if stage:
                conftest_tasks[task_id]["stage"] = stage

    try:
        # 更新任务状态为运行中
        update_task_status("running", "conftest生成")
        send_message("info", f"开始执行自动化测试流程\n测试点: {test_point[:100]}...", "processing", "conftest生成")

        # ========== 阶段1: 生成 conftest.py ==========
        logger.info(f"Task {task_id}: 开始生成 conftest.py")
        send_message("info", "===== 阶段1: 生成 conftest.py =====", "processing", "conftest生成")

        from app.services.cc_workflow import stream_generate_conftest_response

        async for message in stream_generate_conftest_response(test_point=test_point, workspace=workspace):
            message_type = type(message).__name__

            # 提取消息内容
            message_content = ""
            if hasattr(message, 'content'):
                message_content = message.content
            elif hasattr(message, 'text'):
                message_content = message.text
            elif hasattr(message, 'model_response'):
                message_content = str(message.model_response)
            else:
                message_content = str(message)

            # 判断是否是错误消息
            is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False

            # 判断是否是结果消息
            is_result = "Result" in message_type or "result" in message_type.lower()

            # 发送消息
            msg_status = "end" if (is_result or is_error) else "processing"
            send_message(message_type, message_content, msg_status, "conftest生成")

            if is_error:
                update_task_status("failed", "conftest生成")
                send_message("error", "conftest.py生成失败，终止流程", "end", "conftest生成")
                return

        logger.info(f"Task {task_id}: conftest.py 生成完成")
        send_message("info", "✓ conftest.py 生成完成", "processing", "conftest生成")

        # 拷贝 conftest.py 到指定目录
        try:
            import getpass

            username = getpass.getuser()
            target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"
            os.makedirs(target_dir, exist_ok=True)

            # 查找 workspace 中的 conftest.py 文件
            conftest_files = []
            workspace_realpath = os.path.realpath(workspace)  # 获取真实路径

            # 需要过滤的目录（虚拟环境、缓存、版本控制等）
            filtered_dirs = {
                'ke',           # KE 目录
                'venv',         # 虚拟环境
                '.venv',        # 虚拟环境
                'env',          # 虚拟环境
                '.env',         # 虚拟环境
                '__pycache__',  # Python 缓存
                '.git',         # Git 版本控制
                '.svn',         # SVN 版本控制
                'node_modules', # Node.js 模块
                '.pytest_cache',# pytest 缓存
                'dist',         # 构建目录
                'build',        # 构建目录
                '.tox',         # tox 测试环境
                '.eggs',        # eggs 目录
                '*.egg-info',   # egg-info 目录
            }

            for root, dirs, files in os.walk(workspace):
                # 过滤掉不需要的目录（大小写不敏感）
                dirs[:] = [d for d in dirs if d.lower() not in filtered_dirs and not d.startswith('.')]

                # 安全检查：确保只在工作目录内查找
                root_realpath = os.path.realpath(root)
                if not root_realpath.startswith(workspace_realpath):
                    logger.warning(f"跳过工作目录外的路径: {root}")
                    continue

                if "conftest.py" in files:
                    conftest_files.append(os.path.join(root, "conftest.py"))

            logger.info(f"找到 {len(conftest_files)} 个 conftest.py 文件")

            if conftest_files:
                # 使用找到的第一个 conftest.py 文件（通常只有一个）
                source_conftest = conftest_files[0]
                target_conftest = os.path.join(target_dir, "conftest.py")

                # 拷贝文件（覆盖已存在的文件）
                shutil.copy2(source_conftest, target_conftest)

                # 设置文件权限为 777（其他用户可读可写）
                try:
                    os.chmod(target_conftest, 0o777)
                    os.chmod(target_dir, 0o777)
                except PermissionError:
                    logger.warning(f"Task {task_id}: 权限不足，无法设置文件权限 {target_conftest}，但文件已成功拷贝")

                logger.info(f"Task {task_id}: conftest.py 已拷贝到 {target_conftest}")
                send_message("info", f"✓ conftest.py 已备份到: {target_conftest}", "processing", "conftest生成")
            else:
                logger.warning(f"Task {task_id}: 在 {workspace} 中未找到 conftest.py 文件")
                send_message("warning", f"⚠ 未找到 conftest.py 文件，跳过备份", "processing", "conftest生成")

        except Exception as e:
            logger.error(f"Task {task_id}: 拷贝 conftest.py 失败: {str(e)}")
            send_message("warning", f"⚠ 备份 conftest.py 失败: {str(e)}，继续执行后续流程", "processing", "conftest生成")

        # ========== 阶段2: 生成测试脚本 ==========
        logger.info(f"Task {task_id}: 开始生成测试脚本")
        update_task_status("running", "测试脚本生成")
        send_message("info", "\n===== 阶段2: 生成测试脚本 =====", "processing", "测试脚本生成")

        # 生成前：记录工作目录中已存在的测试脚本文件
        existing_scripts_before = set()
        workspace_realpath = os.path.realpath(workspace)

        # 需要过滤的目录（虚拟环境、缓存、版本控制等）
        filtered_dirs = {
            'ke',           # KE 目录
            'venv',         # 虚拟环境
            '.venv',        # 虚拟环境
            'env',          # 虚拟环境
            '.env',         # 虚拟环境
            '__pycache__',  # Python 缓存
            '.git',         # Git 版本控制
            '.svn',         # SVN 版本控制
            'node_modules', # Node.js 模块
            '.pytest_cache',# pytest 缓存
            'dist',         # 构建目录
            'build',        # 构建目录
            '.tox',         # tox 测试环境
            '.eggs',        # eggs 目录
            '*.egg-info',   # egg-info 目录
        }

        try:
            for root, dirs, files in os.walk(workspace):
                # 过滤掉不需要的目录（大小写不敏感）
                dirs[:] = [d for d in dirs if d.lower() not in filtered_dirs and not d.startswith('.')]

                # 安全检查：确保只在工作目录内查找
                root_realpath = os.path.realpath(root)
                if not root_realpath.startswith(workspace_realpath):
                    logger.warning(f"Task {task_id}: 跳过工作目录外的路径: {root}")
                    continue

                for file in files:
                    # 只查找以 test_ 开头的 .py 文件（测试脚本）
                    # 排除 conftest.py, __init__.py 和项目代码文件（如 _*.py）
                    if (file.startswith('test_') and
                        file.endswith('.py') and
                        file not in ['conftest.py', '__init__.py']):
                        # 使用完整路径，避免不同目录下的同名文件冲突
                        full_path = os.path.join(root, file)
                        existing_scripts_before.add(full_path)

            logger.info(f"Task {task_id}: 生成前已有测试脚本数量: {len(existing_scripts_before)}")
            if existing_scripts_before:
                sample_scripts = list(existing_scripts_before)[:3]
                logger.info(f"Task {task_id}: 生成前已有测试脚本示例: {[os.path.basename(p) for p in sample_scripts]}")
        except Exception as e:
            logger.warning(f"Task {task_id}: 扫描已有测试脚本失败: {str(e)}")

        from app.services.cc_workflow import stream_test_script_response

        async for message in stream_test_script_response(test_point=test_point, workspace=workspace):
            message_type = type(message).__name__

            # 提取消息内容
            message_content = ""
            if hasattr(message, 'content'):
                message_content = message.content
            elif hasattr(message, 'text'):
                message_content = message.text
            elif hasattr(message, 'model_response'):
                message_content = str(message.model_response)
            else:
                message_content = str(message)

            # 判断是否是错误消息
            is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False

            # 判断是否是结果消息
            is_result = "Result" in message_type or "result" in message_type.lower()

            # 发送消息
            msg_status = "end" if (is_result or is_error) else "processing"
            send_message(message_type, message_content, msg_status, "测试脚本生成")

            if is_error:
                update_task_status("failed", "测试脚本生成")
                send_message("error", "测试脚本生成失败，终止流程", "end", "测试脚本生成")
                return

        logger.info(f"Task {task_id}: 测试脚本生成完成")
        send_message("info", "✓ 测试脚本生成完成", "processing", "测试脚本生成")

        # 拷贝生成的测试脚本到指定目录（只拷贝本次AI生成的文件）
        try:
            import getpass

            username = getpass.getuser()
            target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"
            os.makedirs(target_dir, exist_ok=True)

            # 需要过滤的目录（虚拟环境、缓存、版本控制等）
            filtered_dirs = {
                'ke',           # KE 目录
                'venv',         # 虚拟环境
                '.venv',        # 虚拟环境
                'env',          # 虚拟环境
                '.env',         # 虚拟环境
                '__pycache__',  # Python 缓存
                '.git',         # Git 版本控制
                '.svn',         # SVN 版本控制
                'node_modules', # Node.js 模块
                '.pytest_cache',# pytest 缓存
                'dist',         # 构建目录
                'build',        # 构建目录
                '.tox',         # tox 测试环境
                '.eggs',        # eggs 目录
                '*.egg-info',   # egg-info 目录
            }

            # 生成后：扫描工作目录，找出新增的测试脚本文件
            new_scripts = []
            all_scripts_after = set()

            for root, dirs, files in os.walk(workspace):
                # 过滤掉不需要的目录（大小写不敏感）
                dirs[:] = [d for d in dirs if d.lower() not in filtered_dirs and not d.startswith('.')]

                # 安全检查：确保只在工作目录内查找
                root_realpath = os.path.realpath(root)
                if not root_realpath.startswith(workspace_realpath):
                    logger.warning(f"Task {task_id}: 跳过工作目录外的路径: {root}")
                    continue

                for file in files:
                    # 只查找以 test_ 开头的 .py 文件（测试脚本）
                    # 排除 conftest.py, __init__.py 和项目代码文件（如 _*.py）
                    if (file.startswith('test_') and
                        file.endswith('.py') and
                        file not in ['conftest.py', '__init__.py']):
                        # 使用完整路径
                        full_path = os.path.join(root, file)
                        all_scripts_after.add(full_path)
                        # 如果这个文件不在生成前的列表中，说明是本次生成的
                        if full_path not in existing_scripts_before:
                            new_scripts.append(full_path)

            logger.info(f"Task {task_id}: 生成后所有测试脚本数量: {len(all_scripts_after)}")
            logger.info(f"Task {task_id}: 本次新增测试脚本数量: {len(new_scripts)}")
            logger.info(f"Task {task_id}: 本次新增测试脚本: {[os.path.basename(f) for f in new_scripts]}")

            if new_scripts:
                # 只拷贝本次生成的测试脚本文件
                copied_count = 0
                for script_file in new_scripts:
                    filename = os.path.basename(script_file)
                    target_script = os.path.join(target_dir, filename)

                    # 拷贝文件（覆盖已存在的文件）
                    shutil.copy2(script_file, target_script)

                    # 设置文件和目录权限为 777（其他用户可读可写）
                    try:
                        os.chmod(target_script, 0o777)
                        os.chmod(target_dir, 0o777)
                    except PermissionError:
                        logger.warning(f"Task {task_id}: 权限不足，无法设置文件权限 {target_script}，但文件已成功拷贝")

                    copied_count += 1
                    logger.info(f"Task {task_id}: {filename} 已拷贝到 {target_script}")

                send_message("info", f"✓ 已备份 {copied_count} 个新生成的测试脚本到: {target_dir}", "processing", "测试脚本生成")
            else:
                logger.warning(f"Task {task_id}: 未检测到新生成的测试脚本文件")
                send_message("warning", f"⚠ 未检测到新生成的测试脚本，跳过备份", "processing", "测试脚本生成")

        except Exception as e:
            logger.error(f"Task {task_id}: 拷贝测试脚本失败: {str(e)}")
            send_message("warning", f"⚠ 备份测试脚本失败: {str(e)}，继续执行后续流程", "processing", "测试脚本生成")

        # ========== 阶段3: 调用 ITC run 接口执行脚本 ==========
        logger.info(f"Task {task_id}: 开始调用 ITC run 接口")
        update_task_status("running", "ITC脚本执行")
        send_message("info", "\n===== 阶段3: 执行测试脚本 =====", "processing", "ITC脚本执行")

        # 获取 executorip
        from app.core.config import settings
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            send_message("error", "未找到部署的执行机IP，请先调用 /deploy 接口部署环境", "end", "ITC脚本执行")
            update_task_status("failed", "ITC脚本执行")
            return

        send_message("info", f"使用执行机: {executorip}", "processing", "ITC脚本执行")

        # 构造脚本路径（根据实际情况调整）
        import getpass
        username = getpass.getuser()
        scriptspath = f"//10.144.41.149/webide/aigc_tool/{username}"

        send_message("info", f"脚本路径: {scriptspath}", "processing", "ITC脚本执行")
        send_message("info", "正在调用 ITC run 接口...", "processing", "ITC脚本执行")

        # 调用 ITC run 接口
        from app.services.itc.itc_service import itc_service
        from app.models.itc.itc_models import RunScriptRequest

        itc_request = RunScriptRequest(
            scriptspath=scriptspath,
            executorip=executorip
        )

        # 执行 ITC run（带异常保护）
        try:
            result = await itc_service.run_script(itc_request)
        except Exception as e:
            # ITC Service 不应该抛出异常，但以防万一
            logger.error(f"Task {task_id}: ITC run 调用异常: {str(e)}")
            result = {
                "return_code": "500",
                "return_info": f"ITC run 调用异常: {str(e)}",
                "result": None
            }

        # 记录返回结果（带异常保护）
        try:
            logger.info(f"Task {task_id}: ITC run 接口返回: {result}")
        except Exception as e:
            logger.error(f"Task {task_id}: 记录 ITC 返回结果失败: {str(e)}")

        # 发送结果消息（带异常保护）
        try:
            result_message = return_code_to_message(result)
            send_message("info", f"\nITC run 接口返回结果:\n{result_message}", "end", "ITC脚本执行")
        except Exception as e:
            logger.error(f"Task {task_id}: 发送 ITC 结果消息失败: {str(e)}")
            send_message("warning", "ITC run 执行完成，但结果解析失败", "end", "ITC脚本执行")

        # 更新任务状态为完成
        update_task_status("completed", "ITC脚本执行")
        send_message("info", "\n===== 自动化测试流程完成 =====", "end", "完成")

    except Exception as e:
        import traceback
        error_msg = f"自动化测试流程执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")

        update_task_status("failed")
        send_message("error", error_msg, "end", "错误")


def return_code_to_message(result: dict) -> str:
    """将ITC返回结果转换为可读消息"""
    import logging
    logger = logging.getLogger(__name__)

    try:
        # 验证 result 是字典类型
        if not isinstance(result, dict):
            logger.warning(f"ITC 返回结果格式异常: {type(result)}, 期望 dict")
            return f"✗ 返回结果格式错误: {result}"

        return_code = result.get("return_code", "unknown")
        return_info = result.get("return_info", {})

        if return_code == "200":
            return f"✓ 执行成功\n返回信息: {return_info}"
        else:
            return f"✗ 执行失败 (错误码: {return_code})\n错误信息: {return_info}"
    except Exception as e:
        logger.error(f"解析 ITC 返回结果失败: {str(e)}, result={result}")
        return f"✗ 解析返回结果失败: {str(e)}"


@router.websocket("/prompt/{task_id}")
async def websocket_prompt_endpoint(websocket: WebSocket, task_id: str):
    """prompt流程专用的WebSocket端点"""
    import logging
    logger = logging.getLogger(__name__)

    await websocket.accept()
    logger.info(f"WebSocket连接已建立: task_id={task_id}, endpoint=/prompt/{task_id}")

    try:
        # 发送连接确认
        await websocket.send_text(json.dumps({
            "status": "connected",
            "task_id": task_id,
            "message": "WebSocket连接已建立",
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False))

        # 如果任务已存在，发送已缓存的消息
        if task_id in conftest_tasks and "messages" in conftest_tasks[task_id]:
            cached_messages = conftest_tasks[task_id]["messages"]
            logger.info(f"发送 {len(cached_messages)} 条缓存消息")
            for msg in cached_messages:
                await websocket.send_text(json.dumps(msg, ensure_ascii=False))
        else:
            logger.info(f"任务 {task_id} 尚未开始或没有消息")

        # 保持连接，持续发送新消息
        last_sent_count = len(conftest_tasks.get(task_id, {}).get("messages", []))

        while True:
            try:
                # 检查是否有新消息
                if task_id in conftest_tasks:
                    messages = conftest_tasks[task_id].get("messages", [])
                    if len(messages) > last_sent_count:
                        # 发送新消息
                        new_messages = messages[last_sent_count:]
                        logger.info(f"发送 {len(new_messages)} 条新消息")
                        for msg in new_messages:
                            await websocket.send_text(json.dumps(msg, ensure_ascii=False))

                            # 如果是结束状态，关闭连接
                            if msg.get("status") == "end":
                                logger.info(f"收到结束状态消息，关闭连接")
                                await websocket.close()
                                return

                        last_sent_count = len(messages)

                    # 如果任务已完成且没有新消息，关闭连接
                    task_status = conftest_tasks[task_id].get("status")
                    if task_status in ["completed", "failed"] and len(messages) == last_sent_count:
                        logger.info(f"任务状态={task_status}，没有新消息，关闭连接")
                        await asyncio.sleep(0.5)  # 等待最后消息发送
                        await websocket.close()
                        return

                # 处理心跳（带超时）
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    message = json.loads(data)

                    if message.get("type") == "ping":
                        await websocket.send_text(json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }, ensure_ascii=False))
                except asyncio.TimeoutError:
                    # 超时继续循环，检查新消息
                    continue

            except WebSocketDisconnect:
                logger.info(f"WebSocket断开连接: task_id={task_id}")
                break
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"WebSocket错误: {str(e)}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket连接断开: task_id={task_id}")
    except Exception as e:
        logger.error(f"WebSocket端点异常: {str(e)}")
    finally:
        logger.info(f"WebSocket连接清理: task_id={task_id}")
        pass


async def execute_script_write_back(task_id: str, script_full_path: str, script_filename: str, device_commands: str):
    """
    后台执行脚本生成和回写任务

    Args:
        task_id: 任务ID
        script_full_path: 脚本文件的绝对路径
        script_filename: 脚本文件名
        device_commands: 用户输入的新命令内容
    """
    import logging
    import tempfile
    import sys
    from pathlib import Path

    logger = logging.getLogger(__name__)

    def send_message(message_type: str, data: str, status: str = "processing"):
        """发送消息到WebSocket消息队列"""
        ws_message = {
            "status": status,
            "type": message_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        if task_id in conftest_tasks:
            conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
            logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

    def update_task_status(status: str):
        """更新任务状态"""
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = status

    try:
        # 更新任务状态为运行中
        update_task_status("running")
        send_message("info", "开始执行脚本生成和回写任务", "processing")

        # ========== 第1步：从 filename_command_mapping 获取旧命令 ==========
        logger.info(f"Task {task_id}: 从 filename_command_mapping 获取旧命令")
        send_message("info", "===== 第1步：获取旧命令 =====", "processing")

        from app.services.script_command_extract import filename_command_mapping

        # 尝试从 filename_command_mapping 获取旧命令
        old_command = None
        if script_filename in filename_command_mapping:
            old_command = filename_command_mapping[script_filename]
            send_message("info", f"✓ 找到旧命令（长度: {len(old_command)} 字符）", "processing")
        else:
            # 尝试模糊匹配
            for key, value in filename_command_mapping.items():
                if script_filename in key or key in script_filename:
                    old_command = value
                    send_message("info", f"✓ 通过模糊匹配找到旧命令（key: {key}）", "processing")
                    break

        if not old_command:
            send_message("warning", "⚠ 未找到旧命令，将使用空命令", "processing")
            old_command = ""

        # ========== 第2步：创建临时文件 ==========
        logger.info(f"Task {task_id}: 创建临时文件")
        send_message("info", "===== 第2步：创建临时文件 =====", "processing")

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="script_write_back_")
        logger.info(f"Task {task_id}: 临时目录: {temp_dir}")

        # 保存旧命令到临时文件
        old_command_file = os.path.join(temp_dir, "old_command.md")
        with open(old_command_file, 'w', encoding='utf-8') as f:
            f.write(old_command)
        send_message("info", f"✓ 旧命令已保存到临时文件", "processing")

        # 保存新命令到临时文件
        new_command_file = os.path.join(temp_dir, "new_command.md")
        with open(new_command_file, 'w', encoding='utf-8') as f:
            f.write(device_commands)
        send_message("info", f"✓ 新命令已保存到临时文件", "processing")

        # ========== 第3步：调用 command_write_back.py 的 main 函数 ==========
        logger.info(f"Task {task_id}: 调用 command_write_back.py")
        send_message("info", "===== 第3步：执行脚本回写 =====", "processing")

        # 导入 command_write_back 模块
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../services/claude/process_script_write_back"))
        import command_write_back

        # 保存旧的 sys.argv
        old_argv = sys.argv

        try:
            # 设置新的 sys.argv（模拟命令行参数）
            sys.argv = [
                "command_write_back.py",
                script_full_path,  # 参数1：脚本文件路径
                old_command_file,  # 参数2：旧命令文件
                new_command_file   # 参数3：新命令文件
            ]

            logger.info(f"Task {task_id}: 调用参数: {sys.argv}")

            # 调用 main 函数
            send_message("info", "正在执行脚本回写，请稍候...", "processing")

            # 由于 command_write_back.main() 是同步函数，我们在线程池中运行它
            import concurrent.futures
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, command_write_back.main)

            send_message("info", "✓ 脚本回写完成", "processing")

        finally:
            # 恢复旧的 sys.argv
            sys.argv = old_argv

        # ========== 第4步：清理临时文件 ==========
        logger.info(f"Task {task_id}: 清理临时文件")
        send_message("info", "===== 第4步：清理临时文件 =====", "processing")

       

        # ========== 第5步：拷贝修改后的脚本到目标目录 ==========
        logger.info(f"Task {task_id}: 拷贝修改后的脚本到目标目录")
        send_message("info", "===== 第5步：拷贝修改后的脚本到目标目录 =====", "processing")

        import getpass
        import glob
        from pathlib import Path

        username = getpass.getuser()
        target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"

        # 创建目标目录
        os.makedirs(target_dir, exist_ok=True)
        logger.info(f"Task {task_id}: 目标目录: {target_dir}")

        # 拷贝修改后的脚本文件
        script_name = os.path.basename(script_full_path)
        target_script_path = os.path.join(target_dir, script_name)

        try:
            shutil.copy2(script_full_path, target_script_path)

            # 设置文件权限
            try:
                os.chmod(target_script_path, 0o777)
                os.chmod(target_dir, 0o777)
            except PermissionError:
                logger.warning(f"Task {task_id}: 权限不足，无法设置文件权限，但文件已成功拷贝")

            send_message("info", f"✓ 修改后的脚本已拷贝到: {target_script_path}", "processing")
            logger.info(f"Task {task_id}: 脚本已拷贝到 {target_script_path}")
        except Exception as e:
            logger.error(f"Task {task_id}: 拷贝脚本失败: {str(e)}")
            send_message("warning", f"⚠ 拷贝脚本失败: {str(e)}", "processing")

        # ========== 脚本回写完成 ==========
        update_task_status("completed")
        send_message("success", "===== 脚本回写任务完成 =====", "end")
        logger.info(f"Task {task_id}: 脚本回写完成")

    except Exception as e:
        import traceback
        error_msg = f"脚本回写任务执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")

        update_task_status("failed")
        send_message("error", error_msg, "end")


async def execute_copy_and_itc_run(task_id: str, script_full_path: str):
    """
    后台执行脚本拷贝和 ITC run 任务

    Args:
        task_id: 任务ID
        script_full_path: 脚本文件的绝对路径
    """
    import logging
    import getpass
    import glob
    from pathlib import Path

    logger = logging.getLogger(__name__)

    def send_message(message_type: str, data: str, status: str = "processing"):
        """发送消息到WebSocket消息队列"""
        ws_message = {
            "status": status,
            "type": message_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        if task_id in conftest_tasks:
            conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
            logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

    def update_task_status(status: str):
        """更新任务状态"""
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = status

    try:
        # ========== 第5步：拷贝脚本到指定目录 ==========
        logger.info(f"Task {task_id}: 拷贝脚本到指定目录")
        send_message("info", "===== 第5步：拷贝脚本到指定目录 =====", "processing")

        username = getpass.getuser()
        target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"

        # 创建目标目录
        os.makedirs(target_dir, exist_ok=True)
        send_message("info", f"✓ 目标目录已创建: {target_dir}", "processing")

        # 删除目录中的旧 .py 文件（除了 aigc_tool.py）
        py_files = glob.glob(os.path.join(target_dir, "*.py"))
        deleted_count = 0
        for py_file in py_files:
            try:
                if "aigc_tool" in os.path.basename(py_file):
                    continue
                os.remove(py_file)
                deleted_count += 1
                logger.info(f"Task {task_id}: 已删除旧文件: {py_file}")
            except Exception as e:
                logger.warning(f"Task {task_id}: 删除文件 {py_file} 失败: {str(e)}")

        if deleted_count > 0:
            send_message("info", f"✓ 已删除 {deleted_count} 个旧脚本文件", "processing")

        # 拷贝脚本文件
        script_name = os.path.basename(script_full_path)
        target_script_path = os.path.join(target_dir, script_name)
        shutil.copy2(script_full_path, target_script_path)
        send_message("info", f"✓ 脚本已拷贝到: {target_script_path}", "processing")
        logger.info(f"Task {task_id}: 脚本已拷贝到 {target_script_path}")

        # 查找并拷贝项目工作区的 conftest.py
        from app.core.config import settings
        workspace = settings.get_work_directory()
        workspace_realpath = os.path.realpath(workspace)
        conftest_file = None

        # 需要过滤的目录
        filtered_dirs = {
            'ke', 'venv', '.venv', 'env', '.env', '__pycache__',
            '.git', '.svn', 'node_modules', '.pytest_cache',
            'dist', 'build', '.tox', '.eggs', '*.egg-info',
        }

        # 优先从项目工作区根目录查找 conftest.py（只查找顶层，不递归）
        for item in os.listdir(workspace):
            item_path = os.path.join(workspace, item)
            if os.path.isfile(item_path) and item.startswith('conftest') and item.endswith('.py'):
                # 确认不是过滤目录中的文件
                conftest_file = item_path
                break

        if not conftest_file:
            # 如果根目录没找到，再尝试递归查找（但过滤掉不需要的目录）
            pattern = os.path.join(workspace, "**", "conftest.py")
            matches = glob.glob(pattern, recursive=True)

            # 过滤掉虚拟环境等目录中的文件
            for match in matches:
                # 检查路径中是否包含过滤的目录名
                path_parts = Path(match).parts
                if not any(part.lower() in filtered_dirs for part in path_parts):
                    conftest_file = match
                    break

        if conftest_file:
            send_message("info", f"✓ 找到工作区 conftest.py: {os.path.basename(conftest_file)}", "processing")
            logger.info(f"Task {task_id}: 从工作区找到 conftest.py: {conftest_file}")
        else:
            # 工作区未找到，尝试在脚本所在目录查找
            base_dir = os.path.dirname(os.path.abspath(script_full_path))
            pattern = os.path.join(base_dir, "*conftest*.py")
            matches = glob.glob(pattern)

            if matches:
                # 安全检查：确保 conftest.py 在工作目录内
                match_realpath = os.path.realpath(matches[0])
                if match_realpath.startswith(workspace_realpath):
                    conftest_file = matches[0]
                    send_message("info", f"✓ 找到 conftest.py（脚本所在目录）", "processing")
                    logger.info(f"Task {task_id}: 从脚本目录找到 conftest.py: {conftest_file}")
                else:
                    logger.warning(f"Task {task_id}: conftest.py 不在工作目录内，跳过: {matches[0]}")
            else:
                send_message("warning", "⚠ 未找到 conftest.py 文件", "processing")

        if conftest_file:
            target_conftest_path = os.path.join(target_dir, "conftest.py")
            shutil.copy2(conftest_file, target_conftest_path)
            send_message("info", f"✓ conftest.py 已拷贝", "processing")
            logger.info(f"Task {task_id}: conftest.py 已拷贝到 {target_conftest_path}")

        # 创建 __init__.py（如果不存在）
        init_file = os.path.join(target_dir, "__init__.py")
        if not os.path.exists(init_file):
            open(init_file, 'a').close()
            send_message("info", f"✓ __init__.py 已创建", "processing")

        # 设置目录权限为 777
        def set_permissions_recursive(path, mode):
            """递归设置目录及其所有内容的权限（遇到错误继续执行）"""
            errors = []
            for root, dirs, files in os.walk(path):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        os.chmod(dir_path, mode)
                    except Exception as e:
                        errors.append(f"目录 {dir_path}: {str(e)}")
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    try:
                        os.chmod(file_path, mode)
                    except Exception as e:
                        errors.append(f"文件 {file_path}: {str(e)}")
            try:
                os.chmod(path, mode)
            except Exception as e:
                errors.append(f"根目录 {path}: {str(e)}")

            return errors

        # 执行权限设置，即使失败也不影响后续流程
        permission_errors = set_permissions_recursive(target_dir, 0o777)
        if permission_errors:
            send_message("warning", f"⚠ 部分文件权限设置失败（但不影响后续执行）:\n" + "\n".join(permission_errors[:5]), "processing")
            if len(permission_errors) > 5:
                send_message("warning", f"... 还有 {len(permission_errors) - 5} 个文件权限设置失败", "processing")
        else:
            send_message("info", f"✓ 目录权限已设置", "processing")

        # ========== 第6步：调用 ITC run 执行脚本 ==========
        logger.info(f"Task {task_id}: 调用 ITC run")
        send_message("info", "===== 第6步：调用 ITC run 执行脚本 =====", "processing")

        # 获取 executorip
        from app.core.config import settings
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            send_message("error", "未找到部署的执行机IP，请先调用 /deploy 接口部署环境", "end")
            update_task_status("failed")
            return

        send_message("info", f"✓ 执行机IP: {executorip}", "processing")

        # 构造 UNC 路径
        unc_path = "//10.144.41.149/webide/aigc_tool/{username}"
        send_message("info", f"✓ 脚本UNC路径: {unc_path}", "processing")

        # 调用 ITC 服务
        from app.services.itc.itc_service import itc_service
        from app.models.itc.itc_models import RunScriptRequest

        itc_request = RunScriptRequest(
            scriptspath=unc_path,
            executorip=executorip
        )

        send_message("info", "正在调用 ITC run 接口，请稍候...", "processing")
        logger.info(f"Task {task_id}: 调用 ITC run 接口: scriptspath={unc_path}, executorip={executorip}")

        # 执行 ITC run
        result = await itc_service.run_script(itc_request)

        logger.info(f"Task {task_id}: ITC run 接口返回: {result}")

        # 解析并返回结果
        return_code = result.get("return_code", "unknown")
        return_info = result.get("return_info", {})

        if return_code == "200":
            # 成功
            result_message = f"✓ ITC 执行成功\n\n返回信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"
            send_message("success", result_message, "end")
            update_task_status("completed")
        else:
            # 失败
            error_message = f"✗ ITC 执行失败 (错误码: {return_code})\n\n错误信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"
            send_message("error", error_message, "end")
            update_task_status("failed")

        logger.info(f"Task {task_id}: 任务完成")

    except Exception as e:
        import traceback
        error_msg = f"拷贝和执行脚本失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")
        update_task_status("failed")
        send_message("error", error_msg, "end")


async def execute_full_pipeline(task_id: str, script_full_path: str, script_filename: str, device_commands: str):
    """
    执行完整的自动化流程：脚本回写 -> 拷贝脚本 -> ITC run

    Args:
        task_id: 任务ID
        script_full_path: 脚本文件的绝对路径
        script_filename: 脚本文件名
        device_commands: 用户输入的新命令内容
    """
    import logging
    logger = logging.getLogger(__name__)

    def send_message(message_type: str, data: str, status: str = "processing"):
        """发送消息到WebSocket消息队列"""
        ws_message = {
            "status": status,
            "type": message_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

        if task_id in conftest_tasks:
            conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
            logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

    try:
        # 第1步：执行脚本回写
        logger.info(f"Task {task_id}: 开始执行脚本回写")
        await execute_script_write_back(task_id, script_full_path, script_filename, device_commands)

        # 等待一小段时间，确保最后的消息被发送
        await asyncio.sleep(0.5)

        # 重新激活任务状态（因为脚本回写完成后会设置为 completed/end）
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = "running"

        # 发送继续执行的消息
        send_message("info", "\n\n===== 开始执行后续流程 =====", "processing")

        # 第2步：拷贝脚本并执行 ITC run
        logger.info(f"Task {task_id}: 开始执行拷贝和ITC run")
        await execute_copy_and_itc_run(task_id, script_full_path)

    except Exception as e:
        import traceback
        logger.error(f"Task {task_id}: 完整流程执行失败: {str(e)}\n{traceback.format_exc()}")

        # 发送错误消息
        send_message("error", f"完整流程执行失败: {str(e)}", "end")


@router.websocket("/generate-script/{task_id}")
async def websocket_generate_script_endpoint(websocket: WebSocket, task_id: str):
    """generate-script任务专用的WebSocket端点"""
    import logging
    logger = logging.getLogger(__name__)

    await websocket.accept()
    logger.info(f"WebSocket连接已建立: task_id={task_id}, endpoint=/generate-script/{task_id}")

    try:
        # 发送连接确认
        await websocket.send_text(json.dumps({
            "status": "connected",
            "task_id": task_id,
            "message": "WebSocket连接已建立",
            "timestamp": datetime.now().isoformat()
        }, ensure_ascii=False))

        # 如果任务已存在，发送已缓存的消息
        if task_id in conftest_tasks and "messages" in conftest_tasks[task_id]:
            cached_messages = conftest_tasks[task_id]["messages"]
            logger.info(f"发送 {len(cached_messages)} 条缓存消息")
            for msg in cached_messages:
                await websocket.send_text(json.dumps(msg, ensure_ascii=False))
        else:
            logger.info(f"任务 {task_id} 尚未开始或没有消息")

        # 保持连接，持续发送新消息
        last_sent_count = len(conftest_tasks.get(task_id, {}).get("messages", []))

        while True:
            try:
                # 检查是否有新消息
                if task_id in conftest_tasks:
                    messages = conftest_tasks[task_id].get("messages", [])
                    if len(messages) > last_sent_count:
                        # 发送新消息
                        new_messages = messages[last_sent_count:]
                        logger.info(f"发送 {len(new_messages)} 条新消息")
                        for msg in new_messages:
                            await websocket.send_text(json.dumps(msg, ensure_ascii=False))

                            # 如果是结束状态，关闭连接
                            if msg.get("status") == "end":
                                logger.info(f"收到结束状态消息，关闭连接")
                                await websocket.close()
                                return

                        last_sent_count = len(messages)

                    # 如果任务已完成且没有新消息，关闭连接
                    task_status = conftest_tasks[task_id].get("status")
                    if task_status in ["completed", "failed"] and len(messages) == last_sent_count:
                        logger.info(f"任务状态={task_status}，没有新消息，关闭连接")
                        await asyncio.sleep(0.5)  # 等待最后消息发送
                        await websocket.close()
                        return

                # 处理心跳（带超时）
                try:
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                    message = json.loads(data)

                    if message.get("type") == "ping":
                        await websocket.send_text(json.dumps({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        }, ensure_ascii=False))
                except asyncio.TimeoutError:
                    # 超时继续循环，检查新消息
                    continue

            except WebSocketDisconnect:
                logger.info(f"WebSocket断开连接: task_id={task_id}")
                break
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"WebSocket错误: {str(e)}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket连接断开: task_id={task_id}")
    except Exception as e:
        logger.error(f"WebSocket端点异常: {str(e)}")
    finally:
        logger.info(f"WebSocket连接清理: task_id={task_id}")
        pass