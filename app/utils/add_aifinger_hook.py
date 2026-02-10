#!/usr/bin/env python3
"""
Hook脚本 - 自动为本次会话中生成或修改的Python文件添加AI指纹

这个脚本会在定时以及Claude Code任务完成后自动执行，为本次会话中创建或修改的
Python文件添加AI_FingerPrint_UUID注释，忽略.venv目录。
"""

import os
import sys
import subprocess
import glob
import random
import string
import datetime
import time
import re
import tempfile
import shutil
from typing import List, Dict, Optional

def validate_uuid(uuid):
    """
    验证UUID是否合法
    合法的UUID格式应为：YYYYMMDD-8位随机字符（大小写字母和数字的组合）
    同时不允许存在3个及以上连续的字母或数字
    """
    # 检查UUID格式
    if not isinstance(uuid, str):
        return False
    
    # 检查长度和格式
    if len(uuid) != 17:  # 8位日期 + 1位连字符 + 8位随机字符 = 17位
        return False
    
    # 检查格式：YYYYMMDD-xxxxxxxx
    pattern = r'^\d{8}-[a-zA-Z0-9]{8}$'
    if not re.match(pattern, uuid):
        return False
    
    # 检查日期部分是否有效
    date_part = uuid[:8]
    try:
        # 尝试解析日期
        datetime.datetime.strptime(date_part, '%Y%m%d')
    except ValueError:
        return False
    
    # 检查是否存在3个及以上连续的字母或数字
    # 提取随机字符部分（不包含日期部分）
    random_part = uuid[9:]  # 跳过日期和连字符
    
    # 检查连续字母（不区分大小写）
    for i in range(len(random_part) - 2):
        # 确保这三个字符都是字母
        if random_part[i].isalpha() and random_part[i+1].isalpha() and random_part[i+2].isalpha():
            # 转换为小写进行比较
            a, b, c = random_part[i].lower(), random_part[i+1].lower(), random_part[i+2].lower()
            # 检查ASCII码是否连续递增
            if ord(b) == ord(a) + 1 and ord(c) == ord(b) + 1:
                return False
    
    # 检查连续数字
    for i in range(len(random_part) - 2):
        # 确保这三个字符都是数字
        if random_part[i].isdigit() and random_part[i+1].isdigit() and random_part[i+2].isdigit():
            # 转换为整数进行比较
            a, b, c = int(random_part[i]), int(random_part[i+1]), int(random_part[i+2])
            # 检查数字是否连续递增
            if b == a + 1 and c == b + 1:
                return False
    
    return True

def generate_unique_id():
    """
    生成格式为"当天年月日-8位随机字符"的UUID，通过时间戳和随机字符尽量保证当天唯一性
    不再使用文件存储，但通过增加随机因素和时间戳来提高唯一性概率
    """
    # 获取当前日期，格式为YYYYMMDD
    today = datetime.datetime.now().strftime('%Y%m%d')

    # 生成随机字符集（大小写字母+数字）
    chars = string.ascii_letters + string.digits

    # 为了提高唯一性，我们可以：
    # 1. 使用更精确的时间信息作为随机种子
    # 2. 结合进程ID
    # 3. 增加随机字符的随机性

    # 使用当前时间戳（微秒级别）和进程ID作为随机种子
    timestamp = int(time.time() * 1000000)  # 微秒级时间戳
    process_id = os.getpid()
    seed = f"{timestamp}{process_id}"

    # 使用独立的随机数生成器，避免影响全局 random 模块
    rng = random.Random(seed)

    # 生成8位随机字符
    random_str = ''.join(rng.choice(chars) for _ in range(8))

    # 组合成最终的ID
    unique_id = f"{today}-{random_str}"

    return unique_id


def _atomic_write_file(file_path, content):
    """原子性写入文件，避免写入过程中文件损坏

    Args:
        file_path: 文件路径
        content: 要写入的内容

    Returns:
        bool: 写入成功返回True，失败返回False
    """
    try:
        # 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=os.path.dirname(file_path),
            delete=False
        ) as tmp_f:
            tmp_f.write(content)
            tmp_path = tmp_f.name

        # 原子性替换原文件
        shutil.move(tmp_path, file_path)
        return True
    except (IOError, PermissionError):
        return False


