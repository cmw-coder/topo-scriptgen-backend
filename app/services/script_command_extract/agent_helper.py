"""
Agent Helper Module - 旧版本功能的辅助模块

此模块提供从日志文件中提取命令信息的功能，
作为新旧版本之间的桥梁。

AI_FingerPrint_UUID: 20251225-PpWqM9nN
"""

import os
import json
from typing import Any, Dict, List
from pathlib import Path

from app.services.script_command_extract.log_decode import JSONProcessor
from app.services.script_command_extract.log_process import LOGPROCESS
from app.core.config import settings


# Global static variable for filename-command mapping
# 全局静态变量：文件名到命令的映射
filename_command_mapping: Dict[str, str] = {}


def find_command_by_filename(script_filename: str) -> str:
    """
    根据脚本文件名查找对应的命令

    优先级：
    1. 精确匹配文件名
    2. 去除扩展名后匹配
    3. 使用更严格的模糊匹配（基于文件名的相似度）

    Args:
        script_filename: 脚本文件名（如 test_script3.py）

    Returns:
        匹配到的命令，如果未找到则返回空字符串
    """
    global filename_command_mapping

    if not script_filename:
        return ""

    # 1. 精确匹配
    if script_filename in filename_command_mapping:
        return filename_command_mapping[script_filename]

    # 2. 去除扩展名后匹配（处理 .py 等扩展名不一致的情况）
    name_without_ext = os.path.splitext(script_filename)[0]
    for key, value in filename_command_mapping.items():
        key_without_ext = os.path.splitext(key)[0]
        if name_without_ext == key_without_ext:
            return value

    # 3. 更严格的模糊匹配：只匹配包含文件名核心部分的键
    # 优先匹配最相似的键（基于公共前缀/后缀长度）
    best_match_key = None
    best_match_score = 0

    for key in filename_command_mapping.keys():
        # 计算相似度：公共前缀或后缀的长度
        # 例如：test_script3.py 和 test_script3_function.py
        #      公共部分是 test_script3，得分应为 12

        # 去除扩展名进行比较
        key_core = os.path.splitext(key)[0].lower()
        name_core = name_without_ext.lower()

        # 检查是否一个是另一个的前缀或后缀
        if key_core.startswith(name_core):
            score = len(name_core)
        elif name_core.startswith(key_core):
            score = len(key_core)
        elif name_core in key_core or key_core in name_core:
            # 包含关系，但不是前缀/后缀，降低权重
            score = max(len(name_core), len(key_core)) * 0.5
        else:
            continue

        if score > best_match_score:
            best_match_score = score
            best_match_key = key

    # 只有当相似度超过阈值时才返回（至少3个字符的匹配）
    if best_match_key and best_match_score >= 3:
        print(f"[agent_helper] 模糊匹配: '{script_filename}' -> '{best_match_key}' (score: {best_match_score})")
        return filename_command_mapping[best_match_key]

    # 未找到匹配
    print(f"[agent_helper] 未找到匹配的命令: '{script_filename}'")
    print(f"[agent_helper] 可用的键: {list(filename_command_mapping.keys())}")
    return ""


def refresh_static_variables() -> Dict[str, str]:
    """
    从日志文件中刷新全局静态变量

    此函数会：
    1. 从配置的日志路径读取所有 .pytestlog.json 文件
    2. 解码和处理日志文件
    3. 提取命令信息并更新 filename_command_mapping

    Returns:
        Dict[str, str]: 更新后的 filename_command_mapping

    Raises:
        Exception: 当日志处理失败时
    """
    global filename_command_mapping

    # 创建 ExtractCommandAgent 实例并处理日志
    agent = ExtractCommandAgent(settings.get_script_command_log_path())
    res = agent.get_log_command_info()

    if res:
        # 使用结果更新 filename_command_mapping
        # 假设 res 是一个字典，文件名为key，命令行为value
        if isinstance(res, dict):
            filename_command_mapping = res
        elif isinstance(res, list):
            # 如果 res 是列表，转换为字典，使用索引作为key
            for i, item in enumerate(res):
                filename_command_mapping[f"file_{i}"] = item

    return filename_command_mapping


