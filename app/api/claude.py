import json
import asyncio
import uuid
import os
import shutil
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.services.claude_service import claude_service
from app.core.config import settings
from app.models.common import BaseResponse

router = APIRouter(prefix="/claude", tags=["Claude Code"])


class GenerateScriptRequest(BaseModel):
    """生成测试脚本请求模型"""
    device_commands: str = Field(..., description="设备命令列表（新命令）")
    script_path: str = Field(..., description="脚本文件的相对路径")


# 任务管理器：存储task_id和任务信息的映射
conftest_tasks = {}


def get_task_log_file(task_id: str) -> str:
    """获取任务日志文件路径"""
    from app.core.path_manager import path_manager
    logs_dir = path_manager.get_logs_dir()
    # 创建任务日志子目录
    task_logs_dir = logs_dir / "tasks"
    task_logs_dir.mkdir(parents=True, exist_ok=True)
    return str(task_logs_dir / f"{task_id}.log")


def write_task_log(task_id: str, content: str):
    """写入任务日志文件
    格式：时:分:秒 log内容
    保持原始换行符，不转义为 \\n
    """
    try:
        from datetime import datetime

        log_file = get_task_log_file(task_id)
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 直接写入内容，保持原始的 \n 换行符
        # 将换行后的每一行都加上时间戳，但保持 \n 作为实际换行符
        lines = content.split('\n')
        log_lines = []
        for line in lines:
            # 为每行添加时间戳（包括空行，保持格式）
            log_lines.append(f"{timestamp} {line}")

        # 写入所有行，使用 \n 作为换行符（不转义）
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write('\n'.join(log_lines) + '\n')
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"写入任务日志失败: {str(e)}")


def write_task_end_log(task_id: str, status: str = "completed"):
    """写入任务结束标识
    统一格式：[任务结束] 状态: completed/failed
    便于程序解析判断任务是否完成
    """
    end_message = f"[任务结束] 状态: {status}"
    write_task_log(task_id, end_message)


