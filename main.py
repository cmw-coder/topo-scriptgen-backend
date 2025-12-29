#!/usr/bin/env python3
"""
Script Generator API 主程序入口

这个文件是项目的启动入口，使用 uvicorn 运行 FastAPI 应用。
"""

import uvicorn
import sys
import asyncio
from pathlib import Path
import argparse

# ============ Python 3.13 + Windows 事件循环修复 ============
# 必须在导入任何异步库之前设置事件循环策略
if sys.version_info >= (3, 13) and sys.platform == "win32":
    try:
        # 设置使用 ProactorEventLoop 而不是 WindowsSelectorEventLoop
        # 这对于支持 subprocess 是必需的
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        print("[INFO] Python 3.13 + Windows detected: ProactorEventLoop enabled for subprocess support")
    except AttributeError:
        print("[WARNING] Cannot set WindowsProactorEventLoopPolicy (may not be Windows)")
# ============================================================

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.core.config import settings
from app.core.path_manager import path_manager

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Script Generator API")
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
        "--debug",
        action="store_true",
        help="启用调试模式"
    )
    parser.add_argument(
        "--work-dir",
        type=str,
        help="设置工作目录"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="工作进程数量 (默认: 1)"
    )

    args = parser.parse_args()

    # 设置工作目录
    if args.work_dir:
        try:
            path_manager.set_project_root(Path(args.work_dir))
            print(f"工作目录设置为: {args.work_dir}")
        except Exception as e:
            print(f"设置工作目录失败: {e}")
            sys.exit(1)

    # 设置调试模式
    if args.debug:
        settings.DEBUG = True

    # 显示启动信息
    print("=" * 60)
    print(f"[START] Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"[INFO] Description: {settings.DESCRIPTION}")
    print(f"[INFO] Server URL: http://{args.host}:{args.port}")
    print(f"[INFO] API Docs: http://{args.host}:{args.port}/docs")
    print(f"[INFO] ReDoc: http://{args.host}:{args.port}/redoc")
    print(f"[INFO] Work Directory: {path_manager.get_project_root()}")
    print(f"[INFO] Scripts Directory: {path_manager.get_scripts_dir()}")
    print(f"[INFO] Logs Directory: {path_manager.get_logs_dir()}")
    print(f"[INFO] Topo Directory: {path_manager.get_topox_dir()}")
    if args.reload:
        print("[INFO] Auto-reload: Enabled")
    if args.debug:
        print("[INFO] Debug mode: Enabled")
    print("=" * 60)

    # 启动服务器
    try:
        # Python 3.13 + Windows: 确保 uvicorn 使用 ProactorEventLoop
        loop = None
        if sys.version_info >= (3, 13) and sys.platform == "win32":
            loop = "uvloop" if sys.platform != "win32" else "asyncio"
            print(f"[INFO] Uvicorn event loop: {loop}")

        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=args.workers if not args.reload else 1,
            log_level="debug" if args.debug else "info",
            access_log=True,
            loop=loop  # 明确指定事件循环类型
        )
    except KeyboardInterrupt:
        print("\n[STOP] Server stopped")
    except Exception as e:
        print(f"[ERROR] Failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()