def add_fingerprint_to_file(file_path, uuid, is_update=False):
    """为指定Python文件添加AI指纹，当文件正在被读写时会跳过
    
    Args:
        file_path: 文件路径
        uuid: 要添加的UUID
        is_update: 是否是更新不合法的UUID
        
    Returns:
        tuple: (成功状态, 是否是更新操作)
    """
    try:
        # 尝试以非阻塞方式读取文件内容
        try:
            # 首先尝试读取文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (IOError, PermissionError):
            print(f"文件 {file_path} 正在被其他进程读写，跳过处理")
            return False, False

        # 检查是否已存在AI指纹
        if 'AI_FingerPrint_UUID:' in content:
            # 尝试提取现有的UUID并验证其合法性
            match = re.search(r'AI_FingerPrint_UUID:\s*(\S+)', content)
            if match:
                existing_uuid = match.group(1)
                # 如果UUID合法，则跳过处理
                if validate_uuid(existing_uuid):
                    print(f"文件 {file_path} 已包含合法的AI指纹，跳过处理")
                    return False, False
                else:
                    print(f"文件 {file_path} 包含的AI指纹不合法，将替换为新的指纹")
                    # 移除不合法的指纹
                    content = re.sub(r'AI_FingerPrint_UUID:\s*\S+\n?', '', content)
                    is_update = True
            else:
                print(f"文件 {file_path} 包含无效的AI指纹格式，将添加新的指纹")
                content = re.sub(r'AI_FingerPrint_UUID:\s*.*?\n?', '', content)
                is_update = True

        # 查找合适的位置插入AI指纹
        # 优化：寻找类定义前面的第一个多行注释块，兼容"""和'''
        # 支持任意类名，不限制为TestClass

        # 查找任意类定义：class <AnyClassName> 或 class <AnyClassName>(Base):
        test_class_pattern = r'class\s+\w+\s*(?:\([^)]*\))?\s*:'
        class_match = re.search(test_class_pattern, content)
        
        if class_match:
            # 获取类定义的位置
            class_pos = class_match.start()
            
            # 提取类定义前的文本
            text_before_class = content[:class_pos]
            
            # 查找类定义前的最后一个多行注释块（兼容"""和'''）
            # 先查找"""类型的注释块
            double_quote_matches = list(re.finditer(r'"""[\s\S]*?"""', text_before_class))
            # 再查找'''类型的注释块
            single_quote_matches = list(re.finditer(r"'''[\s\S]*?'''", text_before_class))
            
            # 合并所有匹配结果并按位置排序
            all_matches = double_quote_matches + single_quote_matches
            all_matches.sort(key=lambda x: x.start())
            
            if all_matches:
                # 取最后一个注释块（离类定义最近的）
                last_comment = all_matches[-1]
                comment_content = last_comment.group(0)
                comment_start = last_comment.start()
                
                # 检查注释块中是否包含"======xxxx====="项目详细信息结构
                project_info_pattern = r'(=+\s*项目详细信息START\s*=+)([\s\S]*?)(=+\s*项目详细信息END\s*=+)'
                project_info_match = re.search(project_info_pattern, comment_content)
                
                if project_info_match:
                    # 找到项目详细信息结构，在项目详细信息END标记前插入UUID
                    # 获取项目详细信息内容部分
                    info_content = project_info_match.group(2)
                    # 获取项目详细信息END标记的开始位置
                    end_marker_start = comment_content.find(project_info_match.group(3))
                    
                    # 在项目详细信息END标记前插入UUID
                    fingerprint_line = f'\nAI_FingerPrint_UUID: {uuid}\n'
                    insert_pos = comment_start + end_marker_start
                    new_content = (
                        content[:insert_pos] +
                        fingerprint_line +
                        content[insert_pos:]
                    )
                    
                    # 尝试原子写入文件
                    try:
                        if _atomic_write_file(file_path, new_content):
                            if is_update:
                                print(f"成功为 {file_path} 更新AI指纹: {uuid}")
                            else:
                                print(f"成功为 {file_path} 添加AI指纹: {uuid}")
                            return True, is_update
                        else:
                            print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                            return False, False
                    except (IOError, PermissionError):
                        print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                        return False, False
                else:
                    # 没有找到项目详细信息结构，使用原有逻辑在注释块结束位置前插入AI指纹
                    # 检查注释块类型并找到结束引号位置
                    if '"""' in comment_content:
                        last_quote_pos = comment_content.rfind('"""')
                    else:
                        last_quote_pos = comment_content.rfind("'''")
                    
                    if last_quote_pos != -1:
                        # 在注释块结束位置前插入AI指纹
                        fingerprint_line = f'\nAI_FingerPrint_UUID: {uuid}\n'
                        insert_pos = comment_start + last_quote_pos
                        new_content = (
                            content[:insert_pos] +
                            fingerprint_line +
                            content[insert_pos:]
                        )
                        
                        # 尝试原子写入文件
                        try:
                            if _atomic_write_file(file_path, new_content):
                                if is_update:
                                    print(f"成功为 {file_path} 更新AI指纹: {uuid}")
                                else:
                                    print(f"成功为 {file_path} 添加AI指纹: {uuid}")
                                return True, is_update
                            else:
                                print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                                return False, False
                        except (IOError, PermissionError):
                            print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                            return False, False
        
        # 如果没有找到指定类定义前的注释块，继续处理普通注释块
        # 如果没有找到类定义前面的注释块，检查文件中是否有任何多行注释块
        for comment_marker in ['"""', "'''"]:
            if comment_marker in content:
                # 查找第一个多行注释块
                first_comment_start = content.find(comment_marker)
                if first_comment_start != -1:
                    first_comment_end = content.find(comment_marker, first_comment_start + 3)
                    if first_comment_end != -1:
                        # 在注释块内插入AI指纹
                        fingerprint_line = f'\nAI_FingerPrint_UUID: {uuid}\n'
                        new_content = (
                            content[:first_comment_end] +
                            fingerprint_line +
                            content[first_comment_end:]
                        )

                        # 尝试原子写入文件，使用异常处理捕获文件被占用的情况
                        try:
                            if _atomic_write_file(file_path, new_content):
                                if is_update:
                                    print(f"成功为 {file_path} 更新AI指纹: {uuid}")
                                else:
                                    print(f"成功为 {file_path} 添加AI指纹: {uuid}")
                                return True, is_update
                            else:
                                print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                                return False, False
                        except (IOError, PermissionError):
                            print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                            return False, False
                break

        # 如果没有多行注释块，在文件开头添加注释
        fingerprint_comment = f'"""\nAI_FingerPrint_UUID: {uuid}\n"""\n'
        try:
            if _atomic_write_file(file_path, fingerprint_comment + content):
                if is_update:
                    print(f"成功为 {file_path} 更新AI指纹: {uuid}")
                else:
                    print(f"成功为 {file_path} 添加AI指纹: {uuid}")
                return True, is_update
            else:
                print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
                return False, False
        except (IOError, PermissionError):
            print(f"文件 {file_path} 正在被其他进程写入，跳过处理")
            return False, False

    except Exception as e:
        print(f"处理文件 {file_path} 时出错: {e}")
        return False, False


