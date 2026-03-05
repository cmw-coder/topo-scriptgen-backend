#!/usr/bin/env python3
"""
配置管理模块
"""

import os
from pathlib import Path
from typing import Optional
from datetime import datetime


class Settings:
    """应用配置类"""

    # ========== 项目基础设置 ==========
    PROJECT_NAME: str = "Minimal ITC API"
    VERSION: str = "1.0.1"
    DESCRIPTION: str = "Minimal FastAPI application for ITC topox deployment and script execution"

    # ========== 服务器设置 ==========
    HOST: str = "0.0.0.0"
    PORT: int = 5032 #用不同的端口避免与主项目冲突
    DEBUG: bool = False

    # ========== ITC 服务配置 ==========
    ITC_SERVER_URL: str = "http://10.111.8.68:8000/aigc"
    ITC_REQUEST_TIMEOUT: int = 1200  # 20分钟超时

    # ========== 目录配置 ==========
    # 基础保存目录（硬编码为 w14512 用户）
    BASE_DIR: str = "/opt/coder/statistics/build/aigc_tool/w14512"

    # UNC 路径基础（用于 ITC 部署）
    BASE_UNC_DIR: str = "//10.144.41.149/webide/aigc_tool/w14512"

    # 临时目录名称（每次部署时更新）
    _temp_dir_name: Optional[str] = None

    # ========== 文件上传配置 ==========
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_TOPOX_EXTENSIONS: set = {".topox"}
    ALLOWED_SCRIPT_EXTENSIONS: set = {".py", ".sh", ".yaml", ".yml", ".json"}

    # ========== 日志配置 ==========
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"

    @classmethod
    def get_base_dir(cls) -> Path:
        """获取基础目录"""
        base_path = Path(cls.BASE_DIR)
        base_path.mkdir(parents=True, exist_ok=True)
        return base_path

    @classmethod
    def create_temp_dir(cls) -> str:
        """
        创建新的临时目录
        格式: temp_YYYYMMDD_HHMMSS
        返回: 临时目录名称
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cls._temp_dir_name = f"temp_{timestamp}"

        temp_dir = cls.get_base_dir() / cls._temp_dir_name
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 设置权限为 777（任意用户可读写执行）
        try:
            os.chmod(temp_dir, 0o777)
        except Exception as e:
            print(f"警告: 设置临时目录权限失败: {e}")

        return cls._temp_dir_name

    @classmethod
    def get_temp_dir_name(cls) -> Optional[str]:
        """获取当前临时目录名称"""
        return cls._temp_dir_name

    @classmethod
    def get_temp_dir(cls) -> Optional[Path]:
        """
        获取当前临时目录的完整路径
        如果不存在则创建
        """
        if cls._temp_dir_name is None:
            cls.create_temp_dir()

        temp_dir = cls.get_base_dir() / cls._temp_dir_name
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 设置权限为 777
        try:
            os.chmod(temp_dir, 0o777)
        except Exception:
            pass

        return temp_dir

    @classmethod
    def get_temp_dir_uname(cls) -> str:
        """获取临时目录的 UNC 路径"""
        temp_name = cls.get_temp_dir_name()
        if temp_name is None:
            temp_name = cls.create_temp_dir()
        return f"{cls.BASE_UNC_DIR}/{temp_name}"

    @classmethod
    def set_directory_permissions(cls, directory: Path) -> None:
        """
        递归设置目录及其所有内容的权限为 777
        """
        try:
            # 设置目录本身权限
            os.chmod(directory, 0o777)

            # 递归设置所有子目录和文件的权限
            for root, dirs, files in os.walk(directory):
                for dir_name in dirs:
                    dir_path = os.path.join(root, dir_name)
                    try:
                        os.chmod(dir_path, 0o777)
                    except Exception:
                        pass

                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    try:
                        os.chmod(file_path, 0o777)
                    except Exception:
                        pass
        except Exception:
            pass

    @classmethod
    def create_temp_dir_standalone(cls) -> tuple[str, Path]:
        """
        创建独立的临时目录（不更新全局 _temp_dir_name）
        用于 upload-scripts 接口中包含 topox 文件的场景

        返回: (临时目录名称, 临时目录完整路径)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir_name = f"temp_{timestamp}"

        temp_dir = cls.get_base_dir() / temp_dir_name
        temp_dir.mkdir(parents=True, exist_ok=True)

        # 设置权限为 777
        try:
            os.chmod(temp_dir, 0o777)
        except Exception as e:
            print(f"警告: 设置临时目录权限失败: {e}")

        return temp_dir_name, temp_dir


settings = Settings()
