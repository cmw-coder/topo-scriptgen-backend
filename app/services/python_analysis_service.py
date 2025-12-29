import os
import re
import ast
from pathlib import Path
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

from app.core.path_manager import path_manager
from app.models.python_analysis import PythonFileInfo, CommandLineInfo

logger = logging.getLogger(__name__)

class PythonAnalysisService:
    """Python文件分析服务
AI_FingerPrint_UUID: 20251225-A8DjNGVl
"""

    def __init__(self):
        self.path_manager = path_manager

    async def find_all_python_files(self, base_path: Optional[str] = None) -> List[PythonFileInfo]:
        """查找项目中的所有Python文件"""
        try:
            if base_path:
                resolved_path = self.path_manager.resolve_path(base_path)
            else:
                resolved_path = self.path_manager.get_project_root()

            if not self.path_manager.is_safe_path(resolved_path):
                logger.warning(f"路径不安全或超出项目范围: {resolved_path}")
                return []

            if not resolved_path.exists():
                logger.warning(f"路径不存在: {resolved_path}")
                return []

            python_files = []
            
            # 递归查找所有.py文件
            for py_file in resolved_path.rglob("*.py"):
                try:
                    # 检查文件安全性
                    if not self.path_manager.is_safe_path(py_file):
                        continue

                    # 过滤掉 .venv, test_example 和 KE 目录中的文件（大小写不敏感）
                    path_parts_upper = [part.upper() for part in py_file.parts]
                    if '.venv' in py_file.parts or 'test_example' in py_file.parts or 'KE' in path_parts_upper:
                        logger.debug(f"过滤Python文件: {py_file}")
                        continue

                    # 获取文件信息
                    stat_info = py_file.stat()
                    modified_time = datetime.fromtimestamp(stat_info.st_mtime)
                    
                    # 获取相对路径
                    relative_path = self.path_manager.get_relative_path(py_file)
                    
                    file_info = PythonFileInfo(
                        file_path=str(py_file),
                        file_name=py_file.name,
                        modified_time=modified_time,
                        size=stat_info.st_size,
                        relative_path=relative_path
                    )
                    python_files.append(file_info)
                    
                except (OSError, PermissionError) as e:
                    logger.warning(f"无法访问文件: {py_file}, 错误: {str(e)}")
                    continue

            # 按修改时间倒序排序（最新的在前）
            python_files.sort(key=lambda x: x.modified_time, reverse=True)
            
            return python_files

        except Exception as e:
            logger.error(f"查找Python文件失败: {str(e)}")
            return []

    async def extract_command_lines(self, file_path: str) -> Dict[str, Any]:
        """从Python文件中提取命令行，特别处理gl.DUTX.CheckCommand、gl.DUTX.send和gl.DUTX.clear_buffer等模式"""
        try:
            # 解析路径并检查安全性
            resolved_path = self.path_manager.resolve_path(file_path)
            if not self.path_manager.is_safe_path(resolved_path):
                logger.warning(f"路径不安全或超出项目范围: {file_path}")
                return {
                    "command_lines": [],
                    "clear_buffer_count": 0,
                    "clear_buffer_locations": []
                }

            if not resolved_path.exists():
                logger.warning(f"文件不存在: {file_path}")
                return {
                    "command_lines": [],
                    "clear_buffer_count": 0,
                    "clear_buffer_locations": []
                }

            if not resolved_path.is_file():
                logger.warning(f"路径不是文件: {file_path}")
                return {
                    "command_lines": [],
                    "clear_buffer_count": 0,
                    "clear_buffer_locations": []
                }

            # 检查文件扩展名
            if resolved_path.suffix.lower() != '.py':
                logger.warning(f"文件不是Python文件: {file_path}")
                return {
                    "command_lines": [],
                    "clear_buffer_count": 0,
                    "clear_buffer_locations": []
                }

            # 读取文件内容
            with open(resolved_path, 'r', encoding='utf-8') as file:
                content = file.read()

            command_lines = []
            clear_buffer_locations = []
            command_id = 1
            current_function = None

            # 首先解析AST获取函数定义
            try:
                tree = ast.parse(content)
                current_function = self._get_current_function(tree)
            except SyntaxError as e:
                logger.warning(f"文件语法错误: {file_path}, 错误: {str(e)}")

            # 逐行分析，提取命令行
            lines = content.split('\n')

            for line_num, line in enumerate(lines, 1):
                # 检查函数定义
                function_match = re.match(r'\s*def\s+(\w+)\s*\(', line)
                if function_match:
                    current_function = function_match.group(1)
                    continue

                # 提取gl.DUTX.CheckCommand模式（处理多行）
                checkcommand_match = re.search(r'gl\.(\w+)\.CheckCommand\s*\(', line)
                if checkcommand_match:
                    dut_device = checkcommand_match.group(1)

                    # 查找完整的CheckCommand调用
                    full_call = self._find_full_function_call(lines, line_num - 1)
                    if full_call:
                        # 从完整调用中提取信息
                        extracted_info = self._extract_checkcommand_from_full_call(full_call, line_num)
                        if extracted_info:
                            command_info = CommandLineInfo(
                                id=command_id,
                                command=extracted_info['command'],
                                line_number=line_num,
                                context=self._get_context(lines, line_num),
                                function_name=current_function,
                                dut_device=f"DUT{dut_device.replace('DUT', '')}" if dut_device.startswith('DUT') else dut_device,
                                command_type="CheckCommand",
                                parameters=extracted_info['parameters'],
                                description=extracted_info['description']
                            )
                            command_lines.append(command_info)
                            command_id += 1
                            continue

                # 提取gl.DUTX.send模式（处理多行，同时支持大写和小写）
                send_match = re.search(r'gl\.(\w+)\.send\s*\(', line, re.IGNORECASE)
                if send_match:
                    dut_device = send_match.group(1)

                    # 查找完整的send调用
                    full_call = self._find_full_function_call(lines, line_num - 1)
                    if full_call:
                        # 提取命令内容（支持多行和复杂参数）
                        command = self._extract_send_command(full_call)
                        if command:
                            command_info = CommandLineInfo(
                                id=command_id,
                                command=command,
                                line_number=line_num,
                                context=self._get_context(lines, line_num),
                                function_name=current_function,
                                dut_device=f"DUT{dut_device.replace('DUT', '')}" if dut_device.startswith('DUT') else dut_device,
                                command_type="send",
                                description=f"发送命令到{dut_device}",
                                parameters=self._extract_send_parameters(full_call)
                            )
                            command_lines.append(command_info)
                            command_id += 1
                            continue

                # 提取gl.DUTX.clear_buffer模式（记录出现位置和次数）
                clear_buffer_match = re.search(r'gl\.(\w+)\.clear_buffer\s*\(', line, re.IGNORECASE)
                if clear_buffer_match:
                    dut_device = clear_buffer_match.group(1)

                    clear_buffer_info = {
                        "line_number": line_num,
                        "dut_device": f"DUT{dut_device.replace('DUT', '')}" if dut_device.startswith('DUT') else dut_device,
                        "function_name": current_function,
                        "code_line": line.strip(),
                        "context": self._get_context(lines, line_num, context_lines=2)
                    }
                    clear_buffer_locations.append(clear_buffer_info)
                    continue

                # 提取其他系统调用模式
                command_patterns = [
                    (r'os\.system\s*\(\s*[\'"]([^\'"]+)[\'"]', 'os.system'),
                    (r'subprocess\.run\s*\(\s*[\'"]([^\'"]+)[\'"]', 'subprocess.run'),
                    (r'subprocess\.Popen\s*\(\s*[\'"]([^\'"]+)[\'"]', 'subprocess.Popen'),
                    (r'exec\s*\(\s*[\'"]([^\'"]+)[\'"]', 'exec'),
                    (r'eval\s*\(\s*[\'"]([^\'"]+)[\'"]', 'eval')
                ]

                for pattern, cmd_type in command_patterns:
                    match = re.search(pattern, line)
                    if match:
                        command = match.group(1)
                        command_info = CommandLineInfo(
                            id=command_id,
                            command=command,
                            line_number=line_num,
                            context=self._get_context(lines, line_num),
                            function_name=current_function,
                            command_type=cmd_type,
                            description=f"系统调用: {cmd_type}"
                        )
                        command_lines.append(command_info)
                        command_id += 1
                        break

            return {
                "command_lines": command_lines,
                "clear_buffer_count": len(clear_buffer_locations),
                "clear_buffer_locations": clear_buffer_locations
            }

        except Exception as e:
            logger.error(f"提取命令行失败: {file_path}, 错误: {str(e)}")
            return {
                "command_lines": [],
                "clear_buffer_count": 0,
                "clear_buffer_locations": []
            }

    def _get_current_function(self, tree: ast.AST) -> Optional[str]:
        """获取当前函数名"""
        # 这是一个简化的实现，实际可能需要更复杂的逻辑
        return None

    def _get_context(self, lines: List[str], line_num: int, context_lines: int = 3) -> str:
        """获取命令行的上下文"""
        start_line = max(1, line_num - context_lines)
        end_line = min(len(lines), line_num + context_lines)
        context_lines_list = lines[start_line-1:end_line]
        return '\n'.join(context_lines_list)

    def _extract_checkcommand_parameters(self, line: str, all_lines: List[str], line_num: int) -> Dict[str, Any]:
        """提取CheckCommand的参数"""
        parameters = {}

        # 基本参数提取
        patterns = {
            'expect': r'expect\s*=\s*\[([^\]]+)\]',
            'not_expect': r'not_expect\s*=\s*\[([^\]]+)\]',
            'is_strict': r'is_strict\s*=\s*(True|False)',
            'stop_max_attempt': r'stop_max_attempt\s*=\s*(\d+)',
            'wait_fixed': r'wait_fixed\s*=\s*(\d+)',
            'timeout': r'timeout\s*=\s*(\d+)',
            'cmd': r'cmd\s*=\s*([\'"][^\'"]+[\'"]|\w+)',
        }

        for param_name, pattern in patterns.items():
            match = re.search(pattern, line)
            if match:
                value = match.group(1)
                # 清理引号
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                elif value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                parameters[param_name] = value

        # 处理多行参数（如果参数跨越多行）
        if '(' in line and ')' not in line:
            # 查找完整的函数调用
            full_call = self._find_full_function_call(all_lines, line_num - 1)
            if full_call:
                for param_name, pattern in patterns.items():
                    match = re.search(pattern, full_call)
                    if match:
                        value = match.group(1)
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        elif value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        parameters[param_name] = value

        return parameters

    def _extract_checkcommand_from_full_call(self, full_call: str, line_num: int) -> Optional[Dict[str, Any]]:
        """从完整的CheckCommand调用中提取信息"""
        try:
            # 提取描述（第一个字符串参数）
            desc_match = re.search(r'CheckCommand\s*\(\s*[\'"]([^\'"]+)[\'"]\s*,', full_call)
            description = desc_match.group(1) if desc_match else "Unknown"

            # 提取cmd参数
            cmd_match = re.search(r'cmd\s*=\s*[\'"]([^\'"]+)[\'"]', full_call)
            command = cmd_match.group(1) if cmd_match else ""

            # 提取所有参数
            parameters = {}
            param_patterns = {
                'cmd': r'cmd\s*=\s*[\'"]([^\'"]+)[\'"]',
                'expect': r'expect\s*=\s*\[([^\]]+)\]',
                'not_expect': r'not_expect\s*=\s*\[([^\]]+)\]',
                'is_strict': r'is_strict\s*=\s*(True|False)',
                'stop_max_attempt': r'stop_max_attempt\s*=\s*(\d+)',
                'wait_fixed': r'wait_fixed\s*=\s*(\d+)',
                'timeout': r'timeout\s*=\s*(\d+)',
            }

            for param_name, pattern in param_patterns.items():
                match = re.search(pattern, full_call)
                if match:
                    value = match.group(1)
                    # 清理引号和转换类型
                    if param_name in ['is_strict']:
                        parameters[param_name] = value == 'True'
                    elif param_name in ['stop_max_attempt', 'wait_fixed', 'timeout']:
                        try:
                            parameters[param_name] = int(value)
                        except ValueError:
                            parameters[param_name] = value
                    else:
                        # 清理引号
                        if value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        elif value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        parameters[param_name] = value

            return {
                'command': command,
                'description': description,
                'parameters': parameters
            }

        except Exception as e:
            logger.warning(f"解析CheckCommand失败: {str(e)}")
            return None

    def _extract_send_command(self, full_call: str) -> Optional[str]:
        """从send调用中提取命令内容"""
        try:
            # 尝试多种模式提取命令
            patterns = [
                # 模式1: 简单字符串参数
                r'send\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
                # 模式2: 三引号多行字符串
                r'send\s*\(\s*[\'"]{3}([^\'"]+)[\'"]{3}\s*\)',
                # 模式3: 变量或表达式（返回原始调用）
                r'send\s*\(\s*([^,\)]+)\s*\)',
                # 模式4: 多行格式化字符串
                r'send\s*\(\s*f?[\'"]{3}([^\'"]+)[\'"]{3}\s*\)',
                # 模式5: 带格式化的单行字符串
                r'send\s*\(\s*f?[\'"]([^\'"]+)[\'"]\s*\)'
            ]

            for pattern in patterns:
                match = re.search(pattern, full_call, re.DOTALL | re.IGNORECASE)
                if match:
                    command = match.group(1).strip()
                    # 清理命令中的多余空白字符
                    command = re.sub(r'\s+', ' ', command)
                    return command

            return None

        except Exception as e:
            logger.warning(f"提取send命令失败: {str(e)}")
            return None

    def _extract_send_parameters(self, full_call: str) -> Dict[str, Any]:
        """提取send命令的参数"""
        parameters = {}

        try:
            # 提取可能的参数
            param_patterns = {
                'timeout': r'timeout\s*=\s*(\d+)',
                'encoding': r'encoding\s*=\s*[\'"]([^\'"]+)[\'"]',
                'shell': r'shell\s*=\s*(True|False)',
                'capture_output': r'capture_output\s*=\s*(True|False)'
            }

            for param_name, pattern in param_patterns.items():
                match = re.search(pattern, full_call, re.IGNORECASE)
                if match:
                    value = match.group(1)
                    if param_name in ['shell', 'capture_output']:
                        parameters[param_name] = value.lower() == 'true'
                    elif param_name == 'timeout':
                        try:
                            parameters[param_name] = int(value)
                        except ValueError:
                            parameters[param_name] = value
                    else:
                        parameters[param_name] = value

        except Exception as e:
            logger.warning(f"提取send参数失败: {str(e)}")

        return parameters

    def _find_full_function_call(self, lines: List[str], start_idx: int) -> Optional[str]:
        """查找完整的函数调用（处理多行情况）"""
        if start_idx >= len(lines):
            return None

        start_line = lines[start_idx]
        if '(' not in start_line:
            return None

        paren_count = start_line.count('(') - start_line.count(')')
        full_call = start_line

        i = start_idx + 1
        while i < len(lines) and paren_count > 0:
            line = lines[i]
            paren_count += line.count('(') - line.count(')')
            full_call += ' ' + line
            i += 1

        return full_call if paren_count == 0 else None

# 创建Python分析服务实例
python_analysis_service = PythonAnalysisService()