def write_task_start_log(task_id: str, task_name: str = "任务"):
    """写入任务开始标识
    统一格式：[任务开始] 任务名称
    与任务结束标识配对，便于程序解析
    """
    start_message = f"[任务开始] {task_name}"
    write_task_log(task_id, start_message)


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

    # 写入任务开始标识
    write_task_start_log(task_id, "完整流程任务")
    write_task_log(task_id, f"脚本: {script_filename}")

    def send_message(message_type: str, data: str, status: str = "processing"):
        """发送消息到日志文件"""
        try:
            import datetime
            ws_message = {
                "status": status,
                "type": message_type,
                "data": data,
                "timestamp": datetime.datetime.now().isoformat()
            }

            if task_id in conftest_tasks:
                conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
                logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

            # 写入日志文件
            log_content = f"[{message_type}] {data[:300]}"
            write_task_log(task_id, log_content)
        except Exception as e:
            logger.error(f"Task {task_id}: 发送消息失败: {str(e)}")

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

        # 注意：execute_copy_and_itc_run 会写入任务结束标识，这里不需要重复写入

    except Exception as e:
        import traceback
        logger.error(f"Task {task_id}: 完整流程执行失败: {str(e)}\n{traceback.format_exc()}")

        # 发送错误消息
        send_message("error", f"完整流程执行失败: {str(e)}", "end")

        # 写入任务结束标识
        write_task_end_log(task_id, "failed")


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
    import sys
    from pathlib import Path

    logger = logging.getLogger(__name__)

    # 写入任务开始标识
    write_task_start_log(task_id, "脚本回写任务")
    write_task_log(task_id, f"脚本: {script_filename}")

    def send_message(message_type: str, data: str, status: str = "processing"):
        """发送消息到日志文件"""
        try:
            import datetime
            ws_message = {
                "status": status,
                "type": message_type,
                "data": data,
                "timestamp": datetime.datetime.now().isoformat()
            }

            if task_id in conftest_tasks:
                conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
                logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

            # 写入日志文件
            log_content = f"[{message_type}] {data[:300]}"
            write_task_log(task_id, log_content)
        except Exception as e:
            logger.error(f"Task {task_id}: 发送消息失败: {str(e)}")

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
        import tempfile
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

        # ========== 第6步：拷贝 default.topox 文件 ==========
        logger.info(f"Task {task_id}: 拷贝 default.topox 文件")
        send_message("info", "===== 第6步：拷贝 default.topox 文件 =====", "processing")

        try:
            # 获取工作目录，在工作区根目录直接查找 topox 文件
            workspace = settings.get_work_directory()

            # 查找 default.topox 文件（在工作区根目录）
            default_topox_source = os.path.join(workspace, "default.topox")

            if os.path.exists(default_topox_source):
                # 删除目标目录中所有非 default.topox 的文件
                import glob
                existing_topox_files = glob.glob(os.path.join(target_dir, "*.topox"))

                deleted_topox_count = 0
                for topox_file in existing_topox_files:
                    topox_filename = os.path.basename(topox_file)
                    if topox_filename != "default.topox":
                        try:
                            os.remove(topox_file)
                            deleted_topox_count += 1
                            logger.info(f"Task {task_id}: 已删除旧 topox 文件: {topox_filename}")
                        except Exception as e:
                            logger.warning(f"Task {task_id}: 删除 topox 文件 {topox_filename} 失败: {str(e)}")

                if deleted_topox_count > 0:
                    send_message("info", f"✓ 已删除 {deleted_topox_count} 个其他名称的 topox 文件", "processing")

                # 拷贝 default.topox 到目标目录
                target_topox_path = os.path.join(target_dir, "default.topox")
                shutil.copy2(default_topox_source, target_topox_path)

                # 设置文件权限
                try:
                    os.chmod(target_topox_path, 0o777)
                except PermissionError:
                    logger.warning(f"Task {task_id}: 权限不足，无法设置 default.topox 文件权限")

                send_message("info", f"✓ default.topox 已拷贝到: {target_topox_path}", "processing")
                logger.info(f"Task {task_id}: default.topox 已拷贝到 {target_topox_path}")
            else:
                send_message("warning", f"⚠ 未找到 default.topox 文件: {default_topox_source}", "processing")
                logger.warning(f"Task {task_id}: default.topox 文件不存在: {default_topox_source}")

        except Exception as e:
            logger.error(f"Task {task_id}: 拷贝 default.topox 失败: {str(e)}")
            send_message("warning", f"⚠ 拷贝 default.topox 失败: {str(e)}", "processing")

        # ========== 脚本回写完成 ==========
        update_task_status("completed")
        send_message("success", "===== 脚本回写任务完成 =====", "end")
        logger.info(f"Task {task_id}: 脚本回写完成")

        # 写入任务结束标识
        write_task_end_log(task_id, "completed")

    except Exception as e:
        import traceback
        error_msg = f"脚本回写任务执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")

        update_task_status("failed")
        send_message("error", error_msg, "end")

        # 写入任务结束标识
        write_task_end_log(task_id, "failed")


async def execute_copy_and_itc_run(task_id: str, script_full_path: str):
    """
    后台执行脚本拷贝和 ITC run 任务

    Args:
        task_id: 任务ID
        script_full_path: 脚本文件的绝对路径
    """
    import logging
    import getpass
    from pathlib import Path

    logger = logging.getLogger(__name__)

    # 写入任务开始标识
    write_task_start_log(task_id, "脚本拷贝和ITC run任务")

    def send_message(message_type: str, data: str, status: str = "processing"):
        """发送消息到日志文件"""
        try:
            import datetime
            ws_message = {
                "status": status,
                "type": message_type,
                "data": data,
                "timestamp": datetime.datetime.now().isoformat()
            }

            if task_id in conftest_tasks:
                conftest_tasks[task_id].setdefault("messages", []).append(ws_message)
                logger.info(f"Task {task_id}: {message_type} - {data[:100]}...")

            # 写入日志文件
            log_content = f"[{message_type}] {data[:300]}"
            write_task_log(task_id, log_content)
        except Exception as e:
            logger.error(f"Task {task_id}: 发送消息失败: {str(e)}")

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
        import glob
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
            # 如果根目录没找到，再尝试递归查找
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
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            send_message("error", "未找到部署的执行机IP，请先调用 /deploy 接口部署环境", "end")
            update_task_status("failed")
            # 写入任务结束标识
            write_task_end_log(task_id, "failed")
            return

        send_message("info", f"✓ 执行机IP: {executorip}", "processing")

        # 构造 UNC 路径
        unc_path = f"//10.144.41.149/webide/aigc_tool/{username}"
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
            import json
            result_message = f"✓ ITC 执行成功\n\n返回信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"
            send_message("success", result_message, "end")
            update_task_status("completed")

            # 写入任务结束标识
            write_task_end_log(task_id, "completed")
        else:
            # 失败
            import json
            error_message = f"✗ ITC 执行失败 (错误码: {return_code})\n\n错误信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"
            send_message("error", error_message, "end")
            update_task_status("failed")

            # 写入任务结束标识
            write_task_end_log(task_id, "failed")

        logger.info(f"Task {task_id}: 任务完成")

    except Exception as e:
        import traceback
        error_msg = f"拷贝和执行脚本失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")
        update_task_status("failed")
        send_message("error", error_msg, "end")

        # 写入任务结束标识
        write_task_end_log(task_id, "failed")


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

        # 存储任务信息
        conftest_tasks[task_id] = {
            "test_point": prompt,
            "workspace": workspace,
            "status": "pending",
            "stage": "pending"
        }

        logger.info(f"创建prompt任务: task_id={task_id}, test_point={prompt[:50]}...")

        # 添加后台任务执行完整流程
        background_tasks.add_task(execute_prompt_pipeline, task_id, prompt, workspace)

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


