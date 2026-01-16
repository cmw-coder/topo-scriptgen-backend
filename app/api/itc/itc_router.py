from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from typing import Optional
from app.models.itc.itc_models import (
    NewDeployRequest,
    RunScriptRequest,
    ExecutorRequest,
    RunScriptResponse,
    SimpleResponse,
    ItcLogFileListResponse,
    ItcLogFileContentRequest,
    ItcLogFileContentResponse,
    AllPytestJsonFilesResponse,
    ItcResultResponse
)
from app.services.itc.itc_service import itc_service, itc_log_service
from app.models.common import BaseResponse
from app.core.config import settings

router = APIRouter(tags=["ITC 自动化测试"])

@router.post("/deploy", response_model=BaseResponse)
async def deploy_environment(request: NewDeployRequest, background_tasks: BackgroundTasks):
    """
    部署测试环境 - 自动查找工作目录中的 topox 文件
    立即返回成功响应，后台异步执行部署

    请求参数：
    - **verisonPath**: 版本目录（旧拼写，兼容性），可选，与 versionpath 二选一
    - **versionpath**: 版本目录（正确拼写，推荐），可选，与 verisonPath 二选一
    - **devicetype**: 设备类型，支持simware9cen、simware9dis、simware7dis，默认simware9cen

    说明：
    1. 版本路径参数支持两种拼写：verisonPath（旧）和 versionpath（新）
    2. 如果同时提供两个参数，优先使用 versionpath
    3. 如果不提供版本路径，则不会向 ITC 服务器传递该参数
    4. Windows 路径（反斜杠）会自动转换为 ITC 期望的格式（正斜杠）
    5. 本接口立即返回成功响应，实际的部署在后台异步执行
    6. 部署完成后，设备列表会保存到全局静态变量，可通过 /deployDeviceList 接口查询
    
    """
    try:
        import getpass
        from app.services.itc.itc_service import itc_service
        import logging

        # 初始化 logger
        logger = logging.getLogger(__name__)

        # 获取用户名
        username = getpass.getuser()

        # 查找 topox 文件并获取路径信息
        from app.core.config import settings
        import os

        work_dir = settings.get_work_directory()

        # 只检查工作目录根目录下的 topox 文件
        import glob
        pattern = os.path.join(work_dir, "*.topox")
        topox_files = glob.glob(pattern)

        if topox_files:
            # 如果存在 topox 文件，调用 topo_service 的 _copy_to_aigc_target 函数拷贝
            from app.services.topo_service import topo_service
            from pathlib import Path

            default_topox_file = topox_files[0]
            topox_path = Path(default_topox_file)
            filename = topox_path.name

            # 拷贝 topox 到指定目录
            try:
                topo_service._copy_to_aigc_target(topox_path, filename)
            except Exception as copy_error:
                # 拷贝失败记录日志但不阻断部署流程
                logger.warning(f"拷贝 topox 文件到 AIGC 目标目录失败: {str(copy_error)}")

            # 使用 UNC 路径用于部署
            unc_topofile = f"//10.144.41.149/webide/aigc_tool/{username}"
        else:
            # 不存在 topox 文件，使用旧的逻辑查找
            test_scripts_dir = os.path.join(work_dir, "test_scripts")
            pattern = os.path.join(test_scripts_dir, "*.topox")
            topox_files = glob.glob(pattern)
            if not topox_files:
                pattern = os.path.join(work_dir, "**/*.topox")
                topox_files = glob.glob(pattern, recursive=True)

            if not topox_files:
                raise HTTPException(
                    status_code=404,
                    detail="未找到任何 .topox 文件"
                )

            default_topox_file = topox_files[0]

            # 使用旧的 UNC 路径格式（不包含文件名）
            unc_topofile = f"//10.144.41.149/webide/aigc_tool/{username}"


        # 保存 versionPath 和 deviceType 到全局变量
        version_path = request.get_version_path()
        device_type = request.devicetype

        if version_path:
            settings.set_version_path(version_path)
            logger.info(f"已设置版本路径: {version_path}")

        if device_type:
            settings.set_device_type(device_type)
            logger.info(f"已设置设备类型: {device_type}")

        # 启动后台部署任务
        itc_service.start_background_deploy(request, default_topox_file, unc_topofile)

        # 立即返回成功
        return BaseResponse(
            status="ok",
            message="部署任务已提交，正在后台执行中",
            data={
                "status": "deploying",
                "message": "请稍后调用接口查询部署结果"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息，包括类型和详细堆栈信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"提交部署任务失败: {error_detail}")


@router.get("/deploy-info", response_model=BaseResponse)
async def get_deploy_info():
    """
    获取部署信息

    返回当前保存的版本路径和设备类型信息
    """
    try:
        version_path = settings.get_version_path()
        device_type = settings.get_device_type()

        return BaseResponse(
            status="ok",
            message="获取部署信息成功",
            data={
                "versionPath": version_path,
                "deviceType": device_type
            }
        )
    except Exception as e:
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"获取部署信息失败: {error_detail}")



