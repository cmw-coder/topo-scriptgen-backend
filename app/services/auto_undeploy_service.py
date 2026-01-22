import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from app.core.config import settings
from app.services.itc.itc_service import itc_service

logger = logging.getLogger(__name__)


class AutoUndeployService:
    """自动卸载服务

    定期检查最后一次 API 调用时间，如果超过 8 小时未调用且处于已部署状态，
    则自动调用 undeploy 接口卸载组网并清理配置。
    """

    # 检查间隔（秒）
    CHECK_INTERVAL = 1200  # 20分钟检查一次

    # 自动卸载的超时时间（小时）
    AUTO_UNDEPLOY_TIMEOUT_HOURS = 8

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def _check_and_auto_undeploy(self) -> None:
        """检查并自动执行 undeploy"""
        try:
            last_call_time = settings.get_last_api_call_time()

            # 如果从未调用过 API，不执行自动卸载
            if last_call_time is None:
                logger.debug("从未调用过 API，跳过自动卸载检查")
                return

            # 计算距离最后一次调用的时间
            now = datetime.now()
            time_since_last_call = now - last_call_time
            hours_since_last_call = time_since_last_call.total_seconds() / 3600

            logger.info(f"距离最后一次 API 调用: {hours_since_last_call:.2f} 小时")

            # 检查是否超过超时时间
            if hours_since_last_call >= self.AUTO_UNDEPLOY_TIMEOUT_HOURS:
                # 检查部署状态
                deploy_status = settings.get_deploy_status()

                logger.info(f"当前部署状态: {deploy_status}")

                # 只有在已部署状态下才执行自动卸载
                if deploy_status == "deployed":
                    logger.warning("=" * 80)
                    logger.warning(f"已超过 {self.AUTO_UNDEPLOY_TIMEOUT_HOURS} 小时未调用 API")
                    logger.warning("当前处于已部署状态，准备自动卸载组网...")
                    logger.warning("=" * 80)

                    # 从 aigc.json 获取 executorip
                    executorip = settings.get_deploy_executor_ip()

                    if not executorip:
                        logger.warning("无法获取 executorip，跳过自动卸载")
                        return

                    logger.info(f"获取到 executorip: {executorip}")

                    # 调用 undeploy
                    from app.models.itc.itc_models import ExecutorRequest
                    request = ExecutorRequest(executorip=executorip)

                    logger.info("开始调用 undeploy 接口...")
                    result = await itc_service.undeploy_environment(request)

                    if result.return_code == "200":
                        logger.info("自动卸载成功")
                        logger.warning("=" * 80)
                        logger.warning("自动卸载完成，已清理配置")
                        logger.warning("=" * 80)
                    else:
                        logger.error(f"自动卸载失败: {result.return_info}")
                else:
                    logger.debug(f"部署状态为 {deploy_status}，无需自动卸载")
            else:
                logger.debug(f"未超过 {self.AUTO_UNDEPLOY_TIMEOUT_HOURS} 小时，无需自动卸载")

        except Exception as e:
            logger.error(f"自动卸载检查异常: {str(e)}", exc_info=True)

    async def _auto_undeploy_loop(self) -> None:
        """自动卸载循环"""
        logger.info("=" * 80)
        logger.info("自动卸载服务已启动")
        logger.info(f"检查间隔: {self.CHECK_INTERVAL} 秒")
        logger.info(f"自动卸载超时: {self.AUTO_UNDEPLOY_TIMEOUT_HOURS} 小时")
        logger.info("=" * 80)

        while self._running:
            try:
                await self._check_and_auto_undeploy()
            except Exception as e:
                logger.error(f"自动卸载循环异常: {str(e)}", exc_info=True)

            # 等待下一次检查
            await asyncio.sleep(self.CHECK_INTERVAL)

        logger.info("自动卸载服务已停止")

    def start(self) -> None:
        """启动自动卸载服务（在后台线程中运行）"""
        if self._running:
            logger.warning("自动卸载服务已在运行中")
            return

        import threading

        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._running = True
            try:
                loop.run_until_complete(self._auto_undeploy_loop())
            finally:
                loop.close()

        thread = threading.Thread(target=run_in_thread, daemon=True, name="AutoUndeployService")
        thread.start()
        logger.info(f"自动卸载服务线程已启动: {thread.name}")

    def stop(self) -> None:
        """停止自动卸载服务"""
        if not self._running:
            logger.warning("自动卸载服务未运行")
            return

        logger.info("正在停止自动卸载服务...")
        self._running = False


# 创建全局实例
auto_undeploy_service = AutoUndeployService()
