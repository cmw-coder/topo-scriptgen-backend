"""
用户上下文管理工具
用于获取用户名并将其保存为全局环境变量
"""
import os
import getpass
from typing import Optional

class UserContext:
    """用户上下文管理器"""

    # 全局变量存储当前用户名
    _current_username: Optional[str] = None

    @classmethod
    def get_username(cls) -> str:
        """获取当前用户名并缓存"""
        if cls._current_username is None:
            cls._current_username = getpass.getuser()
            # 设置为环境变量
            os.environ['SCRIPTGEN_USERNAME'] = cls._current_username
        return cls._current_username

    @classmethod
    def get_aigc_target_dir(cls) -> str:
        """获取 AIGC 工具的目标目录"""
        username = cls.get_username()
        return f"/opt/coder/statistics/build/aigc_tool/{username}"

    @classmethod
    def set_permissions_recursive(cls, path, mode, silent=False):
        """递归设置目录及其所有内容的权限（静默模式，不记录日志）

        Args:
            path: 目录或文件路径
            mode: 权限模式（如 0o777）
            silent: 是否静默模式（默认True，不记录警告日志）

        Returns:
            bool: 是否成功设置权限
        """
        # 完全静默，不记录任何日志
        try:
            if os.path.isfile(path):
                # 如果是文件，直接设置权限
                os.chmod(path, mode)
            else:
                # 如果是目录，递归设置权限
                for root, dirs, files in os.walk(path):
                    for dir_name in dirs:
                        dir_path = os.path.join(root, dir_name)
                        try:
                            os.chmod(dir_path, mode)
                        except (PermissionError, OSError):
                            # 静默忽略权限错误
                            pass
                    for file_name in files:
                        file_path = os.path.join(root, file_name)
                        try:
                            os.chmod(file_path, mode)
                        except (PermissionError, OSError):
                            # 静默忽略权限错误
                            pass
                # 最后设置顶层目录的权限
                try:
                    os.chmod(path, mode)
                except (PermissionError, OSError):
                    # 静默忽略权限错误
                    pass
            return True
        except (PermissionError, OSError):
            # 静默忽略所有权限错误
            return False
        except Exception:
            # 其他异常也静默处理
            return False

    @classmethod
    def safe_mkdirs(cls, path, mode=0o777):
        """安全地创建目录并设置权限

        Args:
            path: 目录路径
            mode: 权限模式（默认 0o777）

        Returns:
            bool: 是否成功创建并设置权限
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            os.makedirs(path, mode=mode, exist_ok=True)
            # 再次确保权限设置正确（makedirs 的 mode 参数可能受 umask 影响）
            cls.set_permissions_recursive(path, mode, silent=True)
            return True
        except PermissionError as e:
            logger.error(f"权限不足: 无法创建目录 {path} - {str(e)}")
            return False
        except Exception as e:
            logger.error(f"创建目录失败 {path}: {str(e)}")
            return False

    @classmethod
    def check_and_fix_permissions(cls, target_dir):
        """检查并尝试修复目录权限

        Args:
            target_dir: 目标目录路径

        Returns:
            dict: 包含检查结果和修复建议的字典
        """
        import logging
        logger = logging.getLogger(__name__)

        result = {
            "exists": False,
            "writable": False,
            "permission_fixed": False,
            "error": None,
            "suggestions": []
        }

        try:
            # 检查目录是否存在
            if not os.path.exists(target_dir):
                result["error"] = f"目录不存在: {target_dir}"
                result["suggestions"].append(f"请先创建目录: sudo mkdir -p {target_dir}")
                result["suggestions"].append(f"然后设置权限: sudo chmod 777 {target_dir}")
                return result

            result["exists"] = True

            # 检查是否有写权限
            test_file = os.path.join(target_dir, ".permission_test")
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                result["writable"] = True
            except PermissionError:
                result["error"] = f"权限不足: 无法写入目录 {target_dir}"
                result["suggestions"].append(f"请执行命令修复权限: sudo chmod 777 {target_dir}")
                result["suggestions"].append(f"或者修改目录所有者: sudo chown -R $USER:$USER {target_dir}")
                return result

            # 尝试修复权限
            if cls.set_permissions_recursive(target_dir, 0o777):
                result["permission_fixed"] = True
                logger.info(f"权限修复成功: {target_dir}")
            else:
                result["suggestions"].append(f"无法自动修复权限，请手动执行: sudo chmod -R 777 {target_dir}")

        except Exception as e:
            result["error"] = f"检查权限时发生错误: {str(e)}"
            logger.error(result["error"])

        return result

# 创建全局实例
user_context = UserContext()
