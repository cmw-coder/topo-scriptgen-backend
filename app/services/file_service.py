import os
import aiofiles
from pathlib import Path
from typing import List, Optional, Union
import logging
from datetime import datetime

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
                        # 过滤掉 .venv 和 test_example 目录
                        if item.name in ['.venv', 'test_example']:
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

# 创建文件服务实例
file_service = FileService()
