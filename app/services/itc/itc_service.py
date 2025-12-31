import httpx
import logging
import glob
import os
import getpass
import shutil
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path
from app.core.config import settings
from app.models.itc.itc_models import (
    NewDeployRequest,
    RunScriptRequest,
    ExecutorRequest,
    SimpleResponse
)

logger = logging.getLogger(__name__)

class ITCService:
    """ITC API 代理服务
AI_FingerPrint_UUID: 20251224-0v1bChBB
"""

    def __init__(self):
        self.base_url = settings.ITC_SERVER_URL
        self.timeout = settings.ITC_REQUEST_TIMEOUT

    async def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """发送 HTTP 请求到 ITC 服务器"""
        url = f"{self.base_url}/{endpoint}"

        logger.info(f"准备发送请求到: {url}")
        logger.info(f"请求数据: {data}")
        logger.info(f"请求超时设置: {self.timeout}秒")

        # 显示 JSON 序列化后的数据（用于调试转义）
        import json
        json_data = json.dumps(data, ensure_ascii=False, indent=2)
        logger.info(f"JSON 序列化后的数据:\n{json_data}")

        try:
            # 禁用代理，避免代理导致的 ReadError
            # trust_env=False 表示不从环境变量读取代理设置
            logger.info(f"正在连接到 ITC 服务器: {url}")
            logger.info(f"代理设置: trust_env=False (已禁用环境代理)")

            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                logger.info(f"HTTP 客户端已创建，开始发送请求...")
                response = await client.post(url, json=data)
                logger.info(f"收到响应 - 状态码: {response.status_code}")
                logger.info(f"响应内容: {response.text}")
                response.raise_for_status()
                return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP 错误: {e.response.status_code} - {e.response.text}")
            return {
                "return_code": str(e.response.status_code),
                "return_info": f"HTTP 错误: {e.response.text}",
                "result": None
            }
        except httpx.TimeoutException:
            logger.error(f"请求超时: {endpoint}")
            return {
                "return_code": "500",
                "return_info": "请求超时，请稍后重试",
                "result": None
            }
        except Exception as e:
            # 记录完整的异常信息，包括类型、消息和堆栈
            import traceback
            error_type = type(e).__name__
            error_msg = str(e) if str(e) else "(空错误消息)"
            error_trace = traceback.format_exc()
            logger.error(f"请求异常: {endpoint}")
            logger.error(f"异常类型: {error_type}")
            logger.error(f"错误消息: {error_msg}")
            logger.error(f"堆栈信息:\n{error_trace}")
            return {
                "return_code": "500",
                "return_info": f"请求异常: {error_type} - {error_msg}",
                "result": None
            }

    def _find_topox_directory(self) -> str:
        """在工作目录中查找 topox 文件所在的目录"""
        work_dir = settings.get_work_directory()

        # 优先使用 test_scripts 目录
        test_scripts_dir = os.path.join(work_dir, "test_scripts")
        if os.path.exists(test_scripts_dir):
            pattern = os.path.join(test_scripts_dir, "*.topox")
            topox_files = glob.glob(pattern)

            if topox_files:
                logger.info(f"找到 test_scripts 目录，包含 topox 文件")
                topox_dir = test_scripts_dir.replace('\\', '/')
                logger.info(f"使用 topox 目录: {topox_dir}")
                return topox_dir

        # 如果 test_scripts 目录不存在或没有 topox 文件，递归查找
        pattern = os.path.join(work_dir, "**/*.topox")
        topox_files = glob.glob(pattern, recursive=True)

        if not topox_files:
            raise ValueError(f"在工作目录 {work_dir} 中未找到任何 .topox 文件")

        # 获取第一个 topox 文件所在的目录
        topox_file = topox_files[0]
        topox_dir = os.path.dirname(topox_file).replace('\\', '/')

        # 检查该目录下是否有唯一的 topox 文件
        dir_pattern = os.path.join(os.path.dirname(topox_file), "*.topox")
        dir_topox_files = glob.glob(dir_pattern)

        if len(dir_topox_files) > 1:
            logger.warning(f"目录 {topox_dir} 中包含多个 topox 文件: {[os.path.basename(f) for f in dir_topox_files]}")
        else:
            logger.info(f"找到唯一的 topox 文件: {os.path.basename(topox_file)}")

        logger.info(f"使用 topox 目录: {topox_dir}")
        return topox_dir

    def _find_default_topox_file(self) -> str:
        """在工作目录中查找默认的 topox 文件的完整路径

        Returns:
            topox 文件的绝对路径
        """
        work_dir = settings.get_work_directory()

        # 优先使用 test_scripts 目录
        test_scripts_dir = os.path.join(work_dir, "test_scripts")
        if os.path.exists(test_scripts_dir):
            pattern = os.path.join(test_scripts_dir, "*.topox")
            topox_files = glob.glob(pattern)

            if topox_files:
                # 返回第一个 topox 文件的完整路径
                topox_file = topox_files[0]
                logger.info(f"找到默认 topox 文件: {topox_file}")
                return topox_file

        # 如果 test_scripts 目录不存在或没有 topox 文件，递归查找
        pattern = os.path.join(work_dir, "**/*.topox")
        topox_files = glob.glob(pattern, recursive=True)

        if not topox_files:
            raise ValueError(f"在工作目录 {work_dir} 中未找到任何 .topox 文件")

        # 返回第一个 topox 文件的完整路径
        topox_file = topox_files[0]
        logger.info(f"找到默认 topox 文件: {topox_file}")
        return topox_file

    def _get_exec_ip_from_aigc_json(self) -> Optional[str]:
        """从 aigc.json 文件中读取 exec_ip

        Returns:
            exec_ip 字符串，如果不存在或读取失败则返回 None
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 检查文件是否存在
            if not os.path.exists(aigc_json_path):
                logger.info(f"aigc.json 文件不存在: {aigc_json_path}")
                return None

            # 读取文件
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    logger.info("aigc.json 文件为空")
                    return None

                config = json.loads(content)

                # 获取 exec_ip 字段
                exec_ip = config.get("exec_ip")

                if exec_ip:
                    logger.info(f"从 aigc.json 读取到 exec_ip: {exec_ip}")
                else:
                    logger.info("aigc.json 中未找到 exec_ip 字段")

                return exec_ip

        except json.JSONDecodeError as e:
            logger.warning(f"解析 aigc.json 失败: {str(e)}")
            return None
        except Exception as e:
            logger.warning(f"读取 aigc.json 时出错: {str(e)}")
            return None

    def _get_device_list_from_aigc_json(self) -> Optional[List[Dict[str, Any]]]:
        """从 aigc.json 文件中读取 device_list

        Returns:
            device_list 列表，如果不存在或读取失败则返回 None
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 检查文件是否存在
            if not os.path.exists(aigc_json_path):
                logger.info(f"aigc.json 文件不存在: {aigc_json_path}")
                return None

            # 读取文件
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    logger.info("aigc.json 文件为空")
                    return None

                config = json.loads(content)

                # 获取 device_list 字段
                device_list = config.get("device_list")

                if device_list and isinstance(device_list, list):
                    logger.info(f"从 aigc.json 读取到 device_list: 共 {len(device_list)} 个设备")
                else:
                    logger.info("aigc.json 中未找到 device_list 字段或字段为空")
                    device_list = None

                return device_list

        except json.JSONDecodeError as e:
            logger.warning(f"解析 aigc.json 失败: {str(e)}")
            return None
        except Exception as e:
            logger.warning(f"读取 aigc.json 时出错: {str(e)}")
            return None

    def _cleanup_aigc_config_after_undeploy(self) -> None:
        """在 undeploy 成功后清理 aigc.json 配置

        将以下字段置空（空字符串）：
        - exec_ip 字段
        - 设备列表中每个设备的 host、port、title 字段

        Returns:
            None
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 检查文件是否存在
            if not os.path.exists(aigc_json_path):
                logger.info(f"aigc.json 文件不存在，无需清理: {aigc_json_path}")
                # 更新部署状态
                settings.set_deploy_status("not_deployed")
                return

            # 读取文件
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    logger.info("aigc.json 文件为空，无需清理")
                    # 更新部署状态
                    settings.set_deploy_status("not_deployed")
                    return

                config = json.loads(content)

            # 记录清理前的内容
            logger.info(f"清理前的 aigc.json 内容:\n{json.dumps(config, indent=2, ensure_ascii=False)}")

            # 1. 将 exec_ip 字段置空
            if "exec_ip" in config:
                config["exec_ip"] = ""
                logger.info("已将 exec_ip 字段置空")

            # 2. 将设备列表中的 host、port、title 字段置空
            if "device_list" in config and isinstance(config["device_list"], list):
                device_count = 0
                for device in config["device_list"]:
                    if isinstance(device, dict):
                        # 置空 host
                        if "host" in device:
                            device["host"] = ""
                        # 置空 port
                        if "port" in device:
                            device["port"] = ""
                        # 置空 title
                        if "title" in device:
                            device["title"] = ""
                        device_count += 1
                logger.info(f"已将 {device_count} 个设备的 host、port、title 字段置空")

            # 写回文件
            with open(aigc_json_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info(f"已更新 aigc.json 文件: {aigc_json_path}")
            logger.info(f"清理后的 aigc.json 内容:\n{json.dumps(config, indent=2, ensure_ascii=False)}")

            # 更新部署状态为 not_deployed
            settings.set_deploy_status("not_deployed")
            logger.info("已更新部署状态为: not_deployed")

        except json.JSONDecodeError as e:
            logger.error(f"解析 aigc.json 失败: {str(e)}")
        except Exception as e:
            logger.error(f"清理 aigc.json 时出错: {str(e)}")

    def _save_aigc_config(
        self,
        topox_file: str,
        version_path: Optional[str],
        device_type: str,
        executorip: Optional[str] = None,
        device_list: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """在用户目录中创建或更新 .aigc_tool/aigc.json 文件

        Args:
            topox_file: topox 文件的本地绝对路径
            version_path: 版本路径（可选）
            device_type: 设备类型
            executorip: 执行机IP（可选）
            device_list: 设备列表（可选）
        """
        work_dir = settings.get_work_directory()

        # 创建 .aigc_tool 目录
        aigc_tool_dir = os.path.join(work_dir, ".aigc_tool")
        os.makedirs(aigc_tool_dir, exist_ok=True)
        logger.info(f"确保 .aigc_tool 目录存在: {aigc_tool_dir}")

        # 转换 version_path：将所有斜杠转换为双反斜杠
        # 输入示例: //10.153.3.125/cilibv9/V9R1/.../version/release
        # 输出示例: \\\\10.153.3.125\\cilibv9\\V9R1\\...\\version\\release
        converted_version_path = ""
        if version_path:
            # 将正斜杠转换为双反斜杠
            converted_version_path = version_path.replace('/', '\\\\')
            logger.info(f"版本路径转换: {version_path} -> {converted_version_path}")

        # 构造 aigc.json 数据
        aigc_config = {
            "topx_file": topox_file,
            "version_path": converted_version_path,
            "device_type": device_type
        }

        # 如果提供了 executorip，添加执行相关配置
        if executorip:
            aigc_config["exec_ip"] = executorip
            aigc_config["username"] = "itc"
            aigc_config["password"] = "auto_123"
            logger.info(f"添加执行机配置: exec_ip={executorip}, username=itc, password=auto_123")

        # 如果提供了 device_list，添加设备列表
        if device_list:
            aigc_config["device_list"] = device_list
            logger.info(f"添加设备列表: 共 {len(device_list)} 个设备")

        # aigc.json 文件路径
        aigc_json_path = os.path.join(aigc_tool_dir, "aigc.json")

        # 写入 JSON 文件
        with open(aigc_json_path, 'w', encoding='utf-8') as f:
            json.dump(aigc_config, f, indent=2, ensure_ascii=False)

        logger.info(f"已创建/更新 aigc.json 文件: {aigc_json_path}")
        logger.info(f"aigc.json 内容:\n{json.dumps(aigc_config, indent=2, ensure_ascii=False)}")

    def _convert_to_unc_path(self, local_dir: str) -> str:
        """将本地目录路径转换为 UNC 网络路径，供 ITC 服务器访问

        参考 aigc_tool.py 的处理方式：
        1. 拷贝文件到服务器的网络共享目录
        2. 返回 UNC 路径格式

        Args:
            local_dir: 本地目录路径

        Returns:
            UNC 网络路径字符串
        """
        try:
            # 获取当前用户名
            username = getpass.getuser()

            # 目标 UNC 目录（参考 aigc_tool.py）
            # 使用固定的网络共享路径
            unc_base_dir = f"\\\\10.144.41.149\\webide\\aigc_tool\\{username}"

            # 创建临时 topox 子目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            unc_topox_dir = os.path.join(unc_base_dir, f"topox_{timestamp}")

            # 转换为正斜杠格式
            unc_topox_dir = unc_topox_dir.replace('\\', '/')

            logger.info(f"将本地目录 {local_dir} 的文件拷贝到网络共享: {unc_topox_dir}")

            # 注意：这里只是返回 UNC 路径
            # 实际的文件拷贝需要在 Windows 环境下执行
            # 如果无法访问网络共享，可以抛出异常或返回本地路径

            return unc_topox_dir

        except Exception as e:
            logger.warning(f"无法转换 UNC 路径，使用本地路径: {str(e)}")
            return local_dir

    def _copy_topox_to_shared_folder(self, topox_file_path: str) -> str:
        """将指定的 topox 文件拷贝到 /opt/coder/statistics/build/aigc_tool/{username}/ 目录

        Args:
            topox_file_path: 本地 topox 文件的完整路径

        Returns:
            拷贝后的目标目录路径
        """
        try:
            username = getpass.getuser()

            # 目标目录：/opt/coder/statistics/build/aigc_tool/{username}/
            target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"
            os.makedirs(target_dir, exist_ok=True)

            logger.info(f"准备拷贝 topox 文件到: {target_dir}")
            logger.info(f"源文件: {topox_file_path}")

            # 检查源文件是否存在
            if not os.path.exists(topox_file_path):
                logger.error(f"topox 文件不存在: {topox_file_path}")
                return os.path.dirname(topox_file_path)

            # 获取文件名
            filename = os.path.basename(topox_file_path)
            target_file_path = os.path.join(target_dir, filename)

            # 拷贝文件到目标目录（保留源文件，额外拷贝一份）
            shutil.copy2(topox_file_path, target_file_path)

            # 设置文件和目录权限为 777（其他用户可读可写）
            try:
                os.chmod(target_file_path, 0o777)
                os.chmod(target_dir, 0o777)
            except PermissionError:
                logger.warning(f"权限不足，无法设置文件权限 {target_file_path}，但文件已成功拷贝")

            logger.info(f"已拷贝 {filename} 到 {target_dir}")
            logger.info(f"目标文件: {target_file_path}")

            # 返回目标目录路径
            return target_dir

        except Exception as e:
            logger.error(f"拷贝 topox 文件失败: {str(e)}")
            # 如果拷贝失败，返回源文件所在目录
            return os.path.dirname(topox_file_path)

    def _convert_terminalinfo_to_device_list(self, executorip: str, terminalinfo: Dict[str, Any]) -> List[Dict[str, Any]]:
        """将 terminalinfo 转换为设备列表格式（类似 /api/v1/physical-devices）

        新增：为每个设备添加 title 属性
        """
        device_list = []
        local_ip = settings.get_local_ip()

        for device_name, connection_info in terminalinfo.items():
            if isinstance(connection_info, list) and len(connection_info) >= 3:
                # 基本属性
                device = {
                    "name": device_name,
                    "host": connection_info[0],  # IP地址
                    "port": int(connection_info[1]),  # 端口号
                    "type": connection_info[2],  # 协议类型 (telnet/ssh)
                    "executorip": executorip,  # 执行机IP
                    "userip": local_ip  # 本机IP
                }

                # 添加 title 属性（如果有第4个元素）
                if len(connection_info) >= 4:
                    device["title"] = connection_info[3]
                else:
                    # 如果没有 title，使用设备名作为默认值
                    device["title"] = device_name

                device_list.append(device)

        logger.info(f"转换后的设备列表: {device_list}")
        logger.info(f"设备列表包含 title 属性: {all('title' in device for device in device_list)}")
        return device_list

    async def _test_itc_connection(self) -> bool:
        """测试 ITC 服务器连接是否正常"""
        try:
            import socket
            from urllib.parse import urlparse

            parsed_url = urlparse(self.base_url)
            host = parsed_url.hostname
            port = parsed_url.port or 80

            logger.info(f"测试 ITC 服务器连接: {host}:{port}")

            # 尝试 TCP 连接
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                logger.info(f"ITC 服务器连接正常: {host}:{port}")
                return True
            else:
                logger.error(f"无法连接到 ITC 服务器: {host}:{port} - 错误码: {result}")
                return False

        except Exception as e:
            logger.error(f"ITC 服务器连接测试失败: {str(e)}")
            return False

    def _execute_deploy_background(
        self,
        request: NewDeployRequest,
        default_topox_file: str,
        unc_topofile: str
    ) -> None:
        """后台任务：执行实际的部署逻辑

        Args:
            request: 部署请求对象
            default_topox_file: 默认 topox 文件路径
            unc_topofile: UNC 网络路径
        """
        import asyncio

        async def _deploy_task():
            try:
                logger.info("=" * 80)
                logger.info("后台部署任务开始执行")
                logger.info("=" * 80)

                # 先测试 ITC 服务器连接
                logger.info("开始测试 ITC 服务器连接...")
                connection_ok = await self._test_itc_connection()
                if not connection_ok:
                    logger.error("ITC 服务器连接失败，终止部署任务")
                    settings.set_deploy_status("failed")
                    settings.set_deploy_error_message("无法连接到 ITC 服务器，请检查网络和服务器状态")
                    return

                logger.info("ITC 服务器连接正常，继续部署流程")

                # 构建请求数据
                data = {"topofile": unc_topofile}

                # 获取版本路径
                version_path = request.get_version_path()
                if version_path:
                    data["versionpath"] = version_path
                    logger.info(f"版本路径: {version_path}")

                # 只在有值时才添加 devicetype
                if request.devicetype:
                    data["devicetype"] = request.devicetype

                logger.info(f"请求数据: {data}")
                logger.info(f"请求 URL: {self.base_url}/newdeploy")

                # 验证必要参数
                if not data.get("topofile"):
                    logger.error("错误: topofile 参数为空")
                    settings.set_deploy_status("failed")
                    settings.set_deploy_error_message("topofile 参数不能为空")
                    return

                # 检查 aigc.json 中是否存在 exec_ip，如果存在则先调用 undeploy
                existing_exec_ip = self._get_exec_ip_from_aigc_json()
                if existing_exec_ip:
                    logger.info("=" * 80)
                    logger.info(f"检测到已存在的部署 (exec_ip={existing_exec_ip})")
                    logger.info("正在执行 undeploy 以释放旧环境...")
                    logger.info("=" * 80)

                    # 构造 undeploy 请求
                    undeploy_data = {"executorip": existing_exec_ip}
                    undeploy_result = await self._make_request("undeploy", undeploy_data)

                    logger.info(f"Undeploy 响应: {undeploy_result}")

                    if undeploy_result.get("return_code") == "200":
                        logger.info("旧环境释放成功 (undeploy 成功)")
                    else:
                        error_msg = str(undeploy_result.get('return_info', '未知错误'))
                        logger.warning(f"Undeploy 返回非成功状态: {error_msg}")
                        logger.warning("继续执行 deploy，可能会遇到资源冲突")

                    logger.info("=" * 80)
                else:
                    logger.info("未检测到已存在的部署，直接执行 deploy")

                # 发送部署请求
                logger.info("开始发送部署请求到 ITC 服务器...")
                result = await self._make_request("newdeploy", data)

                logger.info(f"部署环境响应: {result}")

                # 处理部署结果
                if result.get("return_code") == "200":
                    return_info = result.get("return_info", {})
                    if isinstance(return_info, dict):
                        executorip = return_info.get("executorip")
                        terminalinfo = return_info.get("terminalinfo")

                        if executorip and terminalinfo:
                            # 转换 terminalinfo 为设备列表格式
                            device_list = self._convert_terminalinfo_to_device_list(executorip, terminalinfo)
                            logger.info(f"设备列表转换完成，共 {len(device_list)} 个设备")

                            # 保存配置到 .aigc_tool/aigc.json（包含 executorip 和 device_list）
                            try:
                                self._save_aigc_config(
                                    topox_file=default_topox_file,
                                    version_path=version_path,
                                    device_type=request.devicetype or "simware9cen",
                                    executorip=executorip,
                                    device_list=device_list
                                )
                                logger.info(f"已保存 aigc.json 配置文件，包含执行机IP和设备列表")
                            except Exception as e:
                                logger.warning(f"保存 aigc.json 配置文件失败: {str(e)}")
                        else:
                            # 只保存基本信息（没有设备列表）
                            try:
                                self._save_aigc_config(
                                    topox_file=default_topox_file,
                                    version_path=version_path,
                                    device_type=request.devicetype or "simware9cen",
                                    executorip=executorip
                                )
                                logger.info(f"已保存 aigc.json 配置文件（不含设备列表）")
                            except Exception as e:
                                logger.warning(f"保存 aigc.json 配置文件失败: {str(e)}")

                    # 部署成功，更新状态
                    settings.set_deploy_status("deployed")
                    settings.set_deploy_error_message(None)
                    logger.info("=" * 80)
                    logger.info("后台部署任务执行成功")
                    logger.info("=" * 80)
                else:
                    # 部署失败
                    error_msg = str(result.get('return_info', '未知错误'))
                    logger.error(f"部署失败 - return_code: {result.get('return_code')}")
                    logger.error(f"错误信息: {error_msg}")

                    settings.set_deploy_status("failed")
                    settings.set_deploy_error_message(error_msg)
                    logger.info("=" * 80)
                    logger.info("后台部署任务执行失败")
                    logger.info("=" * 80)

            except Exception as e:
                logger.error(f"后台部署任务异常: {str(e)}", exc_info=True)
                settings.set_deploy_status("failed")
                settings.set_deploy_error_message(f"部署异常: {str(e)}")
                logger.info("=" * 80)
                logger.info("后台部署任务异常结束")
                logger.info("=" * 80)

        # 在新的事件循环中运行异步任务
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            logger.info("后台任务事件循环已创建")
            loop.run_until_complete(_deploy_task())
            logger.info("后台任务事件循环已关闭")
        except Exception as e:
            logger.error(f"后台任务事件循环异常: {str(e)}", exc_info=True)
            settings.set_deploy_status("failed")
            settings.set_deploy_error_message(f"后台任务异常: {str(e)}")
        finally:
            try:
                loop.close()
            except Exception as e:
                logger.warning(f"关闭事件循环时出错: {str(e)}")

    async def deploy_environment(self, request: NewDeployRequest) -> Dict[str, Any]:
        """部署测试环境 - 立即返回，后台异步执行

        Args:
            request: 部署请求对象

        Returns:
            立即返回成功响应
        """
        try:
            logger.info("收到部署请求，准备启动后台部署任务")

            # 在工作目录中查找默认的 topox 文件
            default_topox_file = self._find_default_topox_file()
            local_topox_dir = os.path.dirname(default_topox_file)

            # 拷贝默认 topox 文件到指定目录（额外备份，不影响本地文件）
            shared_topox_dir = self._copy_topox_to_shared_folder(default_topox_file)
            logger.info(f"已拷贝 topox 文件到共享目录: {shared_topox_dir}")

            # 使用 UNC 网络路径作为 topofile
            username = getpass.getuser()
            unc_topofile = f"\\\\10.144.41.149\\webide\\aigc_tool\\{username}"
            # 转换为正斜杠格式
            unc_topofile = unc_topofile.replace('\\', '/')
            logger.info(f"使用 UNC 网络路径: {unc_topofile}")

            # 设置部署状态为 "deploying"
            settings.set_deploy_status("deploying")
            settings.set_deploy_error_message(None)

            logger.info("部署任务已提交到后台执行，将立即返回成功响应")

            # 立即返回成功
            return {
                "return_code": "200",
                "return_info": "部署任务已提交，正在后台执行",
                "result": None
            }

        except Exception as e:
            logger.error(f"提交部署任务失败: {str(e)}", exc_info=True)
            return {
                "return_code": "500",
                "return_info": f"提交部署任务失败: {str(e)}",
                "result": None
            }

    def start_background_deploy(
        self,
        request: NewDeployRequest,
        default_topox_file: str,
        unc_topofile: str
    ) -> None:
        """启动后台部署任务的同步方法

        Args:
            request: 部署请求对象
            default_topox_file: 默认 topox 文件路径
            unc_topofile: UNC 网络路径
        """
        import threading

        # 在新线程中执行后台任务
        thread = threading.Thread(
            target=self._execute_deploy_background,
            args=(request, default_topox_file, unc_topofile),
            daemon=True
        )
        thread.start()
        logger.info(f"后台部署线程已启动: {thread.name}")

    def _copy_python_scripts_to_target_dir(self) -> str:
        """将工作目录中的 Python 脚本拷贝到目标目录并授权

        拷贝内容：
        - test 开头的测试脚本（test_*.py）
        - conftest.py

        目标目录：/opt/coder/statistics/build/aigc_tool/{username}/

        Returns:
            str: 目标目录路径
        """
        try:
            username = getpass.getuser()
            target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"

            # 创建目标目录
            os.makedirs(target_dir, exist_ok=True)
            logger.info(f"目标目录已确认: {target_dir}")

            # 获取工作目录
            work_dir = settings.get_work_directory()
            logger.info(f"工作目录: {work_dir}")

            # 查找并拷贝 test_*.py 脚本
            import glob
            test_scripts_pattern = os.path.join(work_dir, "test_*.py")
            test_scripts = glob.glob(test_scripts_pattern)

            copied_count = 0

            # 拷贝 test 开头的脚本
            for script_path in test_scripts:
                if os.path.isfile(script_path):
                    script_name = os.path.basename(script_path)
                    target_path = os.path.join(target_dir, script_name)

                    # 拷贝文件
                    shutil.copy2(script_path, target_path)
                    # 设置权限为可读写（777）
                    os.chmod(target_path, 0o777)

                    logger.info(f"已拷贝测试脚本: {script_name} -> {target_path}")
                    copied_count += 1

            # 查找并拷贝 conftest.py
            conftest_pattern = os.path.join(work_dir, "conftest.py")
            conftest_files = glob.glob(conftest_pattern)

            for conftest_path in conftest_files:
                if os.path.isfile(conftest_path):
                    target_path = os.path.join(target_dir, "conftest.py")

                    # 拷贝文件
                    shutil.copy2(conftest_path, target_path)
                    # 设置权限为可读写（777）
                    os.chmod(target_path, 0o777)

                    logger.info(f"已拷贝 conftest.py -> {target_path}")
                    copied_count += 1

            # 设置目标目录权限为 777
            os.chmod(target_dir, 0o777)

            logger.info(f"脚本拷贝完成，共拷贝 {copied_count} 个文件到 {target_dir}")

            return target_dir

        except Exception as e:
            logger.error(f"拷贝 Python 脚本失败: {str(e)}", exc_info=True)
            raise

    async def run_script(self, request: RunScriptRequest) -> Dict[str, Any]:
        """运行测试脚本"""
        logger.info(f"运行脚本请求 - scriptspath: {request.scriptspath}, executorip: {request.executorip}")

        # 在调用 ITC run 前，拷贝工作目录中的 Python 脚本到目标目录
        try:
            logger.info("开始拷贝 Python 脚本到目标目录...")
            target_dir = self._copy_python_scripts_to_target_dir()
            logger.info(f"Python 脚本已成功拷贝到: {target_dir}")
        except Exception as e:
            logger.warning(f"拷贝 Python 脚本失败，但继续执行: {str(e)}")

        data = {
            "scriptspath": request.scriptspath,
            "executorip": request.executorip
        }

        logger.info(f"准备调用 ITC run 接口...")
        result = await self._make_request("run", data)

        logger.info(f"运行脚本响应: {result}")

        # 直接返回字典，不使用 Pydantic 模型验证
        return result

    async def undeploy_environment(self, request: ExecutorRequest) -> SimpleResponse:
        """释放测试环境"""
        data = {
            "executorip": request.executorip
        }

        logger.info(f"释放环境请求: {data}")
        result = await self._make_request("undeploy", data)

        # 如果 undeploy 成功，清理 aigc.json 配置
        if result.get("return_code") == "200":
            logger.info("undeploy 成功，开始清理 aigc.json 配置")
            self._cleanup_aigc_config_after_undeploy()
            logger.info("aigc.json 配置清理完成")
        else:
            logger.warning(f"undeploy 未成功 (return_code: {result.get('return_code')})，跳过配置清理")

        return SimpleResponse(**result)

    async def restore_configuration(self, request: ExecutorRequest) -> SimpleResponse:
        """配置回滚"""
        data = {
            "executorip": request.executorip
        }

        logger.info(f"配置回滚请求: {data}")
        result = await self._make_request("restoreconfiguration", data)

        return SimpleResponse(**result)

    async def suspend_script(self, request: ExecutorRequest) -> SimpleResponse:
        """暂停脚本执行"""
        data = {
            "executorip": request.executorip
        }

        logger.info(f"暂停脚本请求: {data}")
        result = await self._make_request("suspend", data)

        return SimpleResponse(**result)

    async def resume_script(self, request: ExecutorRequest) -> SimpleResponse:
        """恢复脚本执行"""
        data = {
            "executorip": request.executorip
        }

        logger.info(f"恢复脚本请求: {data}")
        result = await self._make_request("resume", data)

        return SimpleResponse(**result)

# 创建 ITC 服务实例
itc_service = ITCService()