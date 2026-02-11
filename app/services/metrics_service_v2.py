"""
基于脚本的度量服务 v2 - 完整实现（优化版）

核心功能：
1. 以脚本为核心度量单位
2. 支持多次部署、多次调试、多次ITC run
3. 自动追踪全局最新活跃脚本
4. 持久化存储所有度量数据
5. 延迟加载 - 启动时只恢复状态，按需加载数据
6. 线程安全 - 使用锁保护共享状态
"""
import getpass
import glob
import json
import logging
import os
import platform
import re
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from app.models.metrics_v2 import (
    ScriptMetrics,
    DeployRecord,
    ActivityRecord,
    ActivityType,
    ScriptType
)
from app.core.config import settings
from app.core.path_manager import path_manager

logger = logging.getLogger(__name__)


# 全局活跃文件记录（内存中，线程安全）
class GlobalActiveFile:
    """全局活跃文件记录（存储在内存中，线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()
        self.file_path: Optional[str] = None  # 文件路径
        self.script_uuid: Optional[str] = None  # 脚本 UUID
        self.file_name: Optional[str] = None  # 文件名
        self.last_modified: Optional[datetime] = None  # 最后修改时间
        self.last_active: Optional[datetime] = None  # 最后活跃时间

    def update(self, file_path: str, script_uuid: str, last_modified: datetime):
        """更新活跃文件记录（线程安全）"""
        with self._lock:
            self.file_path = file_path
            self.script_uuid = script_uuid
            self.file_name = Path(file_path).name
            self.last_modified = last_modified
            self.last_active = datetime.now()

    def clear(self):
        """清空活跃文件记录（线程安全）"""
        with self._lock:
            self.file_path = None
            self.script_uuid = None
            self.file_name = None
            self.last_modified = None
            self.last_active = None

    def is_valid(self) -> bool:
        """检查是否有有效的活跃文件"""
        with self._lock:
            return self.script_uuid is not None

    def get(self) -> Tuple[Optional[str], Optional[str], Optional[datetime]]:
        """获取活跃文件信息（线程安全）"""
        with self._lock:
            return self.file_path, self.script_uuid, self.last_modified

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        with self._lock:
            return {
                "file_path": self.file_path,
                "script_uuid": self.script_uuid,
                "file_name": self.file_name,
                "last_modified": self.last_modified.isoformat() if self.last_modified else None,
                "last_active": self.last_active.isoformat() if self.last_active else None
            }


class MetricsServiceV2:
    """基于脚本的度量服务 v2（延迟加载版本）"""

    # 全局活跃文件记录（类级别，所有实例共享）
    _global_active_file = GlobalActiveFile()

    def __init__(self):
        # 线程锁
        self._lock = threading.RLock()

        # 当前活跃脚本 UUID（延迟加载：只在需要时加载脚本数据）
        self._current_script_uuid: Optional[str] = None
        self._latest_deploy_id: Optional[str] = None
        self._workspace: str = ""

        # 脚本度量：key 为 script_uuid，value 为 ScriptMetrics
        # 延迟加载：不在启动时加载所有脚本
        self._scripts: Dict[str, ScriptMetrics] = {}
        self._scripts_loaded = False  # 标记是否已加载所有脚本

        # 部署记录：key 为 deploy_id，value 为 DeployRecord
        self._deploys: Dict[str, DeployRecord] = {}
        self._deploys_loaded = False  # 标记是否已加载部署记录

        # 活动记录缓存：key 为 activity_id，value 为 ActivityRecord
        #（实际存储在对应的 script_metrics 中，这里用于快速查找）
        self._activities: Dict[str, ActivityRecord] = {}

        # 当前正在进行的部署（key 为 username，value 为 deploy_id）
        self._pending_deploys: Dict[str, str] = {}

        # 当前正在进行的活动（key 为 activity_id，value 为 script_uuid）
        self._pending_activities: Dict[str, str] = {}

        # 脚本 UUID 到文件名的映射（用于通过 script_uuid 快速定位文件）
        self._script_uuid_to_file: Dict[str, Path] = {}

        # ========== 启动优化：只恢复状态，不加载所有数据 ==========
        # 1. 恢复当前活跃脚本 UUID（持久化的状态）
        self._restore_session_state()

        # 2. 延迟加载：只在需要时才加载脚本和部署数据
        # 不在启动时扫描工作区或加载所有数据
        # ===================================================

    # ==================== 路径管理 ====================

    def _get_metrics_dir(self) -> Path:
        """获取统计文件存储目录（保存到共享目录）"""
        username = getpass.getuser()

        # 根据操作系统选择共享目录路径
        if platform.system() == "Windows":
            # Windows 网络共享路径 - 直接使用 Path 处理
            unc_dir = settings.get_aigc_tool_unc_dir(username)
            base_dir = Path(unc_dir) / "metrics_v2"
        else:
            # Linux 共享目录路径
            base_dir = Path(settings.get_aigc_tool_local_metrics_dir(username).replace("/metrics", "/metrics_v2"))

        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            return base_dir
        except Exception as e:
            logger.warning(f"无法访问共享目录 {base_dir}，回退到本地目录: {e}", exc_info=True)
            # 回退到本地 .metrics 目录
            work_dir = path_manager.get_project_root()
            fallback_dir = work_dir / ".metrics" / "metrics_v2"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            return fallback_dir

    def _get_script_file_path(self, ai_fingerprint_uuid: str) -> Path:
        """获取脚本统计文件路径，使用 AI 指纹 UUID 作为文件名"""
        metrics_dir = self._get_metrics_dir()
        return metrics_dir / f"script_{ai_fingerprint_uuid}.json"

    def _get_deploy_file_path(self, deploy_time: datetime) -> Path:
        """
        获取部署记录文件路径

        文件名格式：deploy-YYYYMMDD-HHMMSS.json
        存储目录：metrics_v2/deploylog/

        Args:
            deploy_time: 部署时间

        Returns:
            部署记录文件路径
        """
        metrics_dir = self._get_metrics_dir()
        # 创建 deploylog 子目录
        deploylog_dir = metrics_dir / "deploylog"
        deploylog_dir.mkdir(parents=True, exist_ok=True)

        # 格式：deploy-YYYYMMDD-HHMMSS.json
        time_str = deploy_time.strftime('%Y%m%d-%H%M%S')
        return deploylog_dir / f"deploy-{time_str}.json"

    def _get_session_file_path(self) -> Path:
        """获取会话状态文件路径"""
        metrics_dir = self._get_metrics_dir()
        return metrics_dir / ".session_state.json"

    def _save_session_state(self):
        """持久化当前会话状态到文件"""
        try:
            session_data = {
                "current_script_uuid": self._current_script_uuid,
                "latest_deploy_id": self._latest_deploy_id,
                "workspace": self._workspace,
                "saved_at": datetime.now().isoformat()
            }

            file_path = self._get_session_file_path()
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)

            logger.debug(f"保存会话状态: current_script={self._current_script_uuid}")

        except Exception as e:
            logger.warning(f"保存会话状态失败: {e}")

    def _restore_session_state(self):
        """从文件恢复会话状态"""
        try:
            file_path = self._get_session_file_path()
            if not file_path.exists():
                logger.info("没有找到会话状态文件，使用默认状态")
                return

            with open(file_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)

            self._current_script_uuid = session_data.get("current_script_uuid")
            self._latest_deploy_id = session_data.get("latest_deploy_id")
            self._workspace = session_data.get("workspace", "")

            logger.info(
                f"恢复会话状态: current_script={self._current_script_uuid}, "
                f"latest_deploy={self._latest_deploy_id}"
            )

            # 如果有当前活跃脚本 UUID，尝试加载该脚本的数据
            if self._current_script_uuid:
                self._load_script(self._current_script_uuid)

        except Exception as e:
            logger.warning(f"恢复会话状态失败: {e}")

    def _get_username(self) -> str:
        """获取当前用户名"""
        return getpass.getuser()

    # ==================== 数据加载（延迟加载） ====================

    def _ensure_scripts_loaded(self):
        """确保所有脚本数据已加载（延迟加载）"""
        with self._lock:
            if self._scripts_loaded:
                return

            logger.info("开始延迟加载所有脚本数据...")
            self._load_all_scripts()
            self._scripts_loaded = True

    def _ensure_deploys_loaded(self):
        """确保所有部署记录已加载（延迟加载）"""
        with self._lock:
            if self._deploys_loaded:
                return

            logger.info("开始延迟加载所有部署记录...")
            self._load_all_deploys()
            self._deploys_loaded = True

    def _load_all_deploys(self):
        """加载所有部署记录（仅在需要时调用）"""
        try:
            metrics_dir = self._get_metrics_dir()
            deploylog_dir = metrics_dir / "deploylog"

            if not deploylog_dir.exists():
                logger.info("部署记录目录不存在")
                return

            # 扫描所有部署记录文件
            deploy_files = list(deploylog_dir.glob("deploy-*.json"))
            if not deploy_files:
                logger.info("没有找到部署记录文件")
                return

            logger.info(f"找到 {len(deploy_files)} 个部署记录文件，开始加载...")
            for deploy_file in deploy_files:
                try:
                    with open(deploy_file, 'r', encoding='utf-8') as f:
                        deploy_data = json.load(f)
                    deploy_record = DeployRecord(**deploy_data)
                    self._deploys[deploy_record.deploy_id] = deploy_record
                except Exception as e:
                    logger.warning(f"加载部署记录文件 {deploy_file.name} 失败: {e}")

            logger.info(f"成功加载 {len(self._deploys)} 个部署记录")
        except Exception as e:
            logger.error(f"加载部署记录数据失败: {e}")

    def _load_all_scripts(self):
        """加载所有脚本数据（仅在需要时调用）"""
        try:
            metrics_dir = self._get_metrics_dir()

            # 扫描所有脚本文件
            script_files = list(metrics_dir.glob("script_*.json"))

            if not script_files:
                logger.info("没有找到脚本度量文件")
                return

            logger.info(f"找到 {len(script_files)} 个脚本度量文件，开始加载...")

            for script_file in script_files:
                try:
                    script_uuid = script_file.stem.replace("script_", "")
                    # 只加载尚未加载的脚本
                    if script_uuid not in self._scripts:
                        self._load_script_from_file(script_file)

                except Exception as e:
                    logger.warning(f"加载脚本文件 {script_file.name} 失败: {e}")

            logger.info(f"成功加载 {len(self._scripts)} 个脚本")

        except Exception as e:
            logger.error(f"加载脚本数据失败: {e}")

    def _load_script_from_file(self, script_file: Path):
        """从文件加载单个脚本"""
        with open(script_file, 'r', encoding='utf-8') as f:
            script_data = json.load(f)
        script = ScriptMetrics(**script_data)
        self._scripts[script.script_uuid] = script

        # 更新脚本 UUID 到文件名的映射
        self._script_uuid_to_file[script.script_uuid] = script_file

        # 验证文件名中的 AI 指纹 UUID 是否与脚本中的一致
        file_stem = script_file.stem
        if file_stem.startswith("script_"):
            file_ai_fingerprint = file_stem.replace("script_", "")
            if file_ai_fingerprint != script.ai_fingerprint_uuid:
                logger.warning(
                    f"文件名 AI 指纹 UUID 不匹配: "
                    f"文件={file_ai_fingerprint}, "
                    f"脚本={script.ai_fingerprint_uuid}"
                )

        # 加载部署记录（向后兼容：如果脚本文件中包含部署记录，加载到缓存）
        if script.deploy_records:
            for deploy_record in script.deploy_records:
                if deploy_record.deploy_id not in self._deploys:
                    self._deploys[deploy_record.deploy_id] = deploy_record
            logger.debug(f"从脚本文件加载了 {len(script.deploy_records)} 个部署记录（向后兼容）")

        # 加载活动记录到缓存
        for activity in script.activity_records:
            self._activities[activity.activity_id] = activity

        logger.debug(f"加载脚本: {script.script_name}, UUID={script.script_uuid}, AI指纹={script.ai_fingerprint_uuid}")

    def _load_script(self, script_uuid: str) -> Optional[ScriptMetrics]:
        """加载指定脚本的数据（按需加载）"""
        # 如果已经在内存中，直接返回
        if script_uuid in self._scripts:
            return self._scripts.get(script_uuid)

        # 从文件加载
        try:
            # 先检查映射
            script_file = self._script_uuid_to_file.get(script_uuid)
            if script_file and script_file.exists():
                self._load_script_from_file(script_file)
                logger.info(f"按需加载脚本: {script_uuid}")
                return self._scripts.get(script_uuid)

            # 映射中没有，扫描目录查找文件
            metrics_dir = self._get_metrics_dir()
            script_files = list(metrics_dir.glob("script_*.json"))
            found_file = None

            for file_path in script_files:
                try:
                    # 快速读取文件内容，只提取 script_uuid 字段
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data.get("script_uuid") == script_uuid:
                        found_file = file_path
                        break
                except Exception as e:
                    logger.warning(f"读取文件失败 {file_path}: {e}")
                    continue

            if found_file:
                self._load_script_from_file(found_file)
                logger.info(f"按需加载脚本（通过扫描）: {script_uuid}")
                return self._scripts.get(script_uuid)
            else:
                logger.warning(f"脚本文件不存在: {script_uuid}")
                return None

        except Exception as e:
            logger.error(f"加载脚本 {script_uuid} 失败: {e}")
            return None


    # ==================== 工作区扫描和活跃文件管理 ====================
    # 注意：启动时扫描工作区的功能已移除，改为延迟加载和按需创建脚本记录
    # 避免启动时读取大量文件影响性能


    def _extract_uuid_from_file(self, file_path: str) -> Optional[str]:
        """
        从 Python 文件中提取 AI 指纹 UUID

        AI 指纹格式: AI_FingerPrint_UUID: YYYYMMDD-xxxxxxxx
        例如: AI_FingerPrint_UUID: 20250110-a1B2c3D4
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 读取前 200 行（AI 指纹通常在文件开头的注释块中）
                for i, line in enumerate(f):
                    if i > 200:
                        break
                    # 匹配 AI_FingerPrint_UUID 模式：AI_FingerPrint_UUID: YYYYMMDD-xxxxxxxx
                    # 格式：8位日期 + 1位连字符 + 8位随机字符（大小写字母和数字）
                    match = re.search(r'AI_FingerPrint_UUID:\s*(\d{8}-[a-zA-Z0-9]{8})', line)
                    if match:
                        return match.group(1)
        except Exception as e:
            logger.debug(f"读取文件 {file_path} 失败: {e}")

        return None


    def _infer_script_type(self, file_path: str) -> ScriptType:
        """根据文件名推断脚本类型"""
        file_name = Path(file_path).name.lower()

        if 'conftest' in file_name:
            return ScriptType.CONFTEST
        elif file_name.startswith('test_'):
            return ScriptType.TEST_SCRIPT
        else:
            return ScriptType.OTHER_PYTHON

    def _create_default_metrics_file(self, workspace: str):
        """创建默认统计文件和虚空记录"""
        try:
            username = self._get_username()
            now = datetime.now()

            # 检查是否已存在虚拟脚本，避免重复创建
            for script in self._scripts.values():
                if script.status == "virtual":
                    logger.info(f"虚拟脚本已存在: {script.script_uuid}，跳过创建")
                    self._current_script_uuid = script.script_uuid
                    return

            logger.info("=" * 60)
            logger.info("工作区中没有 Python 文件，创建虚空记录")
            logger.info(f"工作区: {workspace}")
            logger.info(f"时间: {now}")
            logger.info("=" * 60)

            # 设置工作区
            self._workspace = workspace

            # 生成虚拟脚本的 AI 指纹 UUID
            virtual_fingerprint = self.generate_ai_fingerprint()

            # 生成虚拟脚本的内部 UUID
            virtual_script_uuid = str(uuid.uuid4())

            # 创建虚空脚本记录
            virtual_script = ScriptMetrics(
                script_uuid=virtual_script_uuid,
                script_path=f"{workspace}/__virtual__.py",
                script_name="__virtual__.py",
                script_type=ScriptType.OTHER_PYTHON,
                created_at=now,
                generation_duration=None,
                last_active_time=now,
                ai_fingerprint_uuid=virtual_fingerprint,
                status="virtual"  # 标记为虚拟脚本
            )

            # 确保部署记录已加载
            self._ensure_deploys_loaded()

            # 检查是否有最新的部署记录，如果有则关联到虚拟脚本
            if self._latest_deploy_id and self._latest_deploy_id in self._deploys:
                deploy_record = self._deploys[self._latest_deploy_id]

                # 检查部署记录是否已经被关联
                if deploy_record.associated_script_ai_fingerprint:
                    logger.info(
                        f"部署记录 {self._latest_deploy_id} 已经被脚本关联: "
                        f"AI指纹={deploy_record.associated_script_ai_fingerprint}，跳过关联"
                    )
                else:
                    # 更新部署记录中的活跃文件信息和关联信息
                    deploy_record.active_file_at_deploy = f"{workspace}/__virtual__.py"
                    deploy_record.active_file_name_at_deploy = "__virtual__.py"
                    deploy_record.active_ai_fingerprint_at_deploy = virtual_fingerprint
                    deploy_record.active_script_uuid_at_deploy = virtual_script_uuid
                    deploy_record.associated_script_ai_fingerprint = virtual_fingerprint

                    # 持久化更新后的部署记录
                    self._save_deploy_record(deploy_record)

                    logger.info(f"关联最新部署记录到虚空记录:")
                    logger.info(f"  deploy_id={deploy_record.deploy_id}")
                    logger.info(f"  部署调用时间={deploy_record.deploy_call_time}")
                    logger.info(f"  部署完成时间={deploy_record.deploy_complete_time}")
                    logger.info(f"  部署耗时={deploy_record.deploy_duration}秒")
                    logger.info(f"  关联AI指纹={virtual_fingerprint}")

            # 保存虚拟脚本到内存
            self._scripts[virtual_script_uuid] = virtual_script

            # 更新当前活跃脚本为虚拟脚本
            self._current_script_uuid = virtual_script_uuid

            # 持久化脚本度量
            self._save_script_metrics(virtual_script_uuid)

            # 设置全局活跃文件为虚拟记录
            MetricsServiceV2._global_active_file.update(
                f"{workspace}/__virtual__.py",
                virtual_script_uuid,
                now
            )

            logger.info("=" * 60)
            logger.info("虚空记录创建成功:")
            logger.info(f"  虚拟脚本名称: __virtual__.py")
            logger.info(f"  脚本内部UUID: {virtual_script_uuid}")
            logger.info(f"  AI指纹UUID: {virtual_fingerprint}")
            logger.info(f"  状态: virtual (虚拟)")
            logger.info("=" * 60)
            logger.info("提示: 所有活跃时间和部署记录将关联到此虚拟脚本")
            logger.info("      当生成真实的 Python 脚本后，将自动切换为真实脚本")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"创建虚空记录失败: {e}")
            # 失败时清空全局活跃文件
            MetricsServiceV2._global_active_file.clear()

    # ==================== 全局活跃文件访问方法 ====================

    @classmethod
    def get_global_active_file(cls) -> Dict[str, Any]:
        """获取全局活跃文件记录（只读）"""
        return cls._global_active_file.to_dict()

    @classmethod
    def update_global_active_file(cls, file_path: str, script_uuid: str, last_modified: datetime):
        """更新全局活跃文件记录"""
        cls._global_active_file.update(file_path, script_uuid, last_modified)
        logger.info(f"更新全局活跃文件: {Path(file_path).name}, UUID={script_uuid}")

    # ==================== AI 指纹辅助方法 ====================

    @classmethod
    def generate_ai_fingerprint(cls) -> str:
        """
        生成 AI 指纹 UUID

        使用与 add_aifinger_hook 相同的生成逻辑
        返回格式：YYYYMMDD-xxxxxxxx

        Returns:
            AI 指纹 UUID 字符串
        """
        from app.utils.add_aifinger_hook import generate_unique_id
        return generate_unique_id()

    @classmethod
    def add_ai_fingerprint_to_script(cls, script_path: str) -> Tuple[bool, Optional[str]]:
        """
        为脚本文件添加 AI 指纹

        使用 add_aifinger_hook 工具添加指纹

        Args:
            script_path: 脚本文件路径

        Returns:
            (成功状态, UUID) 元组
        """
        try:
            from app.utils.add_aifinger_hook import generate_unique_id, add_fingerprint_to_file

            # 生成 AI 指纹
            fingerprint_uuid = generate_unique_id()

            # 添加到文件
            success, _ = add_fingerprint_to_file(script_path, fingerprint_uuid)

            if success:
                logger.info(f"成功为脚本添加 AI 指纹: {Path(script_path).name}, UUID={fingerprint_uuid}")
            else:
                logger.warning(f"为脚本添加 AI 指纹失败: {Path(script_path).name}")

            return success, fingerprint_uuid if success else None

        except Exception as e:
            logger.error(f"添加 AI 指纹时出错: {e}")
            return False, None

    # ==================== 脚本管理 ====================

    def create_script(
        self,
        script_path: str,
        script_type: ScriptType = ScriptType.TEST_SCRIPT,
        generation_duration: Optional[float] = None,
        ai_fingerprint_uuid: Optional[str] = None
    ) -> str:
        """
        创建新的脚本度量记录

        Args:
            script_path: 脚本文件路径
            script_type: 脚本类型
            generation_duration: 生成耗时
            ai_fingerprint_uuid: AI指纹UUID

        Returns:
            script_uuid: 脚本唯一标识
        """
        username = self._get_username()
        script_path_obj = Path(script_path)

        # 设置工作区
        if not self._workspace:
            self._workspace = str(script_path_obj.parent)

        # 检查当前活跃脚本是否是虚拟脚本，如果是则提示并保存引用
        is_switching_from_virtual = False
        virtual_script = None
        if self._current_script_uuid:
            current_script = self._scripts.get(self._current_script_uuid)
            if current_script and current_script.status == "virtual":
                is_switching_from_virtual = True
                virtual_script = current_script
                logger.info("=" * 60)
                logger.info(f"检测到当前活跃的是虚拟脚本 ({current_script.script_name})")
                logger.info(f"将切换到真实脚本: {script_path_obj.name}")
                logger.info("=" * 60)

        # 如果没有提供 AI 指纹，自动添加
        if ai_fingerprint_uuid is None:
            success, ai_fingerprint_uuid = self.add_ai_fingerprint_to_script(script_path)
            if not success:
                # 如果添加到文件失败，仍然生成一个 UUID 保存到记录中
                ai_fingerprint_uuid = self.generate_ai_fingerprint()
                logger.warning(f"无法为 {script_path_obj.name} 添加 AI 指纹到文件，已生成 UUID 保存到记录: {ai_fingerprint_uuid}")
            else:
                logger.info(f"已为脚本添加 AI 指纹: {script_path_obj.name}, UUID={ai_fingerprint_uuid}")

        # 生成脚本 UUID
        script_uuid = str(uuid.uuid4())

        # 从 aigc.json 读取项目配置（新增）
        aigc_config = self._read_aigc_config()
        aigc_project_name = aigc_config.get("aigc_project_name")
        nvid = aigc_config.get("nvid")
        sessionId = aigc_config.get("sessionId")

        # 创建脚本度量
        script_metrics = ScriptMetrics(
            script_uuid=script_uuid,
            script_path=str(script_path_obj.absolute()),
            script_name=script_path_obj.name,
            script_type=script_type,
            created_at=datetime.now(),
            generation_duration=generation_duration,
            last_active_time=datetime.now(),
            ai_fingerprint_uuid=ai_fingerprint_uuid,
            # 新增字段
            aigc_project_name=aigc_project_name,
            nvid=nvid,
            sessionId=sessionId
        )

        # 保存到内存
        self._scripts[script_uuid] = script_metrics

        # 更新当前活跃脚本
        self._current_script_uuid = script_uuid

        # 确保部署记录已加载
        self._ensure_deploys_loaded()

        # 如果有最新的部署记录，关联到该脚本（只能关联一次）
        if self._latest_deploy_id and self._latest_deploy_id in self._deploys:
            deploy_record = self._deploys[self._latest_deploy_id]

            # 检查部署记录是否已经被关联
            if deploy_record.associated_script_ai_fingerprint:
                logger.info(
                    f"部署记录 {self._latest_deploy_id} 已经被脚本关联: "
                    f"AI指纹={deploy_record.associated_script_ai_fingerprint}，跳过关联"
                )
            else:
                # ========== 更新部署记录中的活跃文件信息和关联信息 ==========
                # 更新原始部署记录
                deploy_record.active_file_at_deploy = str(script_path_obj.absolute())
                deploy_record.active_file_name_at_deploy = script_path_obj.name
                deploy_record.active_ai_fingerprint_at_deploy = ai_fingerprint_uuid
                deploy_record.active_script_uuid_at_deploy = script_uuid
                # 设置关联脚本的AI指纹
                deploy_record.associated_script_ai_fingerprint = ai_fingerprint_uuid

                # 持久化更新后的部署记录
                self._save_deploy_record(deploy_record)

                logger.info(
                    f"部署记录关联到脚本: "
                    f"deploy_id={self._latest_deploy_id}, "
                    f"file={script_path_obj.name}, "
                    f"AI指纹={ai_fingerprint_uuid}"
                )
                # ================================================

                # 注意：不再复制部署记录到脚本的 deploy_records 字段
                # 查询脚本关联的部署记录需要通过扫描部署记录文件
                # script_deploy = DeployRecord(**deploy_record.model_dump())
                # script_metrics.deploy_records.append(script_deploy)
                # logger.info(f"脚本关联最新部署: deploy_id={self._latest_deploy_id}")

        # 如果是从虚拟脚本切换，转移数据到新脚本
        if is_switching_from_virtual and virtual_script:
            logger.info("=" * 60)
            logger.info("开始将虚拟脚本的数据转移到新脚本")
            logger.info(f"虚拟脚本: {virtual_script.script_name}, UUID={virtual_script.script_uuid}")
            logger.info(f"新脚本: {script_metrics.script_name}, UUID={script_metrics.script_uuid}")

            # 转移累计时长
            script_metrics.keep_alive_duration += virtual_script.keep_alive_duration
            script_metrics.command_debug_duration += virtual_script.command_debug_duration
            script_metrics.write_script_duration += virtual_script.write_script_duration

            # 转移耗时记录列表（合并，保留所有记录）
            script_metrics.write_back_durations.extend(virtual_script.write_back_durations)
            script_metrics.itc_run_durations.extend(virtual_script.itc_run_durations)

            # 转移活动记录（合并）
            script_metrics.activity_records.extend(virtual_script.activity_records)

            # 转移部署记录（已弃用，不再使用 deploy_records 字段）
            # 虚拟脚本可能关联了部署记录，需要将这些部署记录的关联信息更新为新脚本
            if virtual_script.ai_fingerprint_uuid:
                # 确保部署记录已加载
                self._ensure_deploys_loaded()
                updated_count = 0
                for deploy_id, deploy_record in self._deploys.items():
                    # 如果部署记录关联到虚拟脚本的AI指纹，更新为新脚本的AI指纹
                    if deploy_record.associated_script_ai_fingerprint == virtual_script.ai_fingerprint_uuid:
                        deploy_record.associated_script_ai_fingerprint = ai_fingerprint_uuid
                        self._save_deploy_record(deploy_record)
                        updated_count += 1
                if updated_count > 0:
                    logger.info(f"更新了 {updated_count} 个部署记录的关联信息: 从虚拟脚本 {virtual_script.ai_fingerprint_uuid} 到新脚本 {ai_fingerprint_uuid}")

            logger.info(f"数据转移完成:")
            logger.info(f"  keep_alive_duration: {virtual_script.keep_alive_duration} -> {script_metrics.keep_alive_duration}")
            logger.info(f"  command_debug_duration: {virtual_script.command_debug_duration} -> {script_metrics.command_debug_duration}")
            logger.info(f"  write_script_duration: {virtual_script.write_script_duration} -> {script_metrics.write_script_duration}")
            logger.info(f"  write_back_durations: {len(virtual_script.write_back_durations)} 条记录")
            logger.info(f"  itc_run_durations: {len(virtual_script.itc_run_durations)} 条记录")
            logger.info(f"  activity_records: {len(virtual_script.activity_records)} 条记录")
            # 部署记录不再存储在脚本中，通过关联字段管理
            # 日志中显示虚拟脚本原有的部署记录数量（仅作参考）
            logger.info("=" * 60)

        # 持久化脚本度量
        self._save_script_metrics(script_uuid)

        # 更新全局活跃文件记录
        try:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(script_path))
            MetricsServiceV2._global_active_file.update(
                str(script_path_obj.absolute()),
                script_uuid,
                file_mtime
            )
        except Exception as e:
            logger.warning(f"更新全局活跃文件失败: {e}")

        logger.info(
            f"创建脚本度量: script_uuid={script_uuid}, "
            f"script={script_path_obj.name}, "
            f"type={script_type}, "
            f"generation_duration={generation_duration}"
        )

        # 如果是从虚拟脚本切换，添加额外提示
        if is_switching_from_virtual:
            logger.info(f"成功从虚拟脚本切换到真实脚本: {script_path_obj.name}")
            logger.info(f"虚拟脚本的度量数据已转移到新脚本")

        return script_uuid

    def get_current_script_uuid(self) -> Optional[str]:
        """获取当前活跃脚本的 UUID"""
        return self._current_script_uuid

    def get_script_metrics(self, script_uuid: str) -> Optional[ScriptMetrics]:
        """获取脚本度量"""
        # 先检查内存，如果不存在则尝试从文件加载
        script = self._scripts.get(script_uuid)
        if script:
            return script
        # 按需加载脚本
        return self._load_script(script_uuid)

    def get_current_script(self) -> Optional[ScriptMetrics]:
        """获取当前活跃脚本"""
        script_uuid = self.get_current_script_uuid()
        if script_uuid:
            return self.get_script_metrics(script_uuid)
        return None

    def find_or_create_script_by_path(self, script_path: str) -> Optional[str]:
        """
        根据文件路径查找或创建脚本记录，并设置为当前活跃脚本

        Args:
            script_path: 脚本文件路径

        Returns:
            script_uuid: 脚本唯一标识，如果失败返回 None
        """
        script_path_obj = Path(script_path).absolute()

        # 1. 先检查是否已存在该脚本的记录（通过路径匹配）
        for script_uuid, script in self._scripts.items():
            if Path(script.script_path).absolute() == script_path_obj:
                # 找到已存在的脚本，设置为当前活跃脚本
                self._current_script_uuid = script_uuid
                logger.info(f"找到已存在的脚本记录: {script.script_name}, UUID={script_uuid}")

                # 更新全局活跃文件记录
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(script_path))
                    MetricsServiceV2._global_active_file.update(
                        str(script_path_obj),
                        script_uuid,
                        file_mtime
                    )
                except Exception as e:
                    logger.warning(f"更新全局活跃文件失败: {e}")

                return script_uuid

        # 2. 不存在则创建新的脚本记录
        script_type = self._infer_script_type(str(script_path_obj))

        # 尝试从文件中提取 AI 指纹
        ai_fingerprint_uuid = self._extract_uuid_from_file(str(script_path_obj))

        script_uuid = self.create_script(
            script_path=str(script_path_obj),
            script_type=script_type,
            generation_duration=None,
            ai_fingerprint_uuid=ai_fingerprint_uuid
        )

        logger.info(f"为脚本创建新的度量记录: {script_path_obj.name}, UUID={script_uuid}")
        return script_uuid

    def update_script_fingerprint(self, script_uuid: str, ai_fingerprint_uuid: str) -> bool:
        """更新脚本的 AI 指纹"""
        script = self._scripts.get(script_uuid)
        if not script:
            logger.warning(f"脚本不存在: {script_uuid}")
            return False

        script.ai_fingerprint_uuid = ai_fingerprint_uuid
        self._save_script_metrics(script_uuid)
        return True

    # ==================== 部署管理 ====================

    def start_deploy(
        self,
        topox_file: str,
        version_path: Optional[str] = None,
        device_type: str = "simware9cen"
    ) -> str:
        """
        开始部署（记录调用时间）

        自动从 aigc.json 读取项目配置（aigc_project_name、nvid、sessionId）

        Args:
            topox_file: topox 文件路径
            version_path: 版本路径
            device_type: 设备类型

        Returns:
            deploy_id: 部署ID
        """
        username = self._get_username()
        workspace = str(path_manager.get_project_root())
        deploy_call_time = datetime.now()

        # 生成部署 ID
        deploy_id = str(uuid.uuid4())

        # ========== 获取当前活跃文件信息 ==========
        active_file_path = None
        active_file_name = None
        active_ai_fingerprint = None
        active_script_uuid = None

        current_script = self.get_current_script()
        if current_script:
            active_file_path = current_script.script_path
            active_file_name = current_script.script_name
            active_ai_fingerprint = current_script.ai_fingerprint_uuid
            active_script_uuid = current_script.script_uuid
            logger.info(f"部署时活跃文件: {active_file_name}, AI指纹: {active_ai_fingerprint}")
        else:
            logger.info("部署时没有活跃脚本")
        # ===========================================

        # 创建部署记录
        deploy_record = DeployRecord(
            deploy_id=deploy_id,
            deploy_call_time=deploy_call_time,
            username=username,
            workspace=workspace,
            topox_file=topox_file,
            version_path=version_path,
            device_type=device_type,
            status="deploying",
            active_file_at_deploy=active_file_path,
            active_file_name_at_deploy=active_file_name,
            active_ai_fingerprint_at_deploy=active_ai_fingerprint,
            active_script_uuid_at_deploy=active_script_uuid
        )

        # 保存到内存
        self._deploys[deploy_id] = deploy_record
        self._pending_deploys[username] = deploy_id

        # 更新最新部署ID和工作区
        self._latest_deploy_id = deploy_id
        self._workspace = workspace

        # 持久化
        self._save_deploy_record(deploy_record)

        logger.info(
            f"开始部署: deploy_id={deploy_id}, "
            f"topox={Path(topox_file).name}, "
            f"device_type={device_type}"
        )

        return deploy_id

    def complete_deploy(
        self,
        executor_ip: str,
        device_list: Optional[List[Dict[str, Any]]] = None,
        status: str = "deployed"
    ) -> bool:
        """
        完成部署（记录完成时间和结果）

        Args:
            executor_ip: 执行机IP
            device_list: 设备列表
            status: 部署状态

        Returns:
            是否成功
        """
        username = self._get_username()

        # 确保部署记录已加载
        self._ensure_deploys_loaded()

        # 获取待完成的部署
        deploy_id = self._pending_deploys.get(username)
        if not deploy_id:
            logger.warning(f"用户 {username} 没有待完成的部署")
            return False

        deploy_record = self._deploys.get(deploy_id)
        if not deploy_record:
            logger.warning(f"部署记录不存在: {deploy_id}")
            return False

        # 更新部署记录
        deploy_record.deploy_complete_time = datetime.now()
        deploy_record.executor_ip = executor_ip
        deploy_record.device_list = device_list
        deploy_record.status = status

        if deploy_record.deploy_call_time:
            deploy_record.deploy_duration = (
                deploy_record.deploy_complete_time - deploy_record.deploy_call_time
            ).total_seconds()

        # 清除待处理标记
        del self._pending_deploys[username]

        # 持久化
        self._save_deploy_record(deploy_record)

        # 注意：部署记录不再立即关联到当前活跃脚本
        # 根据新需求，部署记录只被部署结束后第一个生成的脚本文件关联
        # 关联逻辑在 create_script 方法中实现

        logger.info(
            f"完成部署: deploy_id={deploy_id}, "
            f"duration={deploy_record.deploy_duration}秒, "
            f"status={status}, "
            f"executor_ip={executor_ip}"
        )

        return True

    def fail_deploy(self, error_message: str = "") -> bool:
        """
        标记部署失败

        Args:
            error_message: 错误信息

        Returns:
            是否成功
        """
        username = self._get_username()

        # 确保部署记录已加载
        self._ensure_deploys_loaded()

        deploy_id = self._pending_deploys.get(username)
        if not deploy_id:
            logger.warning(f"用户 {username} 没有待完成的部署")
            return False

        deploy_record = self._deploys.get(deploy_id)
        if not deploy_record:
            return False

        # 更新部署记录
        deploy_record.deploy_complete_time = datetime.now()
        deploy_record.status = "failed"

        if deploy_record.deploy_call_time:
            deploy_record.deploy_duration = (
                deploy_record.deploy_complete_time - deploy_record.deploy_call_time
            ).total_seconds()

        del self._pending_deploys[username]

        # 持久化
        self._save_deploy_record(deploy_record)

        logger.error(f"部署失败: deploy_id={deploy_id}, error={error_message}")

        return True

    # ==================== 活动管理 ====================

    def start_activity(
        self,
        activity_type: ActivityType,
        related_file: Optional[str] = None,
        extra_info: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        开始活动

        Args:
            activity_type: 活动类型
            related_file: 相关文件
            extra_info: 额外信息

        Returns:
            activity_id: 活动ID
        """
        # 获取当前活跃脚本
        script = self.get_current_script()
        if not script:
            logger.warning("没有活跃脚本，无法开始活动")
            return ""

        # 生成活动 ID
        activity_id = str(uuid.uuid4())

        # 创建活动记录
        activity = ActivityRecord(
            activity_id=activity_id,
            activity_type=activity_type,
            start_time=datetime.now(),
            related_file=related_file,
            extra_info=extra_info or {}
        )

        # 保存到缓存
        self._activities[activity_id] = activity
        self._pending_activities[activity_id] = script.script_uuid

        logger.debug(
            f"开始活动: activity_id={activity_id}, "
            f"type={activity_type}, "
            f"script={script.script_name}"
        )

        return activity_id

    def complete_activity(
        self,
        activity_id: str,
        extra_info: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        完成活动

        Args:
            activity_id: 活动ID
            extra_info: 额外信息（会合并到活动的 extra_info 中）

        Returns:
            是否成功
        """
        # 获取活动记录
        activity = self._activities.get(activity_id)
        if not activity:
            logger.warning(f"活动不存在: {activity_id}")
            return False

        # 检查是否已经完成
        if activity.end_time:
            logger.warning(f"活动已经完成: {activity_id}")
            return False

        # 获取关联的脚本
        script_uuid = self._pending_activities.get(activity_id)
        if not script_uuid:
            logger.warning(f"活动没有关联脚本: {activity_id}")
            return False

        script = self._scripts.get(script_uuid)
        if not script:
            logger.warning(f"脚本不存在: {script_uuid}")
            return False

        # 更新活动记录
        activity.end_time = datetime.now()
        if activity.start_time:
            activity.duration = (activity.end_time - activity.start_time).total_seconds()

        # 合并额外信息
        if extra_info:
            if activity.extra_info is None:
                activity.extra_info = {}
            activity.extra_info.update(extra_info)

        # 添加到脚本的活动记录
        script.activity_records.insert(0, activity)  # 插入到开头
        script.last_active_time = datetime.now()

        # 清除待处理标记
        if activity_id in self._pending_activities:
            del self._pending_activities[activity_id]

        # 持久化
        self._save_script_metrics(script_uuid)

        logger.info(
            f"完成活动: activity_id={activity_id}, "
            f"type={activity.activity_type}, "
            f"duration={activity.duration}秒, "
            f"script={script.script_name}"
        )

        return True

    # ==================== 便捷方法 ====================

    def record_command_debug(
        self,
        file_name: str,
        duration: float
    ) -> Optional[str]:
        """
        记录命令行调试（一次性完成）

        Args:
            file_name: 文件名
            duration: 耗时

        Returns:
            activity_id: 活动ID
        """
        activity_id = self.start_activity(
            activity_type=ActivityType.COMMAND_DEBUG,
            related_file=file_name
        )

        if activity_id:
            self.complete_activity(activity_id, {"duration_input": duration})

        return activity_id

    def record_write_script(
        self,
        file_name: str,
        duration: float
    ) -> Optional[str]:
        """
        记录写脚本时间（一次性完成）

        Args:
            file_name: 文件名
            duration: 耗时

        Returns:
            activity_id: 活动ID
        """
        activity_id = self.start_activity(
            activity_type=ActivityType.WRITE_SCRIPT,
            related_file=file_name
        )

        if activity_id:
            self.complete_activity(activity_id, {"duration_input": duration})

        return activity_id

    def record_itc_run(
        self,
        duration: float,
        return_code: str,
        return_info: Any = None
    ) -> Optional[str]:
        """
        记录 ITC run（一次性完成）

        Args:
            duration: 耗时
            return_code: 返回码
            return_info: 返回信息（已忽略，不再记录）

        Returns:
            activity_id: 活动ID
        """
        activity_id = self.start_activity(
            activity_type=ActivityType.ITC_RUN
        )

        if activity_id:
            self.complete_activity(activity_id, {
                "duration_input": duration,
                "return_code": return_code
            })

        return activity_id

    def add_keep_alive_duration(self, interval: float) -> bool:
        """
        累加 Web 活跃时间

        Args:
            interval: 时间间隔（秒）

        Returns:
            是否成功
        """
        script = self.get_current_script()
        if not script:
            # 没有活跃脚本，创建虚拟脚本
            logger.info("没有活跃脚本，创建虚拟脚本用于记录活跃时间")
            try:
                workspace = str(path_manager.get_project_root())
                self._create_default_metrics_file(workspace)
                script = self.get_current_script()
                if not script:
                    logger.warning("创建虚拟脚本失败，无法记录活跃时间")
                    return False
            except Exception as e:
                logger.error(f"创建虚拟脚本失败: {e}")
                return False

        script.keep_alive_duration = round(script.keep_alive_duration + interval, 2)
        script.last_active_time = datetime.now()

        # 持久化
        self._save_script_metrics(script.script_uuid)

        logger.info(
            f"累加活跃时间: script={script.script_name}, "
            f"interval={interval}秒, "
            f"total={script.keep_alive_duration}秒"
        )

        return True

    def add_write_back_duration(self, duration: float, script_path: Optional[str] = None) -> bool:
        """
        添加回写耗时记录到当前活跃脚本（或指定脚本）

        Args:
            duration: 回写耗时（秒）
            script_path: 可选，指定脚本路径。如果提供，会先设置为活跃脚本

        Returns:
            是否成功
        """
        # 如果提供了脚本路径，先找到或创建该脚本并设置为活跃脚本
        if script_path:
            script_uuid = self.find_or_create_script_by_path(script_path)
            if not script_uuid:
                logger.warning(f"无法找到或创建脚本: {script_path}")
                return False

        script = self.get_current_script()
        if not script:
            logger.warning("没有活跃脚本，无法记录回写耗时")
            return False

        # 创建耗时记录
        from app.models.metrics_v2 import DurationRecord
        duration_record = DurationRecord(
            timestamp=datetime.now(),
            duration=duration,
            extra_info=None
        )

        # 追加到数组开头
        script.write_back_durations.insert(0, duration_record)
        script.last_active_time = datetime.now()

        # 持久化
        self._save_script_metrics(script.script_uuid)

        logger.info(
            f"记录回写耗时: script={script.script_name}, "
            f"duration={duration}秒, "
            f"total_records={len(script.write_back_durations)}"
        )

        return True

    def add_itc_run_duration(
        self,
        duration: float,
        return_code: str,
        return_info: Any = None,
        script_path: Optional[str] = None
    ) -> bool:
        """
        添加ITC run耗时记录到当前活跃脚本（或指定脚本）

        Args:
            duration: ITC run耗时（秒）
            return_code: 返回码
            return_info: 返回信息（已忽略，不再记录）
            script_path: 可选，指定脚本路径。如果提供，会先设置为活跃脚本

        Returns:
            是否成功
        """
        # 如果提供了脚本路径，先找到或创建该脚本并设置为活跃脚本
        if script_path:
            script_uuid = self.find_or_create_script_by_path(script_path)
            if not script_uuid:
                logger.warning(f"无法找到或创建脚本: {script_path}")
                return False

        script = self.get_current_script()
        if not script:
            logger.warning("没有活跃脚本，无法记录ITC run耗时")
            return False

        # 创建耗时记录
        from app.models.metrics_v2 import DurationRecord
        duration_record = DurationRecord(
            timestamp=datetime.now(),
            duration=duration,
            extra_info={
                "return_code": return_code
            }
        )

        # 追加到数组开头
        script.itc_run_durations.insert(0, duration_record)
        script.last_active_time = datetime.now()

        # 持久化
        self._save_script_metrics(script.script_uuid)

        logger.info(
            f"记录ITC run耗时: script={script.script_name}, "
            f"duration={duration}秒, "
            f"return_code={return_code}, "
            f"total_records={len(script.itc_run_durations)}"
        )

        return True

    def push_metrics(
        self,
        metrics_type: str,
        file_name: Optional[str],
        interval: float
    ) -> dict:
        """
        推送指标数据（兼容旧版 /push 接口，但适配到 v2 版本）

        新增功能：
        - 对于 write_script 和 command_debug 类型，会根据 file_name 找到对应脚本并设为活跃脚本
        - 将耗时累加到对应脚本的 command_debug_duration 或 write_script_duration 字段

        Args:
            metrics_type: 指标类型 (command_debug | keep_alive | write_script)
            file_name: 文件名（command_debug 和 write_script 类型必需）
            interval: 操作耗时（秒）

        Returns:
            包含更新后指标数据的字典

        Raises:
            ValueError: 参数不合法时抛出
        """
        from pathlib import Path

        if metrics_type == "command_debug":
            # 命令行调试指标
            if not file_name:
                raise ValueError("command_debug 类型需要 file_name 参数")

            # 构建完整文件路径
            workspace = path_manager.get_project_root()
            file_path = os.path.join(workspace, file_name)

            # 1. 找到或创建脚本，并设置为活跃脚本
            script_uuid = self.find_or_create_script_by_path(file_path)
            if not script_uuid:
                logger.warning(f"无法找到或创建脚本: {file_path}")
                raise ValueError(f"无法找到或创建脚本: {file_name}")

            script = self._scripts.get(script_uuid)
            if not script:
                raise ValueError(f"脚本不存在: {script_uuid}")

            # 2. 累加 command_debug_duration
            script.command_debug_duration = round(script.command_debug_duration + interval, 2)
            script.last_active_time = datetime.now()

            # 3. 同时记录到活动记录中（保持与原有逻辑的兼容性）
            activity_id = self.record_command_debug(file_name, interval)

            # 4. 持久化
            self._save_script_metrics(script_uuid)

            logger.info(
                f"记录command_debug指标: script={script.script_name}, "
                f"interval={interval}秒, "
                f"total_command_debug_duration={script.command_debug_duration}秒"
            )

            return {
                "type": metrics_type,
                "file_name": file_name,
                "interval": interval,
                "script_uuid": script_uuid,
                "script_name": script.script_name,
                "command_debug_duration": script.command_debug_duration,
                "activity_id": activity_id
            }

        elif metrics_type == "write_script":
            # 写脚本时间指标
            if not file_name:
                raise ValueError("write_script 类型需要 file_name 参数")

            # 构建完整文件路径
            workspace = path_manager.get_project_root()
            file_path = os.path.join(workspace, file_name)

            # 1. 找到或创建脚本，并设置为活跃脚本
            script_uuid = self.find_or_create_script_by_path(file_path)
            if not script_uuid:
                logger.warning(f"无法找到或创建脚本: {file_path}")
                raise ValueError(f"无法找到或创建脚本: {file_name}")

            script = self._scripts.get(script_uuid)
            if not script:
                raise ValueError(f"脚本不存在: {script_uuid}")

            # 2. 累加 write_script_duration
            script.write_script_duration = round(script.write_script_duration + interval, 2)
            script.last_active_time = datetime.now()

            # 3. 同时记录到活动记录中（保持与原有逻辑的兼容性）
            activity_id = self.record_write_script(file_name, interval)

            # 4. 持久化
            self._save_script_metrics(script_uuid)

            logger.info(
                f"记录write_script指标: script={script.script_name}, "
                f"interval={interval}秒, "
                f"total_write_script_duration={script.write_script_duration}秒"
            )

            return {
                "type": metrics_type,
                "file_name": file_name,
                "interval": interval,
                "script_uuid": script_uuid,
                "script_name": script.script_name,
                "write_script_duration": script.write_script_duration,
                "activity_id": activity_id
            }

        elif metrics_type == "keep_alive":
            # Web使用时间 - 使用现有的 add_keep_alive_duration 方法
            success = self.add_keep_alive_duration(interval)

            if not success:
                # 即使失败也不抛出错误，返回默认响应
                logger.warning("记录keep_alive时间失败，返回默认响应")
                return {
                    "type": metrics_type,
                    "interval": interval,
                    "keep_alive_duration": interval,
                    "note": "记录失败，使用默认值"
                }

            script = self.get_current_script()
            if script:
                logger.info(
                    f"记录keep_alive指标: script={script.script_name}, "
                    f"interval={interval}秒, "
                    f"total_keep_alive_duration={script.keep_alive_duration}秒"
                )

                return {
                    "type": metrics_type,
                    "interval": interval,
                    "script_uuid": script.script_uuid,
                    "script_name": script.script_name,
                    "keep_alive_duration": script.keep_alive_duration
                }
            else:
                # 理论上不会走到这里，因为add_keep_alive_duration应该已经创建了脚本
                logger.warning("记录keep_alive时间后仍然没有活跃脚本")
                return {
                    "type": metrics_type,
                    "interval": interval,
                    "keep_alive_duration": interval,
                    "note": "无活跃脚本，使用默认值"
                }

        else:
            raise ValueError(
                f"不支持的指标类型: {metrics_type}，支持的类型: command_debug, keep_alive, write_script"
            )

    # ==================== aigc.json 相关方法 ====================

    def _read_aigc_config(self) -> Dict[str, Any]:
        """读取 aigc.json 配置文件

        Returns:
            aigc.json 的配置字典，如果文件不存在返回空字典
        """
        try:
            work_dir = path_manager.get_project_root()
            aigc_tool_dir = os.path.join(work_dir, ".aigc_tool")
            aigc_json_path = os.path.join(aigc_tool_dir, "aigc.json")

            if os.path.exists(aigc_json_path):
                with open(aigc_json_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info(f"读取 aigc.json 配置: aigc_project_name={config.get('aigc_project_name')}, nvid={config.get('nvid')}, sessionId={config.get('sessionId')}")
                return config
            else:
                logger.warning("aigc.json 文件不存在")
                return {}
        except Exception as e:
            logger.error(f"读取 aigc.json 失败: {e}")
            return {}

    def update_scripts_from_aigc_config(self, aigc_config: Dict[str, Any]) -> int:
        """根据 aigc.json 的配置更新所有相关脚本度量记录

        Args:
            aigc_config: aigc.json 配置字典

        Returns:
            更新的脚本数量
        """
        try:
            aigc_project_name = aigc_config.get("aigc_project_name")
            nvid = aigc_config.get("nvid")
            sessionId = aigc_config.get("sessionId")

            if not any([aigc_project_name, nvid, sessionId]):
                logger.debug("aigc.json 中没有项目相关配置，跳过更新脚本")
                return 0

            updated_count = 0
            for script_uuid, script in self._scripts.items():
                # 更新这三个字段
                needs_update = False
                if aigc_project_name and script.aigc_project_name != aigc_project_name:
                    script.aigc_project_name = aigc_project_name
                    needs_update = True
                if nvid and script.nvid != nvid:
                    script.nvid = nvid
                    needs_update = True
                if sessionId and script.sessionId != sessionId:
                    script.sessionId = sessionId
                    needs_update = True

                if needs_update:
                    # 持久化更新后的脚本
                    self._save_script_metrics(script_uuid)
                    updated_count += 1
                    logger.debug(f"更新脚本 {script.script_name} 的 aigc 配置: aigc_project_name={aigc_project_name}, nvid={nvid}, sessionId={sessionId}")

            logger.info(f"根据 aigc.json 更新了 {updated_count} 个脚本的配置")
            return updated_count

        except Exception as e:
            logger.error(f"根据 aigc.json 更新脚本失败: {e}")
            return 0

    # ==================== 查询方法 ====================

    def get_all_scripts(self, status: str = "active") -> List[ScriptMetrics]:
        """获取所有脚本"""
        self._ensure_scripts_loaded()
        scripts = []
        for script in self._scripts.values():
            if status == "" or script.status == status:
                scripts.append(script)
        return scripts

    # ==================== 持久化 ====================

    def _save_script_metrics(self, script_uuid: str) -> bool:
        """保存脚本指标到文件"""
        try:
            script = self._scripts.get(script_uuid)
            if not script:
                logger.warning(f"脚本不存在: {script_uuid}")
                return False

            file_path = self._get_script_file_path(script.ai_fingerprint_uuid)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(
                    script.model_dump(mode='json'),
                    f,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                )
            # 更新脚本 UUID 到文件名的映射
            self._script_uuid_to_file[script_uuid] = file_path
            return True
        except Exception as e:
            logger.error(f"保存脚本指标失败: {e}")
            return False

    def _save_deploy_record(self, deploy_record: DeployRecord) -> bool:
        """
        保存部署记录到文件

        文件名格式：deploy-YYYYMMDD-HHMMSS.json
        """
        try:
            # 使用部署调用时间生成文件名
            file_path = self._get_deploy_file_path(deploy_record.deploy_call_time)

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(
                    deploy_record.model_dump(mode='json'),
                    f,
                    ensure_ascii=False,
                    indent=2,
                    default=str
                )

            logger.debug(f"保存部署记录: {file_path.name}")
            return True
        except Exception as e:
            logger.error(f"保存部署记录失败: {e}")
            return False


# 创建全局实例
metrics_service_v2 = MetricsServiceV2()
