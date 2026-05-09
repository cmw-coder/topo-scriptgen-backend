"""
Claude Agent SDK 认证模块

启动时查询 API Key 服务，缓存到本地文件，设置环境变量。
后续 claude_agent_sdk 调用通过环境变量自动获取认证信息。
"""
import getpass
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# 查询 API Key 的服务地址
QUERY_API_URL = "http://10.141.187.201:5001"

# Anthropic API 配置（与 h3ccodecli 保持一致）
BASE_URL = "http://10.141.187.201:33380/"
MODEL = "comware-model"
HAIKU_MODEL = "comware-model-air"

# 缓存文件路径：~/project/.aigc_tool/aigc_key.json
CACHE_DIR = Path.home() / "project" / ".aigc_tool"
CACHE_FILE = CACHE_DIR / "aigc_key.json"


def _query_user_key(username: str) -> tuple[str, str]:
    """调用查询 API 获取用户 API Key

    Args:
        username: 域账号用户名

    Returns:
        (api_key, dept) 元组

    Raises:
        RuntimeError: 无法连接服务或获取 key 失败时抛出
    """
    try:
        # trust_env=False 禁用代理（忽略 HTTP_PROXY/HTTPS_PROXY 等环境变量）
        with httpx.Client(trust_env=False) as client:
            resp = client.get(
                f"{QUERY_API_URL}/api/query",
                params={"name": username},
                timeout=30,
            )
    except httpx.RequestError:
        logger.error("无法连接到查询 API Key 服务 (%s)", QUERY_API_URL)
        logger.error("请联系测试部检查是否启动查询 API Key 服务")
        raise RuntimeError(f"无法连接到查询 API Key 服务 ({QUERY_API_URL})")

    if resp.status_code != 200:
        logger.error("查询 API Key 服务请求失败 (HTTP %d)", resp.status_code)
        logger.error("请联系测试部检查是否启动查询 API Key 服务")
        raise RuntimeError(f"查询 API Key 服务请求失败 (HTTP {resp.status_code})")

    try:
        data = resp.json()
        items = data.get("items", [])
        if not items:
            logger.error("未查询到用户 %s 的 API Key", username)
            raise RuntimeError(f"未查询到用户 {username} 的 API Key")
        api_key = items[0].get("key", "")
        dept = items[0].get("group", "")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error("解析 API Key 查询响应失败: %s", e)
        raise RuntimeError(f"解析 API Key 查询响应失败: {e}")

    if not api_key:
        logger.error("未获取到用户 %s 的 API Key", username)
        raise RuntimeError(f"未获取到用户 {username} 的 API Key")

    return api_key, dept


def _load_cache(username: str) -> Optional[dict]:
    """从本地缓存加载 API Key，校验用户名匹配

    Args:
        username: 当前用户名，用于校验缓存是否匹配

    Returns:
        缓存数据字典，如果不存在、读取失败或用户名不匹配则返回 None
    """
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not data.get("api_key"):
            logger.warning("缓存文件缺少 api_key，视为无效")
            return None
        if data.get("username") != username:
            logger.warning("缓存用户名不匹配 (expected=%s, got=%s)，重新查询", username, data.get("username"))
            return None
        logger.info("从本地缓存加载 API Key (用户: %s)", username)
        return data
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("读取 API Key 缓存失败: %s", e)
    return None


def _save_cache(api_key: str, username: str) -> None:
    """保存 API Key 到本地缓存

    Args:
        api_key: 用户 API Key
        username: 域账号用户名
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_data = {
        "api_key": api_key,
        "username": username,
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)
    logger.info("API Key 已缓存到 %s", CACHE_FILE)


def setup_claude_auth() -> None:
    """设置 Claude Agent SDK 认证环境变量

    优先从本地缓存加载，缓存未命中时查询 API Key 服务。
    在应用启动时调用一次即可。

    Raises:
        RuntimeError: 无法获取 API Key 时抛出
    """
    username = getpass.getuser()
    logger.info("[认证] 正在获取用户 %s 的 API Key...", username)

    # 1. 尝试从缓存加载
    cache = _load_cache(username)
    if cache is not None:
        api_key = cache["api_key"]
    else:
        # 2. 缓存未命中，查询服务
        api_key, _ = _query_user_key(username)
        _save_cache(api_key, username)

    # 3. 设置环境变量
    os.environ["ANTHROPIC_AUTH_TOKEN"] = api_key
    os.environ["ANTHROPIC_BASE_URL"] = BASE_URL
    os.environ["ANTHROPIC_MODEL"] = MODEL
    os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] = MODEL
    os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = MODEL
    os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = HAIKU_MODEL

    masked = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "****"
    logger.info("[认证] 用户信息获取成功")
    logger.info("[认证] 域账号: %s", username)
    logger.info("[认证] API Key: %s", masked)
    logger.info("[认证] 模型地址: %s", BASE_URL)
