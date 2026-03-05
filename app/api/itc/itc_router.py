from datetime import datetime
import getpass
import glob
import logging
import os
import shutil
import traceback
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from app.models.itc.itc_models import (
    NewDeployRequest,
    RunSingleScriptRequest,
    ExecutorRequest,
    ItcLogFileListResponse,
    ItcLogFileContentRequest,
    ItcLogFileContentResponse,
    AllPytestJsonFilesResponse,
    ItcResultResponse
)
from app.services.itc.itc_service import itc_service, itc_log_service
from app.models.common import BaseResponse
from app.core.config import settings

def _copy_resource_directory(work_dir: str, target_dir: str, logger: logging.Logger) -> bool:
    """
    拷贝用户工作区的 resource 目录到目标目录

    行为：
    - 如果 work_dir/resource 不存在，静默跳过（返回 True）
    - 如果 target_dir/resource 已存在，先删除再拷贝（覆盖）
    - 递归拷贝整个目录及其内容
    - 设置目录权限为 777，文件权限为 644
    - 如果拷贝失败，记录 warning 日志但返回 True（不阻断）

    Args:
        work_dir: 用户工作区目录
        target_dir: 目标目录（通常是 AIGC 工具目录）
        logger: 日志记录器

    Returns:
        bool: 始终返回 True（即使失败也不阻断流程）
    """
    try:
        resource_dir = os.path.join(work_dir, "resource")

        # 检查源目录是否存在
        if not os.path.exists(resource_dir):
            # 静默跳过
            return True

        logger.info(f"发现 resource 目录，准备拷贝到 {target_dir}")

        target_resource_dir = os.path.join(target_dir, "resource")

        # 如果目标位置已存在 resource 目录，先删除
        if os.path.exists(target_resource_dir):
            try:
                shutil.rmtree(target_resource_dir)
                logger.info(f"已删除目标目录中的旧 resource 目录")
            except Exception as e:
                logger.warning(f"删除旧 resource 目录失败: {str(e)}")
                return True

        # 拷贝 resource 目录
        try:
            shutil.copytree(resource_dir, target_resource_dir)
            logger.info(f"成功拷贝 resource 目录到 {target_resource_dir}")
        except Exception as e:
            logger.warning(f"拷贝 resource 目录失败: {str(e)}")
            return True

        # 设置目录和文件权限
        try:
            set_permissions_recursive(target_resource_dir, 0o777)
            # 单独设置文件权限为 644
            for root, dirs, files in os.walk(target_resource_dir):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    try:
                        os.chmod(file_path, 0o644)
                    except Exception as e:
                        logger.warning(f"设置文件权限失败 {file_path}: {str(e)}")
            logger.info(f"已设置 resource 目录权限")
        except Exception as e:
            logger.warning(f"设置 resource 目录权限失败: {str(e)}")

        return True

    except Exception as e:
        logger.warning(f"拷贝 resource 目录失败: {str(e)}")
        return True

router = APIRouter(tags=["ITC 自动化测试"])

@router.post("/deploy", response_model=BaseResponse)
async def deploy_environment(request: NewDeployRequest):
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
        from app.services.itc.itc_service import itc_service

        # 初始化 logger
        logger = logging.getLogger(__name__)

        # 获取用户名
        username = getpass.getuser()

        # 查找 topox 文件并获取路径信息
        work_dir = settings.get_work_directory()

        # 只检查工作目录根目录下的 topox 文件
        pattern = os.path.join(work_dir, "*.topox")
        topox_files = glob.glob(pattern)

        if topox_files:
            # 如果存在 topox 文件，调用 topo_service 的 _copy_to_aigc_target 函数拷贝
            from app.services.topo_service import topo_service

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
            unc_topofile = settings.get_aigc_tool_unc_dir(username)
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
            unc_topofile = settings.get_aigc_tool_unc_dir(username)


        # 持久化保存 versionPath 和 deviceType 到 aigc.json 文件
        version_path = request.get_version_path()
        device_type = request.deviceType
        itc_service.save_deploy_info(version_path, device_type)
        logger.info(f"已保存部署信息: version_path={version_path}, device_type={device_type}")

        # ========== 度量 v2：开始部署 ==========
        deploy_id = None
        try:
            from app.services.metrics_service_v2 import metrics_service_v2
            deploy_id = metrics_service_v2.start_deploy(
                topox_file=default_topox_file,
                version_path=version_path,
                device_type=device_type or "simware9cen"
            )
            logger.info(f"度量 v2: 开始部署, deploy_id={deploy_id}")
        except Exception as metrics_error:
            logger.warning(f"度量 v2: 开始部署失败: {metrics_error}")
        # =====================================

        # 启动后台部署任务
        itc_service.start_background_deploy(request, default_topox_file, unc_topofile, deploy_id)

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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"提交部署任务失败: {error_detail}")