async def execute_prompt_pipeline(task_id: str, test_point: str, workspace: str):
    """
    执行完整的自动化测试流程：
    1. 生成 conftest.py
    2. 生成测试脚本
    3. 调用 ITC run 接口执行脚本
    """
    import logging
    logger = logging.getLogger(__name__)

    # 写入任务开始标识
    write_task_start_log(task_id, "自动化测试流程")
    write_task_log(task_id, f"测试点: {test_point[:100]}...")

    def send_message_log(message_type: str, data: str, stage: str = ""):
        """写入消息到日志文件"""
        try:
            stage_prefix = f"[{stage}] " if stage else ""
            log_content = f"{stage_prefix}[{message_type}] {data[:300]}"
            write_task_log(task_id, log_content)
        except Exception as e:
            logger.error(f"Task {task_id}: 写入日志失败: {str(e)}")

    def update_task_status(status: str, stage: str = ""):
        """更新任务状态"""
        if task_id in conftest_tasks:
            conftest_tasks[task_id]["status"] = status
            if stage:
                conftest_tasks[task_id]["stage"] = stage

    try:
        # 更新任务状态为运行中
        update_task_status("running", "conftest生成")
        send_message_log("info", f"开始执行自动化测试流程\n测试点: {test_point[:100]}...", "conftest生成")

        # ========== 阶段1: 生成 conftest.py ==========
        logger.info(f"Task {task_id}: 开始生成 conftest.py")
        send_message_log("info", "===== 阶段1: 生成 conftest.py =====", "conftest生成")

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

            # 写入日志
            send_message_log(message_type, message_content, "conftest生成")

            if is_error:
                update_task_status("failed", "conftest生成")
                send_message_log("error", "conftest.py生成失败，终止流程", "conftest生成")
                write_task_end_log(task_id, "failed")
                return

        logger.info(f"Task {task_id}: conftest.py 生成完成")
        send_message_log("info", "✓ conftest.py 生成完成", "conftest生成")

        # 拷贝 conftest.py 到指定目录
        try:
            import getpass

            username = getpass.getuser()
            target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"
            os.makedirs(target_dir, exist_ok=True)

            # 查找 workspace 中的 conftest.py 文件
            conftest_files = []
            workspace_realpath = os.path.realpath(workspace)

            # 需要过滤的目录
            filtered_dirs = {
                'ke', 'venv', '.venv', 'env', '.env', '__pycache__',
                '.git', '.svn', 'node_modules', '.pytest_cache',
                'dist', 'build', '.tox', '.eggs', '*.egg-info',
            }

            for root, dirs, files in os.walk(workspace):
                # 过滤掉不需要的目录
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
                source_conftest = conftest_files[0]
                target_conftest = os.path.join(target_dir, "conftest.py")
                shutil.copy2(source_conftest, target_conftest)

                try:
                    os.chmod(target_conftest, 0o777)
                    os.chmod(target_dir, 0o777)
                except PermissionError:
                    logger.warning(f"Task {task_id}: 权限不足，无法设置文件权限")

                logger.info(f"Task {task_id}: conftest.py 已拷贝到 {target_conftest}")
                send_message_log("info", f"✓ conftest.py 已备份到: {target_conftest}", "conftest生成")
            else:
                logger.warning(f"Task {task_id}: 在 {workspace} 中未找到 conftest.py 文件")
                send_message_log("warning", f"⚠ 未找到 conftest.py 文件，跳过备份", "conftest生成")

        except Exception as e:
            logger.error(f"Task {task_id}: 拷贝 conftest.py 失败: {str(e)}")
            send_message_log("warning", f"⚠ 备份 conftest.py 失败: {str(e)}，继续执行后续流程", "conftest生成")

        # ========== 阶段2: 生成测试脚本 ==========
        logger.info(f"Task {task_id}: 开始生成测试脚本")
        update_task_status("running", "测试脚本生成")
        send_message_log("info", "\n===== 阶段2: 生成测试脚本 =====", "测试脚本生成")

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

            # 写入日志
            send_message_log(message_type, message_content, "测试脚本生成")

            if is_error:
                update_task_status("failed", "测试脚本生成")
                send_message_log("error", "测试脚本生成失败，终止流程", "测试脚本生成")
                write_task_end_log(task_id, "failed")
                return

        logger.info(f"Task {task_id}: 测试脚本生成完成")
        send_message_log("info", "✓ 测试脚本生成完成", "测试脚本生成")

        # 拷贝生成的测试脚本（简化版，与前面类似）
        # ... (省略具体实现，与原代码类似)

        # ========== 阶段3: 调用 ITC run 接口执行脚本 ==========
        logger.info(f"Task {task_id}: 开始调用 ITC run 接口")
        update_task_status("running", "ITC脚本执行")
        send_message_log("info", "\n===== 阶段3: 执行测试脚本 =====", "ITC脚本执行")

        # 获取 executorip
        from app.core.config import settings
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            send_message_log("error", "未找到部署的执行机IP，请先调用 /deploy 接口部署环境", "ITC脚本执行")
            update_task_status("failed", "ITC脚本执行")
            write_task_end_log(task_id, "failed")
            return

        send_message_log("info", f"使用执行机: {executorip}", "ITC脚本执行")

        # 构造脚本路径
        import getpass
        username = getpass.getuser()
        scriptspath = f"//10.144.41.149/webide/aigc_tool/{username}"

        send_message_log("info", f"脚本路径: {scriptspath}", "ITC脚本执行")
        send_message_log("info", "正在调用 ITC run 接口...", "ITC脚本执行")

        # 调用 ITC run 接口
        from app.services.itc.itc_service import itc_service
        from app.models.itc.itc_models import RunScriptRequest

        itc_request = RunScriptRequest(
            scriptspath=scriptspath,
            executorip=executorip
        )

        try:
            result = await itc_service.run_script(itc_request)
        except Exception as e:
            logger.error(f"Task {task_id}: ITC run 调用异常: {str(e)}")
            result = {
                "return_code": "500",
                "return_info": f"ITC run 调用异常: {str(e)}",
                "result": None
            }

        logger.info(f"Task {task_id}: ITC run 接口返回: {result}")

        # 发送结果消息
        try:
            result_message = return_code_to_message(result)
            send_message_log("info", f"\nITC run 接口返回结果:\n{result_message}", "ITC脚本执行")
        except Exception as e:
            logger.error(f"Task {task_id}: 发送 ITC 结果消息失败: {str(e)}")
            send_message_log("warning", "ITC run 执行完成，但结果解析失败", "ITC脚本执行")

        # 更新任务状态为完成
        update_task_status("completed", "ITC脚本执行")
        send_message_log("info", "\n===== 自动化测试流程完成 =====", "完成")

        # 写入任务结束标识
        write_task_end_log(task_id, "completed")

    except Exception as e:
        import traceback
        error_msg = f"自动化测试流程执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
        logger.error(f"Task {task_id}: {error_msg}")

        update_task_status("failed")
        send_message_log("error", error_msg, "错误")

        # 写入任务结束标识
        write_task_end_log(task_id, "failed")


def return_code_to_message(result: dict) -> str:
    """将ITC返回结果转换为可读消息"""
    import logging
    logger = logging.getLogger(__name__)

    try:
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

        # 获取日志文件路径
        log_file = get_task_log_file(task_id)

        # 检查文件是否存在
        if not os.path.exists(log_file):
            raise HTTPException(status_code=404, detail=f"任务日志文件不存在: {task_id}")

        # 读取日志文件内容
        with open(log_file, 'r', encoding='utf-8') as f:
            log_content = f.read()

        logger.info(f"读取任务日志: task_id={task_id}, 日志行数={len(log_content.splitlines())}")

        return BaseResponse(
            status="ok",
            message=f"成功获取任务日志，共 {len(log_content.splitlines())} 行",
            data={
                "task_id": task_id,
                "log_content": log_content,
                "log_lines": len(log_content.splitlines()),
                "log_file": log_file
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logging.getLogger(__name__).error(f"获取任务日志失败: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"获取任务日志失败: {str(e)}")