@router.get("/log", response_model=BaseResponse)
async def read_file_or_directory(
    taskId: str = Query(..., description="本次执行任务ID")
):
   
    try:
        return BaseResponse(
            status="ok",
            message="",
            content="",
            data={
                "logContent": "logContent-待补充"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"读取失败: {error_detail}")




@router.post("/run", response_model=BaseResponse)
async def run_script():
    """
    运行测试脚本（无需参数，使用固定配置）

    自动使用：
    - scriptspath: 固定路径 /opt/coder/statistics/build/aigc_tool/{username}
    - executorip: 从部署的设备列表中自动获取

    在运行前会自动：
    - 将工作目录中所有 test 开头的 .py 文件和 conftest.py 拷贝到目标目录
    - 设置目录权限为 755，文件权限为 644
    """
    try:
        from app.core.config import settings
        import os
        import shutil
        import glob
        import getpass

        # 从全局变量获取 executorip（取第一个设备的）
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            raise HTTPException(
                status_code=400,
                detail="未找到部署的设备，请先调用 /deploy 接口部署环境"
            )

        # 获取工作目录
        work_dir = settings.get_work_directory()

        # 获取用户名
        username = getpass.getuser()

        # 使用本地路径作为目标目录
        target_dir = f"/opt/coder/statistics/build/aigc_tool/{username}"

        # 查找所有需要拷贝的文件：
        # 1. 工作目录下所有 test 开头的 .py 文件
        # 2. 工作目录下的 conftest.py
        test_pattern = os.path.join(work_dir, "test*.py")
        conftest_path = os.path.join(work_dir, "conftest.py")

        test_files = glob.glob(test_pattern)
        files_to_copy = list(test_files)  # 复制列表

        # 如果 conftest.py 存在，添加到拷贝列表
        if os.path.exists(conftest_path):
            files_to_copy.append(conftest_path)

        # 拷贝文件到目标目录
        if files_to_copy:
            # 确保目标目录存在并设置权限
            os.makedirs(target_dir, exist_ok=True)

            # 设置目录权限为 755 (rwxr-xr-x)
            os.chmod(target_dir, 0o755)

            copied_files = []
            for src_file in files_to_copy:
                filename = os.path.basename(src_file)
                dst_file = os.path.join(target_dir, filename)
                shutil.copy2(src_file, dst_file)
                # 设置文件权限为 644 (rw-r--r--)
                os.chmod(dst_file, 0o644)
                copied_files.append(filename)

            # 返回时包含拷贝的文件信息
            copy_info = f"已拷贝 {len(copied_files)} 个文件: {', '.join(copied_files)}"
        else:
            copy_info = "未找到需要拷贝的测试文件"

        # 构造请求
        from app.models.itc.itc_models import RunScriptRequest
        request = RunScriptRequest(
            scriptspath=f"//10.144.41.149/webide/aigc_tool/{username}",
            executorip=executorip
        )

        result = await itc_service.run_script(request)

        if result.get("return_code") == "200":
            return BaseResponse(
                status="ok",
                message=f"脚本执行成功，{copy_info}",
                data=result
            )
        elif result.get("return_code") in ["400", "500"]:
            error_msg = result.get("return_info")
            if isinstance(error_msg, dict):
                error_msg = str(error_msg)
            raise HTTPException(
                status_code=500 if result.get("return_code") == "500" else 400,
                detail=f"{error_msg}\n{copy_info}"
            )
        else:
            raise HTTPException(status_code=500, detail=f"未知错误\n{copy_info}")

    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"运行脚本失败: {error_detail}")

@router.post("/undeploy", response_model=BaseResponse)
async def undeploy_environment(request: ExecutorRequest, background_tasks: BackgroundTasks):
    """
    释放测试环境

    - **executorip**: 执行机IP地址
    """
    try:
        result = await itc_service.undeploy_environment(request)

        if result.return_code == "200":
            return BaseResponse(
                status="ok",
                message=result.return_info,
                data=result.dict()
            )
        elif result.return_code in ["400", "500"]:
            raise HTTPException(
                status_code=500 if result.return_code == "500" else 400,
                detail=result.return_info
            )
        else:
            raise HTTPException(status_code=500, detail="未知错误")

    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"释放环境失败: {error_detail}")

