"""
Metrics API 路由

提供指标统计相关的接口
"""
import logging
from fastapi import APIRouter, HTTPException

from app.models.metrics import MetricsPushRequest
from app.models.common import BaseResponse
from app.services.metrics.command_debug_service import command_debug_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.post("/push", response_model=BaseResponse)
async def push_metrics(request: MetricsPushRequest):
    """
    推送指标数据

    请求参数（JSON Body）：
    - **type**: 指标类型，目前支持 "command_debug"
    - **file_name**: 调试的脚本文件名

    返回更新后的指标数据

    命令行调试指标统计规则：
    - 记录用户每次调用接口的时间
    - 如果前后两次调用间隔 < 5分钟，认为是调试时间
    - 如果间隔 >= 5分钟，则不算调试时间（新的一段调试）
    - 对于连续的调试调用（间隔都 < 5分钟），取最大间隔作为该段调试时间
    - 总调试耗时是所有调试段的最大间隔之和
    - 指标保存到当前用户的最新流程文件中
    """
    try:
        if request.type == "command_debug":
            # 命令行调试指标
            result = command_debug_service.push_command_debug(request.file_name)

            # 检查是否有错误
            if "error" in result:
                if result["error"] == "no_active_flow":
                    return BaseResponse(
                        status="warning",
                        message=result.get("message", "当前没有活动流程"),
                        data=result
                    )
                elif result["error"] == "flow_not_found":
                    return BaseResponse(
                        status="error",
                        message=result.get("message", "流程不存在"),
                        data=result
                    )

            return BaseResponse(
                status="ok",
                message="成功记录命令行调试指标",
                data=result
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的指标类型: {request.type}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"推送指标失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"推送指标失败: {str(e)}")


@router.get("/command-debug", response_model=BaseResponse)
async def get_command_debug_metrics(file_name: str):
    """
    获取指定文件的命令行调试指标

    参数：
    - **file_name**: 调试的脚本文件名

    返回该文件的调试指标数据
    """
    try:
        result = command_debug_service.get_debug_metrics(file_name)

        # 检查是否有错误
        if "error" in result:
            if result["error"] in ("no_active_flow", "flow_not_found"):
                return BaseResponse(
                    status="warning",
                    message=result.get("message", "未找到调试指标"),
                    data=result
                )
            if result["error"] == "no_metrics":
                return BaseResponse(
                    status="ok",
                    message=result.get("message", "该文件没有调试记录"),
                    data=None
                )

        return BaseResponse(
            status="ok",
            message="成功获取调试指标",
            data=result
        )

    except Exception as e:
        logger.error(f"获取调试指标失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取调试指标失败: {str(e)}")
