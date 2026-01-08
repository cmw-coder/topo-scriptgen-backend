import os
import aiofiles
from pathlib import Path
from typing import List, Optional, Union
import logging
from datetime import datetime
import glob

from app.core.path_manager import path_manager
from app.core.config import settings
from app.models.common import DirectoryItem, FileOperationRequest, FileOperationResponse

logger = logging.getLogger(__name__)

class FileService:
    """文件操作服务
AI_FingerPrint_UUID: 20251225-VPMtKjgr
"""

    def __init__(self):
        self.path_manager = path_manager

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