@router.post("/restoreconfiguration", response_model=BaseResponse)
async def restore_configuration(request: ExecutorRequest, background_tasks: BackgroundTasks):
    """
    配置回滚

    - **executorip**: 执行机IP地址
    """
    try:
        return BaseResponse(
            status="ok",
            message="清除成功",
            data=""
        )
        # result = await itc_service.restore_configuration(request)

        # if result.return_code == "200":
        #     return BaseResponse(
        #         status="ok",
        #         message=result.return_info,
        #         data=result.dict()
        #     )
        # elif result.return_code in ["400", "500"]:
        #     raise HTTPException(
        #         status_code=500 if result.return_code == "500" else 400,
        #         detail=result.return_info
        #     )
        # else:
        #     raise HTTPException(status_code=500, detail="未知错误")

    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"配置回滚失败: {error_detail}")

@router.post("/suspend", response_model=BaseResponse)
async def suspend_script(request: ExecutorRequest, background_tasks: BackgroundTasks):
    """
    暂停脚本执行（暂定功能）

    - **executorip**: 执行机IP地址
    """
    try:
        result = await itc_service.suspend_script(request)

        if result.return_code == "200":
            return BaseResponse(
                status="ok",
                message=result.return_info,
                data=result.dict()
            )
        elif result.return_code in ["400", "500"]:
            raise HTTPException(
                status_code=500 if result.return_code == "500" else 400,
                detail=result.return_info
            )
        else:
            raise HTTPException(status_code=500, detail="未知错误")

    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"暂停脚本失败: {error_detail}")

@router.post("/resume", response_model=BaseResponse)
async def resume_script(request: ExecutorRequest, background_tasks: BackgroundTasks):
    """
    恢复脚本执行（暂定功能）

    - **executorip**: 执行机IP地址
    """
    try:
        result = await itc_service.resume_script(request)

        if result.return_code == "200":
            return BaseResponse(
                status="ok",
                message=result.return_info,
                data=result.dict()
            )
        elif result.return_code in ["400", "500"]:
            raise HTTPException(
                status_code=500 if result.return_code == "500" else 400,
                detail=result.return_info
            )
        else:
            raise HTTPException(status_code=500, detail="未知错误")

    except HTTPException:
        raise
    except Exception as e:
        # 返回原始异常信息
        import traceback
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"恢复脚本失败: {error_detail}")


# ========== ITC日志文件管理接口 ==========

@router.get("/logs/list", response_model=ItcLogFileListResponse)
async def get_itc_log_files():
    """获取ITC日志文件列表

    返回当前用户的ITC日志目录(/opt/coder/statistics/build/aigc_tool/{username}/log/)下的所有文件列表
    自动使用当前系统用户名，无需传递参数

    对于 .pytestlog.json 文件，会额外解析其中的 Result 和 elapsed_time 属性，并在响应中返回统计信息

    Returns:
        ItcLogFileListResponse: 包含ITC日志文件列表和统计信息的响应
    """
    try:
        success, message, log_files, statistics = await itc_log_service.get_itc_log_files()

        if success:
            return ItcLogFileListResponse(
                status="ok",
                message=message,
                data=log_files,
                total_count=len(log_files) if log_files else 0,
                statistics=statistics
            )
        else:
            raise HTTPException(status_code=400, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取ITC日志文件列表失败: {str(e)}")


@router.post("/logs/content", response_model=ItcLogFileContentResponse)
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


@router.get("/logs/all-pytestlog-json", response_model=AllPytestJsonFilesResponse)
async def get_all_pytestlog_json_files():
    """获取所有 .pytestlog.json 文件的内容

    返回日志目录下所有 .pytestlog.json 后缀文件的完整 JSON 内容

    返回的数据结构是一个列表，列表中每个对象是单个文件的 JSON 内容，
    并且每个对象中会包含一个 "_filename" 字段表示文件名

    Returns:
        AllPytestJsonFilesResponse: 包含所有 .pytestlog.json 文件内容的响应
    """
    try:
        success, message, all_files_content = await itc_log_service.get_all_pytestlog_json_files()

        if success:
            return AllPytestJsonFilesResponse(
                status="ok",
                message=message,
                data=all_files_content,
                total_count=len(all_files_content) if all_files_content else 0
            )
        else:
            raise HTTPException(status_code=400, detail=message)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 .pytest.json 文件内容失败: {str(e)}")


@router.get("/itcresult", response_model=ItcResultResponse)
async def get_itc_run_result():
    """获取ITC最新运行结果

    返回最近一次调用 ITC run 接口的结果。

    返回数据结构：
    - data.status: "ok" 表示执行成功，"error" 表示执行异常
    - data.message: 结果消息或错误信息

    如果没有运行记录或 aigc.json 文件不存在，message 返回 "itc 执行中请稍后"

    Returns:
        ItcResultResponse: 包含 ITC 运行结果的响应
    """
    try:
        # 从 aigc.json 读取 ITC run 结果
        result_data = itc_service._get_itc_run_result()

        return ItcResultResponse(
            data=result_data
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取ITC运行结果失败: {str(e)}")


__all__ = ["router"]
