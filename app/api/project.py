"""
项目配置 API 路由

提供 nvid 和 sessionId 的查询、修改和刷新功能
"""

import re
import json
import logging
import getpass
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["项目配置"])

# aigc.json 文件路径
AIGC_JSON_PATH = Path(settings.get_work_directory()) / ".aigc_tool" / "aigc.json"


# ========== 数据模型 ==========

class NvidRequest(BaseModel):
    """nvid 请求模型"""
    nvid: str

    @field_validator('nvid')
    @classmethod
    def validate_nvid_format(cls, v):
        """验证 nvid 格式"""
        if not v:
            raise ValueError('nvid 不能为空')

        # 验证项目类型格式: NV202509090001 (NV+年月日+4位序号)
        project_pattern = r'^NV\d{8}\d{4}$'
        # 验证临时项目格式: V9, B75, B64, B70 等 (字母+数字)
        temp_pattern = r'^[A-Z]\d+$'

        if re.match(project_pattern, v):
            return v
        elif re.match(temp_pattern, v):
            # 验证是否为允许的临时项目格式
            allowed_temp = ['V9', 'B75', 'B64', 'B70']
            if v in allowed_temp:
                return v
            else:
                raise ValueError(
                    f'临时项目格式只允许: {", ".join(allowed_temp)}'
                )
        else:
            raise ValueError(
                '项目类型请输入格式: NV202509090001 (NV+年月日+4位序号) 或 '
                '临时项目格式: V9, B75, B64, B70'
            )


class ProjectConfigResponse(BaseModel):
    """项目配置响应模型"""
    nvid: Optional[str] = None
    sessionId: Optional[str] = None
    message: str = ""


# ========== 辅助函数 ==========

def ensure_aigc_json_exists() -> None:
    """确保 aigc.json 文件存在"""
    if not AIGC_JSON_PATH.exists():
        AIGC_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        # 创建空的配置文件
        with open(AIGC_JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump({}, f, indent=2, ensure_ascii=False)


def get_aigc_config() -> dict:
    """读取 aigc.json 配置"""
    ensure_aigc_json_exists()
    with open(AIGC_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_aigc_config(config: dict) -> None:
    """保存 aigc.json 配置"""
    with open(AIGC_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def generate_session_id() -> str:
    """生成 sessionId

    规则: AI + 用户名中数字部分 + 时间戳
    例如: AI12320250209163045
    """
    username = getpass.getuser()
    # 提取用户名中的数字部分
    username_nums = ''.join(re.findall(r'\d+', username))
    if not username_nums:
        username_nums = '000'

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"AI{username_nums}{timestamp}"


def ensure_nvid_and_session_in_config(config: dict) -> dict:
    """确保配置中有 nvid 和 sessionId，如果没有则添加到最前面"""

    # 检查并添加 nvid
    if 'nvid' not in config:
        config = {'nvid': '', **config}

    # 检查并添加 sessionId
    if 'sessionId' not in config:
        config = {'sessionId': '', **config}

    return config


# ========== API 接口 ==========

@router.get("/api/v1/project/config", response_model=ProjectConfigResponse, tags=["项目配置"])
async def get_project_config():
    """
    查询项目配置

    返回当前的 nvid 和 sessionId
    """
    try:
        config = get_aigc_config()

        # 确保 nvid 和 sessionId 在配置中
        config = ensure_nvid_and_session_in_config(config)

        return ProjectConfigResponse(
            nvid=config.get('nvid', ''),
            sessionId=config.get('sessionId', ''),
            message="查询成功"
        )
    except Exception as e:
        logger.error(f"查询项目配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.post("/api/v1/project/nvid", response_model=ProjectConfigResponse, tags=["项目配置"])
async def update_nvid(request: NvidRequest):
    """
    修改 nvid

    传入 nvid 时，保存 nvid 并自动生成 sessionId
    """
    try:
        config = get_aigc_config()

        # 验证 nvid 格式（已在模型中验证）
        nvid = request.nvid

        # 生成新的 sessionId
        session_id = generate_session_id()

        # 更新配置 - 将 nvid 和 sessionId 放在最前面
        new_config = {
            'nvid': nvid,
            'sessionId': session_id,
        }

        # 保留原有的其他字段
        for key, value in config.items():
            if key not in ['nvid', 'sessionId']:
                new_config[key] = value

        # 保存配置
        save_aigc_config(new_config)

        logger.info(f"更新 nvid: {nvid}, 生成 sessionId: {session_id}")

        return ProjectConfigResponse(
            nvid=nvid,
            sessionId=session_id,
            message="nvid 更新成功，sessionId 已自动生成"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"更新 nvid 失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.post("/api/v1/project/session/refresh", response_model=ProjectConfigResponse, tags=["项目配置"])
async def refresh_session_id():
    """
    刷新 sessionId

    生成新的 sessionId，保持 nvid 不变
    """
    try:
        config = get_aigc_config()

        # 生成新的 sessionId
        new_session_id = generate_session_id()

        # 更新配置 - 将 sessionId 和 nvid 放在最前面
        new_config = {
            'nvid': config.get('nvid', ''),
            'sessionId': new_session_id,
        }

        # 保留原有的其他字段
        for key, value in config.items():
            if key not in ['nvid', 'sessionId']:
                new_config[key] = value

        # 保存配置
        save_aigc_config(new_config)

        logger.info(f"刷新 sessionId: {new_session_id}")

        return ProjectConfigResponse(
            nvid=config.get('nvid', ''),
            sessionId=new_session_id,
            message="sessionId 刷新成功"
        )
    except Exception as e:
        logger.error(f"刷新 sessionId 失败: {e}")
        raise HTTPException(status_code=500, detail=f"刷新失败: {str(e)}")


