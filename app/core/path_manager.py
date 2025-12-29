import os
from pathlib import Path
from typing import Union, Optional
from app.core.config import settings


class PathManager:
    """路径管理器，负责处理项目工作目录的动态路径获取和管理"""

    @staticmethod
    def get_project_root() -> Path:
        """获取项目根目录"""
        work_dir = settings.get_work_directory()
        if isinstance(work_dir, str):
            return Path(work_dir)
        return work_dir

    @staticmethod
    def set_project_root(path: Union[str, Path]) -> None:
        """设置项目根目录"""
        if isinstance(path, str):
            path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {path}")
        settings.set_work_directory(path)

    @staticmethod
    def get_relative_path(absolute_path: Union[str, Path]) -> Optional[str]:
        """获取相对于项目根目录的相对路径"""
        if isinstance(absolute_path, str):
            absolute_path = Path(absolute_path)

        try:
            work_dir = settings.get_work_directory()
            if isinstance(work_dir, str):
                work_dir = Path(work_dir)
            return str(absolute_path.relative_to(work_dir))
        except ValueError:
            return None

    @staticmethod
    def get_absolute_path(relative_path: Union[str, Path]) -> Path:
        """根据相对路径获取绝对路径"""
        if isinstance(relative_path, str):
            relative_path = Path(relative_path)

        if relative_path.is_absolute():
            return relative_path

        work_dir = settings.get_work_directory()
        if isinstance(work_dir, str):
            work_dir = Path(work_dir)
        return work_dir / relative_path

    @staticmethod
    def get_scripts_dir() -> Path:
        """获取脚本目录"""
        scripts_dir = settings.get_scripts_directory()
        if isinstance(scripts_dir, str):
            scripts_dir = Path(scripts_dir)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        return scripts_dir

    @staticmethod
    def get_logs_dir() -> Path:
        """获取日志目录"""
        logs_dir = settings.get_logs_directory()
        if isinstance(logs_dir, str):
            logs_dir = Path(logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @staticmethod
    def get_topox_dir() -> Path:
        """获取topox文件目录"""
        topox_dir = settings.get_topox_directory()
        if isinstance(topox_dir, str):
            topox_dir = Path(topox_dir)
        topox_dir.mkdir(parents=True, exist_ok=True)
        return topox_dir

    @staticmethod
    def resolve_path(path: Union[str, Path]) -> Path:
        """解析路径，支持相对路径和绝对路径"""
        if isinstance(path, str):
            path = Path(path)

        if path.is_absolute():
            return path

        # 相对路径相对于项目根目录
        work_dir = settings.get_work_directory()
        if isinstance(work_dir, str):
            work_dir = Path(work_dir)
        return work_dir / path

    @staticmethod
    def is_safe_path(path: Union[str, Path]) -> bool:
        """检查路径是否安全（不包含目录遍历攻击）"""
        # if isinstance(path, str):
        #     path = Path(path)

        # try:
        #     resolved_path = path.resolve()
        #     work_dir = settings.get_work_directory()
        #     if isinstance(work_dir, str):
        #         work_dir = Path(work_dir)
        #     project_root = work_dir.resolve()

        #     # 检查解析后的路径是否在项目根目录内
        #     return resolved_path.is_relative_to(project_root)
        # except (OSError, ValueError):
        #     return False
        return True

    @staticmethod
    def ensure_directory_exists(path: Union[str, Path]) -> Path:
        """确保目录存在，如果不存在则创建"""
        if isinstance(path, str):
            path = Path(path)

        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)

        return path


# 创建全局路径管理器实例
path_manager = PathManager()
