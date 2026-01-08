"""ITC日志文件服务
AI_FingerPrint_UUID: 20250108-Lm8kQ3xR
"""
import os
import aiofiles
from pathlib import Path
from typing import List, Optional
import logging
from datetime import datetime

from app.models.itc_log import ItcLogFileInfo
from app.core.config import settings


logger = logging.getLogger(__name__)


class ItcLogService:
    """ITC日志文件服务类"""

    def __init__(self):
        """初始化ITC日志服务"""
        self.log_base_path = "/opt/coder/statistics/build/aigc_tool"

    def _get_user_log_dir(self, username: Optional[str] = None) -> Path:
        """获取用户的ITC日志目录

        Args:
            username: 用户名，如果为None则使用当前系统用户名

        Returns:
            Path: 用户ITC日志目录的完整路径
        """
        if username is None:
            # 获取当前系统用户名
            username = os.getenv("USER") or os.getenv("USERNAME") or "default"

        # 构建ITC日志目录路径: /opt/coder/statistics/build/aigc_tool/{username}/log/
        log_dir = Path(self.log_base_path) / username / "log"
        return log_dir

    async def get_itc_log_files(self, username: Optional[str] = None) -> tuple[bool, str, Optional[List[ItcLogFileInfo]]]:
        """获取指定用户的ITC日志文件列表

        Args:
            username: 用户名，如果为None则使用当前系统用户名

        Returns:
            tuple: (success, message, log_files)
                - success: 是否成功
                - message: 响应消息
                - log_files: ITC日志文件信息列表，失败时为None
        """
        try:
            log_dir = self._get_user_log_dir(username)

            # 检查目录是否存在
            if not log_dir.exists():
                logger.warning(f"ITC日志目录不存在: {log_dir}")
                return True, f"ITC日志目录不存在: {log_dir}", []

            if not log_dir.is_dir():
                logger.error(f"ITC日志路径不是目录: {log_dir}")
                return False, f"ITC日志路径不是目录: {log_dir}", None

            # 读取目录中的所有文件
            log_files: List[ItcLogFileInfo] = []
            for file_path in log_dir.iterdir():
                # 只处理文件，跳过目录
                if file_path.is_file():
                    try:
                        # 获取文件信息
                        stat = file_path.stat()

                        # 格式化修改时间
                        modified_time = datetime.fromtimestamp(
                            stat.st_mtime
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        # 创建ITC日志文件信息对象
                        log_file_info = ItcLogFileInfo(
                            filename=file_path.name,
                            size=stat.st_size,
                            modified_time=modified_time
                        )
                        log_files.append(log_file_info)

                    except Exception as e:
                        logger.warning(f"无法读取文件信息 {file_path.name}: {str(e)}")
                        continue

            # 按文件名排序
            log_files.sort(key=lambda x: x.filename)

            logger.info(f"成功获取ITC日志文件列表，共 {len(log_files)} 个文件")
            return True, f"成功获取ITC日志文件列表，共 {len(log_files)} 个文件", log_files

        except Exception as e:
            logger.error(f"获取ITC日志文件列表失败: {str(e)}")
            return False, f"获取ITC日志文件列表失败: {str(e)}", None

    async def get_itc_log_content(self, filename: str, username: Optional[str] = None) -> tuple[bool, str, Optional[dict]]:
        """读取指定ITC日志文件的内容

        Args:
            filename: ITC日志文件名
            username: 用户名，如果为None则使用当前系统用户名

        Returns:
            tuple: (success, message, data)
                - success: 是否成功
                - message: 响应消息
                - data: 包含文件信息的字典，失败时为None
        """
        try:
            # 验证文件名安全性，防止路径遍历攻击
            if "/" in filename or "\\" in filename or ".." in filename:
                logger.warning(f"检测到非法文件名: {filename}")
                return False, "文件名包含非法字符", None

            log_dir = self._get_user_log_dir(username)
            file_path = log_dir / filename

            # 检查文件是否存在
            if not file_path.exists():
                logger.warning(f"ITC日志文件不存在: {file_path}")
                return False, f"ITC日志文件不存在: {filename}", None

            if not file_path.is_file():
                logger.error(f"路径不是文件: {file_path}")
                return False, f"路径不是文件: {filename}", None

            # 读取文件内容
            async with aiofiles.open(file_path, mode="r", encoding="utf-8", errors="ignore") as f:
                content = await f.read()

            # 获取文件信息
            stat = file_path.stat()
            modified_time = datetime.fromtimestamp(
                stat.st_mtime
            ).strftime("%Y-%m-%d %H:%M:%S")

            # 构建返回数据
            data = {
                "filename": filename,
                "size": stat.st_size,
                "modified_time": modified_time,
                "content": content,
                "encoding": "utf-8"
            }

            logger.info(f"成功读取ITC日志文件: {filename}, 大小: {stat.st_size} 字节")
            return True, f"成功读取ITC日志文件: {filename}", data

        except UnicodeDecodeError as e:
            logger.error(f"文件编码错误: {str(e)}")
            return False, f"文件编码错误，无法读取文件内容", None
        except Exception as e:
            logger.error(f"读取ITC日志文件失败: {str(e)}")
            return False, f"读取ITC日志文件失败: {str(e)}", None


# 创建全局ITC日志服务实例
itc_log_service = ItcLogService()
