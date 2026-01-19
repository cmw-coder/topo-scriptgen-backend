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

    def _save_itc_run_result(self, run_result: Dict[str, Any]) -> None:
        """保存 ITC run 接口返回的结果到 aigc.json

        将 ITC run 接口返回的结果保存到 aigc.json 的 itc_run_result 字段中。

        Args:
            run_result: ITC run 接口返回的结果字典
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 创建 .aigc_tool 目录（如果不存在）
            aigc_tool_dir = os.path.join(work_dir, ".aigc_tool")
            os.makedirs(aigc_tool_dir, exist_ok=True)

            # 读取现有的 aigc.json（如果存在）
            existing_config = None
            if os.path.exists(aigc_json_path):
                try:
                    with open(aigc_json_path, 'r', encoding='utf-8') as f:
                        existing_config = json.load(f)
                    logger.info(f"读取到现有的 aigc.json 配置")
                except Exception as e:
                    logger.warning(f"读取现有 aigc.json 失败: {str(e)}，将创建新文件")

            # 构造或更新 aigc.json 数据
            if existing_config is None:
                # 创建新配置
                aigc_config = {}
            else:
                # 更新现有配置
                aigc_config = existing_config.copy()

            # 保存 ITC run 结果
            aigc_config["itc_run_result"] = run_result
            logger.info(f"已保存 ITC run 结果到 aigc.json")

            # 写入 JSON 文件
            with open(aigc_json_path, 'w', encoding='utf-8') as f:
                json.dump(aigc_config, f, indent=2, ensure_ascii=False)

            logger.info(f"已更新 aigc.json 文件: {aigc_json_path}")

        except Exception as e:
            logger.error(f"保存 ITC run 结果到 aigc.json 失败: {str(e)}")

    def _clear_itc_run_result(self) -> None:
        """清除 aigc.json 中的 itc_run_result 字段

        在调用 ITC run 接口前调用，确保查询接口能正确返回"执行中"状态。
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 检查文件是否存在
            if not os.path.exists(aigc_json_path):
                logger.info(f"aigc.json 文件不存在，无需清除: {aigc_json_path}")
                return

            # 读取现有的 aigc.json
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            # 移除 itc_run_result 字段
            if "itc_run_result" in config:
                del config["itc_run_result"]
                logger.info("已清除 aigc.json 中的 itc_run_result 字段")

                # 写回文件
                with open(aigc_json_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
            else:
                logger.info("aigc.json 中没有 itc_run_result 字段，无需清除")

        except json.JSONDecodeError as e:
            logger.warning(f"解析 aigc.json 失败: {str(e)}")
        except Exception as e:
            logger.warning(f"清除 itc_run_result 失败: {str(e)}")

    def _get_itc_run_result(self) -> Dict[str, Any]:
        """从 aigc.json 读取 ITC run 结果

        Returns:
            包含 status 和 message 的字典
            - status: "ok" 或 "error"
            - message: 结果消息或错误信息
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 检查文件是否存在
            if not os.path.exists(aigc_json_path):
                logger.info(f"aigc.json 文件不存在: {aigc_json_path}")
                return {
                    "status": "ok",
                    "message": "itc 执行中请稍后"
                }

            # 读取文件
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    logger.info("aigc.json 文件为空")
                    return {
                        "status": "ok",
                        "message": "itc 执行中请稍后"
                    }

                config = json.loads(content)

            # 获取 itc_run_result 字段
            itc_run_result = config.get("itc_run_result")

            if not itc_run_result:
                logger.info("aigc.json 中未找到 itc_run_result 字段")
                return {
                    "status": "ok",
                    "message": "itc 执行中请稍后"
                }

            # 根据 return_code 判断 status
            return_code = itc_run_result.get("return_code")
            return_info = itc_run_result.get("return_info", "")

            if return_code == "200":
                return {
                    "status": "ok",
                    "message": str(return_info) if return_info else "执行成功"
                }
            else:
                # 接口异常返回 error
                error_msg = str(return_info) if return_info else "未知错误"
                return {
                    "status": "error",
                    "message": error_msg
                }

        except json.JSONDecodeError as e:
            logger.warning(f"解析 aigc.json 失败: {str(e)}")
            return {
                "status": "ok",
                "message": "itc 执行中请稍后"
            }
        except Exception as e:
            logger.warning(f"读取 aigc.json 时出错: {str(e)}")
            return {
                "status": "ok",
                "message": "itc 执行中请稍后"
            }

    def _cleanup_aigc_config_after_deploy_failure(self) -> None:
        """在 deploy 失败后清理 aigc.json 配置

        将以下字段置空（空字符串）：
        - exec_ip 字段
        - 设备列表中每个设备的 host、port、type、title 字段

        Returns:
            None
        """
        try:
            work_dir = settings.get_work_directory()
            aigc_json_path = os.path.join(work_dir, ".aigc_tool", "aigc.json")

            # 检查文件是否存在
            if not os.path.exists(aigc_json_path):
                logger.info(f"aigc.json 文件不存在，无需清理: {aigc_json_path}")
                return

            # 读取文件
            with open(aigc_json_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    logger.info("aigc.json 文件为空，无需清理")
                    return

                config = json.loads(content)

            # 记录清理前的内容
            logger.info(f"清理前的 aigc.json 内容:\n{json.dumps(config, indent=2, ensure_ascii=False)}")

            # 1. 将 exec_ip 字段置空
            if "exec_ip" in config:
                config["exec_ip"] = ""
                logger.info("已将 exec_ip 字段置空")

            # 2. 将设备列表中的 host、port、type、title 字段置空
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
                        # 置空 type
                        if "type" in device:
                            device["type"] = ""
                        # 置空 title
                        if "title" in device:
                            device["title"] = ""
                        device_count += 1
                logger.info(f"已将 {device_count} 个设备的 host、port、type、title 字段置空")

            # 写回文件
            with open(aigc_json_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

            logger.info(f"已更新 aigc.json 文件: {aigc_json_path}")
            logger.info(f"清理后的 aigc.json 内容:\n{json.dumps(config, indent=2, ensure_ascii=False)}")

        except json.JSONDecodeError as e:
            logger.error(f"解析 aigc.json 失败: {str(e)}")
        except Exception as e:
            logger.error(f"清理 aigc.json 时出错: {str(e)}")

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

        如果 aigc.json 已存在且包含 device_list，则更新以下属性：
        - exec_ip（全局执行机IP）
        - 设备的 executorip、host、port、type、title 属性

        不修改设备的其他属性（如 name、userip 等其他自定义字段）

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

        # aigc.json 文件路径
        aigc_json_path = os.path.join(aigc_tool_dir, "aigc.json")

        # 转换 version_path：将所有斜杠转换为双反斜杠
        # 输入示例: //10.153.3.125/cilibv9/V9R1/.../version/release
        # 输出示例: \\\\10.153.3.125\\cilibv9\\V9R1\\...\\version\\release
        converted_version_path = ""
        if version_path:
            # 将正斜杠转换为双反斜杠
            converted_version_path = version_path.replace('/', '\\\\')
            logger.info(f"版本路径转换: {version_path} -> {converted_version_path}")

        # 读取现有的 aigc.json（如果存在）
        existing_config = None
        if os.path.exists(aigc_json_path):
            try:
                with open(aigc_json_path, 'r', encoding='utf-8') as f:
                    existing_config = json.load(f)
                logger.info(f"读取到现有的 aigc.json 配置")
            except Exception as e:
                logger.warning(f"读取现有 aigc.json 失败: {str(e)}，将创建新文件")

        # 构造或更新 aigc.json 数据
        if existing_config is None:
            # 创建新配置
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

            # 如果提供了 device_list，直接添加设备列表
            if device_list:
                aigc_config["device_list"] = device_list
                logger.info(f"添加设备列表: 共 {len(device_list)} 个设备")

        else:
            # 更新现有配置
            aigc_config = existing_config.copy()

            # 更新基本字段
            aigc_config["topx_file"] = topox_file
            aigc_config["version_path"] = converted_version_path
            aigc_config["device_type"] = device_type

            # 更新执行机配置
            if executorip:
                aigc_config["exec_ip"] = executorip
                aigc_config["username"] = "itc"
                aigc_config["password"] = "auto_123"
                logger.info(f"更新执行机配置: exec_ip={executorip}, username=itc, password=auto_123")

            # 更新设备列表：只更新 executorip、host、port、type、title 属性
            if device_list:
                if "device_list" not in aigc_config:
                    # 如果原来没有设备列表，直接添加
                    aigc_config["device_list"] = device_list
                    logger.info(f"添加新设备列表: 共 {len(device_list)} 个设备")
                else:
                    # 如果已有设备列表，按设备名称匹配并只更新特定属性
                    existing_device_list = aigc_config["device_list"]

                    # 创建设备名称到现有设备的映射
                    existing_devices_map = {}
                    for existing_device in existing_device_list:
                        if isinstance(existing_device, dict) and "name" in existing_device:
                            device_name = existing_device["name"]
                            existing_devices_map[device_name] = existing_device

                    # 更新或添加设备
                    updated_device_list = []
                    for new_device in device_list:
                        if not isinstance(new_device, dict):
                            continue

                        device_name = new_device.get("name")
                        if not device_name:
                            # 如果没有名称，直接添加新设备
                            updated_device_list.append(new_device)
                            logger.info(f"添加无名称设备: {new_device}")
                            continue

                        if device_name in existing_devices_map:
                            # 设备已存在，只更新 executorip、host、port、type、title 属性
                            existing_device = existing_devices_map[device_name].copy()

                            # 更新 executorip
                            if "executorip" in new_device:
                                existing_device["executorip"] = new_device["executorip"]

                            # 更新 host
                            if "host" in new_device:
                                existing_device["host"] = new_device["host"]

                            # 更新 port
                            if "port" in new_device:
                                existing_device["port"] = new_device["port"]

                            # 更新 type（telnet/ssh）
                            if "type" in new_device:
                                existing_device["type"] = new_device["type"]
                            # 更新 title
                            if "title" in new_device:
                                existing_device["title"] = new_device["title"]

                            # 更新 userip（如果有的话）
                            if "userip" in new_device:
                                existing_device["userip"] = new_device["userip"]

                            updated_device_list.append(existing_device)
                            logger.info(f"更新设备 {device_name} 的 executorip/host/port/type/title 属性")
                        else:
                            # 新设备，直接添加
                            updated_device_list.append(new_device)
                            logger.info(f"添加新设备: {device_name}")

                    # 保留原有列表中不存在于新列表的设备
                    existing_device_names = {d.get("name") for d in device_list if isinstance(d, dict) and "name" in d}
                    for existing_device in existing_device_list:
                        if isinstance(existing_device, dict) and "name" in existing_device:
                            if existing_device["name"] not in existing_device_names:
                                updated_device_list.append(existing_device)
                                logger.info(f"保留原有设备: {existing_device['name']}")

                    aigc_config["device_list"] = updated_device_list
                    logger.info(f"更新设备列表完成: 共 {len(updated_device_list)} 个设备")

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

            # 设置 topox 文件权限（权限不足时记录警告）
            try:
                os.chmod(target_file_path, 0o777)
            except PermissionError:
                logger.warning(f"⚠️ 权限不足，无法设置 topox 文件权限: {target_file_path}，但文件已成功拷贝")

            # 不再修改目录权限
            # try:
            #     os.chmod(target_dir, 0o777)
            # except PermissionError:
            #     pass

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
                settings.set_deploy_status("deploying")
                settings.set_deploy_error_message(None)
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

                    # ========== 统计：记录部署完成时间 ==========
                    try:
                        from app.services.metrics_service import metrics_service
                        from datetime import datetime
                        metrics_service.record_deploy_complete(datetime.now())
                    except Exception as metrics_error:
                        logger.warning(f"记录部署完成时间失败: {metrics_error}")
                    # ===========================================

                    logger.info("=" * 80)
                    logger.info("后台部署任务执行成功")
                    logger.info("=" * 80)
                else:
                    # 部署失败
                    error_msg = str(result.get('return_info', '未知错误'))
                    logger.error(f"部署失败 - return_code: {result.get('return_code')}")
                    logger.error(f"错误信息: {error_msg}")

                    # 清理 aigc.json 配置
                    logger.info("=" * 80)
                    logger.info("部署失败，开始清理 aigc.json 配置")
                    logger.info("=" * 80)
                    self._cleanup_aigc_config_after_deploy_failure()
                    logger.info("=" * 80)
                    logger.info("aigc.json 配置清理完成")
                    logger.info("=" * 80)

                    settings.set_deploy_status("failed")
                    settings.set_deploy_error_message(error_msg)
                    logger.info("=" * 80)
                    logger.info("后台部署任务执行失败")
                    logger.info("=" * 80)

            except Exception as e:
                logger.error(f"后台部署任务异常: {str(e)}", exc_info=True)

                # 清理 aigc.json 配置
                logger.info("=" * 80)
                logger.info("部署异常，开始清理 aigc.json 配置")
                logger.info("=" * 80)
                self._cleanup_aigc_config_after_deploy_failure()
                logger.info("=" * 80)
                logger.info("aigc.json 配置清理完成")
                logger.info("=" * 80)

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

    def _copy_python_scripts_to_target_dir(self, run_new: bool = False) -> str:
        """将工作目录中的 Python 脚本拷贝到目标目录并授权

        操作步骤：
        1. 删除目标目录下所有 conftest.py 和 test_ 开头的 .py 文件
        2. 从工作目录拷贝 test_*.py 和 conftest.py 到目标目录

        目标目录：/opt/coder/statistics/build/aigc_tool/{username}/

        Returns:
            str: 目标目录路径
        """
        try:
            import glob

            username = getpass.getuser()
            target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"

            # 创建目标目录
            os.makedirs(target_dir, exist_ok=True)
            logger.info(f"目标目录已确认: {target_dir}")

            # ========== 第1步：删除目标目录下所有 conftest.py 和 test_ 开头的 .py 文件 ==========
            deleted_files = []
            # 查找并删除所有 test_*.py 文件
            test_pattern = os.path.join(target_dir, "test_*.py")
            test_files = glob.glob(test_pattern)
            for file_path in test_files:
                try:
                    os.remove(file_path)
                    deleted_files.append(os.path.basename(file_path))
                    logger.info(f"已删除目标目录中的测试文件: {os.path.basename(file_path)}")
                except Exception as e:
                    logger.warning(f"删除文件失败 {file_path}: {str(e)}")

            # 查找并删除 conftest.py
            conftest_pattern = os.path.join(target_dir, "conftest.py")
            if os.path.exists(conftest_pattern):
                try:
                    os.remove(conftest_pattern)
                    deleted_files.append("conftest.py")
                    logger.info(f"已删除目标目录中的 conftest.py")
                except Exception as e:
                    logger.warning(f"删除 conftest.py 失败: {str(e)}")

            if deleted_files:
                logger.info(f"已删除目标目录中的 {len(deleted_files)} 个旧文件: {', '.join(deleted_files)}")

            # ========== 第2步：从工作目录拷贝文件到目标目录 ==========
            # 获取工作目录
            work_dir = settings.get_work_directory()
            logger.info(f"工作目录: {work_dir}")

            # 查找并拷贝 test_*.py 脚本
            test_scripts_pattern = os.path.join(work_dir, "test_*.py")
            test_scripts = glob.glob(test_scripts_pattern)

            copied_count = 0
            if run_new:
                newest_file = None
                newest_time = 0
                for script_path in test_scripts:
                    if os.path.isfile(script_path):
                        try:
                            file_mtime = os.path.getmtime(script_path)
                            if file_mtime > newest_time:
                                newest_time = file_mtime
                                newest_file = script_path
                        except Exception as e:
                            logger.warning(f"获取文件修改时间失败 {script_path}: {str(e)}")
                            continue

                # 检查是否找到有效的测试脚本文件
                if newest_file is None:
                    logger.warning("没有找到有效的测试脚本文件，跳过拷贝")
                else:
                    # 拼装脚本路径
                    script_name = os.path.basename(newest_file)
                    target_path = os.path.join(target_dir, script_name)

                    # 删除旧脚本（如果存在）
                    if os.path.exists(target_path):
                        try:
                            os.remove(target_path)
                            logger.info(f"已删除旧的测试脚本: {script_name}")
                        except Exception as e:
                            logger.warning(f"删除旧脚本失败 {target_path}: {str(e)}")

                    # 拷贝最新文件
                    try:
                        shutil.copy2(newest_file, target_path)
                        # 设置权限为可读写（777）
                        os.chmod(target_path, 0o777)
                        logger.info(f"已拷贝测试脚本: {script_name} -> {target_path}")
                        copied_count += 1
                    except Exception as e:
                        logger.error(f"拷贝文件失败 {newest_file} -> {target_path}: {str(e)}")
                        raise
            else:           
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

            logger.info(f"脚本拷贝完成，已删除 {len(deleted_files)} 个旧文件，已拷贝 {copied_count} 个文件到 {target_dir}")

            return target_dir

        except Exception as e:
            logger.error(f"拷贝 Python 脚本失败: {str(e)}", exc_info=True)
            raise

    async def run_script(self, request: RunScriptRequest, run_new: bool = False) -> Dict[str, Any]:
        """运行测试脚本"""
        logger.info(f"运行脚本请求 - scriptspath: {request.scriptspath}, executorip: {request.executorip}")

        # 在调用 ITC run 前，清除 aigc.json 中的旧运行结果
        # 这样查询接口可以正确返回"执行中"状态
        self._clear_itc_run_result()
        logger.info("已清除 aigc.json 中的旧 ITC run 结果")

        # 在调用 ITC run 前，拷贝工作目录中的 Python 脚本到目标目录
        try:
            logger.info("开始拷贝 Python 脚本到目标目录...")
            target_dir = self._copy_python_scripts_to_target_dir(run_new)
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

        # 保存 ITC run 结果到 aigc.json
        self._save_itc_run_result(result)

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

class ItcLogService:
    """ITC日志文件服务类"""

    def __init__(self):
        """初始化ITC日志服务"""
        self.itc_log_base_path = "/opt/coder/statistics/build/aigc_tool"

    def _get_user_log_dir(self, username: Optional[str] = None) -> Path:
        """获取用户的ITC日志目录

        优先使用 ITC 服务器日志目录，如果不存在则使用工作区 logs 目录

        Args:
            username: 用户名，如果为None则使用当前系统用户名

        Returns:
            Path: 用户ITC日志目录的完整路径
        """
        # 使用 ITC 日志目录: /opt/coder/statistics/build/aigc_tool/{username}/log/
        if username is None:
            import getpass
            username = getpass.getuser()

        itc_log_dir = Path(self.itc_log_base_path) / username / "log"

        # 检查 ITC 日志目录是否存在
        if itc_log_dir.exists() and itc_log_dir.is_dir():
            logger.info(f"使用 ITC 日志目录: {itc_log_dir}")
            return itc_log_dir

        # 使用工作区 logs 目录
        work_dir = settings.get_work_directory()
        workspace_log_dir = Path(work_dir) / "logs"
        logger.info(f"使用工作区 log 目录: {workspace_log_dir}")
        return workspace_log_dir

    async def get_itc_log_files(self, username: Optional[str] = None) -> tuple[bool, str, Optional[List[Dict[str, Any]]], Optional[Dict[str, Any]]]:
        """获取指定用户的ITC日志文件列表

        优先使用 ITC 服务器日志目录，如果不存在则使用工作区 logs 目录

        对于 .pytestlog.json 后缀的文件，会解析其中的 Result 和 elapsed_time 属性

        Args:
            username: 用户名，如果为None则使用当前系统用户名

        Returns:
            tuple: (success, message, log_files, statistics)
                - success: 是否成功
                - message: 响应消息
                - log_files: ITC日志文件信息列表，失败时为None
                - statistics: 统计信息（仅.pytestlog.json文件），包含 result_counts 和 total_elapsed_time
        """
        try:
            log_dir = self._get_user_log_dir(username)

            # 检查目录是否存在，如果不存在则创建
            if not log_dir.exists():
                logger.warning(f"日志目录不存在，尝试创建: {log_dir}")
                try:
                    log_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"已创建日志目录: {log_dir}")
                except Exception as e:
                    logger.error(f"无法创建日志目录: {str(e)}")
                    return True, f"日志目录不存在且无法创建: {log_dir}", [], None

            if not log_dir.is_dir():
                logger.error(f"日志路径不是目录: {log_dir}")
                return False, f"日志路径不是目录: {log_dir}", None, None

            # 读取目录中的所有文件
            log_files: List[Dict[str, Any]] = []
            result_counts: Dict[str, int] = {}
            elapsed_time_list: List[str] = []

            for file_path in log_dir.iterdir():
                # 只处理文件，跳过目录
                if file_path.is_file():
                    # 过滤掉 .log 格式的文件
                    if file_path.name.endswith(".log"):
                        continue

                    try:
                        # 获取文件信息
                        stat = file_path.stat()

                        # 格式化修改时间
                        modified_time = datetime.fromtimestamp(
                            stat.st_mtime
                        ).strftime("%Y-%m-%d %H:%M:%S")

                        # 创建ITC日志文件信息对象
                        log_file_info = {
                            "filename": file_path.name,
                            "size": stat.st_size,
                            "modified_time": modified_time
                        }

                        # 检查是否是 .pytestlog.json 文件
                        if file_path.name.endswith(".pytestlog.json"):
                            # 尝试解析文件内容获取 Result 和 elapsed_time
                            try:
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                    data = json.loads(content)

                                    # 提取 Result 和 elapsed_time（保持原始格式，不做错误处理）
                                    result = data.get("Result")
                                    elapsed_time = data.get("elapsed_time")

                                    if result is not None:
                                        log_file_info["Result"] = result
                                        # 统计 Result 类型个数
                                        result_counts[result] = result_counts.get(result, 0) + 1

                                    if elapsed_time is not None:
                                        log_file_info["elapsed_time"] = elapsed_time
                                        elapsed_time_list.append(elapsed_time)

                            except Exception as parse_error:
                                # 解析失败时不抛出错误，继续处理其他文件
                                logger.debug(f"解析 .pytestlog.json 文件失败 {file_path.name}: {str(parse_error)}")

                        log_files.append(log_file_info)

                    except Exception as e:
                        logger.warning(f"无法读取文件信息 {file_path.name}: {str(e)}")
                        continue

            # 按文件名排序
            log_files.sort(key=lambda x: x["filename"])

            # 构建统计信息
            statistics = None
            if result_counts or elapsed_time_list:
                # 计算 elapsed_time 总和
                total_elapsed_time = None
                if elapsed_time_list:
                    total_seconds = 0.0
                    for time_str in elapsed_time_list:
                        try:
                            # 解析时间格式 "H:MM:SS.ffffff" 或 "MM:SS.ffffff"
                            parts = time_str.split(":")
                            if len(parts) == 3:
                                # 格式: H:MM:SS.ffffff
                                hours = int(parts[0])
                                minutes = int(parts[1])
                                seconds = float(parts[2])
                                total_seconds += hours * 3600 + minutes * 60 + seconds
                            elif len(parts) == 2:
                                # 格式: MM:SS.ffffff
                                minutes = int(parts[0])
                                seconds = float(parts[1])
                                total_seconds += minutes * 60 + seconds
                        except (ValueError, IndexError) as e:
                            # 解析失败时跳过该时间
                            logger.debug(f"解析时间字符串失败: {time_str}, 错误: {str(e)}")
                            continue

                    # 将总秒数转换为时分秒格式
                    total_hours = int(total_seconds // 3600)
                    total_seconds %= 3600
                    total_minutes = int(total_seconds // 60)
                    total_seconds %= 60

                    # 格式化为 "H:MM:SS.ffffff"
                    total_elapsed_time = f"{total_hours}:{total_minutes:02d}:{total_seconds:06f}"

                statistics = {
                    "result_counts": result_counts if result_counts else None,
                    "total_elapsed_time": total_elapsed_time
                }

            logger.info(f"成功获取日志文件列表，共 {len(log_files)} 个文件")
            return True, f"成功获取日志文件列表，共 {len(log_files)} 个文件", log_files, statistics

        except Exception as e:
            logger.error(f"获取日志文件列表失败: {str(e)}")
            return False, f"获取日志文件列表失败: {str(e)}", None, None

    async def get_all_pytestlog_json_files(self, username: Optional[str] = None) -> tuple[bool, str, Optional[List[Dict[str, Any]]]]:
        """获取目录下所有 .pytestlog.json 后缀文件的内容

        优先使用 ITC 服务器日志目录，如果不存在则使用工作区 logs 目录

        Args:
            username: 用户名，如果为None则使用当前系统用户名

        Returns:
            tuple: (success, message, all_files_content)
                - success: 是否成功
                - message: 响应消息
                - all_files_content: 所有 .pytest.json 文件内容的列表，失败时为None
        """
        try:
            log_dir = self._get_user_log_dir(username)

            # 检查目录是否存在
            if not log_dir.exists():
                logger.warning(f"日志目录不存在: {log_dir}")
                return False, f"日志目录不存在: {log_dir}", None

            if not log_dir.is_dir():
                logger.error(f"日志路径不是目录: {log_dir}")
                return False, f"日志路径不是目录: {log_dir}", None

            # 读取目录中所有 .pytestlog.json 文件
            all_files_content: List[Dict[str, Any]] = []

            for file_path in log_dir.iterdir():
                # 只处理 .pytestlog.json 文件
                if file_path.is_file() and file_path.name.endswith(".pytestlog.json"):
                    try:
                        # 读取文件内容
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            data = json.loads(content)

                            # 将文件名添加到数据中
                            if isinstance(data, dict):
                                data["_filename"] = file_path.name

                            all_files_content.append(data)

                    except json.JSONDecodeError as e:
                        logger.warning(f"解析 JSON 文件失败 {file_path.name}: {str(e)}")
                        continue
                    except Exception as e:
                        logger.warning(f"读取文件失败 {file_path.name}: {str(e)}")
                        continue

            # 按文件名排序
            all_files_content.sort(key=lambda x: x.get("_filename", ""))

            logger.info(f"成功获取 {len(all_files_content)} 个 .pytestlog.json 文件的内容")
            return True, f"成功获取 {len(all_files_content)} 个 .pytestlog.json 文件的内容", all_files_content

        except Exception as e:
            logger.error(f"获取 .pytestlog.json 文件内容失败: {str(e)}")
            return False, f"获取 .pytestlog.json 文件内容失败: {str(e)}", None

    async def get_itc_log_content(self, filename: str, username: Optional[str] = None) -> tuple[bool, str, Optional[dict]]:
        """读取指定ITC日志文件的内容

        优先使用 ITC 服务器日志目录，如果不存在则使用工作区 logs 目录

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
            import aiofiles

            # 验证文件名安全性，防止路径遍历攻击
            if "/" in filename or "\\" in filename or ".." in filename:
                logger.warning(f"检测到非法文件名: {filename}")
                return False, "文件名包含非法字符", None

            log_dir = self._get_user_log_dir(username)
            file_path = log_dir / filename

            # 检查文件是否存在
            if not file_path.exists():
                logger.warning(f"日志文件不存在: {file_path}")
                return False, f"日志文件不存在: {filename}", None

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

            logger.info(f"成功读取日志文件: {filename}, 大小: {stat.st_size} 字节")
            return True, f"成功读取日志文件: {filename}", data

        except UnicodeDecodeError as e:
            logger.error(f"文件编码错误: {str(e)}")
            return False, f"文件编码错误，无法读取文件内容", None
        except Exception as e:
            logger.error(f"读取日志文件失败: {str(e)}")
            return False, f"读取日志文件失败: {str(e)}", None


# 创建 ITC 服务实例
itc_service = ITCService()

# 创建 ITC 日志服务实例
itc_log_service = ItcLogService()