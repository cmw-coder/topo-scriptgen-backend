#!/usr/bin/env python3
"""
Minimal ITC API - FastAPI 主应用
独立的最小化 FastAPI 项目，用于 topox 部署和脚本执行

功能特性：
- 使用 ITC newdeploy 接口部署 topox 文件
- 每次部署创建新的临时目录（格式: temp_YYYYMMDD_HHMMSS）
- 所有文件（topox 和脚本）都保存到当前临时目录
- 自动设置临时目录权限为 777（任意用户可读写）
- 智能临时目录管理：
  * 上传包含 .topox 文件时：创建新临时目录
  * 只上传脚本文件时：复用上一次部署的临时目录
"""

import asyncio
import logging
import os
import sys
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 导入本地模块
from config import settings
from models import BaseResponse, DeployResponse, RunResponse, HealthResponse
from itc_client import create_itc_client
from exec_ip_mapper import save_mapping, get_mapping, delete_mapping


# ========== 配置日志 ==========
def setup_logging():
    """设置日志配置"""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format=settings.LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)]
    )


# ========== 应用生命周期管理 ==========
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的处理"""
    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info(f"启动 {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"基础目录: {settings.BASE_DIR}")
    logger.info(f"ITC 服务器: {settings.ITC_SERVER_URL}")
    logger.info("=" * 50)

    # 确保基础目录存在
    base_dir = settings.get_base_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"基础目录已准备: {base_dir}")

    # 创建 ITC 客户端
    app.state.itc_client = create_itc_client(
        base_url=settings.ITC_SERVER_URL,
        timeout=settings.ITC_REQUEST_TIMEOUT
    )
    logger.info("ITC 客户端已初始化")

    # 初始化第一个临时目录
    initial_temp_dir = settings.create_temp_dir()
    logger.info(f"初始临时目录已创建: {initial_temp_dir}")

    yield

    # 关闭时执行
    logger.info("应用正在关闭...")


# ========== 创建 FastAPI 应用 ==========
def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    setup_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # 添加 CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ========== 全局异常处理 ==========
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """HTTP 异常处理"""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "message": exc.detail,
            }
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """通用异常处理"""
        logger = logging.getLogger(__name__)
        logger.error(f"未处理的异常: {str(exc)}", exc_info=True)

        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"服务器内部错误: {str(exc)}",
            }
        )

    # ========== 健康检查端点 ==========
    @app.get("/health", response_model=HealthResponse, tags=["健康检查"])
    async def health_check():
        """健康检查端点"""
        return HealthResponse(
            status="ok",
            project=settings.PROJECT_NAME,
            version=settings.VERSION
        )

    @app.get("/", tags=["根路径"])
    async def root():
        """根路径"""
        temp_dir_name = settings.get_temp_dir_name()
        temp_dir = settings.get_temp_dir()
        return {
            "message": f"欢迎使用 {settings.PROJECT_NAME}",
            "version": settings.VERSION,
            "docs_url": "/docs",
            "endpoints": {
                "upload_topox": "/api/v1/upload-topox",
                "upload_scripts": "/api/v1/upload-scripts",
                "undeploy": "/api/v1/undeploy",
                "health": "/health",
                "temp_info": "/api/v1/temp-info"
            },
            "current_temp_dir": {
                "name": temp_dir_name,
                "local_path": str(temp_dir) if temp_dir else None,
                "unc_path": settings.get_temp_dir_uname() if temp_dir_name else None
            }
        }

    @app.get("/api/v1/temp-info", tags=["ITC API"])
    async def get_temp_info():
        """获取当前临时目录信息"""
        temp_dir_name = settings.get_temp_dir_name()
        temp_dir = settings.get_temp_dir()

        return {
            "status": "ok",
            "temp_dir_name": temp_dir_name,
            "temp_dir_local_path": str(temp_dir) if temp_dir else None,
            "temp_dir_unc_path": settings.get_temp_dir_uname() if temp_dir_name else None,
            "base_dir": settings.BASE_DIR,
            "base_unc_dir": settings.BASE_UNC_DIR
        }

    # ========== API 端点 ==========

    @app.post("/api/v1/upload-topox", response_model=DeployResponse, tags=["ITC API"])
    async def upload_topox_and_deploy(
        topox_file: UploadFile = File(..., description="Topox 文件"),
        version_path: str = Form(None, description="版本目录路径"),
        device_type: str = Form("simware9cen", description="设备类型"),
        user: str = Form(None, description="用户标识")
    ):
        """
        上传 topox 文件并部署组网

        1. 创建新的临时目录（每次部署都会创建新的临时目录）
        2. 接收上传的 topox 文件
        3. 保存到临时目录并设置权限
        4. 调用 ITC newdeploy 接口
        5. 返回部署结果
        """
        logger = logging.getLogger(__name__)

        try:
            # 验证文件扩展名
            if not topox_file.filename.endswith(".topox"):
                raise HTTPException(
                    status_code=400,
                    detail="只支持 .topox 文件"
                )

            # 创建新的临时目录（每次部署刷新）
            temp_dir_name = settings.create_temp_dir(user=user)
            temp_dir = settings.get_temp_dir()
            logger.info(f"创建新临时目录: {temp_dir}")

            # 保存 topox 文件到临时目录
            file_path = temp_dir / topox_file.filename
            logger.info(f"保存 topox 文件到临时目录: {file_path}")

            with open(file_path, "wb") as f:
                content = await topox_file.read()
                f.write(content)

            # 设置文件权限为 777
            settings.set_directory_permissions(temp_dir)

            # 验证文件大小
            file_size = file_path.stat().st_size
            if file_size > settings.MAX_FILE_SIZE:
                file_path.unlink()
                raise HTTPException(
                    status_code=400,
                    detail=f"文件过大: {file_size} 字节（最大 {settings.MAX_FILE_SIZE} 字节）"
                )

            logger.info(f"文件已保存到临时目录: {topox_file.filename} ({file_size} 字节)")
            logger.info(f"临时目录 UNC 路径: {settings.get_temp_dir_uname()}")

            # topofile 参数只传临时目录路径（不包含文件名）
            topofile_unc = settings.get_temp_dir_uname()
            logger.info(f"Topofile UNC 路径（目录级）: {topofile_unc}")

            # 调用 ITC newdeploy 接口
            itc_client = app.state.itc_client
            deploy_result = await itc_client.newdeploy(
                topofile_unc=topofile_unc,
                versionpath=version_path,
                device_type=device_type
            )

            # 检查部署结果
            return_code = deploy_result.get("return_code")
            return_info = deploy_result.get("return_info")
            result = deploy_result.get("result")

            if return_code == "200":
                logger.info(f"部署成功: {return_info}")

                # Extract executor_ip from ITC response
                executor_ip = None
                if return_info and isinstance(return_info, dict):
                    executor_ip = return_info.get("executorip")

                # Save mapping if executor_ip is available
                if executor_ip:
                    try:
                        save_mapping(
                            executor_ip=executor_ip,
                            temp_dir_name=temp_dir_name,
                            temp_dir_path=str(temp_dir),
                            temp_dir_unc=settings.get_temp_dir_uname(),
                            user=user
                        )
                        logger.info(f"Saved mapping: executor_ip={executor_ip}, temp_dir={temp_dir_name}, user={user}")
                    except Exception as e:
                        logger.error(f"Failed to save mapping: {e}")

                return DeployResponse(
                    status="ok",
                    message=f"Topox 文件已保存到临时目录 ({temp_dir_name}) 并部署成功",
                    data={
                        # ITC 完整响应信息（透传）
                        "return_code": return_code,
                        "return_info": return_info,
                        "result": result,
                        # 临时目录信息
                        "temp_dir_name": temp_dir_name,
                        "temp_dir_path": str(temp_dir),
                        "temp_dir_unc": settings.get_temp_dir_uname(),
                        # 映射信息
                        "executor_ip": executor_ip,
                        "user": user
                    }
                )
            else:
                logger.error(f"部署失败: {return_info}")
                return DeployResponse(
                    status="error",
                    message=f"部署失败: {return_info}",
                    data={
                        # ITC 完整响应信息（透传）
                        "return_code": return_code,
                        "return_info": return_info,
                        "result": result,
                        # 临时目录信息
                        "temp_dir_name": temp_dir_name
                    }
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"处理 topox 上传时出错: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"处理 topox 上传时出错: {str(e)}"
            )

    @app.post("/api/v1/upload-scripts", response_model=RunResponse, tags=["ITC API"])
    async def upload_scripts_and_run(
        script_files: list[UploadFile] = File(..., description="脚本文件列表"),
        executor_ip: str = Form(..., description="执行机 IP 地址")
    ):
        """
        批量上传文件并运行脚本（支持脚本和 topox 文件）

        逻辑：
        1. 如果上传的文件列表中包含 .topox 文件：
           - 创建独立的临时目录（不影响全局临时目录状态）
           - 保存所有文件（包括 topox 和脚本）
           - 调用 ITC run_scripts 接口执行脚本
        2. 如果只上传脚本文件（不含 .topox）：
           - 使用上一次通过 /api/v1/upload-topox 部署的临时目录
           - 保存脚本文件
           - 调用 ITC run_scripts 接口执行脚本

        注意：
        - 只有 /api/v1/upload-topox 接口会更新全局临时目录
        - upload-scripts 包含 topox 时创建的临时目录是独立的，不影响后续调用
        """
        logger = logging.getLogger(__name__)

        try:
            # 验证执行机 IP
            if not executor_ip:
                raise HTTPException(
                    status_code=400,
                    detail="必须提供 executor_ip 参数"
                )

            # 检查上传文件中是否包含 .topox 文件
            has_topox = any(
                f.filename and f.filename.endswith(".topox")
                for f in script_files
            )

            if has_topox:
                # ========== 包含 topox 文件：创建独立的临时目录（不影响全局状态） ==========
                logger.info("检测到 .topox 文件，将创建独立的临时目录")

                # 创建独立的临时目录（不更新全局 _temp_dir_name）
                temp_dir_name, temp_dir = settings.create_temp_dir_standalone()
                logger.info(f"创建独立临时目录: {temp_dir}")

            else:
                # ========== 只包含脚本文件：查询映射文件获取临时目录 ==========
                logger.info("未检测到 .topox 文件，将查询映射文件获取临时目录")

                try:
                    # Query mapping using executor_ip
                    mapping = get_mapping(executor_ip)

                    if mapping is None:
                        raise HTTPException(
                            status_code=400,
                            detail=f"未找到 executor_ip {executor_ip} 对应的临时目录，请先调用 upload-topox 进行部署"
                        )

                    # Validate temp directory still exists
                    if not Path(mapping.temp_dir_path).exists():
                        raise HTTPException(
                            status_code=400,
                            detail=f"临时目录 {mapping.temp_dir_name} 不存在，请重新部署"
                        )

                    # Use mapped temp directory
                    temp_dir = Path(mapping.temp_dir_path)
                    temp_dir_name = mapping.temp_dir_name
                    logger.info(f"使用映射的临时目录: {temp_dir}")

                except FileNotFoundError:
                    raise HTTPException(
                        status_code=400,
                        detail="映射文件不存在，请先调用 upload-topox 进行部署"
                    )
                except Exception as e:
                    if isinstance(e, HTTPException):
                        raise
                    logger.error(f"读取映射文件时出错: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail="映射文件损坏，请联系管理员"
                    )

            # 保存所有文件到临时目录
            saved_files = []
            for upload_file in script_files:
                # 验证文件扩展名
                file_ext = Path(upload_file.filename).suffix.lower()
                if file_ext not in settings.ALLOWED_TOPOX_EXTENSIONS and \
                   file_ext not in settings.ALLOWED_SCRIPT_EXTENSIONS:
                    logger.warning(f"跳过不支持的文件类型: {upload_file.filename}")
                    continue

                # 保存文件到临时目录
                file_path = temp_dir / upload_file.filename
                logger.info(f"保存文件到临时目录: {file_path}")

                with open(file_path, "wb") as f:
                    content = await upload_file.read()
                    f.write(content)

                file_size = file_path.stat().st_size
                saved_files.append({
                    "filename": upload_file.filename,
                    "size": file_size,
                    "path": str(file_path)
                })
                logger.info(f"文件已保存到临时目录: {upload_file.filename} ({file_size} 字节)")

            if not saved_files:
                raise HTTPException(
                    status_code=400,
                    detail="没有有效的文件被上传"
                )

            # 设置临时目录及其所有文件的权限为 777
            settings.set_directory_permissions(temp_dir)

            logger.info(f"共保存 {len(saved_files)} 个文件到临时目录: {temp_dir_name}")

            # 获取临时目录的 UNC 路径
            # 注意：standalone 临时目录需要手动构建 UNC 路径
            if has_topox:
                scripts_unc_path = f"{settings.BASE_UNC_DIR}/{temp_dir_name}"
            else:
                # Use mapped temp_dir_unc from mapping
                mapping = get_mapping(executor_ip)
                scripts_unc_path = mapping.temp_dir_unc if mapping else settings.get_temp_dir_uname()
            logger.info(f"临时目录 UNC 路径: {scripts_unc_path}")

            # 调用 ITC 运行接口
            itc_client = app.state.itc_client
            run_result = await itc_client.run_scripts(
                scripts_unc_path=scripts_unc_path,
                executor_ip=executor_ip
            )

            # 检查运行结果
            return_code = run_result.get("return_code")
            return_info = run_result.get("return_info")
            result = run_result.get("result")

            if return_code == "200":
                return RunResponse(
                    status="ok",
                    message=f"已保存 {len(saved_files)} 个文件到临时目录 ({temp_dir_name}) 并执行成功",
                    data={
                        # ITC 完整响应信息（透传）
                        "return_code": return_code,
                        "return_info": return_info,
                        "result": result,
                        # 保存的文件信息
                        "saved_files": saved_files,
                        # 临时目录信息
                        "temp_dir_name": temp_dir_name,
                        "temp_dir_path": str(temp_dir),
                        "temp_dir_unc": scripts_unc_path
                    }
                )
            else:
                logger.error(f"脚本执行失败")
                return RunResponse(
                    status="error",
                    message=f"脚本执行失败: {return_info}",
                    data={
                        # ITC 完整响应信息（透传）
                        "return_code": return_code,
                        "return_info": return_info,
                        "result": result,
                        # 保存的文件信息
                        "saved_files": saved_files,
                        # 临时目录信息
                        "temp_dir_name": temp_dir_name
                    }
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"处理文件上传时出错: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"处理文件上传时出错: {str(e)}"
            )

    @app.post("/api/v1/undeploy", response_model=BaseResponse, tags=["ITC API"])
    async def undeploy_environment(
        executor_ip: str = Form(..., description="执行机 IP 地址")
    ):
        """
        卸载组网环境

        1. 根据执行机 IP 调用 ITC 卸载接口
        2. 释放占用的网络资源
        3. 返回卸载结果
        """
        logger = logging.getLogger(__name__)

        try:
            # 验证执行机 IP
            if not executor_ip:
                raise HTTPException(
                    status_code=400,
                    detail="必须提供 executor_ip 参数"
                )

            logger.info(f"开始卸载执行机 {executor_ip} 的组网环境")

            # 调用 ITC 卸载接口
            itc_client = app.state.itc_client
            undeploy_result = await itc_client.undeploy(
                executor_ip=executor_ip
            )

            # Delete mapping regardless of ITC result
            try:
                deleted = delete_mapping(executor_ip)
                if deleted:
                    logger.info(f"Deleted mapping: executor_ip={executor_ip}")
                else:
                    logger.info(f"No mapping found for executor_ip: {executor_ip}")
            except Exception as e:
                logger.error(f"Failed to delete mapping: {e}")
                # Mapping deletion failure doesn't affect response

            # 检查卸载结果
            return_code = undeploy_result.get("return_code")
            return_info = undeploy_result.get("return_info")
            result = undeploy_result.get("result")

            if return_code == "200":
                logger.info(f"卸载成功: {return_info}")
                return BaseResponse(
                    status="ok",
                    message=f"执行机 {executor_ip} 的组网环境已成功卸载",
                    data={
                        # ITC 完整响应信息（透传）
                        "return_code": return_code,
                        "return_info": return_info,
                        "result": result,
                        # 执行机信息
                        "executor_ip": executor_ip
                    }
                )
            else:
                logger.error(f"卸载失败: {return_info}")
                return BaseResponse(
                    status="error",
                    message=f"卸载失败: {return_info}",
                    data={
                        # ITC 完整响应信息（透传）
                        "return_code": return_code,
                        "return_info": return_info,
                        "result": result,
                        # 执行机信息
                        "executor_ip": executor_ip
                    }
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"卸载组网环境时出错: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"卸载组网环境时出错: {str(e)}"
            )

    return app


# ========== 创建应用实例 ==========
app = create_app()


# ========== 主函数 ==========
def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description=settings.PROJECT_NAME)
    parser.add_argument(
        "--host",
        default=settings.HOST,
        help=f"服务器主机地址 (默认: {settings.HOST})"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=settings.PORT,
        help=f"服务器端口 (默认: {settings.PORT})"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用自动重载 (开发模式)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="工作进程数量 (默认: 1)"
    )

    args = parser.parse_args()

    # 显示启动信息
    print("=" * 60)
    print(f"[START] Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"[INFO] Description: {settings.DESCRIPTION}")
    print(f"[INFO] Server URL: http://{args.host}:{args.port}")
    print(f"[INFO] API Docs: http://{args.host}:{args.port}/docs")
    print(f"[INFO] Base Directory: {settings.BASE_DIR}")
    print(f"[INFO] ITC Server: {settings.ITC_SERVER_URL}")
    print(f"[INFO] Temporary Directory: temp_YYYYMMDD_HHMMSS")
    print(f"[INFO] Using ITC newdeploy endpoint")
    if args.reload:
        print("[INFO] Auto-reload: Enabled")
    print("=" * 60)

    # 启动服务器
    try:
        uvicorn.run(
            "main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=args.workers if not args.reload else 1,
            log_level=settings.LOG_LEVEL.lower(),
            access_log=True,
        )
    except KeyboardInterrupt:
        print("\n[STOP] Server stopped")
    except Exception as e:
        print(f"[ERROR] Failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