def add_fingerprint_to_files(file_paths: List[str]) -> Dict[str, bool]:
    """批量为文件列表添加AI指纹

    Args:
        file_paths: 文件路径列表（绝对路径）

    Returns:
        dict: {file_path: success} 的字典，表示每个文件的处理结果
    """
    results = {}

    for file_path in file_paths:
        # 只处理Python文件
        if not file_path.endswith('.py'):
            continue

        # 检查文件是否存在
        if not os.path.exists(file_path):
            continue

        # 为每个文件生成独立的UUID
        uuid = generate_unique_id()
        success, _ = add_fingerprint_to_file(file_path, uuid)
        results[file_path] = success

    return results


def is_copied_file(file_path):
    """
    判断文件是否为复制/上传的文件
    如果文件创建时间远早于修改时间，说明是复制进来的文件
    """
    try:
        ctime = os.path.getctime(file_path)  # 创建时间
        mtime = os.path.getmtime(file_path)  # 修改时间

        # 如果创建时间比修改时间早超过1小时，可能是复制文件
        # 这个阈值可以根据实际情况调整
        time_diff_threshold = 3600  # 1小时

        return ctime < mtime - time_diff_threshold
    except OSError:
        # 如果无法获取时间信息，默认不是复制文件
        return False


def get_files_modified_in_window(project_root, start_time, end_time=None, file_extensions=None, exclude_dirs=None):
    """
    获取在指定时间窗口内修改或创建的文件

    Args:
        project_root: 项目根目录
        start_time: 时间窗口开始时间（时间戳）
        end_time: 时间窗口结束时间（时间戳），默认为当前时间
        file_extensions: 需要处理的文件扩展名列表，如 ['.py']，默认为 None（所有文件）
        exclude_dirs: 需要排除的目录名列表，默认为 ['.venv', '.claude', '.git', '__pycache__', 'venv', 'env']

    Returns:
        list: 修改时间在时间窗口内的文件路径列表
    """
    if end_time is None:
        end_time = time.time()

    if exclude_dirs is None:
        exclude_dirs = {'.venv', '.claude', '.git', '__pycache__', 'venv', 'env', '.pytest_cache', '.tox', 'dist', 'build', '.eggs', '*.egg-info'}

    if file_extensions is None:
        file_extensions = ['.py']

    modified_files = []

    for root, dirs, files in os.walk(project_root):
        # 过滤掉不需要的目录
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]

        for file in files:
            # 检查文件扩展名
            if file_extensions:
                if not any(file.endswith(ext) for ext in file_extensions):
                    continue

            file_path = os.path.join(root, file)

            try:
                # 获取文件修改时间
                mtime = os.path.getmtime(file_path)

                # 检查修改时间是否在时间窗口内
                if start_time <= mtime <= end_time:
                    modified_files.append(file_path)

            except OSError:
                # 如果无法获取文件时间，跳过
                continue

    return modified_files


