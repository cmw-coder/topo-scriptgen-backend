"""
Metrics API v2 - 基于脚本的度量接口

只提供 /push 接口用于推送度量数据
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.metrics_v2 import MetricsPushRequest
from app.services.metrics_service_v2 import metrics_service_v2
from app.models.common import BaseResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"])


# ==================== /push 接口 ====================

@router.post("/push", response_model=BaseResponse)
async def push_metrics(request: MetricsPushRequest):
    """
    推送指标数据（兼容旧版 /push 接口，但适配到 v2 版本）

    请求参数（JSON Body）：
    - **type**: 指标类型，支持 "command_debug"(命令行调试)、"keep_alive"(Web使用时间) 或 "write_script"(写脚本时间)
    - **file_name**: 脚本文件名（command_debug 和 write_script 类型必需）
    - **interval**: 用户操作耗时（秒）（所有类型都必需）

    返回更新后的指标数据

    新增功能（v2版本）：
    - command_debug: 按文件匹配对应脚本，标记为活跃脚本，累加耗时到脚本的 command_debug_duration 字段
    - write_script: 按文件匹配对应脚本，标记为活跃脚本，累加耗时到脚本的 write_script_duration 字段
    - keep_alive: 累加Web使用总时间到当前活跃脚本

    注意：
    - 如果 file_name 对应的脚本不存在，会自动创建脚本记录
    - 匹配到脚本后，该脚本会被设置为当前活跃脚本
    - 度量日志文件名格式：script_AI指纹ID.json
    """
    try:
        # 校验 interval 参数
        if request.interval is None:
            raise HTTPException(
                status_code=400,
                detail="interval 参数是必需的"
            )

        # 调用 service 层处理业务逻辑
        result = metrics_service_v2.push_metrics(
            metrics_type=request.type,
            file_name=request.file_name,
            interval=request.interval
        )

        # 根据类型返回不同的消息
        message_map = {
            "command_debug": "成功记录命令行调试指标",
            "write_script": "成功记录写脚本时间",
            "keep_alive": "成功记录Web使用时间"
        }

        return BaseResponse(
            status="ok",
            message=message_map.get(request.type, "成功记录指标"),
            data=result
        )

    except ValueError as e:
        # 业务参数错误
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"推送指标失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"推送指标失败: {str(e)}")


__all__ = ["router"]
