import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from app.core.config import settings

logger = logging.getLogger(__name__)


class APICallTrackerMiddleware(BaseHTTPMiddleware):
    """API 调用追踪中间件

    记录最后一次 API 调用时间，用于自动卸载功能
    """

    # 需要追踪的路径前缀
    TRACKED_PATHS = [
        "/api/",
        "/itc/",
    ]

    # 排除的路径（健康检查等）
    EXCLUDED_PATHS = [
        "/health",
        "/ping",
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    async def dispatch(self, request: Request, call_next) -> Response:
        # 处理请求
        response = await call_next(request)

        # 检查是否需要追踪此请求
        path = request.url.path

        # 排除不需要追踪的路径
        if any(path.startswith(excluded) for excluded in self.EXCLUDED_PATHS):
            return response

        # 只追踪指定的路径
        if any(path.startswith(tracked) for tracked in self.TRACKED_PATHS):
            # 更新最后 API 调用时间
            settings.update_last_api_call_time()
            logger.debug(f"API 调用已记录: {path} {request.method}")

        return response
