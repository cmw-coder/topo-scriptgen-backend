#!/usr/bin/env python3
"""
ITC 服务客户端模块
"""

import logging
from typing import Dict, Any, Optional
from pathlib import Path

import httpx


logger = logging.getLogger(__name__)


class ITCClient:
    """ITC API 客户端"""

    def __init__(self, base_url: str, timeout: int = 1200):
        """
        初始化 ITC 客户端

        Args:
            base_url: ITC 服务器基础 URL
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    async def newdeploy(
        self,
        topofile_unc: str,
        versionpath: Optional[str] = None,
        device_type: str = "simware9cen"
    ) -> Dict[str, Any]:
        """
        调用 ITC 新部署接口 (newdeploy)

        Args:
            topofile_unc: topox 文件所在目录的 UNC 路径（格式: //server/path/to/dir，不包含文件名）
            versionpath: 版本目录路径（可选）
            device_type: 设备类型（默认 simware9cen）

        Returns:
            ITC 响应数据
        """
        url = f"{self.base_url}/newdeploy"

        # 构建请求数据 - 使用 newdeploy 接口的参数格式
        data = {
            "topofile": topofile_unc,
            "deviceType": device_type
        }

        if versionpath:
            data["versionpath"] = versionpath

        logger.info(f"ITC newdeploy 请求: {url}")
        logger.info(f"请求数据: {data}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
                result = response.json()
                logger.info(f"ITC newdeploy 响应: {result}")
                return result

        except httpx.HTTPStatusError as e:
            logger.error(f"ITC newdeploy 请求失败: {e.response.status_code} - {e.response.text}")
            return {
                "return_code": str(e.response.status_code),
                "return_info": f"HTTP 错误: {e.response.text}",
                "result": None
            }
        except Exception as e:
            logger.error(f"ITC newdeploy 请求异常: {str(e)}")
            return {
                "return_code": "500",
                "return_info": f"请求异常: {str(e)}",
                "result": None
            }

    async def run_scripts(
        self,
        scripts_unc_path: str,
        executor_ip: str
    ) -> Dict[str, Any]:
        """
        调用 ITC 运行脚本接口

        Args:
            scripts_unc_path: 脚本目录的 UNC 路径
            executor_ip: 执行机 IP 地址

        Returns:
            ITC 响应数据
        """
        url = f"{self.base_url}/run"

        # 构建请求数据
        data = {
            "scriptspath": scripts_unc_path,
            "executorip": executor_ip
        }

        logger.info(f"ITC 运行请求: {url}")
        logger.info(f"请求数据: {data}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
                result = response.json()
                logger.info(f"ITC 运行响应: {result}")
                return result

        except httpx.HTTPStatusError as e:
            logger.error(f"ITC 运行请求失败: {e.response.status_code} - {e.response.text}")
            return {
                "return_code": str(e.response.status_code),
                "return_info": f"HTTP 错误: {e.response.text}",
                "result": None
            }
        except Exception as e:
            logger.error(f"ITC 运行请求异常: {str(e)}")
            return {
                "return_code": "500",
                "return_info": f"请求异常: {str(e)}",
                "result": None
            }

    async def undeploy(
        self,
        executor_ip: str
    ) -> Dict[str, Any]:
        """
        调用 ITC 卸载接口

        Args:
            executor_ip: 执行机 IP 地址

        Returns:
            ITC 响应数据
        """
        url = f"{self.base_url}/undeploy"

        # 构建请求数据
        data = {
            "executorip": executor_ip
        }

        logger.info(f"ITC 卸载请求: {url}")
        logger.info(f"请求数据: {data}")

        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(url, json=data)
                response.raise_for_status()
                result = response.json()
                logger.info(f"ITC 卸载响应: {result}")
                return result

        except httpx.HTTPStatusError as e:
            logger.error(f"ITC 卸载请求失败: {e.response.status_code} - {e.response.text}")
            return {
                "return_code": str(e.response.status_code),
                "return_info": f"HTTP 错误: {e.response.text}",
                "result": None
            }
        except Exception as e:
            logger.error(f"ITC 卸载请求异常: {str(e)}")
            return {
                "return_code": "500",
                "return_info": f"请求异常: {str(e)}",
                "result": None
            }


# 创建全局客户端实例
def create_itc_client(base_url: str, timeout: int = 1200) -> ITCClient:
    """创建 ITC 客户端实例"""
    return ITCClient(base_url=base_url, timeout=timeout)
