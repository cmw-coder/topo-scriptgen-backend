import os
import aiofiles
from pathlib import Path
from typing import List, Optional, Union, Set
import logging
import asyncio
import hashlib
from datetime import datetime
import glob
import time

from app.core.path_manager import path_manager
from app.core.config import settings
from app.models.common import DirectoryItem, FileOperationRequest, FileOperationResponse
from app.services.topo_service import topo_service
from app.services.itc.itc_service import itc_service

logger = logging.getLogger(__name__)

class FileService:
    """文件操作服务
AI_FingerPrint_UUID: 20251225-VPMtKjgr
"""

    def __init__(self):
        self.path_manager = path_manager
        # 异步任务追踪
        self._undeploy_tasks: Set[asyncio.Task] = set()
        # 并发控制信号量（最多同时1个卸载任务）
        self._undeploy_semaphore = asyncio.Semaphore(1)
        # 当前卸载任务引用
        self._current_undeploy_task: Optional[asyncio.Task] = None
        # 幂等性控制
        self._last_upload_hash: Optional[str] = None
        self._last_upload_time: Optional[datetime] = None

    def _is_duplicate_upload(self, content: str) -> bool:
        """检查是否为重复上传（2秒内相同内容）

        Args:
            content: 文件内容

        Returns:
            bool: True 表示重复上传，False 表示新上传
        """
        content_hash = hashlib.md5(content.encode()).hexdigest()
        now = datetime.now()

        if (self._last_upload_hash == content_hash and
            self._last_upload_time and
            (now - self._last_upload_time).total_seconds() <
            settings.DEFAULT_TOPOX_DEBOUNCE_SECONDS):
            logger.debug("检测到重复上传（2秒内相同内容），跳过处理")
            return True

        # 更新记录
        self._last_upload_hash = content_hash
        self._last_upload_time = now
        return False

    async def _handle_default_topox_upload(self, file_path: Path, content: str) -> None:
        """处理 default.topox 文件上传

        Args:
            file_path: 上传的文件路径
            content: 文件内容（XML 格式）
        """
        import time
        start_time = time.time()

        logger.info("检测到 default.topox 上传，开始处理")

        try:
            # 幂等性检查
            if self._is_duplicate_upload(content):
                return

            # 解析 topox 文件
            network = topo_service.parse_topox_xml(content)
            logger.debug(f"成功解析 topox，设备数: {len(network.device_list)}, 链路数: {len(network.link_list)}")

            # 更新 aigc.json
            topo_service.save_device_list_to_aigc_json(network)

            # 重置部署状态
            settings.set_deploy_status("not_deployed")
            settings.set_deploy_error_message("通过上传 default.topox")
            logger.info("已重置部署状态为 not_deployed，原因：通过上传 default.topox")

            # 异步卸载
            self._async_undeploy_if_needed()

            elapsed = time.time() - start_time
            logger.info(f"default.topox 处理完成，耗时 {elapsed:.2f} 秒")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"处理 default.topox 失败: {str(e)}，耗时 {elapsed:.2f} 秒", exc_info=True)
            # 不抛出异常，允许文件保存成功

    async def _async_undeploy_if_needed(self) -> None:
        """如果存在 executorip，异步调用卸载组网接口

        特性：
        - 任务生命周期管理：追踪所有创建的任务
        - 并发控制：使用信号量限制并发数量
        - 任务替换：取消之前的卸载任务，创建新任务
        """
        try:
            # Use self.settings instead of importing from app.core.config
            # This allows mocking in tests

            # 检查配置是否启用异步卸载
            if not getattr(self, 'settings', None):
                logger.info("No settings object available, skip async undeploy")
                return

            if not self.settings.DEFAULT_TOPOX_ASYNC_UNDEPLOY:
                logger.info("异步卸载功能未启用，跳过")
                return

            executorip = self.settings.get_deploy_executor_ip()

            if not executorip:
                logger.info("不存在 executorip，跳过卸载组网")
                return

            # 如果已有卸载任务在执行，取消它
            if self._current_undeploy_task and not self._current_undeploy_task.done():
                logger.info("取消之前的卸载任务")
                self._current_undeploy_task.cancel()

            logger.info(f"检测到 executorip: {executorip}，创建异步卸载任务")

            # 创建新的卸载任务
            self._current_undeploy_task = asyncio.create_task(
                self._execute_undeploy_with_semaphore(executorip)
            )

            # 添加到任务追踪集合
            self._undeploy_tasks.add(self._current_undeploy_task)
            logger.info(f"任务已添加到集合，当前任务数: {len(self._undeploy_tasks)}")

            # 任务完成时自动从集合中移除
            self._current_undeploy_task.add_done_callback(self._undeploy_tasks.discard)

        except Exception as e:
            logger.error(f"创建异步卸载任务失败: {str(e)}", exc_info=True)

    async def _execute_undeploy_with_semaphore(self, executorip: str) -> None:
        """执行卸载操作（带并发控制）

        Args:
            executorip: 执行器 IP 地址
        """
        async with self._undeploy_semaphore:
            await self._execute_undeploy(executorip)

    async def _execute_undeploy(self, executorip: str) -> None:
        """执行卸载操作（在后台任务中运行）

        Args:
            executorip: 执行器 IP 地址
        """
        import time
        start_time = time.time()

        try:
            logger.info(f"开始异步卸载组网，executorip: {executorip}")

            # Use self.itc_service instead of global itc_service to allow mocking
            if not hasattr(self, 'itc_service'):
                logger.error("No itc_service available, skip undeploy")
                return

            from app.models.itc.itc_models import ExecutorRequest
            request = ExecutorRequest(executorip=executorip)

            # 使用超时控制
            if hasattr(self, 'settings'):
                timeout = self.settings.DEFAULT_TOPOX_UNDEPLOY_TIMEOUT
            else:
                timeout = 30  # Default timeout

            result = await asyncio.wait_for(
                self.itc_service.undeploy_environment(request),
                timeout=timeout
            )

            elapsed = time.time() - start_time

            if result.return_code == "200":
                logger.info(f"异步卸载成功: {executorip}，耗时 {elapsed:.2f} 秒")
            else:
                logger.warning(f"异步卸载失败: {result.return_info}，耗时 {elapsed:.2f} 秒")

        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            logger.error(f"异步卸载超时（{timeout}秒），耗时 {elapsed:.2f} 秒")

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"异步卸载异常: {str(e)}，耗时 {elapsed:.2f} 秒", exc_info=True)

    async def wait_for_undeploy_tasks(self, timeout: float = 5.0) -> None:
        """等待所有卸载任务完成（用于应用关闭时）

        Args:
            timeout: 等待超时时间（秒）
        """
        if self._undeploy_tasks:
            logger.info(f"等待 {len(self._undeploy_tasks)} 个卸载任务完成...")
            tasks = list(self._undeploy_tasks)
            done, pending = await asyncio.wait(tasks, timeout=timeout)

            if pending:
                logger.warning(f"有 {len(pending)} 个卸载任务未完成，强制退出")
            else:
                logger.info("所有卸载任务已完成")

    async def read_directory(self, directory_path: str) -> FileOperationResponse:
        """读取目录内容"""
        try:
            # 解析路径并检查安全性
            resolved_path = self.path_manager.resolve_path(directory_path)
            if not self.path_manager.is_safe_path(resolved_path):
                return FileOperationResponse(
                    path=directory_path,
                    operation="read",
                    success=False,
                    message="路径不安全或超出项目范围"
                )

            if not resolved_path.exists():
                return FileOperationResponse(
                    path=directory_path,
                    operation="read",
                    success=False,
                    message="目录不存在"
                )

            if not resolved_path.is_dir():
                return FileOperationResponse(
                    path=directory_path,
                    operation="read",
                    success=False,
                    message="路径不是目录"
                )

            # 构建目录结构
            items = await self._build_directory_tree(resolved_path)

            return FileOperationResponse(
                path=directory_path,
                operation="read",
                success=True,
                content=str([item.model_dump() for item in items]),
                message=f"成功读取目录，共 {len(items)} 个项目"
            )

        except Exception as e:
            logger.error(f"读取目录失败: {directory_path}, 错误: {str(e)}")
            return FileOperationResponse(
                path=directory_path,
                operation="read",
                success=False,
                message=f"读取目录失败: {str(e)}"
            )

    async def read_file(self, file_path: str, encoding: str = "utf-8") -> FileOperationResponse:
        """读取文件内容"""
        try:
            # 解析路径并检查安全性
            resolved_path = self.path_manager.resolve_path(file_path)
            if not self.path_manager.is_safe_path(resolved_path):
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=False,
                    message="路径不安全或超出项目范围"
                )

            if not resolved_path.exists():
                # 特殊处理：如果是 spec.md 文件，在工作目录下全局递归查找最新的文件
                if resolved_path.name == "spec.md":
                    return await self._find_latest_spec_file(file_path, encoding)

                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=False,
                    message="文件不存在"
                )

            if not resolved_path.is_file():
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=False,
                    message="路径不是文件"
                )

            # 检查文件大小
            file_size = resolved_path.stat().st_size
            if file_size > settings.MAX_FILE_SIZE:
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=False,
                    message=f"文件过大，最大支持 {settings.MAX_FILE_SIZE} 字节"
                )

            # 检查文件扩展名
            if resolved_path.suffix.lower() not in settings.ALLOWED_EXTENSIONS:
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=False,
                    message=f"不支持的文件类型，支持的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}"
                )

            # 异步读取文件
            async with aiofiles.open(resolved_path, 'r', encoding=encoding) as file:
                content = await file.read()

            return FileOperationResponse(
                path=file_path,
                operation="read",
                success=True,
                content=content,
                size=file_size,
                message="文件读取成功"
            )

        except UnicodeDecodeError:
            return FileOperationResponse(
                path=file_path,
                operation="read",
                success=False,
                message="文件编码错误，请检查文件编码格式"
            )
        except Exception as e:
            logger.error(f"读取文件失败: {file_path}, 错误: {str(e)}")
            return FileOperationResponse(
                path=file_path,
                operation="read",
                success=False,
                message=f"读取文件失败: {str(e)}"
            )

    async def write_file(self, file_path: str, content: str, encoding: str = "utf-8") -> FileOperationResponse:
        """写入文件内容"""
        try:
            # 解析路径并检查安全性
            resolved_path = self.path_manager.resolve_path(file_path)
            if not self.path_manager.is_safe_path(resolved_path):
                return FileOperationResponse(
                    path=file_path,
                    operation="write",
                    success=False,
                    message="路径不安全或超出项目范围"
                )

            # 检查内容大小
            content_size = len(content.encode(encoding))
            if content_size > settings.MAX_FILE_SIZE:
                return FileOperationResponse(
                    path=file_path,
                    operation="write",
                    success=False,
                    message=f"文件内容过大，最大支持 {settings.MAX_FILE_SIZE} 字节"
                )

            # 确保父目录存在
            parent_dir = resolved_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

            # 异步写入文件
            async with aiofiles.open(resolved_path, 'w', encoding=encoding) as file:
                await file.write(content)

            # 检查文件扩展名
            if resolved_path.suffix.lower() not in settings.ALLOWED_EXTENSIONS:
                return FileOperationResponse(
                    path=file_path,
                    operation="write",
                    success=True,
                    size=content_size,
                    message=f"文件写入成功，但文件类型不在支持列表中。支持的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}"
                )

            return FileOperationResponse(
                path=file_path,
                operation="write",
                success=True,
                size=content_size,
                message="文件写入成功"
            )

        except Exception as e:
            logger.error(f"写入文件失败: {file_path}, 错误: {str(e)}")
            return FileOperationResponse(
                path=file_path,
                operation="write",
                success=False,
                message=f"写入文件失败: {str(e)}"
            )

    async def delete_file(self, file_path: str) -> FileOperationResponse:
        """删除文件或目录"""
        try:
            # 解析路径并检查安全性
            resolved_path = self.path_manager.resolve_path(file_path)
            if not self.path_manager.is_safe_path(resolved_path):
                return FileOperationResponse(
                    path=file_path,
                    operation="delete",
                    success=False,
                    message="路径不安全或超出项目范围"
                )

            if not resolved_path.exists():
                return FileOperationResponse(
                    path=file_path,
                    operation="delete",
                    success=False,
                    message="文件或目录不存在"
                )

            # 获取删除前的大小信息
            if resolved_path.is_file():
                size = resolved_path.stat().st_size
                resolved_path.unlink()
                operation_type = "文件"
            else:
                # 删除目录及其内容
                size = sum(f.stat().st_size for f in resolved_path.rglob('*') if f.is_file())
                import shutil
                shutil.rmtree(resolved_path)
                operation_type = "目录"

            return FileOperationResponse(
                path=file_path,
                operation="delete",
                success=True,
                size=size,
                message=f"{operation_type}删除成功"
            )

        except Exception as e:
            logger.error(f"删除失败: {file_path}, 错误: {str(e)}")
            return FileOperationResponse(
                path=file_path,
                operation="delete",
                success=False,
                message=f"删除失败: {str(e)}"
            )

    async def get_directory_tree(self, directory_path: str = "") -> List[DirectoryItem]:
        """获取目录树结构"""
        try:
            if not directory_path:
                resolved_path = self.path_manager.get_project_root()
            else:
                resolved_path = self.path_manager.resolve_path(directory_path)

            if not self.path_manager.is_safe_path(resolved_path):
                return []

            if not resolved_path.exists():
                return []

            return await self._build_directory_tree(resolved_path)
        except Exception as e:
            logger.error(f"获取目录树失败: {directory_path}, 错误: {str(e)}")
            return []

    async def _build_directory_tree(self, directory_path: Path) -> List[DirectoryItem]:
        """递归构建目录树"""
        items = []

        try:
            for item in directory_path.iterdir():
                try:
                    # 获取相对路径
                    relative_path = self.path_manager.get_relative_path(item)
                    if relative_path is None:
                        continue

                    # 确保相对路径使用正斜杠格式
                    relative_path = relative_path.replace("\\", "/")

                    # 获取文件信息
                    stat_info = item.stat()
                    modified_time = datetime.fromtimestamp(stat_info.st_mtime)

                    if item.is_file():
                        # 文件项
                        file_item = DirectoryItem(
                            label=item.name,
                            path=relative_path,
                            children=None,
                            is_file=True,
                            size=stat_info.st_size,
                            modified_time=modified_time
                        )
                        items.append(file_item)
                    elif item.is_dir():
                        # 过滤掉指定目录
                        skip_dirs = {'.aigc_tool', '.venv', 'KE知识库', 'logs', 'pypilot press', 'test_example'}
                        if item.name in skip_dirs:
                            logger.debug(f"过滤目录: {item.name}")
                            continue

                        # 目录项
                        children = await self._build_directory_tree(item)
                        dir_item = DirectoryItem(
                            label=item.name,
                            path=relative_path,
                            children=children if children else [],
                            is_file=False,
                            size=None,
                            modified_time=modified_time
                        )
                        items.append(dir_item)
                except (OSError, PermissionError) as e:
                    logger.warning(f"无法访问文件/目录: {item}, 错误: {str(e)}")
                    continue

            # 按名称排序，目录在前，文件在后
            items.sort(key=lambda x: (x.is_file, x.label.lower()))

        except (OSError, PermissionError) as e:
            logger.error(f"读取目录失败: {directory_path}, 错误: {str(e)}")

        return items

    async def _find_latest_spec_file(self, file_path: str, encoding: str = "utf-8") -> FileOperationResponse:
        """在工作目录下全局递归查找最新的 spec.md 文件

        Args:
            file_path: 请求的文件路径
            encoding: 文件编码

        Returns:
            FileOperationResponse: 如果找到最新文件则返回其内容，否则返回空内容
        """
        try:
            work_dir = self.path_manager.get_project_root()

            logger.info(f"在工作目录 {work_dir} 下递归查找所有 spec.md 文件")

            # 递归查找所有 spec.md 文件
            pattern = os.path.join(work_dir, "**/spec.md")
            spec_files = glob.glob(pattern, recursive=True)

            if not spec_files:
                logger.info(f"未找到任何 spec.md 文件，返回空内容")
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=True,
                    content="",
                    size=0,
                    message="未找到 spec.md 文件"
                )

            logger.info(f"找到 {len(spec_files)} 个 spec.md 文件: {spec_files}")

            # 按修改时间排序，找到最新的文件
            spec_files_with_time = []
            for spec_file in spec_files:
                try:
                    mtime = os.path.getmtime(spec_file)
                    spec_files_with_time.append((spec_file, mtime))
                except OSError as e:
                    logger.warning(f"无法获取文件 {spec_file} 的修改时间: {str(e)}")
                    continue

            if not spec_files_with_time:
                logger.info(f"无法获取任何文件的修改时间，返回空内容")
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=True,
                    content="",
                    size=0,
                    message="无法读取 spec.md 文件"
                )

            # 按修改时间降序排序，获取最新文件
            spec_files_with_time.sort(key=lambda x: x[1], reverse=True)
            latest_file = spec_files_with_time[0][0]
            latest_mtime = spec_files_with_time[0][1]
            latest_time_str = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M:%S")

            logger.info(f"找到最新的 spec.md 文件: {latest_file} (修改时间: {latest_time_str})")

            # 检查文件大小
            file_size = os.path.getsize(latest_file)
            if file_size > settings.MAX_FILE_SIZE:
                return FileOperationResponse(
                    path=file_path,
                    operation="read",
                    success=False,
                    message=f"文件过大，最大支持 {settings.MAX_FILE_SIZE} 字节"
                )

            # 读取文件内容
            async with aiofiles.open(latest_file, 'r', encoding=encoding) as file:
                content = await file.read()

            # 获取相对路径
            try:
                relative_path = self.path_manager.get_relative_path(latest_file)
                if relative_path:
                    # 转换为正斜杠格式
                    relative_path = relative_path.replace("\\", "/")
                    logger.info(f"返回文件的相对路径: {relative_path}")
                else:
                    relative_path = file_path
            except Exception:
                relative_path = file_path

            return FileOperationResponse(
                path=relative_path,
                operation="read",
                success=True,
                content=content,
                size=file_size,
                message=f"成功读取最新的 spec.md 文件 (修改时间: {latest_time_str})"
            )

        except Exception as e:
            logger.error(f"查找最新 spec.md 文件时出错: {str(e)}")
            # 出错时返回空内容
            return FileOperationResponse(
                path=file_path,
                operation="read",
                success=True,
                content="",
                size=0,
                message=f"查找 spec.md 文件时出错: {str(e)}"
            )

# 创建文件服务实例
file_service = FileService()
