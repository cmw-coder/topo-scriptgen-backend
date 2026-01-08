"""ITC日志文件API接口
AI_FingerPrint_UUID: 20250108-Jp5fR9tK
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.services.itc_log_service import itc_log_service
from app.models.itc_log import ItcLogFileListResponse, ItcLogFileContentRequest, ItcLogFileContentResponse
from app.models.common import BaseResponse


router = APIRouter(prefix="/itclogs", tags=["ITC日志文件管理"])


@router.get("/list", response_model=ItcLogFileListResponse)
async def get_itc_log_files(
    username: Optional[str] = Query(None, description="用户名，为空时使用当前系统用户名")
):
    """获取ITC日志文件列表

    返回指定用户的ITC日志目录(/opt/coder/statistics/build/aigc_tool/{username}/log/)下的所有文件列表

    Args:
        username: 用户名，可选参数。如果为空则使用当前系统用户名

    Returns:
        ItcLogFileListResponse: 包含ITC日志文件列表的响应
    """
    try:
        success, message, log_files = await itc_log_service.get_itc_log_files(username)

        if success:
            return ItcLogFileListResponse(
                status="ok",
                message=message,
                data=log_files,
                total_count=len(log_files) if log_files else 0
            )
        else:
            raise HTTPException(status_code=400, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取ITC日志文件列表失败: {str(e)}")


@router.post("/content", response_model=ItcLogFileContentResponse)
async def get_itc_log_content(request: ItcLogFileContentRequest):
    """获取ITC日志文件内容

    根据文件名读取ITC日志文件的内容

    Args:
        request: 包含filename的请求体

    Returns:
        ItcLogFileContentResponse: 包含文件信息和内容的响应
    """
    try:
        if not request.filename:
            raise HTTPException(status_code=400, detail="文件名不能为空")

        success, message, data = await itc_log_service.get_itc_log_content(request.filename)

        if success:
            return ItcLogFileContentResponse(
                status="ok",
                message=message,
                data=data
            )
        else:
            raise HTTPException(status_code=400, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取ITC日志文件内容失败: {str(e)}")