class ExtractCommandAgent(object):
    """
    从日志文件中提取命令信息的代理类

    此类负责：
    1. 扫描指定目录下的所有 .pytestlog.json 文件
    2. 对每个文件进行Base64解码
    3. 处理解码后的JSON文件，提取命令信息
    """

    def __init__(self, input_path: str):
        """
        初始化代理

        Args:
            input_path: 日志文件所在的目录路径
        """
        self.input_path = input_path

    def get_log_command_info(self) -> Dict[str, str]:
        """
        获取日志文件中的命令信息

        处理流程：
        1. 验证输入路径是否为目录
        2. 创建临时目录用于存放解码后的文件
        3. 递归扫描并处理所有 .pytestlog.json 文件
        4. 使用 LOGPROCESS 处理解码后的文件
        5. 返回提取的命令信息

        Returns:
            Dict[str, str]: 文件名到命令信息的映射字典

        Raises:
            Exception: 当目录创建失败或文件处理失败时
        """
        # 1. 验证输入路径
        if not os.path.isdir(self.input_path):
            print(f"这不是一个文件夹: {self.input_path}")
            return {}

        # 2. 创建临时目录
        folder_name = "local"
        current_dir = os.getcwd()  # 获取当前目录
        folder_path = os.path.join(current_dir, folder_name)

        try:
            os.makedirs(folder_path, exist_ok=True)  # 使用 os.makedirs
            absolute_path = os.path.abspath(folder_path)
            print(f"文件夹已创建/确认存在: {absolute_path}")
        except Exception as e:
            print(f"创建文件夹失败: {e}")
            import traceback
            traceback.print_exc()
            return {}

        # 3. 递归扫描并处理所有 .pytestlog.json 文件
        try:
            for root, dirs, files in os.walk(self.input_path):
                for file in files:
                    if file.endswith('.pytestlog.json'):
                        input_file = os.path.join(root, file)
                        filename = os.path.basename(file)
                        output_file = os.path.join(folder_path, filename)

                        # 解码处理 JSON 文件
                        decode_processor = JSONProcessor(input_file, output_file)
                        decode_data = decode_processor.process()

                        if decode_data:
                            print(f"成功解码文件: {filename}")
                        else:
                            print(f"警告: 解码文件失败: {filename}")

        except Exception as e:
            print(f"扫描或解码文件时出错: {e}")
            import traceback
            traceback.print_exc()
            return {}

        # 4. 使用 LOGPROCESS 处理解码后的文件
        try:
            log_processor = LOGPROCESS(folder_path)
            log_command_info = log_processor.log_file_process()

            if log_command_info:
                print(f"成功提取命令信息，共 {len(log_command_info)} 个文件")
                # 打印获取的文件名列表
                print("=" * 60)
                print("获取的文件名列表:")
                print("=" * 60)
                for idx, filename in enumerate(log_command_info.keys(), 1):
                    print(f"  {idx}. {filename}")
                print("=" * 60)
            else:
                print("警告: 未能提取到命令信息")

            return log_command_info if log_command_info else {}

        except Exception as e:
            print(f"处理日志文件时出错: {e}")
            import traceback
            traceback.print_exc()
            return {}


def _load_default_script_mapping():
    """
    加载默认的脚本配置

    从预定义的文件中加载默认的测试脚本配置
    """
    default_mappings = {
        "test_script3.py": "@temp/test_script3_function_before_modification.md"
    }

    loaded_mappings = {}
    for script_name, file_path in default_mappings.items():
        try:
            # 构建绝对路径
            base_dir = Path(__file__).parent.parent.parent.parent  # 回到项目根目录
            full_path = base_dir / file_path.lstrip('@')

            if full_path.exists():
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    loaded_mappings[script_name] = content
                    print(f"  - 已加载默认配置: {script_name} <- {file_path}")
            else:
                print(f"  - 警告: 默认配置文件不存在: {full_path}")
        except Exception as e:
            print(f"  - 警告: 加载默认配置失败 {script_name}: {e}")

    return loaded_mappings


# 自动初始化：在模块加载时执行
# 这样可以确保 filename_command_mapping 在首次导入时就被填充
def _initialize_on_startup():
    """
    模块启动时自动初始化

    此函数会在模块首次导入时自动调用，
    确保 filename_command_mapping 被正确初始化
    """
    global filename_command_mapping

    try:
        print("Agent Helper: 正在初始化...")

        # 1. 先加载默认配置
        print("Agent Helper: 加载默认脚本配置...")
        default_mappings = _load_default_script_mapping()

        # 2. 再从日志文件刷新（可能会覆盖默认配置）
        log_mappings = refresh_static_variables()

        # 3. 合并配置：默认配置 + 日志配置（日志配置优先）
        filename_command_mapping = {**default_mappings, **log_mappings}

        print(f"Agent Helper: 初始化完成。共 {len(filename_command_mapping)} 个脚本映射。")
    except Exception as e:
        print(f"Agent Helper: 初始化失败 - {e}")
        import traceback
        traceback.print_exc()


# 执行自动初始化
_initialize_on_startup()