@router.get("/deploy-info", response_model=BaseResponse)
async def get_deploy_info():
    """
    获取部署信息

    返回当前保存的版本路径和设备类型信息
    从 aigc.json 文件读取，支持多 worker 进程和服务重启
    """
    try:
        # 从 aigc.json 文件读取部署信息
        deploy_info = itc_service.get_deploy_info()
        version_path = deploy_info.get("version_path")
        device_type = deploy_info.get("device_type")

        return BaseResponse(
            status="ok",
            message="获取部署信息成功",
            data={
                "versionPath": version_path,
                "deviceType": device_type
            }
        )
    except Exception as e:
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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"读取失败: {error_detail}")




@router.post("/run", response_model=BaseResponse)
async def run_script(request: RunSingleScriptRequest):
    """
    运行测试脚本

    请求参数（JSON Body）：
    - **script_path**: 要运行的脚本文件名（如 conftest.py、test_xxx.py），可选
      - 如果为空或空字符串，则拷贝工作区下所有 test_*.py 和 conftest.py 文件
      - 如果为 conftest.py，则不仅拷贝该文件，还会将工作区中的 test_case_demo.py 拷贝到目标目录

    自动使用：
    - scriptspath: 由 settings.get_aigc_tool_unc_dir() 指定的 UNC 路径
    - executorip: 从部署的设备列表中自动获取

    在运行前会自动：
    - 删除目标目录下所有 test_*.py 和 conftest.py 文件
    - 根据参数拷贝相应文件到目标目录
    - 设置目录权限为 755，文件权限为 644
    """
    try:
        logger = logging.getLogger(__name__)

        # 从全局变量获取 executorip（取第一个设备的）
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            error_msg = "未找到部署的设备，请先部署组网占用环境"
            # 更新 aigc.json 中的 ITC 状态为 error
            itc_service._save_itc_run_result({
                "return_code": "400",
                "return_info": error_msg,
                "result": None
            })
            logger.error(f"未找到执行机IP: {error_msg}")
            raise HTTPException(
                status_code=400,
                detail=error_msg
            )

        # 获取工作目录
        work_dir = settings.get_work_directory()

        # 获取用户名
        username = getpass.getuser()

        # 使用本地路径作为目标目录
        target_dir = settings.get_aigc_tool_local_dir(username)

        # 确保目标目录存在并设置权限为 777
        os.makedirs(target_dir, exist_ok=True)

        # 递归设置目录权限为 777
        def set_permissions_recursive(path, mode):
            """递归设置目录及其所有内容的权限"""
            try:
                os.chmod(path, mode)
                for root, dirs, files in os.walk(path):
                    for dir_name in dirs:
                        dir_path = os.path.join(root, dir_name)
                        try:
                            os.chmod(dir_path, mode)
                        except Exception as e:
                            logger.warning(f"设置目录权限失败 {dir_path}: {e}")
                    for file_name in files:
                        file_path = os.path.join(root, file_name)
                        try:
                            os.chmod(file_path, mode)
                        except Exception as e:
                            logger.warning(f"设置文件权限失败 {file_path}: {e}")
            except Exception as e:
                logger.warning(f"设置根目录权限失败 {path}: {e}")

        set_permissions_recursive(target_dir, 0o777)
        logger.info(f"已设置 AIGC 工具目录权限: {target_dir}")

        # 获取请求的脚本路径
        script_path = request.script_path

        # ========== 第1步：删除目标目录下所有 conftest.py 和 test_*.py 文件 ==========
        deleted_files = []
        test_pattern = os.path.join(target_dir, "test_*.py")
        test_files = glob.glob(test_pattern)
        for file_path in test_files:
            try:
                os.remove(file_path)
                deleted_files.append(os.path.basename(file_path))
                logger.info(f"已删除目标目录中的测试文件: {os.path.basename(file_path)}")
            except Exception as e:
                logger.warning(f"删除文件失败 {file_path}: {str(e)}")

        conftest_pattern = os.path.join(target_dir, "conftest.py")
        if os.path.exists(conftest_pattern):
            try:
                os.remove(conftest_pattern)
                deleted_files.append("conftest.py")
                logger.info(f"已删除目标目录中的 conftest.py")
            except Exception as e:
                logger.warning(f"删除 conftest.py 失败: {str(e)}")

        if deleted_files:
            logger.info(f"已删除目标目录中的 {len(deleted_files)} 个文件: {', '.join(deleted_files)}")

        # ========== 第2步：根据 script_path 参数拷贝文件 ==========
        # 设置目录权限为 755 (rwxr-xr-x)
        try:
            os.chmod(target_dir, 0o777)
        except Exception as e:
            logger.warning(f"设置目标目录权限失败: {str(e)}")

        copied_files = []

        # 判断 script_path 是否为空或空字符串
        if not script_path or script_path.strip() == "":
            # ========== 情况1：script_path 为空，拷贝所有 test_*.py 和 conftest.py ==========
            logger.info(f"script_path 为空，拷贝工作区下所有测试文件")

            # 查找工作区下所有 test_*.py 文件
            test_pattern = os.path.join(work_dir, "test_*.py")
            test_source_files = glob.glob(test_pattern)
            for source_file in test_source_files:
                try:
                    script_filename = os.path.basename(source_file)
                    dst_file = os.path.join(target_dir, script_filename)
                    shutil.copy2(source_file, dst_file)
                    try:
                        os.chmod(dst_file, 0o644)
                    except Exception as e:
                        logger.warning(f"设置文件权限失败 {script_filename}: {str(e)}")
                    copied_files.append(script_filename)
                    logger.info(f"已拷贝测试文件: {script_filename} -> {dst_file}")
                except Exception as e:
                    logger.warning(f"拷贝文件失败 {source_file}: {str(e)}")

            # 查找并拷贝 conftest.py
            conftest_source = os.path.join(work_dir, "conftest.py")
            if os.path.exists(conftest_source):
                dst_conftest = os.path.join(target_dir, "conftest.py")
                shutil.copy2(conftest_source, dst_conftest)
                try:
                    os.chmod(dst_conftest, 0o644)
                except Exception as e:
                    logger.warning(f"设置文件权限失败 conftest.py: {str(e)}")
                copied_files.append("conftest.py")
                logger.info(f"已拷贝 conftest.py -> {dst_conftest}")

        elif os.path.basename(script_path) == "conftest.py":
            # ========== 情况2：script_path 是 conftest.py ==========
            logger.info(f"script_path 是 conftest.py，拷贝并创建 test_case_demo.py")

            # 构建源文件的完整路径
            if os.path.isabs(script_path):
                source_file = script_path
            else:
                source_file = os.path.join(work_dir, script_path)

            # 检查源文件是否存在
            if not os.path.exists(source_file):
                raise HTTPException(
                    status_code=404,
                    detail=f"脚本文件不存在: {source_file}"
                )

            # 拷贝 conftest.py
            dst_conftest = os.path.join(target_dir, "conftest.py")
            shutil.copy2(source_file, dst_conftest)
            try:
                os.chmod(dst_conftest, 0o644)
            except Exception as e:
                logger.warning(f"设置文件权限失败 conftest.py: {str(e)}")
            copied_files.append("conftest.py")
            logger.info(f"已拷贝 conftest.py -> {dst_conftest}")

            # 拷贝项目中的 test_case_demo.py 文件
            demo_source = os.path.join(os.path.dirname(__file__), "..","..", "models", "itc", "test_case_demo.py")
            demo_source = os.path.abspath(demo_source)
            if os.path.exists(demo_source):
                demo_dst = os.path.join(target_dir, "test_case_demo.py")
                shutil.copy2(demo_source, demo_dst)
                try:
                    os.chmod(demo_dst, 0o644)
                except Exception as e:
                    logger.warning(f"设置文件权限失败 test_case_demo.py: {str(e)}")
                copied_files.append("test_case_demo.py")
                logger.info(f"已拷贝 test_case_demo.py -> {demo_dst}")
            else:
                logger.warning(f"项目中未找到 test_case_demo.py 文件: {demo_source}")

        else:
            # ========== 情况3：正常拷贝指定脚本文件 ==========
            # 构建源文件的完整路径
            if os.path.isabs(script_path):
                source_file = script_path
            else:
                source_file = os.path.join(work_dir, script_path)

            # 检查源文件是否存在
            if not os.path.exists(source_file):
                raise HTTPException(
                    status_code=404,
                    detail=f"脚本文件不存在: {source_file}"
                )

            # 获取文件名
            script_filename = os.path.basename(source_file)

            # 拷贝用户指定的脚本文件
            dst_script_file = os.path.join(target_dir, script_filename)
            shutil.copy2(source_file, dst_script_file)
            try:
                os.chmod(dst_script_file, 0o644)
            except Exception as e:
                logger.warning(f"设置文件权限失败 {script_filename}: {str(e)}")
            copied_files.append(script_filename)
            logger.info(f"已拷贝脚本文件: {script_filename} -> {dst_script_file}")


            # 查找并拷贝 conftest.py
            conftest_source = os.path.join(work_dir, "conftest.py")
            if os.path.exists(conftest_source) and script_filename != "conftest.py":
                dst_conftest = os.path.join(target_dir, "conftest.py")
                shutil.copy2(conftest_source, dst_conftest)
                try:
                    os.chmod(dst_conftest, 0o644)
                except Exception as e:
                    logger.warning(f"设置文件权限失败 conftest.py: {str(e)}")
                copied_files.append("conftest.py")
                logger.info(f"已拷贝 conftest.py -> {dst_conftest}")

        copy_info = f"已删除 {len(deleted_files)} 个旧文件，已拷贝 {len(copied_files)} 个文件: {', '.join(copied_files)}"

        # 构造请求
        from app.models.itc.itc_models import RunScriptRequest
        itc_request = RunScriptRequest(
            scriptspath=settings.get_aigc_tool_unc_dir(username),
            executorip=executorip
        )

        # ========== 度量 v2：记录ITC run开始时间 ==========
        from datetime import datetime
        itc_run_start_time = datetime.now()
        # ==============================================

        result = await itc_service.run_script(itc_request)

        # ========== 度量 v2：记录 ITC run 耗时到对应脚本 ==========
        itc_run_end_time = datetime.now()
        itc_run_duration = (itc_run_end_time - itc_run_start_time).total_seconds()
        try:
            from app.services.metrics_service_v2 import metrics_service_v2

            # 确定脚本路径：如果传入了 script_path 且不为空，使用它；否则记录到 conftest.py 对应的度量记录
            script_full_path = None
            if script_path and script_path.strip():
                # 传入的 script_path 可能是相对路径，需要构建完整路径
                if os.path.isabs(script_path):
                    script_full_path = script_path
                else:
                    script_full_path = os.path.join(work_dir, script_path)
            else:
                # 当 script_path 为空时，记录到 conftest.py 文件对应的度量记录数据中
                conftest_source = os.path.join(work_dir, "conftest.py")
                if os.path.exists(conftest_source):
                    script_full_path = conftest_source
                    logger.info(f"script_path 为空，将 ITC 运行时间记录到 conftest.py 对应的度量记录")
                else:
                    logger.info(f"script_path 为空且工作区中不存在 conftest.py，将记录到当前活跃脚本")

            # 记录ITC run耗时（如果提供了 script_path，会自动找到或创建该脚本并设为活跃脚本）
            success = metrics_service_v2.add_itc_run_duration(
                duration=itc_run_duration,
                return_code=result.get("return_code", "unknown"),
                script_path=script_full_path
            )
            if success:
                if script_full_path:
                    logger.info(f"度量 v2: 记录 ITC run 耗时到脚本 {os.path.basename(script_full_path)}, duration={itc_run_duration}秒")
                else:
                    logger.info(f"度量 v2: 记录 ITC run 耗时到当前活跃脚本, duration={itc_run_duration}秒")
        except Exception as metrics_error:
            logger.warning(f"度量 v2: 记录 ITC run 失败: {metrics_error}")
        # ======================================================

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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"运行脚本失败: {error_detail}")

@router.post("/undeploy", response_model=BaseResponse)
async def undeploy_environment(request: ExecutorRequest):
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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"释放环境失败: {error_detail}")

@router.post("/restoreconfiguration", response_model=BaseResponse)
async def restore_configuration(request: ExecutorRequest):
    """
    配置回滚

    - **executorip**: 执行机IP地址
    """
    try:
        result = await itc_service.restore_configuration(request)

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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"配置回滚失败: {error_detail}")

@router.post("/suspend", response_model=BaseResponse)
async def suspend_script(request: ExecutorRequest):
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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"暂停脚本失败: {error_detail}")

@router.post("/resume", response_model=BaseResponse)
async def resume_script(request: ExecutorRequest):
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
        error_detail = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=f"恢复脚本失败: {error_detail}")


# ========== ITC日志文件管理接口 ==========

@router.get("/logs/list", response_model=ItcLogFileListResponse)
async def get_itc_log_files():
    """获取ITC日志文件列表

    返回当前用户的ITC日志目录(settings.get_aigc_tool_local_log_dir())下的所有文件列表
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


@router.get("/itc/itcresult", response_model=ItcResultResponse)
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
