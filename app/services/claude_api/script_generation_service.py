"""
脚本生成服务

提供脚本生成、回写、拷贝和ITC执行的完整业务逻辑
"""
import asyncio
import concurrent.futures
import getpass
import glob
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from app.core.config import settings
from app.services.claude_api.task_manager import task_manager
from app.services.claude_api.task_logger import task_logger
from app.services.metrics_service_v2 import metrics_service_v2
from app.models.metrics_v2 import ScriptType
from app.utils import add_aifinger_hook


class ScriptGenerationService:
    """脚本生成服务"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    # ==================== 辅助方法 ====================

    def _send_message(self, task_id: str, message_type: str, data: str, status: str = "processing"):
        """发送消息到任务日志和任务管理器

        Args:
            task_id: 任务ID
            message_type: 消息类型 (info/warning/error/success)
            data: 消息数据
            status: 消息状态 (processing/end)
        """
        try:
            # 添加到任务管理器
            task_manager.add_message(task_id, message_type, data, status)

            # 写入日志文件
            log_content = f"[{message_type}] {data[:300]}"
            task_logger.write_log(task_id, log_content)
        except Exception as e:
            self.logger.error(f"Task {task_id}: 发送消息失败: {str(e)}")

    def _update_task_status(self, task_id: str, status: str, stage: str = ""):
        """更新任务状态

        Args:
            task_id: 任务ID
            status: 新状态
            stage: 当前阶段
        """
        task_manager.update_status(task_id, status, stage)

    def _return_code_to_message(self, result: dict) -> str:
        """将ITC返回结果转换为可读消息

        Args:
            result: ITC返回结果字典

        Returns:
            格式化的消息字符串
        """
        try:
            if not isinstance(result, dict):
                self.logger.warning(f"ITC 返回结果格式异常: {type(result)}, 期望 dict")
                return f"✗ 返回结果格式错误: {result}"

            return_code = result.get("return_code", "unknown")
            return_info = result.get("return_info", {})

            if return_code == "200":
                return f"✓ 执行成功\n返回信息: {return_info}"
            else:
                return f"✗ 执行失败 (错误码: {return_code})\n错误信息: {return_info}"
        except Exception as e:
            self.logger.error(f"解析 ITC 返回结果失败: {str(e)}, result={result}", exc_info=True)
            return f"✗ 解析返回结果失败: {str(e)}"

    def _record_write_back_metrics(self, script_full_path: str, script_filename: str, duration: float) -> None:
        """记录脚本回写度量数据

        Args:
            script_full_path: 脚本完整路径
            script_filename: 脚本文件名
            duration: 回写耗时（秒）
        """
        try:
            success = metrics_service_v2.add_write_back_duration(
                duration=duration,
                script_path=script_full_path
            )
            if success:
                self.logger.info(f"度量 v2: 已设置活跃文件并记录回写耗时: {script_filename}, duration={duration}秒")
            else:
                self.logger.warning(f"度量 v2: 记录回写耗时失败: {script_filename}")
        except Exception as metrics_error:
            self.logger.warning(f"度量 v2: 记录回写耗时失败: {metrics_error}", exc_info=True)

    def _record_itc_run_metrics(
        self,
        script_path: str,
        duration: float,
        return_code: str,
        return_info: Optional[Dict[str, Any]] = None
    ) -> None:
        """记录 ITC run 度量数据

        Args:
            script_path: 脚本路径（None表示使用当前活跃脚本）
            duration: ITC run耗时（秒）
            return_code: ITC返回码
            return_info: ITC返回信息
        """
        try:
            from app.core.config import settings

            kwargs = {"duration": duration, "return_code": return_code}
            if script_path:
                kwargs["script_path"] = script_path
            else:
                # 当 script_path 为空时，尝试查找工作区中的 conftest.py 文件
                work_dir = settings.get_work_directory()
                conftest_source = os.path.join(work_dir, "conftest.py")
                if os.path.exists(conftest_source):
                    kwargs["script_path"] = conftest_source
                    self.logger.info(f"script_path 为空，将 ITC 运行时间记录到 conftest.py 对应的度量记录")
                else:
                    self.logger.info(f"script_path 为空且工作区中不存在 conftest.py，将记录到当前活跃脚本")

            success = metrics_service_v2.add_itc_run_duration(**kwargs)
            if success:
                script_name = os.path.basename(kwargs.get("script_path")) if kwargs.get("script_path") else "当前活跃脚本"
                self.logger.info(f"度量 v2: 记录 ITC run 耗时到脚本 {script_name}, duration={duration}秒")
        except Exception as metrics_error:
            self.logger.warning(f"度量 v2: 记录 ITC run 失败: {metrics_error}", exc_info=True)

    # ==================== 完整流程：脚本回写 + 拷贝 + ITC run ====================

    async def execute_full_pipeline(
        self,
        task_id: str,
        script_full_path: str,
        script_filename: str,
        device_commands: str
    ):
        """
        执行完整的自动化流程：脚本回写 -> 拷贝脚本 -> ITC run

        Args:
            task_id: 任务ID
            script_full_path: 脚本文件的绝对路径
            script_filename: 脚本文件名
            device_commands: 用户输入的新命令内容
        """
        # 写入任务开始标识
        task_logger.write_start_log(task_id, "完整流程任务")
        task_logger.write_log(task_id, f"脚本: {script_filename}")

        try:
            # 第1步：执行脚本回写
            self.logger.info(f"Task {task_id}: 开始执行脚本回写")
            await self._execute_script_write_back(
                task_id, script_full_path, script_filename, device_commands
            )

            # 等待一小段时间，确保最后的消息被发送
            await asyncio.sleep(0.5)

            # 重新激活任务状态（因为脚本回写完成后会设置为 completed/end）
            if task_manager.task_exists(task_id):
                self._update_task_status(task_id, "running")

            # 发送继续执行的消息
            self._send_message(task_id, "info", "\n\n===== 开始执行后续流程 =====", "processing")

            # 第2步：拷贝脚本并执行 ITC run
            self.logger.info(f"Task {task_id}: 开始执行拷贝和ITC run")
            await self._execute_copy_and_itc_run(task_id, script_full_path)

            # 注意：execute_copy_and_itc_run 会写入任务结束标识，这里不需要重复写入

        except Exception as e:
            self.logger.error(f"Task {task_id}: 完整流程执行失败: {str(e)}\n{traceback.format_exc()}")

            # 发送错误消息
            self._send_message(task_id, "error", f"完整流程执行失败: {str(e)}", "end")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "failed")

    # ==================== 脚本回写 ====================

    async def _execute_script_write_back(
        self,
        task_id: str,
        script_full_path: str,
        script_filename: str,
        device_commands: str
    ):
        """
        后台执行脚本生成和回写任务

        Args:
            task_id: 任务ID
            script_full_path: 脚本文件的绝对路径
            script_filename: 脚本文件名
            device_commands: 用户输入的新命令内容
        """
        # 写入脚本信息（不再单独写入任务开始标识，避免重复）
        task_logger.write_log(task_id, f"脚本: {script_filename}")

        # ========== 度量 v2：记录开始时间 ==========
        write_back_start_time = datetime.now()
        # ========================================

        try:
            # 更新任务状态为运行中
            self._update_task_status(task_id, "running")
            self._send_message(task_id, "info", "开始执行脚本生成和回写任务", "processing")

            # ========== 第1步：从 filename_command_mapping 获取旧命令 ==========
            self.logger.info(f"Task {task_id}: 从 filename_command_mapping 获取旧命令")
            self._send_message(task_id, "info", "===== 第1步：获取旧命令 =====", "processing")

            # 首先刷新全局变量，确保使用最新的日志数据
            from app.services.script_command_extract import refresh_static_variables, find_command_by_filename
            self.logger.info(f"Task {task_id}: 刷新 filename_command_mapping...")
            refresh_static_variables()
            self.logger.info(f"Task {task_id}: 刷新完成，开始查找旧命令...")

            # 使用新的查找函数（支持精确匹配、去除扩展名匹配、模糊匹配）
            old_command = find_command_by_filename(script_filename)

            if old_command:
                self._send_message(task_id, "info", f"✓ 找到旧命令（长度: {len(old_command)} 字符）", "processing")
                self.logger.info(f"Task {task_id}: 成功找到旧命令，长度: {len(old_command)} 字符")
            else:
                self._send_message(task_id, "warning", "⚠ 未找到旧命令，将使用空命令", "processing")
                self.logger.warning(f"Task {task_id}: 未找到匹配的旧命令: {script_filename}")

            # ========== 第2步：创建临时文件 ==========
            self.logger.info(f"Task {task_id}: 创建临时文件")
            self._send_message(task_id, "info", "===== 第2步：创建临时文件 =====", "processing")

            # 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix="script_write_back_")
            self.logger.info(f"Task {task_id}: 临时目录: {temp_dir}")

            # 保存旧命令到临时文件
            old_command_file = os.path.join(temp_dir, "old_command.md")
            with open(old_command_file, 'w', encoding='utf-8') as f:
                f.write(old_command if old_command else "")
            self._send_message(task_id, "info", f"✓ 旧命令已保存到临时文件", "processing")

            # 保存新命令到临时文件
            new_command_file = os.path.join(temp_dir, "new_command.md")
            with open(new_command_file, 'w', encoding='utf-8') as f:
                f.write(device_commands)
            self._send_message(task_id, "info", f"✓ 新命令已保存到临时文件", "processing")

            # ========== 第3步：调用 command_write_back.py 的 main 函数 ==========
            self.logger.info(f"Task {task_id}: 调用 command_write_back.py")
            self._send_message(task_id, "info", "===== 第3步：执行脚本回写 =====", "processing")

            # 导入 command_write_back 模块
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../claude/process_script_write_back"))
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

                self.logger.info(f"Task {task_id}: 调用参数: {sys.argv}")

                # 调用 main 函数
                self._send_message(task_id, "info", "正在执行脚本回写，请稍候...", "processing")

                # 由于 command_write_back.main() 是同步函数，我们在线程池中运行它
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, command_write_back.main)

                self._send_message(task_id, "info", "✓ 脚本回写完成", "processing")

            finally:
                # 恢复旧的 sys.argv
                sys.argv = old_argv

            # 添加AI指纹到回写后的脚本
            try:
                uuid = add_aifinger_hook.generate_unique_id()
                success, is_update = add_aifinger_hook.add_fingerprint_to_file(script_full_path, uuid)
                if success:
                    if is_update:
                        self.logger.info(f"Task {task_id}: 已更新回写脚本的AI指纹（原指纹不合法）: {uuid}")
                    else:
                        self.logger.info(f"Task {task_id}: 已为回写脚本添加AI指纹: {uuid}")
                else:
                    # success=False 说明文件已有合法指纹被跳过
                    self.logger.info(f"Task {task_id}: 回写脚本已存在合法的AI指纹，跳过添加")
            except Exception as fingerprint_err:
                self.logger.warning(f"Task {task_id}: 添加AI指纹失败: {str(fingerprint_err)}")

            # ========== 度量 v2：根据脚本名找到对应的文件并记录为活跃文件 ==========
            write_back_end_time = datetime.now()
            write_back_duration = (write_back_end_time - write_back_start_time).total_seconds()

            self._record_write_back_metrics(script_full_path, script_filename, write_back_duration)
            # ===================================================================

            # ========== 脚本回写完成 ==========
            self._update_task_status(task_id, "completed")
            self._send_message(task_id, "success", "===== 脚本回写任务完成 =====", "end")
            self.logger.info(f"Task {task_id}: 脚本回写完成")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "completed")

        except Exception as e:
            error_msg = f"脚本回写任务执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
            self.logger.error(f"Task {task_id}: {error_msg}")

            self._update_task_status(task_id, "failed")
            self._send_message(task_id, "error", error_msg, "end")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "failed")

    # ==================== 拷贝和 ITC run ====================

    async def _execute_copy_and_itc_run(self, task_id: str, script_full_path: str):
        """
        后台执行脚本拷贝和 ITC run 任务

        Args:
            task_id: 任务ID
            script_full_path: 脚本文件的绝对路径
        """
        try:
            # ========== 第5步：拷贝脚本到指定目录 ==========
            self.logger.info(f"Task {task_id}: 拷贝脚本到指定目录")
            self._send_message(task_id, "info", "===== 第5步：拷贝脚本到指定目录 =====", "processing")

            target_dir = settings.get_aigc_tool_local_dir()

            # 创建目标目录
            os.makedirs(target_dir, exist_ok=True)
            self._send_message(task_id, "info", f"✓ 目标目录已创建: {target_dir}", "processing")

            # ========== 删除目标目录下的 conftest.py 和 test_ 开头的 .py 文件 ==========
            deleted_files = []

            # 查找并删除所有 test_*.py 文件
            test_pattern = os.path.join(target_dir, "test_*.py")
            test_files = glob.glob(test_pattern)
            for file_path in test_files:
                try:
                    os.remove(file_path)
                    deleted_files.append(os.path.basename(file_path))
                    self.logger.info(f"Task {task_id}: 已删除目标目录中的测试文件: {os.path.basename(file_path)}")
                except Exception as e:
                    self.logger.warning(f"Task {task_id}: 删除文件 {file_path} 失败: {str(e)}")

            # 查找并删除 conftest.py
            conftest_pattern = os.path.join(target_dir, "conftest.py")
            if os.path.exists(conftest_pattern):
                try:
                    os.remove(conftest_pattern)
                    deleted_files.append("conftest.py")
                    self.logger.info(f"Task {task_id}: 已删除目标目录中的 conftest.py")
                except Exception as e:
                    self.logger.warning(f"Task {task_id}: 删除 conftest.py 失败: {str(e)}")

            if deleted_files:
                self._send_message(task_id, "info", f"✓ 已删除 {len(deleted_files)} 个旧文件: {', '.join(deleted_files)}", "processing")

            # 拷贝脚本文件
            script_name = os.path.basename(script_full_path)
            target_script_path = os.path.join(target_dir, script_name)
            shutil.copy2(script_full_path, target_script_path)
            self._send_message(task_id, "info", f"✓ 脚本已拷贝到: {target_script_path}", "processing")
            self.logger.info(f"Task {task_id}: 脚本已拷贝到 {target_script_path}")

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
                self._send_message(task_id, "info", f"✓ 找到工作区 conftest.py: {os.path.basename(conftest_file)}", "processing")
                self.logger.info(f"Task {task_id}: 从工作区找到 conftest.py: {conftest_file}")
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
                        self._send_message(task_id, "info", f"✓ 找到 conftest.py（脚本所在目录）", "processing")
                        self.logger.info(f"Task {task_id}: 从脚本目录找到 conftest.py: {conftest_file}")
                    else:
                        self.logger.warning(f"Task {task_id}: conftest.py 不在工作目录内，跳过: {matches[0]}")
                else:
                    self._send_message(task_id, "warning", "⚠ 未找到 conftest.py 文件", "processing")

            if conftest_file:
                target_conftest_path = os.path.join(target_dir, "conftest.py")
                shutil.copy2(conftest_file, target_conftest_path)
                self._send_message(task_id, "info", f"✓ conftest.py 已拷贝", "processing")
                self.logger.info(f"Task {task_id}: conftest.py 已拷贝到 {target_conftest_path}")

            # 创建 __init__.py（如果不存在）
            init_file = os.path.join(target_dir, "__init__.py")
            if not os.path.exists(init_file):
                open(init_file, 'a').close()
                self._send_message(task_id, "info", f"✓ __init__.py 已创建", "processing")

            # 设置目录权限为 777
            def set_permissions_recursive(path, mode):
                """递归设置目录及其所有内容的权限（遇到错误继续执行）"""
                errors = []
                for root, dirs, files in os.walk(path):
                    # 跳过 log 目录（共享目录下的日志文件夹）
                    if "log" in dirs:
                        dirs.remove("log")
                    for dir_name in dirs:
                        dir_path = os.path.join(root, dir_name)
                        try:
                            os.chmod(dir_path, mode)
                        except Exception as e:
                            errors.append(f"目录 {dir_path}: {str(e)}")
                    for file_name in files:
                        # 跳过 map_info.json 文件（共享目录下的配置文件）
                        if file_name == "map_info.json":
                            continue
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
                self._send_message(task_id, "warning", f"⚠ 部分文件权限设置失败（但不影响后续执行）:\n" + "\n".join(permission_errors[:5]), "processing")
                if len(permission_errors) > 5:
                    self._send_message(task_id, "warning", f"... 还有 {len(permission_errors) - 5} 个文件权限设置失败", "processing")
            else:
                self._send_message(task_id, "info", f"✓ 目录权限已设置", "processing")

            # ========== 第6步：调用 ITC run 执行脚本 ==========
            self.logger.info(f"Task {task_id}: 调用 ITC run")
            self._send_message(task_id, "info", "===== 第6步：调用 ITC run 执行脚本 =====", "processing")

            # 获取 executorip
            executorip = settings.get_deploy_executor_ip()

            if not executorip:
                self._send_message(task_id, "error", "未找到部署的执行机IP，请先部署组网占用环境", "end")
                self._update_task_status(task_id, "failed")
                # 写入任务结束标识
                task_logger.write_end_log(task_id, "failed")
                return

            self._send_message(task_id, "info", f"✓ 执行机IP: {executorip}", "processing")

            # 构造 UNC 路径
            unc_path = settings.get_aigc_tool_unc_dir()
            self._send_message(task_id, "info", f"✓ 脚本UNC路径: {unc_path}", "processing")

            # 调用 ITC 服务
            from app.services.itc.itc_service import itc_service
            from app.models.itc.itc_models import RunScriptRequest

            itc_request = RunScriptRequest(
                scriptspath=unc_path,
                executorip=executorip
            )

            self._send_message(task_id, "info", "正在调用 ITC run 接口，请稍候...", "processing")
            self.logger.info(f"Task {task_id}: 调用 ITC run 接口: scriptspath={unc_path}, executorip={executorip}")

            # ========== 度量 v2：记录ITC run开始时间 ==========
            itc_run_start_time = datetime.now()
            # ==============================================

            # 执行 ITC run
            result = await itc_service.run_script(itc_request)

            self.logger.info(f"Task {task_id}: ITC run 接口返回: {result}")

            # ========== 度量 v2：记录 ITC run 耗时到指定脚本 ==========
            itc_run_end_time = datetime.now()
            itc_run_duration = (itc_run_end_time - itc_run_start_time).total_seconds()
            self._record_itc_run_metrics(
                script_path=script_full_path,
                duration=itc_run_duration,
                return_code=result.get("return_code", "unknown"),
                return_info=result.get("return_info")
            )
            # ======================================================

            # 解析并返回结果
            return_code = result.get("return_code", "unknown")
            return_info = result.get("return_info", {})

            if return_code == "200":
                # 成功
                result_message = f"✓ ITC 执行成功\n\n返回信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"
                self._send_message(task_id, "success", result_message, "end")
                self._update_task_status(task_id, "completed")

                # 写入任务结束标识
                task_logger.write_end_log(task_id, "completed")
            else:
                # 失败
                error_message = f"✗ ITC 执行失败 (错误码: {return_code})\n\n错误信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"
                self._send_message(task_id, "error", error_message, "end")
                self._update_task_status(task_id, "failed")

                # 写入任务结束标识
                task_logger.write_end_log(task_id, "failed")

            self.logger.info(f"Task {task_id}: 任务完成")

        except Exception as e:
            error_msg = f"拷贝和执行脚本失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
            self.logger.error(f"Task {task_id}: {error_msg}")
            self._update_task_status(task_id, "failed")
            self._send_message(task_id, "error", error_msg, "end")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "failed")

    # ==================== Prompt 流程 ====================

    async def execute_prompt_pipeline(self, task_id: str, test_point: str, workspace: str):
        """
        执行完整的自动化测试流程：
        1. 生成 conftest.py
        2. 生成测试脚本
        3. 调用 ITC run 接口执行脚本
        4. 如果需要，修复脚本并再次执行

        Args:
            task_id: 任务ID
            test_point: 测试点描述
            workspace: 工作目录
        """
        # 记录函数入口时间
        pipeline_start_time = time.time()

        # 导入消息解析器
        from app.utils.claude_message_parser import ClaudeMessageParser
        parser = ClaudeMessageParser()

        # 写入任务开始标识
        task_logger.write_start_log(task_id, "自动化测试流程")
        task_logger.write_log(task_id, f"测试点: {test_point[:100]}...")

        def send_message_log(message_type: str, data: str, stage: str = ""):
            """写入消息到日志文件（保留用于非消息类型的日志）"""
            try:
                stage_prefix = f"[{stage}] " if stage else ""
                log_content = f"{stage_prefix}[{message_type}] {data[:300]}"
                task_logger.write_log(task_id, log_content)
            except Exception as e:
                self.logger.error(f"Task {task_id}: 写入日志失败: {str(e)}")

        try:
            # 更新任务状态为运行中
            self._update_task_status(task_id, "running", "conftest生成")
            send_message_log("info", f"开始执行自动化测试流程\n测试点: {test_point[:100]}...", "conftest生成")

            # 初始化 conftest.py 路径变量
            conftest_path = None

            # ========== 阶段1: 生成 conftest.py ==========
            self.logger.info(f"Task {task_id}: 开始生成 conftest.py")
            task_logger.write_log(task_id, "===== 阶段1: 生成 conftest.py =====")

            from app.services.cc_workflow import stream_generate_conftest_response

            # ========== 统计：记录生成conftest开始时间 ==========
            conftest_start_time = datetime.now()
            # ================================================

            message_count = 0
            conftest_failed = False
            async for message in stream_generate_conftest_response(test_point=test_point, workspace=workspace, task_id=task_id):
                message_count += 1

                # 使用消息解析器解析消息
                parsed_info = parser.parse_message(message, stage="conftest生成")

                # 只记录需要记录的信息
                if parsed_info["should_log"]:
                    log_entry = parser.format_log_entry(parsed_info)
                    if log_entry:
                        task_logger.write_log(task_id, log_entry)

                # 判断是否是错误消息
                is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False
                if is_error:
                    conftest_failed = True
                    self._update_task_status(task_id, "failed", "conftest生成")
                    task_logger.write_log(task_id, "❌ conftest.py生成失败，终止流程")
                    task_logger.write_end_log(task_id, "failed")
                    return

            # ========== 度量 v2：创建 conftest 脚本记录 ==========
            conftest_end_time = datetime.now()
            conftest_duration = (conftest_end_time - conftest_start_time).total_seconds()
            try:
                # 查找 conftest.py 文件
                conftest_files = glob.glob(os.path.join(workspace, "conftest.py"))
                if conftest_files:
                    conftest_path = conftest_files[0]  # 保存 conftest.py 路径
                    conftest_uuid = metrics_service_v2.create_script(
                        script_path=conftest_path,
                        script_type=ScriptType.CONFTEST,
                        generation_duration=conftest_duration
                    )
                    self.logger.info(f"度量 v2: 创建 conftest 脚本记录, uuid={conftest_uuid}")
            except Exception as metrics_error:
                self.logger.warning(f"度量 v2: 创建 conftest 脚本记录失败: {metrics_error}", exc_info=True)
            # ============================================

            # 休眠5秒后再执行后续业务
            await asyncio.sleep(5)
            # ============================================

            self.logger.info(f"Task {task_id}: conftest.py 生成完成，共处理 {message_count} 条消息")
            task_logger.write_log(task_id, f"✓ conftest.py 生成完成 (处理了 {message_count} 条消息)")

            # 拷贝 conftest.py 到指定目录
            try:
                target_dir = settings.get_aigc_tool_local_dir()
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
                        self.logger.warning(f"跳过工作目录外的路径: {root}")
                        continue

                    if "conftest.py" in files:
                        conftest_files.append(os.path.join(root, "conftest.py"))

                self.logger.info(f"找到 {len(conftest_files)} 个 conftest.py 文件")

                if conftest_files:
                    source_conftest = conftest_files[0]
                    target_conftest = os.path.join(target_dir, "conftest.py")
                    shutil.copy2(source_conftest, target_conftest)

                    # 设置 conftest.py 文件权限（权限不足时记录警告）
                    try:
                        os.chmod(target_conftest, 0o777)
                    except PermissionError:
                        self.logger.warning(f"Task {task_id}: ⚠️ 权限不足，无法设置 conftest.py 文件权限: {target_conftest}")

                    self.logger.info(f"Task {task_id}: conftest.py 已拷贝到 {target_conftest}")
                    send_message_log("info", f"✓ conftest.py 已备份到: {target_conftest}", "conftest生成")

                    # 添加AI指纹到 conftest.py
                    try:
                        uuid = add_aifinger_hook.generate_unique_id()
                        success, is_update = add_aifinger_hook.add_fingerprint_to_file(target_conftest, uuid)
                        if success:
                            if is_update:
                                self.logger.info(f"Task {task_id}: 已更新 conftest.py 的AI指纹（原指纹不合法）: {uuid}")
                            else:
                                self.logger.info(f"Task {task_id}: 已为 conftest.py 添加AI指纹: {uuid}")
                        else:
                            # success=False 说明文件已有合法指纹被跳过
                            self.logger.info(f"Task {task_id}: conftest.py 已存在合法的AI指纹，跳过添加")
                    except Exception as fingerprint_err:
                        self.logger.warning(f"Task {task_id}: 添加AI指纹失败: {str(fingerprint_err)}")
                else:
                    self.logger.warning(f"Task {task_id}: 在 {workspace} 中未找到 conftest.py 文件")
                    send_message_log("warning", f"⚠ 未找到 conftest.py 文件，跳过备份", "conftest生成")

            except Exception as e:
                self.logger.error(f"Task {task_id}: 拷贝 conftest.py 失败: {str(e)}")
                send_message_log("warning", f"⚠ 备份 conftest.py 失败: {str(e)}，继续执行后续流程", "conftest生成")

            # ========== 阶段2: 生成测试脚本 ==========
            self.logger.info(f"Task {task_id}: 开始生成测试脚本")
            self._update_task_status(task_id, "running", "测试脚本生成")
            task_logger.write_log(task_id, "\n===== 阶段2: 生成测试脚本 =====")

            from app.services.cc_workflow import stream_test_script_response

            # ========== 统计：记录生成脚本开始时间 ==========
            script_start_time = datetime.now()
            # ==============================================

            # 重置解析器计数器
            parser.reset_counters()
            message_count = 0

            async for message in stream_test_script_response(test_point=test_point, workspace=workspace, task_id=task_id):
                message_count += 1

                # 使用消息解析器解析消息
                parsed_info = parser.parse_message(message, stage="测试脚本生成")

                # 只记录需要记录的信息
                if parsed_info["should_log"]:
                    log_entry = parser.format_log_entry(parsed_info)
                    if log_entry:
                        task_logger.write_log(task_id, log_entry)

                # 判断是否是错误消息
                is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False
                if is_error:
                    self._update_task_status(task_id, "failed", "测试脚本生成")
                    task_logger.write_log(task_id, "❌ 测试脚本生成失败，终止流程")
                    task_logger.write_end_log(task_id, "failed")
                    return

            # ========== 度量 v2：创建测试脚本记录 ==========
            script_end_time = datetime.now()
            script_duration = (script_end_time - script_start_time).total_seconds()
            try:
                # 查找生成的 test_*.py 文件
                test_files = glob.glob(os.path.join(workspace, "test_*.py"))
                if test_files:
                    test_uuid = metrics_service_v2.create_script(
                        script_path=test_files[0],
                        script_type=ScriptType.TEST_SCRIPT,
                        generation_duration=script_duration
                    )
                    self.logger.info(f"度量 v2: 创建测试脚本记录, uuid={test_uuid}, file={os.path.basename(test_files[0])}")
            except Exception as metrics_error:
                self.logger.warning(f"度量 v2: 创建测试脚本记录失败: {metrics_error}", exc_info=True)
            # =========================================

            self.logger.info(f"Task {task_id}: 测试脚本生成完成，共处理 {message_count} 条消息")
            task_logger.write_log(task_id, f"✓ 测试脚本生成完成 (处理了 {message_count} 条消息)")

            # ========== 阶段3: 调用 ITC run 接口执行脚本 ==========
            self.logger.info(f"Task {task_id}: 开始调用 ITC run 接口")
            self._update_task_status(task_id, "running", "ITC脚本执行")
            task_logger.write_log(task_id, "\n===== 阶段3: 执行测试脚本 =====")

            # 获取 executorip
            executorip = settings.get_deploy_executor_ip()

            if not executorip:
                task_logger.write_log(task_id, "❌ 未找到部署的执行机IP，请先部署组网占用环境")
                self._update_task_status(task_id, "failed", "ITC脚本执行")
                task_logger.write_end_log(task_id, "failed")
                return

            task_logger.write_log(task_id, f"ℹ️ 执行机IP: {executorip}，账号:itc 密码:auto_123")

            # 构造脚本路径
            scriptspath = settings.get_aigc_tool_unc_dir()

            task_logger.write_log(task_id, f"ℹ️ 脚本路径: {scriptspath}")
            task_logger.write_log(task_id, "⏳ 正在调用 ITC run 接口...")

            # 调用 ITC run 接口
            from app.services.itc.itc_service import itc_service
            from app.models.itc.itc_models import RunScriptRequest

            itc_request = RunScriptRequest(
                scriptspath=scriptspath,
                executorip=executorip
            )

            # ========== 统计：记录ITC run开始时间 ==========
            itc_run_start_time = datetime.now()
            # ==============================================

            try:
                result = await itc_service.run_script(itc_request, run_new=True)
            except Exception as e:
                self.logger.error(f"Task {task_id}: ITC run 调用异常: {str(e)}")
                result = {
                    "return_code": "500",
                    "return_info": f"ITC run 调用异常: {str(e)}",
                    "result": None
                }

            # ========== 度量 v2：记录 ITC run 耗时到当前活跃脚本 ==========
            itc_run_end_time = datetime.now()
            itc_run_duration = (itc_run_end_time - itc_run_start_time).total_seconds()
            self._record_itc_run_metrics(
                script_path=conftest_path if conftest_path else None,  # 优先使用 conftest.py，否则使用当前活跃脚本
                duration=itc_run_duration,
                return_code=result.get("return_code", "unknown"),
                return_info=result.get("return_info")
            )
            # ===========================================================

            self.logger.info(f"Task {task_id}: ITC run 接口返回: {result}")

            # 发送结果消息（确保 result_message 始终有定义）
            result_message = ""
            try:
                result_message = self._return_code_to_message(result)
                task_logger.write_log(task_id, f"\n📊 ITC 执行结果:\n{result_message}")
            except Exception as e:
                self.logger.error(f"Task {task_id}: 发送 ITC 结果消息失败: {str(e)}")
                task_logger.write_log(task_id, "⚠️ ITC run 执行完成，但结果解析失败")

            # 更新任务状态为完成
            self._update_task_status(task_id, "completed", "ITC脚本执行")
            task_logger.write_log(task_id, "\n===== 自动化测试流程完成 =====")


            # ========== 阶段4: 调用script fix修复脚本 ==========
            # 判断result_message是否需要进行修复
            script_fix = False
            if result_message and " 执行失败 (错误码:" in result_message:
                script_fix = True

            # 如果需要修复
            if script_fix:
                self.logger.info(f"Task {task_id}: 开始修复测试脚本")
                self._update_task_status(task_id, "fix", "测试脚本修复")
                task_logger.write_log(task_id, "\n===== 阶段4: 修复测试脚本 =====")

                from app.services.cc_workflow import stream_fix_script_response
                # 重置解析器计数器
                parser.reset_counters()
                message_count = 0

                async for message in stream_fix_script_response(return_msg=result_message, workspace=workspace, task_id=task_id):
                    message_count += 1
                    # 使用消息解析器解析消息
                    parsed_info = parser.parse_message(message, stage="测试脚本修复")
                    # 只记录需要记录的信息
                    if parsed_info["should_log"]:
                        log_entry = parser.format_log_entry(parsed_info)
                        if log_entry:
                            task_logger.write_log(task_id, log_entry)

                    # 判断是否是错误消息
                    is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False
                    if is_error:
                        self._update_task_status(task_id, "failed", "测试脚本修复")
                        task_logger.write_log(task_id, "❌ 测试脚本修复失败，终止流程")
                        task_logger.write_end_log(task_id, "failed")
                        return

                self.logger.info(f"Task {task_id}: 测试脚本修复完成，共处理 {message_count} 条消息")
                task_logger.write_log(task_id, f"✓ 测试脚本修复完成 (处理了 {message_count} 条消息)")

                # ========== 阶段5: 二次调用 ITC run 接口执行脚本 ==========
                self.logger.info(f"Task {task_id}: 开始调用 ITC run 接口")
                self._update_task_status(task_id, "running", "ITC脚本执行")
                task_logger.write_log(task_id, "\n===== 阶段5: 二次执行测试脚本 =====")

                # 获取 executorip
                executorip = settings.get_deploy_executor_ip()

                if not executorip:
                    task_logger.write_log(task_id, "❌ 未找到部署的执行机IP，请先部署组网占用环境")
                    self._update_task_status(task_id, "failed", "ITC脚本执行")
                    task_logger.write_end_log(task_id, "failed")
                    return

                task_logger.write_log(task_id, f"ℹ️ 执行机IP: {executorip}")

                # 构造脚本路径
                scriptspath = settings.get_aigc_tool_unc_dir()

                task_logger.write_log(task_id, f"ℹ️ 脚本路径: {scriptspath}")
                task_logger.write_log(task_id, "⏳ 正在调用 ITC run 接口...")

                # 调用 ITC run 接口
                from app.services.itc.itc_service import itc_service
                from app.models.itc.itc_models import RunScriptRequest

                itc_request = RunScriptRequest(
                    scriptspath=scriptspath,
                    executorip=executorip
                )

                try:
                    result = await itc_service.run_script(itc_request, run_new=True)
                except Exception as e:
                    self.logger.error(f"Task {task_id}: ITC run 调用异常: {str(e)}")
                    result = {
                        "return_code": "500",
                        "return_info": f"ITC run 调用异常: {str(e)}",
                        "result": None
                    }

                self.logger.info(f"Task {task_id}: ITC run 接口返回: {result}")

                # 发送结果消息
                try:
                    result_message = self._return_code_to_message(result)
                    task_logger.write_log(task_id, f"\n📊 ITC 执行结果:\n{result_message}")
                except Exception as e:
                    self.logger.error(f"Task {task_id}: 发送 ITC 结果消息失败: {str(e)}")
                    task_logger.write_log(task_id, "⚠️ ITC run 执行完成，但结果解析失败")

                # 更新任务状态为完成
                self._update_task_status(task_id, "completed", "ITC脚本执行")
                task_logger.write_log(task_id, "\n===== 自动化测试流程完成 =====")
                task_logger.write_log(task_id, f"ℹ️ 执行机IP: {executorip}，账号:itc 密码:auto_123")
                task_logger.write_log(task_id, f"ℹ️ 脚本路径: {scriptspath}")
                # 写入任务结束标识
                task_logger.write_end_log(task_id, "completed")

            # ========== 为函数执行期间修改的 test_*.py 文件添加 AI 指纹 ==========
            try:
                fingerprint_uuids = add_aifinger_hook.add_fingerprints_and_return_uuids(
                    project_root=workspace,
                    start_time=pipeline_start_time,
                    filename_prefix='test_'
                )
            except Exception as fingerprint_err:
                self.logger.warning(f"Task {task_id}: 为test_文件添加AI指纹失败: {str(fingerprint_err)}")
            # ===================================================================

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "completed")

        # 最外面的try
        except asyncio.CancelledError:
            # 任务被取消
            self.logger.info(f"Task {task_id}: 任务被取消")
            self._update_task_status(task_id, "cancelled")
            task_logger.write_log(task_id, "⚠️ 任务已被用户取消")
            task_logger.write_end_log(task_id, "cancelled")

            raise  # 重新抛出 CancelledError，让 task_cancellation_manager 正确处理

        except Exception as e:
            error_msg = f"自动化测试流程执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
            self.logger.error(f"Task {task_id}: {error_msg}")

            self._update_task_status(task_id, "failed")
            task_logger.write_log(task_id, f"❌ {error_msg}")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "failed")

    # ==================== 获取任务日志 ====================

    def get_task_log_content(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务的完整日志内容

        Args:
            task_id: 任务ID

        Returns:
            包含日志内容的字典，如果文件不存在则返回 None
        """
        log_content = task_logger.read_log(task_id)

        if log_content is None:
            return None

        return {
            "task_id": task_id,
            "log_content": log_content,
            "log_lines": len(log_content.splitlines()),
            "log_file": task_logger.get_log_file_path(task_id)
        }


    # ==================== NETCONF 脚本生成流程 ====================

    async def execute_netconf_script_pipeline(
        self,
        task_id: str,
        workspace: str,
        yang_files: list
    ):
        """
        执行 NETCONF 测试脚本生成流程

        调用 netconf_workflow.execute_netconf_workflow 执行完整的 NETCONF 工作流

        Args:
            task_id: 任务ID
            workspace: 工作目录
            yang_files: YANG 文件名列表
        """
        # 记录函数入口时间
        import time
        pipeline_start_time = time.time()

        # 写入任务开始标识
        task_logger.write_start_log(task_id, "NETCONF 脚本生成任务")
        task_logger.write_log(task_id, f"YANG 文件: {', '.join(yang_files)}")

        try:
            # 更新任务状态为运行中
            self._update_task_status(task_id, "running", "NETCONF脚本生成")
            self._send_message(task_id, "info", "开始执行 NETCONF 脚本生成任务", "processing")

            task_logger.write_log(task_id, f"ℹ️ 工作目录: {workspace}")
            task_logger.write_log(task_id, f"ℹ️ YANG 文件: {', '.join(yang_files)}")
            task_logger.write_log(task_id, "===== 开始调用 NETCONF 工作流 =====")

            # 导入 NETCONF 工作流
            from app.services.netconf.netconf_workflow import execute_netconf_workflow

            # 调用 execute_netconf_workflow 执行完整流程
            # 内部包含：
            # 1. 准备依赖材料
            # 2. 生成 NETCONF 测试脚本
            # 3. 运行测试脚本
            # 4. 解析结果并修复（如果需要）
            test_point = f"基于以下 YANG 文件生成 NETCONF 测试脚本: {', '.join(yang_files)}"
            await execute_netconf_workflow(
                task_id=task_id,
                test_point=test_point,
                workspace=workspace
            )

            # ========== 为函数执行期间修改的 Python 文件添加 AI 指纹 ==========
            try:
                fingerprint_uuids = add_aifinger_hook.add_fingerprints_and_return_uuids(
                    project_root=workspace,
                    start_time=pipeline_start_time,
                    exclude_filename_prefix='test_example',
                    exclude_dirs={'.venv', '.claude', '.git', '__pycache__', 'venv', 'env', '.pytest_cache', '.tox', 'dist', 'build', '.eggs', '*.egg-info', 'yang_files'}
                )
            except Exception as fingerprint_err:
                self.logger.warning(f"Task {task_id}: 为文件添加AI指纹失败: {str(fingerprint_err)}")
            # ===================================================================

            task_logger.write_log(task_id, "\n===== NETCONF 脚本生成流程完成 =====")
            task_logger.write_end_log(task_id, "completed")
            self._update_task_status(task_id, "completed", "NETCONF脚本生成")

        except asyncio.CancelledError:
            # 任务被取消
            self.logger.info(f"Task {task_id}: NETCONF 脚本生成任务被取消")
            self._update_task_status(task_id, "cancelled")
            task_logger.write_log(task_id, "⚠️ NETCONF 脚本生成任务已被用户取消")
            task_logger.write_end_log(task_id, "cancelled")

            raise  # 重新抛出 CancelledError，让 task_cancellation_manager 正确处理

        except Exception as e:
            error_msg = f"NETCONF 脚本生成流程执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
            self.logger.error(f"Task {task_id}: {error_msg}")

            self._update_task_status(task_id, "failed")
            task_logger.write_log(task_id, f"❌ {error_msg}")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "failed")


    # ==================== Claude Chat 流程 ====================

    async def execute_claude_chat_pipeline(self, task_id: str, prompt: str, workspace: str):
        """
        执行 Claude Chat 流程：
        直接调用 Claude Code SDK 处理用户输入，不预设 prompt 模板

        Args:
            task_id: 任务ID
            prompt: 用户输入的prompt
            workspace: 工作目录
        """
        # 导入消息解析器
        from app.utils.claude_message_parser import ClaudeMessageParser
        parser = ClaudeMessageParser()

        # 写入任务开始标识
        task_logger.write_start_log(task_id, "Claude Chat 任务")
        task_logger.write_log(task_id, f"用户输入: {prompt[:200]}...")

        def send_message_log(message_type: str, data: str, stage: str = ""):
            """写入消息到日志文件"""
            try:
                stage_prefix = f"[{stage}] " if stage else ""
                log_content = f"{stage_prefix}[{message_type}] {data[:300]}"
                task_logger.write_log(task_id, log_content)
            except Exception as e:
                self.logger.error(f"Task {task_id}: 写入日志失败: {str(e)}")

        try:
            # 更新任务状态为运行中
            self._update_task_status(task_id, "running", "Claude处理")
            send_message_log("info", f"开始执行 Claude Chat 任务\n用户输入: {prompt[:200]}...", "Claude处理")

            # 调用 Claude Code SDK 处理用户输入

            from app.services.cc_workflow import stream_claude_chat_response

            # 重置解析器计数器
            parser.reset_counters()
            message_count = 0

            async for message in stream_claude_chat_response(prompt=prompt, workspace=workspace, task_id=task_id):
                message_count += 1

                # 使用消息解析器解析消息
                parsed_info = parser.parse_message(message, stage="Claude处理")

                # 只记录需要记录的信息
                if parsed_info["should_log"]:
                    log_entry = parser.format_log_entry(parsed_info)
                    if log_entry:
                        task_logger.write_log(task_id, log_entry)

                # 判断是否是错误消息
                is_error = getattr(message, 'error', False) if hasattr(message, 'error') else False
                if is_error:
                    self._update_task_status(task_id, "failed", "Claude处理")
                    task_logger.write_log(task_id, "❌ Claude Chat 处理失败")
                    task_logger.write_end_log(task_id, "failed")
                    return

            # 更新任务状态为完成
            self._update_task_status(task_id, "completed", "Claude处理")
            task_logger.write_log(task_id, "\n===== Claude Chat 任务完成 =====")
            task_logger.write_end_log(task_id, "completed")

        except asyncio.CancelledError:
            # 任务被取消
            self.logger.info(f"Task {task_id}: Claude Chat 任务被取消")
            self._update_task_status(task_id, "cancelled")
            task_logger.write_log(task_id, "⚠️ Claude Chat 任务已被用户取消")
            task_logger.write_end_log(task_id, "cancelled")
            raise  # 重新抛出 CancelledError，让 task_cancellation_manager 正确处理

        except Exception as e:
            error_msg = f"Claude Chat 任务执行失败: {str(e)}\n\n堆栈信息:\n{traceback.format_exc()}"
            self.logger.error(f"Task {task_id}: {error_msg}")

            self._update_task_status(task_id, "failed")
            task_logger.write_log(task_id, f"❌ {error_msg}")

            # 写入任务结束标识
            task_logger.write_end_log(task_id, "failed")


# 创建全局单例
script_generation_service = ScriptGenerationService()