def add_fingerprints_for_modified_files(project_root, start_time, end_time, file_extensions=None, exclude_dirs=None, filename_prefix=None, exclude_filename_prefix=None):
    """
    为时间窗口内修改的文件批量添加指纹（封装常用逻辑）

    Args:
        project_root: 项目根目录
        start_time: 时间窗口开始时间
        end_time: 时间窗口结束时间
        file_extensions: 文件扩展名列表，默认 ['.py']
        exclude_dirs: 排除的目录列表
        filename_prefix: 只处理指定前缀的文件（如 'test_'），None 表示不限制
        exclude_filename_prefix: 排除指定前缀的文件（如 'test_example'），None 表示不限制

    Returns:
        dict: {file_path: success} 的字典
    """
    modified_files = get_files_modified_in_window(
        project_root=project_root,
        start_time=start_time,
        end_time=end_time,
        file_extensions=file_extensions,
        exclude_dirs=exclude_dirs
    )

    # 根据前缀过滤
    if filename_prefix is not None:
        modified_files = [f for f in modified_files if os.path.basename(f).startswith(filename_prefix)]

    if exclude_filename_prefix is not None:
        modified_files = [f for f in modified_files if not os.path.basename(f).startswith(exclude_filename_prefix)]

    if modified_files:
        return add_fingerprint_to_files(modified_files)

    return {}


