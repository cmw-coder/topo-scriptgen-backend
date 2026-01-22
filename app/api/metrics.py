"""
Metrics API 路由

提供指标统计相关的接口
"""
import logging
from fastapi import APIRouter, HTTPException

from app.models.metrics import MetricsPushRequest
from app.models.common import BaseResponse
from app.services.metrics_service import metrics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.post("/push", response_model=BaseResponse)
async def push_metrics(request: MetricsPushRequest):
    """
    推送指标数据

    请求参数（JSON Body）：
    - **type**: 指标类型，支持 "command_debug"(命令行调试)、"keep_alive"(Web使用时间) 或 "write_script"(写脚本时间)
    - **file_name**: 脚本文件名（command_debug 和 write_script 类型必需）
    - **interval**: 用户操作耗时（秒）（所有类型都必需）

    返回更新后的指标数据

    指标统计规则：
    - command_debug: 按文件累加调试时间（interval）
    - write_script: 按文件累加写脚本时间（interval）
    - keep_alive: 累加Web使用总时间（interval）
    - total_debug_duration: 自动计算 command_debug_metrics 和 write_script_metrics 所有文件的总和
    - 指标保存到当前用户的最新流程文件中
    """
    try:
        # 校验 interval 参数
        if request.interval is None:
            raise HTTPException(
                status_code=400,
                detail="interval 参数是必需的"
            )

        # 调用 service 层处理业务逻辑
        result = metrics_service.push_metrics(
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
