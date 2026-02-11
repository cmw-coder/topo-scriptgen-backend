"""
Metrics API v2 - 基于脚本的度量接口

提供完整的度量数据查询和管理接口
"""
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models.metrics_v2 import (
    ScriptMetrics,
    DeployRecord,
    ActivityRecord,
    ActivityType,
    ScriptType,
    MetricsPushRequest
)
from app.services.metrics_service_v2 import metrics_service_v2
from app.models.common import BaseResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"])


# ==================== 请求模型 ====================

class CreateScriptRequest(BaseModel):
    """创建脚本请求"""
    script_path: str = Field(..., description="脚本文件路径")
    script_type: ScriptType = Field(default=ScriptType.TEST_SCRIPT, description="脚本类型")
    generation_duration: Optional[float] = Field(None, description="生成耗时（秒）")
    ai_fingerprint_uuid: Optional[str] = Field(None, description="AI指纹UUID")


class StartDeployRequest(BaseModel):
    """开始部署请求"""
    topox_file: str = Field(..., description="topox 文件路径")
    version_path: Optional[str] = Field(None, description="版本路径")
    device_type: str = Field(default="simware9cen", description="设备类型")


class CompleteDeployRequest(BaseModel):
    """完成部署请求"""
    deploy_id: Optional[str] = Field(None, description="部署ID（如果不提供则使用当前待完成的部署）")
    executor_ip: str = Field(..., description="执行机IP")
    device_list: Optional[List[dict]] = Field(None, description="设备列表")
    status: str = Field(default="deployed", description="部署状态")


class FailDeployRequest(BaseModel):
    """部署失败请求"""
    deploy_id: Optional[str] = Field(None, description="部署ID")
    error_message: str = Field(default="", description="错误信息")


class StartActivityRequest(BaseModel):
    """开始活动请求"""
    activity_type: ActivityType = Field(..., description="活动类型")
    related_file: Optional[str] = Field(None, description="相关文件")
    extra_info: Optional[dict] = Field(None, description="额外信息")


class CompleteActivityRequest(BaseModel):
    """完成活动请求"""
    activity_id: str = Field(..., description="活动ID")
    extra_info: Optional[dict] = Field(None, description="额外信息")


class RecordCommandDebugRequest(BaseModel):
    """记录命令行调试请求"""
    file_name: str = Field(..., description="文件名")
    duration: float = Field(..., description="耗时（秒）", gt=0)


class RecordWriteScriptRequest(BaseModel):
    """记录写脚本时间请求"""
    file_name: str = Field(..., description="文件名")
    duration: float = Field(..., description="耗时（秒）", gt=0)


class RecordItcRunRequest(BaseModel):
    """记录 ITC run 请求"""
    duration: float = Field(..., description="耗时（秒）", gt=0)
    return_code: str = Field(..., description="返回码")
    return_info: Optional[dict] = Field(None, description="返回信息")


class AddKeepAliveRequest(BaseModel):
    """累加活跃时间请求"""
    interval: float = Field(..., description="时间间隔（秒）", gt=0)


class UpdateFingerprintRequest(BaseModel):
    """更新 AI 指纹请求"""
    script_uuid: str = Field(..., description="脚本UUID")
    ai_fingerprint_uuid: str = Field(..., description="AI指纹UUID")




# ==================== 脚本管理 ====================

@router.post("/scripts/create", response_model=BaseResponse)
async def create_script(request: CreateScriptRequest):
    """
    创建新的脚本度量记录

    通常在脚本生成时调用：
    - 生成 conftest.py 时调用
    - 生成测试脚本时调用
    """
    try:
        script_uuid = metrics_service_v2.create_script(
            script_path=request.script_path,
            script_type=request.script_type,
            generation_duration=request.generation_duration,
            ai_fingerprint_uuid=request.ai_fingerprint_uuid
        )

        return BaseResponse(
            status="ok",
            message="创建脚本度量成功",
            data={"script_uuid": script_uuid}
        )
    except Exception as e:
        logger.error(f"创建脚本度量失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/current", response_model=BaseResponse)