class FileModificationTracker:
    """
    文件修改追踪器 - 用于追踪函数执行期间修改的文件

    使用方法：
        with FileModificationTracker(project_root, file_extensions=['.py']) as tracker:
            # 执行可能修改文件的操作
            ...

        # 获取执行期间修改的文件
        modified_files = tracker.get_modified_files()
    """

    def __init__(self, project_root, file_extensions=None, exclude_dirs=None):
        """
        初始化追踪器

        Args:
            project_root: 项目根目录
            file_extensions: 需要追踪的文件扩展名列表
            exclude_dirs: 需要排除的目录名列表
        """
        self.project_root = project_root
        self.file_extensions = file_extensions if file_extensions else ['.py']
        self.exclude_dirs = exclude_dirs
        self.start_time = None
        self.end_time = None
        self._modified_files = []

    def __enter__(self):
        """进入上下文，记录开始时间"""
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文，记录结束时间并收集修改的文件"""
        _ = exc_type, exc_val, exc_tb  # 避免未使用变量警告
        self.end_time = time.time()
        self._modified_files = get_files_modified_in_window(
            self.project_root,
            self.start_time,
            self.end_time,
            self.file_extensions,
            self.exclude_dirs
        )
        return False

    def get_modified_files(self):
        """获取在追踪期间修改的文件列表"""
        return self._modified_files

    def add_fingerprints_to_modified_files(self):
        """
        为追踪期间修改的文件添加指纹

        Returns:
            dict: {file_path: success} 的字典，表示每个文件的处理结果
        """
        results = {}
        for file_path in self._modified_files:
            # 跳过以 test_example 开头的文件
            if os.path.basename(file_path).startswith('test_example'):
                continue

            uuid = generate_unique_id()
            success, _ = add_fingerprint_to_file(file_path, uuid)
            results[file_path] = success

        return results


# ==================== 函数：为函数执行期间修改的文件添加指纹并返回 UUID ====================

def add_fingerprints_and_return_uuids(
    project_root: str,
    start_time: float,
    file_extensions: Optional[List[str]] = None,
    exclude_dirs: Optional[set] = None,
    filename_prefix: Optional[str] = None,
    exclude_filename_prefix: Optional[str] = None
) -> Dict[str, str]:
    """
    为时间窗口内修改的文件添加指纹并返回 UUID 映射

    Args:
        project_root: 项目根目录
        start_time: 时间窗口开始时间（函数入口时间）
        file_extensions: 文件扩展名列表，默认 ['.py']
        exclude_dirs: 排除的目录集合
        filename_prefix: 只处理指定前缀的文件（如 'test_'）
        exclude_filename_prefix: 排除指定前缀的文件（如 'test_example'）

    Returns:
        {file_path: uuid} 字典，成功添加指纹的文件及其 UUID
    """
    # 自动获取当前时间作为结束时间
    end_time = time.time()

    if file_extensions is None:
        file_extensions = ['.py']
    if exclude_dirs is None:
        exclude_dirs = {'.venv', '.claude', '.git', '__pycache__', 'venv', 'env', '.pytest_cache', '.tox', 'dist', 'build', '.eggs', '*.egg-info'}

    # 获取修改的文件
    modified_files = get_files_modified_in_window(
        project_root=project_root,
        start_time=start_time,
        end_time=end_time,
        file_extensions=file_extensions,
        exclude_dirs=exclude_dirs
    )

    # 根据前缀过滤
    if filename_prefix is not None:
        modified_files = [f for f in modified_files if os.path.basename(f).startswith(filename_prefix)]

    if exclude_filename_prefix is not None:
        modified_files = [f for f in modified_files if not os.path.basename(f).startswith(exclude_filename_prefix)]

    # 为每个文件添加指纹并返回 UUID 映射
    uuid_map = {}
    for file_path in modified_files:
        uuid = generate_unique_id()
        success, _ = add_fingerprint_to_file(file_path, uuid)
        if success:
            uuid_map[file_path] = uuid

    return uuid_map


def get_session_start_time():
    """获取会话开始时间"""
    try:
        # 尝试从环境变量获取会话开始时间
        session_start_env = os.environ.get('CLAUDE_SESSION_START')
        if session_start_env:
            return float(session_start_env)

        # 如果没有设置环境变量，使用默认值（当前时间前10分钟）
        print("警告: 未找到CLAUDE_SESSION_START环境变量，使用默认会话开始时间")
        return time.time() - 1200  # 20分钟前
    except (ValueError, TypeError):
        # 如果环境变量格式错误，使用默认值
        print("警告: CLAUDE_SESSION_START环境变量格式错误，使用默认会话开始时间")
        return time.time() - 1200  # 20分钟前

def get_session_created_files():
    """获取本次会话中新创建的Python文件（排除复制文件和test_example开头的文件）"""
    try:
        # 获取准确的会话开始时间
        session_start_time = get_session_start_time()

        project_root = os.getcwd()
        created_files = []

        # 查找所有.py文件，但忽略.venv目录和test_example开头的文件
        for root, dirs, files in os.walk(project_root):
            # 跳过.venv和.claude目录
            if '.venv' in root or '.claude' in root:
                continue

            for file in files:
                # 跳过以test_example开头的Python文件
                if file.endswith('.py') and not file.startswith('test_example'):
                    file_path = os.path.join(root, file)

                    # 检查文件创建时间和修改时间
                    try:
                        ctime = os.path.getctime(file_path)
                        mtime = os.path.getmtime(file_path)

                        # 条件1：文件在会话期间创建
                        # 条件2：不是复制文件（创建时间不早于修改时间太多）
                        if (ctime >= session_start_time and
                            not is_copied_file(file_path)):
                            created_files.append(file_path)

                    except OSError:
                        # 如果无法获取文件时间，跳过
                        continue

        return created_files

    except Exception as e:
        print(f"获取创建文件列表时出错: {e}")
        return []

def main():
    """主函数 - 扫描本次会话中新创建的Python文件并添加AI指纹（排除复制文件）"""
    print("开始执行 Hook - 自动添加AI指纹检测...")

    # 先获取本次会话中新创建的Python文件（排除复制文件）
    python_files = get_session_created_files()

    # 判断是否存在新增文件
    if not python_files:
        print("未找到在本次会话中新创建的Python文件，跳过AI指纹添加")
        return

    print(f"找到 {len(python_files)} 个在本次会话中新创建的Python文件（已排除复制文件）")

    # 为每个Python文件添加不同的随机指纹
    processed_count = 0
    updated_count = 0
    for file_path in python_files:
        # 为每个文件单独生成一个随机指纹
        uuid = generate_unique_id()
        success, is_update = add_fingerprint_to_file(file_path, uuid)
        if success:
            processed_count += 1
            if is_update:
                updated_count += 1

    print(f"Hook执行完成，成功为 {processed_count} 个文件添加/更新AI指纹")
    if updated_count > 0:
        print(f"其中 {updated_count} 个文件是因为包含不合法的AI指纹而被更新")

if __name__ == "__main__":
    main()