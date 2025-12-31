import os
from pathlib import Path
from typing import Optional, Dict, Any, List

class Settings:
    """应用配置类
    """

    # 项目基础设置
    PROJECT_NAME: str = "Script Generator API"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "FastAPI backend for script generation with topo editor and Claude Code integration"

    # 服务器设置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # 全局静态变量 - 项目工作目录
    # 这个目录会根据运行环境动态调整
    _WORK_DIRECTORY: Optional[Path] = None

    @classmethod
    def get_work_directory(cls) -> str:
        """获取项目工作目录（返回使用正斜杠的字符串路径）"""
        if cls._WORK_DIRECTORY is None:
            # 动态获取当前用户名，构建工作目录路径
            import getpass
            username = getpass.getuser()
            cls._WORK_DIRECTORY = Path(f"/home/{username}/project")
        # 将路径转换为使用正斜杠的字符串
        return str(cls._WORK_DIRECTORY).replace('\\', '/')

    @classmethod
    def set_work_directory(cls, path: Path) -> None:
        """设置项目工作目录"""
        cls._WORK_DIRECTORY = path

    @classmethod
    def get_logs_directory(cls) -> str:
        """获取日志目录（返回使用正斜杠的字符串路径）"""
        work_dir = Path(cls.get_work_directory())
        return str(work_dir / "logs").replace('\\', '/')

    @classmethod
    def get_topox_directory(cls) -> str:
        """获取topox文件目录（返回使用正斜杠的字符串路径）"""
        work_dir = Path(cls.get_work_directory())
        return str(work_dir).replace('\\', '/')

    # 文件操作限制
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_EXTENSIONS: set = {".txt", ".py", ".js", ".json", ".xml", ".topox", ".md", ".yml", ".yaml"}

    # Claude Code 相关设置
    CLAUDE_CODE_EXECUTABLE: str = "claude"
    CLAUDE_CODE_TIMEOUT: int = 600  # 10分钟超时

    # 日志设置
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"
    LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10MB
    LOG_BACKUP_COUNT: int = 5

    # ITC 相关设置
    ITC_SERVER_URL: str = "http://10.111.8.68:8000/aigc"
    ITC_REQUEST_TIMEOUT: int = 600  # 10分钟超时（部署可能需要较长时间）

    # Script command extract 相关设置
    @classmethod
    def get_script_command_log_path(cls) -> str:
        """获取脚本命令日志路径（使用动态用户名）"""
        import getpass
        username = getpass.getuser()
        return f"/opt/coder/statistics/build/aigc_tool/{username}/log"

    # Deploy 日志文件路径
    DEPLOY_LOG_PATH: str = r"D:\Code\green\AIGC\green_test_script_install\ScriptGenerateDev\static\deploy_log.jsonl"

    @classmethod
    def get_default_topofile_path(cls) -> str:
        """获取默认 topo 文件路径（返回使用正斜杠的字符串路径）"""
        work_dir = Path(cls.get_work_directory())
        return str(work_dir / "topo_files").replace('\\', '/')

    # 全局静态变量 - 部署信息存储
    _DEPLOY_DEVICE_LIST: Optional[List[Dict[str, Any]]] = None
    _DEPLOY_STATUS: str = "not_deployed"  # not_deployed, deploying, deployed, failed
    _DEPLOY_ERROR_MESSAGE: Optional[str] = None  # 部署失败的错误信息

    @classmethod
    def get_local_ip(cls) -> str:
        """获取本机IP地址"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except Exception:
            return "127.0.0.1"

    @classmethod
    def get_deploy_executor_ip(cls) -> Optional[str]:
        """从 aigc.json 文件中获取第一个 executorip"""
        try:
            from app.services.itc.itc_service import itc_service
            return itc_service._get_exec_ip_from_aigc_json()
        except Exception as e:
            logger.warning(f"从 aigc.json 读取 executorip 失败: {str(e)}")
            return None

    @classmethod
    def get_deploy_status(cls) -> str:
        """获取部署状态"""
        return cls._DEPLOY_STATUS

    @classmethod
    def get_deploy_device_list(cls) -> Optional[List[Dict[str, Any]]]:
        """从 aigc.json 文件中获取部署的设备列表"""
        try:
            from app.services.itc.itc_service import itc_service
            return itc_service._get_device_list_from_aigc_json()
        except Exception as e:
            logger.warning(f"从 aigc.json 读取 device_list 失败: {str(e)}")
            return None

    @classmethod
    def set_deploy_status(cls, status: str) -> None:
        """设置部署状态"""
        cls._DEPLOY_STATUS = status

    @classmethod
    def set_deploy_device_list(cls, device_list: List[Dict[str, Any]]) -> None:
        """设置部署的设备列表"""
        cls._DEPLOY_DEVICE_LIST = device_list

    @classmethod
    def clear_deploy_info(cls) -> None:
        """清空部署信息"""
        cls._DEPLOY_DEVICE_LIST = None
        cls._DEPLOY_STATUS = "not_deployed"
        cls._DEPLOY_ERROR_MESSAGE = None

    @classmethod
    def get_deploy_error_message(cls) -> Optional[str]:
        """获取部署失败的错误信息"""
        return cls._DEPLOY_ERROR_MESSAGE

    @classmethod
    def set_deploy_error_message(cls, error_message: str) -> None:
        """设置部署失败的错误信息"""
        cls._DEPLOY_ERROR_MESSAGE = error_message

    @classmethod
    def initialize_deploy_status_from_aigc_json(cls) -> None:
        """
        启动时从 aigc.json 文件检查并初始化部署状态

        如果 aigc.json 存在且包含设备列表，并且设备有 host 属性，
        则设置状态为 "deployed"，否则设置为 "not_deployed"

        Returns:
            None
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            import json
            from pathlib import Path

            work_dir = Path(cls.get_work_directory())
            aigc_json_path = work_dir / ".aigc_tool" / "aigc.json"

            # 检查 aigc.json 是否存在
            if not aigc_json_path.exists():
                logger.info(f"aigc.json 不存在: {aigc_json_path}")
                logger.info("设置部署状态为: not_deployed")
                cls._DEPLOY_STATUS = "not_deployed"
                return

            # 读取 aigc.json
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                aigc_config = json.load(f)

            logger.info(f"已找到 aigc.json: {aigc_json_path}")

            # 检查是否有 device_list
            if 'device_list' not in aigc_config:
                logger.info("aigc.json 中没有 device_list")
                logger.info("设置部署状态为: not_deployed")
                cls._DEPLOY_STATUS = "not_deployed"
                return

            device_list = aigc_config['device_list']

            if not device_list or not isinstance(device_list, list):
                logger.info("device_list 为空或格式不正确")
                logger.info("设置部署状态为: not_deployed")
                cls._DEPLOY_STATUS = "not_deployed"
                return

            logger.info(f"device_list 包含 {len(device_list)} 个设备")

            # 检查设备是否有 host 属性
            has_valid_devices = False
            for device in device_list:
                if isinstance(device, dict) and device.get('host'):
                    has_valid_devices = True
                    break

            if has_valid_devices:
                logger.info("设备列表包含有效的 host 属性")
                logger.info("设置部署状态为: deployed")
                cls._DEPLOY_STATUS = "deployed"

                # 同时设置设备列表到缓存
                cls._DEPLOY_DEVICE_LIST = device_list
            else:
                logger.info("设备列表中没有有效的 host 属性")
                logger.info("设置部署状态为: not_deployed")
                cls._DEPLOY_STATUS = "not_deployed"

        except json.JSONDecodeError as e:
            logger.warning(f"解析 aigc.json 失败: {str(e)}")
            logger.info("设置部署状态为: not_deployed")
            cls._DEPLOY_STATUS = "not_deployed"
        except Exception as e:
            logger.warning(f"检查 aigc.json 时出错: {str(e)}")
            logger.info("设置部署状态为: not_deployed")
            cls._DEPLOY_STATUS = "not_deployed"

    # IP 到域名的映射配置
    IP_DOMAIN_MAPPING: Dict[str, str] = {
    }

    @classmethod
    def get_domain_by_ip(cls, ip: str) -> Optional[str]:
        """根据 IP 获取对应的域名"""
        return cls.IP_DOMAIN_MAPPING.get(ip)

    @classmethod
    def convert_ip_to_domain(cls, device_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将设备列表中的 IP 地址转换为域名

        Args:
            device_list: 设备列表

        Returns:
            转换后的设备列表（IP 已替换为域名）
        """
        converted_list = []
        for device in device_list:
            new_device = device.copy()
            host = device.get("host", "")

            # 如果 host 在映射表中，替换为域名
            if host and host in cls.IP_DOMAIN_MAPPING:
                new_device["host"] = cls.IP_DOMAIN_MAPPING[host]

            converted_list.append(new_device)

        return converted_list

settings = Settings()