async def get_current_script():
    """获取当前活跃脚本的度量信息"""
    try:
        script = metrics_service_v2.get_current_script()
        if not script:
            return BaseResponse(
                status="ok",
                message="没有活跃脚本",
                data=None
            )

        return BaseResponse(
            status="ok",
            message="获取当前脚本成功",
            data=script.model_dump(mode='json')
        )
    except Exception as e:
        logger.error(f"获取当前脚本失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/{script_uuid}", response_model=BaseResponse)
async def get_script(script_uuid: str):
    """获取指定脚本的度量信息"""
    try:
        script = metrics_service_v2.get_script_metrics(script_uuid)
        if not script:
            raise HTTPException(status_code=404, detail=f"脚本不存在: {script_uuid}")

        return BaseResponse(
            status="ok",
            message="获取脚本成功",
            data=script.model_dump(mode='json')
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取脚本失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts", response_model=BaseResponse)
async def get_all_scripts(
    status: str = Query(default="active", description="状态筛选")
):
    """获取所有脚本列表"""
    try:
        scripts = metrics_service_v2.get_all_scripts(status=status)

        return BaseResponse(
            status="ok",
            message=f"获取脚本列表成功，共 {len(scripts)} 个",
            data=[s.model_dump(mode='json') for s in scripts]
        )
    except Exception as e:
        logger.error(f"获取脚本列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scripts/update-fingerprint", response_model=BaseResponse)
async def update_script_fingerprint(request: UpdateFingerprintRequest):
    """更新脚本的 AI 指纹"""
    try:
        success = metrics_service_v2.update_script_fingerprint(
            request.script_uuid,
            request.ai_fingerprint_uuid
        )

        if not success:
            raise HTTPException(status_code=404, detail="脚本不存在")

        return BaseResponse(
            status="ok",
            message="更新AI指纹成功",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新AI指纹失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 部署管理 ====================

@router.post("/deploy/start", response_model=BaseResponse)
async def start_deploy(request: StartDeployRequest):
    """
    开始部署（记录调用时间）

    在调用 ITC newdeploy 接口前调用
    """
    try:
        deploy_id = metrics_service_v2.start_deploy(
            topox_file=request.topox_file,
            version_path=request.version_path,
            device_type=request.device_type
        )

        return BaseResponse(
            status="ok",
            message="开始部署",
            data={"deploy_id": deploy_id}
        )
    except Exception as e:
        logger.error(f"开始部署失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deploy/complete", response_model=BaseResponse)
async def complete_deploy(request: CompleteDeployRequest):
    """
    完成部署（记录完成时间和结果）

    在 ITC newdeploy 接口返回成功后调用
    """
    try:
        success = metrics_service_v2.complete_deploy(
            executor_ip=request.executor_ip,
            device_list=request.device_list,
            status=request.status
        )

        if not success:
            raise HTTPException(status_code=400, detail="没有待完成的部署")

        return BaseResponse(
            status="ok",
            message="部署完成",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"完成部署失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deploy/fail", response_model=BaseResponse)
async def fail_deploy(request: FailDeployRequest):
    """
    标记部署失败

    在 ITC newdeploy 接口返回失败后调用
    """
    try:
        success = metrics_service_v2.fail_deploy(request.error_message)

        if not success:
            raise HTTPException(status_code=400, detail="没有待完成的部署")

        return BaseResponse(
            status="ok",
            message="已记录部署失败",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"记录部署失败失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 活动管理 ====================

@router.post("/activity/start", response_model=BaseResponse)
async def start_activity(request: StartActivityRequest):
    """
    开始活动

    返回 activity_id，完成后需要调用 complete_activity
    """
    try:
        activity_id = metrics_service_v2.start_activity(
            activity_type=request.activity_type,
            related_file=request.related_file,
            extra_info=request.extra_info
        )

        if not activity_id:
            raise HTTPException(status_code=400, detail="没有活跃脚本")

        return BaseResponse(
            status="ok",
            message="开始活动",
            data={"activity_id": activity_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"开始活动失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activity/complete", response_model=BaseResponse)
async def complete_activity(request: CompleteActivityRequest):
    """
    完成活动

    需要提供之前 start_activity 返回的 activity_id
    """
    try:
        success = metrics_service_v2.complete_activity(
            activity_id=request.activity_id,
            extra_info=request.extra_info
        )

        if not success:
            raise HTTPException(status_code=400, detail="活动不存在或已完成")

        return BaseResponse(
            status="ok",
            message="活动完成",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"完成活动失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activity/command-debug", response_model=BaseResponse)
async def record_command_debug(request: RecordCommandDebugRequest):
    """
    记录命令行调试（一次性完成）

    用于记录用户在命令行调试脚本的时间
    """
    try:
        activity_id = metrics_service_v2.record_command_debug(
            file_name=request.file_name,
            duration=request.duration
        )

        if not activity_id:
            raise HTTPException(status_code=400, detail="没有活跃脚本")

        return BaseResponse(
            status="ok",
            message="记录命令行调试成功",
            data={"activity_id": activity_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"记录命令行调试失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activity/write-script", response_model=BaseResponse)
async def record_write_script(request: RecordWriteScriptRequest):
    """
    记录写脚本时间（一次性完成）

    用于记录 AI 回写脚本的时间
    """
    try:
        activity_id = metrics_service_v2.record_write_script(
            file_name=request.file_name,
            duration=request.duration
        )

        if not activity_id:
            raise HTTPException(status_code=400, detail="没有活跃脚本")

        return BaseResponse(
            status="ok",
            message="记录写脚本时间成功",
            data={"activity_id": activity_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"记录写脚本时间失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activity/itc-run", response_model=BaseResponse)
async def record_itc_run(request: RecordItcRunRequest):
    """
    记录 ITC run（一次性完成）

    用于记录 ITC 执行脚本的时间和结果
    """
    try:
        activity_id = metrics_service_v2.record_itc_run(
            duration=request.duration,
            return_code=request.return_code
        )

        if not activity_id:
            raise HTTPException(status_code=400, detail="没有活跃脚本")

        return BaseResponse(
            status="ok",
            message="记录 ITC run 成功",
            data={"activity_id": activity_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"记录 ITC run 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/activity/keep-alive", response_model=BaseResponse)
async def add_keep_alive(request: AddKeepAliveRequest):
    """
    累加 Web 活跃时间

    用于记录用户在 Web 界面的活跃时间
    """
    try:
        success = metrics_service_v2.add_keep_alive_duration(request.interval)

        if not success:
            raise HTTPException(status_code=400, detail="没有活跃脚本")

        return BaseResponse(
            status="ok",
            message="累加活跃时间成功",
            data=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"累加活跃时间失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 兼容旧版 /push 接口 ====================

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


# ==================== 查询接口 ====================

@router.get("/is-virtual", response_model=BaseResponse)
async def check_is_virtual_script():
    """
    检查当前活跃脚本是否是虚拟脚本

    返回：
    - is_virtual: 是否是虚拟脚本
    - current_script: 当前活跃脚本信息（如果是虚拟脚本）

    虚拟脚本说明：
    - 虚拟脚本是当项目中不存在任何 Python 文件时创建的默认活跃记录
    - 虚拟脚本可以正常记录活跃时间和部署数据
    - 当生成真实的 Python 脚本后，会自动切换到真实脚本
    """
    try:
        script = metrics_service_v2.get_current_script()
        is_virtual = script and script.status == "virtual" if script else False

        return BaseResponse(
            status="ok",
            message="检查完成",
            data={
                "is_virtual": is_virtual,
                "current_script": script.model_dump(mode='json') if script else None
            }
        )
    except Exception as e:
        logger.error(f"检查虚拟脚本失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/global-active-file", response_model=BaseResponse)
async def get_global_active_file():
    """
    获取全局活跃文件信息

    返回当前内存中的全局活跃文件记录：
    - 文件路径
    - 脚本 UUID
    - 文件名
    - 最后修改时间
    - 最后活跃时间

    注意：这个数据存储在内存中，服务重启后会重新扫描工作区
    """
    try:
        active_file = metrics_service_v2.get_global_active_file()

        return BaseResponse(
            status="ok",
            message="获取全局活跃文件成功",
            data=active_file
        )
    except Exception as e:
        logger.error(f"获取全局活跃文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

__all__ = ["router"]
