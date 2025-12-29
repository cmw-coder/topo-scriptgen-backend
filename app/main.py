import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.config import settings
from app.core.path_manager import path_manager
from app.api import files, claude
from app.api import topo_simple as topo
from app.api.itc.itc_router import router as itc_router

# 注意: Python 3.13 + Windows 事件循环策略已在 main.py 中设置
# 这里不需要重复设置


# 配置日志
def setup_logging():
    """设置日志配置
    AI_FingerPrint_UUID: 20251224-mO3vjOth
    """
    # 创建日志目录
    logs_dir = path_manager.get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 配置根日志记录器
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper()),
        format=settings.LOG_FORMAT,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logs_dir / "app.log", encoding="utf-8", mode="a"),
        ],
    )

    # 设置第三方库日志级别
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)


# 应用生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭时的处理"""
    # 启动时执行
    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info(f"启动 {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"工作目录: {path_manager.get_project_root()}")
    logger.info(f"日志目录: {path_manager.get_logs_dir()}")
    logger.info(f"脚本目录: {path_manager.get_scripts_dir()}")
    logger.info(f"Topox目录: {path_manager.get_topox_dir()}")
    logger.info("=" * 50)

    # 检查并初始化部署状态
    logger.info("检查 aigc.json 并初始化部署状态...")
    settings.initialize_deploy_status_from_aigc_json()
    initial_status = settings.get_deploy_status()
    logger.info(f"初始部署状态: {initial_status}")
    logger.info("=" * 50)

    yield

    # 关闭时执行
    logger.info("应用正在关闭...")


# 创建FastAPI应用
def create_app() -> FastAPI:
    """创建FastAPI应用实例"""
    # 设置日志
    setup_logging()

    # 创建应用
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 添加CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境中应该限制具体的域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 添加请求日志中间件
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = (
            request.state.start_time if hasattr(request.state, "start_time") else None
        )
        response = await call_next(request)

        # 记录请求日志
        logger = logging.getLogger("requests")
        logger.info(
            f"{request.method} {request.url.path} - "
            f"状态码: {response.status_code} - "
            f"客户端: {request.client.host if request.client else 'unknown'}"
        )

        return response

    # 注册路由
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(topo.router, prefix="")  # topo路由已经在内部定义了完整路径
    app.include_router(claude.router, prefix="/api/v1")
    app.include_router(itc_router, prefix="/api/v1")

    # 健康检查端点
    @app.get("/healthz", response_class=PlainTextResponse, tags=["健康检查"])
    async def health_check():
        """健康检查端点"""
        return "OK"

    @app.get("/health", response_class=PlainTextResponse, tags=["健康检查"])
    async def health_check_extended():
        """扩展健康检查端点"""
        return "OK"

    # 项目信息端点（重命名，避免与根路径冲突）
    @app.get("/api/info", tags=["项目信息"])
    async def get_api_info():
        """获取API信息（JSON格式）"""
        return {
            "message": f"欢迎使用 {settings.PROJECT_NAME}",
            "version": settings.VERSION,
            "docs_url": "/docs",
            "redoc_url": "/redoc",
            "work_directory": str(path_manager.get_project_root()),
            "api_endpoints": {
                "文件操作": "/api/v1/files",
                "拓扑管理": "/api/v1/topo",
                "Claude Code": "/api/v1/claude",
                "WebSocket": "/api/v1/claude/ws/{task_id}",
            },
        }

    @app.get("/info", tags=["项目信息"])
    async def get_project_info():
        """获取项目信息"""
        return {
            "project_name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "description": settings.DESCRIPTION,
            "directories": {
                "work_directory": str(path_manager.get_project_root()),
                "scripts_directory": str(path_manager.get_scripts_dir()),
                "logs_directory": str(path_manager.get_logs_dir()),
                "topox_directory": str(path_manager.get_topox_dir()),
            },
            "settings": {
                "max_file_size": settings.MAX_FILE_SIZE,
                "allowed_extensions": list(settings.ALLOWED_EXTENSIONS),
                "claude_timeout": settings.CLAUDE_CODE_TIMEOUT,
            },
        }

    # 设置工作目录的端点
    @app.post("/api/v1/path/set", tags=["路径管理"])
    async def set_work_directory(path: str):
        """设置项目工作目录"""
        try:
            path_manager.set_project_root(path)
            logger = logging.getLogger(__name__)
            logger.info(f"工作目录已更新为: {path}")

            return {
                "status": "ok",
                "message": f"工作目录已设置为: {path}",
                "new_directory": str(path_manager.get_project_root()),
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/v1/path/get", tags=["路径管理"])
    async def get_work_directory():
        """获取当前工作目录"""
        return {
            "status": "ok",
            "work_directory": str(path_manager.get_project_root()),
            "scripts_directory": str(path_manager.get_scripts_dir()),
            "logs_directory": str(path_manager.get_logs_dir()),
            "topox_directory": str(path_manager.get_topox_dir()),
        }

    # 挂载静态文件（支持 SPA 前端）
    public_dir = Path(__file__).parent.parent / "public"
    if public_dir.exists():
        # 静态资源挂载到 /assets 等路径
        app.mount(
            "/assets", StaticFiles(directory=str(public_dir / "assets")), name="assets"
        )
        if (public_dir / "vite.svg").exists():
            app.mount(
                "/vite.svg",
                StaticFiles(directory=str(public_dir), html=False),
                name="favicon",
            )

        logger = logging.getLogger(__name__)
        logger.info("Serving static files from %s", public_dir)
    else:
        logger = logging.getLogger(__name__)
        logger.warning(
            "Public directory %s not found; static files will not be served.",
            public_dir,
        )

    # SPA catch-all 路由：所有未被 API 匹配的路径返回 index.html
    # 必须放在最后，作为 fallback

    # 根路径：返回 index.html
    @app.get("/", include_in_schema=False)
    async def root_index():
        """根路径，返回前端 index.html"""
        index_file = public_dir / "index.html"
        if index_file.exists():
            from fastapi.responses import FileResponse

            return FileResponse(str(index_file))
        else:
            raise HTTPException(status_code=404, detail="Frontend not built")

    @app.get("/api/{full_path:path}", include_in_schema=False)
    async def api_catch_all():
        """API 路径的 catch-all，返回 404"""
        raise HTTPException(status_code=404, detail="API endpoint not found")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA 前端路由的 catch-all，返回 index.html"""
        index_file = public_dir / "index.html"
        if index_file.exists():
            from fastapi.responses import FileResponse

            return FileResponse(str(index_file))
        else:
            raise HTTPException(status_code=404, detail="Frontend not built")

    # 全局异常处理
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """HTTP异常处理"""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "message": exc.detail,
                "status_code": exc.status_code,
            },
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
                "message": "服务器内部错误",
                "status_code": 500,
            },
        )

    return app


# 创建应用实例
app = create_app()
