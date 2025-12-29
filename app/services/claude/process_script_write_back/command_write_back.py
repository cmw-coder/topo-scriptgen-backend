import ast
import re
import os
from pathlib import Path
import sys
import shutil
import connect
import asyncio
import resource

glb_parent_dir=''

def extract_and_merge_commands(py_file_content: str) -> list:
    """
    提取gl.DUTx.send()和gl.DUTx.CheckCommand()中的cmd参数内容
    返回列表，列表中元素是字典，按出现顺序排列
    
AI_FingerPrint_UUID: 20251223-KYjDi3AH
"""
    result = []
    
    # 使用单个正则表达式匹配所有gl.DUTx.xxx()调用
    # 匹配格式：gl.DUTx.send(...) 或 gl.DUTx.CheckCommand(...)
    pos = 0
    while pos < len(py_file_content):
        # 查找下一个函数调用开始
        match = re.search(r'gl\.(DUT\d+)\.(send|CheckCommand)\s*\(', py_file_content[pos:])
        if not match:
            break
            
        start_pos = pos + match.start()
        device_name = match.group(1)
        command_type = match.group(2)
        
        # 从函数开始位置向后查找匹配的右括号
        func_start = pos + match.end()
        paren_count = 1
        current_pos = func_start
        in_string = False
        string_char = None
        in_triple_quote = False
        
        while current_pos < len(py_file_content) and paren_count > 0:
            char = py_file_content[current_pos]
            
            # 处理转义字符
            if char == '\\' and current_pos + 1 < len(py_file_content):
                current_pos += 2  # 跳过转义字符
                continue
                
            # 处理字符串开始/结束
            if char in ['\'', '"'] and not in_string:
                # 检查是否是三引号
                if current_pos + 2 < len(py_file_content) and py_file_content[current_pos:current_pos+3] == char * 3:
                    in_string = True
                    in_triple_quote = True
                    string_char = char
                    current_pos += 2  # 跳过另外两个引号
                else:
                    in_string = True
                    string_char = char
            elif in_string and char == string_char:
                if in_triple_quote and current_pos + 2 < len(py_file_content) and py_file_content[current_pos:current_pos+3] == string_char * 3:
                    # 三引号结束
                    in_string = False
                    in_triple_quote = False
                    string_char = None
                    current_pos += 2  # 跳过另外两个引号
                elif not in_triple_quote:
                    # 单引号或双引号结束
                    in_string = False
                    string_char = None
            
            # 只有在不在字符串中时才计数括号
            if not in_string:
                if char == '(':
                    paren_count += 1
                elif char == ')':
                    paren_count -= 1
            
            current_pos += 1
        
        if paren_count == 0:
            # 提取完整的函数调用
            full_call = py_file_content[start_pos:current_pos]
            
            # 根据命令类型处理
            if command_type == 'send':
                # 对于send()，整个内容就是cmd
                send_content = extract_send_content(full_call)
                if send_content:
                    # 拆分多行命令
                    lines = send_content.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line:
                            result.append({
                                'device': device_name,
                                'type': 'send',
                                'cmd': line,  # 只保存cmd字段
                                'full_call': full_call[:100] + '...' if len(full_call) > 100 else full_call,
                                'index': len(result) + 1
                            })
            
            elif command_type == 'CheckCommand':
                # 对于CheckCommand，只提取cmd参数
                cmd_content = extract_checkcommand_cmd_only(full_call)
                if cmd_content:
                    result.append({
                        'device': device_name,
                        'type': 'check',
                        'cmd': cmd_content,  # 只保存cmd字段
                        'full_call': full_call[:100] + '...' if len(full_call) > 100 else full_call,
                        'index': len(result) + 1
                    })
            
            # 更新位置，继续查找下一个函数调用
            pos = current_pos
        else:
            # 如果没有找到匹配的右括号，向前移动一个字符继续查找
            pos = start_pos + 1
    
    return result


def extract_send_content(full_call: str) -> str:
    """从send()调用中提取命令内容"""
    # 移除开头的函数名，只保留参数部分
    param_start = full_call.find('(') + 1
    param_end = full_call.rfind(')')
    params_str = full_call[param_start:param_end].strip()
    
    # 检查是否是三引号字符串
    if params_str.startswith('f\'\'\'') or params_str.startswith('f"""'):
        # f-string三引号
        content = params_str[4:-3] if params_str.endswith('\'\'\'') or params_str.endswith('"""') else params_str[4:]
    elif params_str.startswith('\'\'\'') or params_str.startswith('"""'):
        # 普通三引号
        content = params_str[3:-3] if params_str.endswith('\'\'\'') or params_str.endswith('"""') else params_str[3:]
    elif params_str.startswith('f\'') or params_str.startswith('f"'):
        # f-string单/双引号
        content = params_str[2:-1] if (params_str.endswith('\'') or params_str.endswith('"')) else params_str[2:]
    elif params_str.startswith('\'') or params_str.startswith('"'):
        # 普通单/双引号
        content = params_str[1:-1] if (params_str.endswith('\'') or params_str.endswith('"')) else params_str[1:]
    else:
        # 其他格式，尝试直接返回
        content = params_str
    
    return content.strip()


def extract_checkcommand_cmd_only(full_call: str) -> str:
    """从CheckCommand调用中只提取cmd参数值"""
    # 移除开头的函数名，只保留参数部分
    param_start = full_call.find('(') + 1
    param_end = full_call.rfind(')')
    params_str = full_call[param_start:param_end]
    
    # 定义cmd参数的正则表达式模式
    cmd_patterns = [
        # cmd=f'''多行内容''' 格式
        r'cmd\s*=\s*f[\'\"\']{3}(.*?)[\'\"\']{3}',
        # cmd='''多行内容''' 格式
        r'cmd\s*=\s*[\'\"\']{3}(.*?)[\'\"\']{3}',
        # cmd=f'单行内容' 格式
        r'cmd\s*=\s*f[\'\"]([^\'\"]*?)[\'\"]',
        # cmd='单行内容' 格式
        r'cmd\s*=\s*[\'\"]([^\'\"]*?)[\'\"]',
        # cmd=gl.DUTx.get_buffer 格式
        r'cmd\s*=\s*(gl\.DUT\d+\.get_buffer)',
        # cmd=变量名 格式
        r'cmd\s*=\s*([a-zA-Z_][a-zA-Z0-9_]*)',
    ]
    
    for pattern in cmd_patterns:
        cmd_match = re.search(pattern, params_str, re.DOTALL)
        if cmd_match:
            cmd_content = cmd_match.group(1).strip()
            return cmd_content
    
    return ""

def extract_functions_with_ast(test_class_code: str) -> dict:
    """
    使用Python的ast模块解析代码，最准确的方法
    修正：函数初始行号包含修饰符
    """
    try:
        if not test_class_code:
            print("文件为空")
            return None
        
        tree = ast.parse(test_class_code)
        functions = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "TestClass":
                # 找到TestClass
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        func_name = item.name
                        
                        # 获取装饰器
                        decorators = []
                        for decorator in item.decorator_list:
                            if isinstance(decorator, ast.Name):
                                decorators.append(f"@{decorator.id}")
                            elif isinstance(decorator, ast.Attribute):
                                decorators.append(f"@{ast.unparse(decorator)}")
                        
                        # 获取参数
                        args = []
                        for arg in item.args.args:
                            args.append(arg.arg)
                        
                        # 获取文档字符串
                        docstring = ast.get_docstring(item) or ""
                        
                        # 关键修改：计算包含装饰器的起始行号
                        # 如果函数有装饰器，起始行号应该是第一个装饰器的行号
                        start_line = item.lineno  # 函数定义的行号
                        
                        if item.decorator_list:
                            # 找到第一个装饰器的行号
                            first_decorator_line = min(
                                decorator.lineno 
                                for decorator in item.decorator_list
                            )
                            start_line = first_decorator_line
                        
                        # 获取函数体源码（包含装饰器）
                        func_body_lines = test_class_code.split('\n')[start_line-1:item.end_lineno]
                        func_content = '\n'.join(func_body_lines)
                        
                        functions[func_name] = {
                            "name": func_name,
                            "decorators": decorators,
                            "parameters": ", ".join(args),
                            "docstring": docstring,
                            "content": func_content,
                            "line_numbers": (start_line, item.end_lineno),  # 使用修正后的起始行号
                            "function_def_line": item.lineno,  # 保留函数定义的实际行号
                            "first_decorator_line": first_decorator_line if item.decorator_list else None
                        }
                
                break
        
        return functions
        
    except SyntaxError as e:
        return {"error": f"语法错误: {e}"}


def extract_device_commands_advanced(py_file_content: str) -> dict:
    """
    高级版本：支持更多格式的send和CheckCommand调用
    """
    result = {}
    
    # 改进的模式，支持更多格式
    patterns = [
        # send命令的各种格式
        (r'gl\.(DUT\d+)\.send\(\s*(?:f)?[\'\"\']{3}(.+?)[\'\"\']{3}\s*\)', 'send'),
        (r'gl\.(DUT\d+)\.send\(\s*[\'\"](.+?)[\'\"]\s*\)', 'send'),
        
        # CheckCommand命令
        (r'gl\.(DUT\d+)\.CheckCommand\(\s*[\'\"](.+?)[\'\"]\s*,', 'check'),
    ]
    
    for pattern, cmd_type in patterns:
        matches = re.finditer(pattern, py_file_content, re.DOTALL)
        
        for match in matches:
            device_name = match.group(1)
            content = match.group(2).strip()
            
            if device_name not in result:
                result[device_name] = {"send_commands": [], "check_commands": []}
            
            if cmd_type == 'send':
                # 处理send命令
                cleaned_commands = []
                for line in content.split('\n'):
                    line = line.strip()
                    if line and not line.startswith('#'):  # 过滤注释
                        cleaned_commands.append(line)
                
                result[device_name]["send_commands"].append({
                    "content": content,
                    "cleaned": cleaned_commands,
                    "line_count": len(cleaned_commands)
                })
            
            elif cmd_type == 'check':
                # 处理CheckCommand命令
                # 提取完整调用
                start_pos = match.start()
                end_pos = py_file_content.find(')', start_pos)
                if end_pos != -1:
                    full_call = py_file_content[start_pos:end_pos+1]
                    
                    # 提取详细信息
                    check_info = {
                        "description": content,
                        "full_call": full_call
                    }
                    
                    # 提取各种参数
                    param_extractors = [
                        (r'cmd=[\'\"](.+?)[\'\"]', 'cmd'),
                        (r'expect=\[(.+?)\]', 'expect_raw'),
                        (r'relationship=[\'\"](.+?)[\'\"]', 'relationship'),
                        (r'stop_max_attempt=(\d+)', 'stop_max_attempt'),
                        (r'wait_fixed=(\d+)', 'wait_fixed')
                    ]
                    
                    for pattern, key in param_extractors:
                        param_match = re.search(pattern, full_call, re.DOTALL)
                        if param_match:
                            if key == 'expect_raw':
                                # 处理expect数组
                                expect_str = param_match.group(1)
                                expect_list = []
                                for item in re.findall(r'[\'\"](.+?)[\'\"]', expect_str):
                                    expect_list.append(item)
                                check_info['expect'] = expect_list
                            else:
                                check_info[key] = param_match.group(1)
                    
                    result[device_name]["check_commands"].append(check_info)
    
    return result


# 参数file_path，脚本文件路径
# 参数command_path，生成的配置文件路径
def process_test_file(file_path, command_path):
    content = ""
    output_str = ""

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    try:
        functions = extract_functions_with_ast(content)
        for name, info in functions.items():
            func_name = info["name"]
            func_content = info["content"]
            output_str = output_str + "!!!func " + func_name + "\n"
            formatted = extract_and_merge_commands(func_content)
            pre_device_name = ""
            device_commands = ""
            last_device_name = ""
            if formatted:
                for item in formatted:
                    device_name = item['device']
                    last_device_name = device_name
                    #print(item['cmd'])
                    if pre_device_name == "":
                        pre_device_name = device_name
                        device_commands = device_commands + "\n" + item['cmd']
                    elif pre_device_name == device_name:
                        device_commands = device_commands + "\n" + item['cmd']
                    elif pre_device_name != device_name:
                        output_str = output_str + "!!device " + device_name
                        output_str = output_str + device_commands + "\n"
                        device_commands = ""
                        pre_device_name = device_name
                else:
                    output_str = output_str + "!!device " + last_device_name
                    output_str = output_str + device_commands + "\n"
        # 覆盖写入
        with open(command_path, 'w', encoding='utf-8') as f:
            f.write(output_str)

    except ImportError:
        print("AST版本需要Python 3.9+")   


def extract_checkcommand_full_content(py_file_content: str) -> dict:
    """
    提取CheckCommand函数的完整内容作为字符串，建立cmd命令与完整CheckCommand内容的对应关系
    
    返回格式：{cmd命令: CheckCommand完整字符串}
    """
    result = {}
    
    # 查找所有的CheckCommand调用，从CheckCommand开始
    # 改进正则表达式以更好地匹配括号内的内容
    checkcommand_pattern = r'CheckCommand\s*\((.*?)\)(?=\s*(?:gl\.|$|\n\s*\S))'
    
    # 使用DOTALL标志来匹配跨行的内容
    matches = re.finditer(checkcommand_pattern, py_file_content, re.DOTALL)
    
    for match in matches:
        function_content = "CheckCommand(" + match.group(1) + ")"  # 完整的CheckCommand(...)字符串
        
        # 改进的cmd参数提取，支持f-string和普通字符串
        # 首先尝试匹配单引号或双引号的字符串（单行）
        cmd_match = re.search(r'cmd\s*=\s*(f?[\'\"][^\'\"]*[\'\"])', function_content)
        
        if not cmd_match:
            # 如果没找到单行字符串，尝试匹配三引号字符串（多行）
            cmd_match = re.search(r'cmd\s*=\s*(f?[\'\"][^\'\"]{3}.*?[\'\"][^\'\"]{3})', 
                                 function_content, re.DOTALL)
        
        if cmd_match:
            cmd_value = cmd_match.group(1)
            
            # 提取实际的命令字符串（去除引号和f前缀）
            cmd_clean = extract_command_string(cmd_value)
            
            if cmd_clean:
                # 将结果添加到字典中，以cmd命令为key，完整CheckCommand内容为value
                result[cmd_clean] = function_content
    
    return result


def extract_command_string(cmd_value: str) -> str:
    """
    从cmd参数值中提取实际的命令字符串
    支持f-string和普通字符串，单引号和双引号，单行和多行
    """
    if not cmd_value:
        return ""
    
    # 判断是否是三引号字符串
    is_triple_single = cmd_value.startswith("'''") or cmd_value.startswith("f'''")
    is_triple_double = cmd_value.startswith('"""') or cmd_value.startswith('f"""')
    
    if is_triple_single:
        # 三单引号
        if cmd_value.startswith("f'''"):
            # f-string三单引号
            return cmd_value[4:-3] if cmd_value.endswith("'''") else cmd_value[4:]
        else:
            # 普通三单引号
            return cmd_value[3:-3] if cmd_value.endswith("'''") else cmd_value[3:]
    
    elif is_triple_double:
        # 三双引号
        if cmd_value.startswith('f"""'):
            # f-string三双引号
            return cmd_value[4:-3] if cmd_value.endswith('"""') else cmd_value[4:]
        else:
            # 普通三双引号
            return cmd_value[3:-3] if cmd_value.endswith('"""') else cmd_value[3:]
    
    else:
        # 单行字符串
        if cmd_value.startswith("f'") or cmd_value.startswith('f"'):
            # f-string单行
            return cmd_value[2:-1] if (cmd_value.endswith("'") or cmd_value.endswith('"')) else cmd_value[2:]
        elif cmd_value.startswith("'") or cmd_value.startswith('"'):
            # 普通单行字符串
            return cmd_value[1:-1] if (cmd_value.endswith("'") or cmd_value.endswith('"')) else cmd_value[1:]
    
    return cmd_value


def extract_command_file_line(file_path: str) -> dict:
    """
    改进版本：更严格地解析，确保格式正确
    """
    result = {}
    current_func = None
    current_device = None
    current_commands = []
    
    with open(file_path, 'r', encoding='utf-8') as file:
        for line_num, line in enumerate(file, 1):
            stripped_line = line.strip()
            
            # 检查是否是函数定义行
            if stripped_line.startswith('!!!func '):
                # 提取函数名
                func_name = stripped_line[8:].strip()
                if not func_name:
                    print(f"警告：第{line_num}行函数名为空")
                    continue
                
                # 如果切换函数，保存当前函数的数据
                if current_func and current_func != func_name:
                    # 保存当前设备的命令
                    if current_device and current_commands:
                        if current_func not in result:
                            result[current_func] = []
                        result[current_func].append({current_device: '\n'.join(current_commands)})
                    
                    # 重置
                    current_commands = []
                
                current_func = func_name
                current_device = None
                continue
            
            # 检查是否是设备定义行
            elif stripped_line.startswith('!!device '):
                if current_func is None:
                    print(f"错误：第{line_num}行设备定义前没有函数定义")
                    continue
                
                device_name = stripped_line[9:].strip()
                if not device_name:
                    print(f"警告：第{line_num}行设备名为空")
                    continue
                
                # 保存上一个设备的命令
                if current_device and current_commands:
                    if current_func not in result:
                        result[current_func] = []
                    result[current_func].append({current_device: '\n'.join(current_commands)})
                
                # 开始新设备
                current_device = device_name
                current_commands = []
                continue
            
            # 普通行：添加到当前设备的命令中
            else:
                if current_device is not None:
                    current_commands.append(stripped_line)
                elif stripped_line.strip():  # 非空行但没有设备
                    print(f"警告：第{line_num}行命令没有对应的设备: {stripped_line}")
    
    # 保存最后一个设备的命令
    if current_func and current_device and current_commands:
        if current_func not in result:
            result[current_func] = []
        result[current_func].append({current_device: '\n'.join(current_commands)})
    
    return result

def read_lines_range_as_string(file_path: str, start_line: int, end_line: int) -> str:
    """
    读取指定范围的行并返回字符串
    :param start_line: 起始行号（从1开始）
    :param end_line: 结束行号（包含）
    """
    lines = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            if i < start_line:
                continue
            if i > end_line:
                break
            lines.append(line.rstrip('\n'))
    return '\n'.join(lines)            

def splice_single_func(command_dict, check_command_dict, diff_func_list):
    functions_code = []
    functions_dict = {}
    is_send_start = 0
    is_send_end = 0

    #遍历txt 函数dict
    for func_name, devices_list in command_dict.items():
        # 仅处理有差异的函数
        if func_name not in diff_func_list:
            continue

        print(f"diff function {func_name}")

        function_code = []
        if is_send_start == 1 and is_send_end ==0:
            function_code.append("          ''')")
        is_send_start = 0
        is_send_end = 0
        if "setup" in func_name or "teardown" in func_name:
            #function_code.append(f"\n    @classmethod")
            function_code.append(f"    def {func_name}(cls):")
        else:
            function_code.append(f"    def {func_name}(self):")
        
        # 遍历txt 函数dict - 设备list
        for device_dict in devices_list:

            # 遍历txt 函数dict - 设备list - 单设备命令dict
            for device_name, commands in device_dict.items():
                # 处理每个设备的命令
                commands = commands.strip()
                if not commands:
                    continue
                
                # 将命令按行分割
                command_lines = commands.split('\n')
                # 遍历txt 函数dict - 设备list - 单设备命令dict - 单行命令str
                for cmd in command_lines:
                    if cmd.startswith('dis'):
                        if is_send_start == 1 and is_send_end ==0:
                            is_send_end =1
                            function_code.append("          ''')")  # 结束前面的send
                        if cmd in check_command_dict:
                            check_command = check_command_dict[cmd]
                            function_code.append(f"        gl.{device_name}.{check_command}")
                        else:
                            function_code.append(f"        gl.{device_name}.CheckCommand('',")
                            function_code.append(f"                             cmd=f'{cmd}'")
                            function_code.append(f"                             relationship = ")
                            function_code.append(f"                             starts = ")
                            function_code.append(f"                             stop_max_attempt = ")
                            function_code.append(f"                             wait_fixed = ")
                            function_code.append(f"                             )")
                    else:
                        if (is_send_start == 0 and is_send_end ==0) or (is_send_start == 1 and is_send_end ==1):
                            is_send_start =1
                            is_send_end =0
                            function_code.append(f"        gl.{device_name}.send(f'''")
                            function_code.append(f"          {cmd}")
                        elif is_send_start == 1 and is_send_end ==0:
                            function_code.append(f"          {cmd}")

            if is_send_start == 1 and is_send_end ==0:  # 结束前面的设备
                function_code.append("          ''')")
                is_send_start = 0
                is_send_end = 0                

        #functions_code.append('\n'.join(function_code)) # 结束函数
        functions_dict[func_name] = function_code;
    #return '\n\n'.join(functions_code)
    return functions_dict


# 在文件种更新函数
def update_func(test_file, func_dict):
    """
    更新Python文件中的指定函数实现
    
    Args:
        test_file (str): 目标Python文件的路径
        func_dict (dict): 键为函数名称（字符串），值为完整的函数内容（字符串）
    
    Raises:
        FileNotFoundError: 当指定的test_file不存在时抛出
    """
    # 1. 检查文件是否存在
    if not os.path.isfile(test_file):
        raise FileNotFoundError(f"无法找到文件：{test_file}")
    
    # 2. 创建文件备份（避免修改出错丢失原内容）
    test_file2 = f"{test_file}.update"
    
    # 3. 读取文件内容并统一缩进（tab转4个空格）
    with open(test_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    # 统一处理tab缩进，避免混合缩进导致识别错误
    lines = [line.replace('\t', '    ') for line in lines]
    
    # 4. 遍历需要更新的函数，逐个替换
    for target_func, new_func_content in func_dict.items():
        # 构建匹配函数定义行的正则（匹配：任意空格 + def + 函数名 + 任意空格 + (）
        func_pattern = re.compile(r'^\s*def\s+{}\s*\('.format(re.escape(target_func)))
        func_start_idx = None  # 函数定义行的索引
        
        # 查找函数定义行
        for idx, line in enumerate(lines):
            if func_pattern.match(line):
                func_start_idx = idx
                break
        
        # 如果没找到目标函数，给出警告并跳过
        if func_start_idx is None:
            print(f"警告：文件中未找到函数「{target_func}」，跳过该函数的更新")
            continue
        
        # 5. 确定函数体的结束位置（通过缩进级别判断）
        func_end_idx = func_start_idx  # 函数结束行的索引
        func_body_indent = None       # 函数体的缩进级别（空格数）
        
        # 从函数定义行的下一行开始，遍历找函数体结束位置
        for idx in range(func_start_idx + 1, len(lines)):
            current_line = lines[idx].rstrip('\n')  # 去掉换行符，保留缩进空格
            
            # 跳过空行（不影响函数体范围判断）
            if not current_line.strip():
                func_end_idx = idx
                continue
            
            # 第一次找到非空行，确定函数体的缩进级别
            if func_body_indent is None:
                func_body_indent = len(current_line) - len(current_line.lstrip())
                func_end_idx = idx
            else:
                # 检查当前行缩进：如果缩进级别小于函数体缩进，说明函数体结束
                current_indent = len(current_line) - len(current_line.lstrip())
                if current_indent < func_body_indent:
                    break
                func_end_idx = idx
        
        # 6. 处理新函数内容（分割成行，补充换行符）
        new_func_lines = new_func_content.split('\n')
        # 为每行添加换行符（最后一行如果是空行则移除，避免多余空行）
        new_func_lines = [line + '\n' for line in new_func_lines]
        if new_func_lines and new_func_lines[-1] == '\n':
            new_func_lines.pop()
        
        # 7. 替换原有函数内容
        lines = lines[:func_start_idx] + new_func_lines + lines[func_end_idx + 1:]
    
    # 8. 将修改后的内容写回文件
    with open(test_file, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    #print(f"文件更新完成！共处理 {len(func_dict)} 个函数（成功更新 {len(func_dict) - sum(1 for k in func_dict if not any(re.match(r'^\s*def\s+{}\s*\('.format(re.escape(k)), line) for line in lines))} 个）")


# 比较字典找到差异函数
def compare_func_dicts(dict1, dict2):
    """
    对比两个指定格式的函数字典，返回内容有差异的函数名称列表
    
    Args:
        dict1 (dict): 第一个待对比的字典，格式为 {函数名: [{'设备名': '命令串'}, ...]}
        dict2 (dict): 第二个待对比的字典，格式同上
    
    Returns:
        list: 有差异的函数名称列表（先按dict1中函数名顺序，再补充dict2独有的函数名）
    """
    # 初始化差异函数名列表
    diff_funcs = []
    
    # 获取所有涉及的函数名（两个字典key的并集），保留dict1的顺序 + dict2独有的部分
    all_func_names = list(dict1.keys())
    for func_name in dict2.keys():
        if func_name not in all_func_names:
            all_func_names.append(func_name)
    
    # 逐个函数名对比内容
    for func_name in all_func_names:
        # 获取两个字典中该函数对应的内容（无则返回空列表，保持格式统一）
        content1 = dict1.get(func_name, [])
        content2 = dict2.get(func_name, [])
        
        # 对比内容是否完全一致（Python的==会递归对比列表、字典的每一层内容）
        if content1 != content2:
            diff_funcs.append(func_name)
    
    return diff_funcs


def parse_py_func(file):
    """
    从文件对象中提取Python函数名称和内容（严格保留原始缩进）
    参数:
        file: 已打开的文件对象（读取模式）
    返回:
        dict: 键为函数名，值为函数完整内容（包含原始缩进、换行符）
    """
    # 读取文件所有行，保留每行原始内容（缩进、换行符等）
    with open(file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    # 存储最终结果的字典
    func_dict = {}
    # 临时变量：当前正在解析的函数名和内容行
    current_func_name = None
    current_func_lines = []

    for line in lines:
        # 去除行首尾空白（仅用于判断，不修改原始行），识别函数定义行
        stripped_line = line.strip()
        # 判断是否为函数定义行：以def开头、包含(和:（符合Python函数定义基本格式）
        if stripped_line.startswith('def ') and '(' in stripped_line and ':' in stripped_line:
            # 如果已有未保存的函数，先将其存入字典
            if current_func_name is not None:
                func_dict[current_func_name] = ''.join(current_func_lines)
            
            # 提取函数名：从"def "后拆分到"("前的部分（忽略前后空白）
            def_body = stripped_line[len('def '):]  # 截取def后的内容，如 "add(a, b):"
            func_name = def_body.split('(', 1)[0].strip()  # 拆分到(，取前半部分作为函数名
            
            # 初始化当前函数的信息
            current_func_name = func_name
            current_func_lines = [line]  # 原始def行加入内容列表
        elif current_func_name is not None:
            # 非函数定义行，但属于当前函数的内容，直接添加（保留原始缩进）
            current_func_lines.append(line)
    
    # 处理文件末尾的最后一个函数（循环结束后可能未保存）
    if current_func_name is not None:
        func_dict[current_func_name] = ''.join(current_func_lines)

    return func_dict


def command_to_func(test_script, new_command, old_command, diff_command_list):
    """
    处理差异函数，生成修改前后的命令文件，调用connect.py并替换测试脚本中的同名函数
    
    参数说明：
    test_script: str - 测试脚本文件路径（如 './test.py'）
    new_command: dict - 新的命令结构字典（示例结构见需求）
    old_command: dict - 旧的命令结构字典（示例结构见需求）
    diff_command_list: list - 有差异的函数名列表（如 ['func1', 'func2']）
    """
    global glb_parent_dir
    target_dir = f"{glb_parent_dir}/../revert"

    # 1. 定义目标目录并创建（确保目录存在）
    os.makedirs(target_dir, exist_ok=True)  # 不存在则创建，存在则不报错
    
    # 2. 遍历每个有差异的函数
    for func_name in diff_command_list:
        # 跳过不存在的函数（容错处理）
        if func_name not in old_command or func_name not in new_command:
            print(f"警告：函数 {func_name} 在旧/新命令中不存在，跳过处理")
            continue
        
        # --------------------------
        # 3. 生成修改前/后的txt文件
        # --------------------------
        # 3.1 生成function_before_modification.txt（基于old_command）
        before_content = []
        before_content.append(f"!!!func {func_name}")  # 函数名标识
        # 遍历旧命令中该函数的所有设备命令
        for device_dict in old_command[func_name]:
            for dev_name, cmd_str in device_dict.items():
                before_content.append(f"!!device {dev_name}")
                # 拆分命令行，清理多余空格并逐行添加
                cmds = [cmd.strip() for cmd in cmd_str.split("\n") if cmd.strip()]
                before_content.extend(cmds)
        # 保存before文件
        before_file = os.path.join(target_dir, "function_before_modification.md")
        with open(before_file, "w", encoding="utf-8") as f:
            f.write("\n".join(before_content))
        
        # 3.2 生成function_after_modification.txt（基于new_command）
        after_content = []
        after_content.append(f"!!!func {func_name}")
        # 遍历新命令中该函数的所有设备命令
        for device_dict in new_command[func_name]:
            for dev_name, cmd_str in device_dict.items():
                after_content.append(f"!!device {dev_name}")
                cmds = [cmd.strip() for cmd in cmd_str.split("\n") if cmd.strip()]
                after_content.extend(cmds)
        # 保存after文件
        after_file = os.path.join(target_dir, "function_after_modification.md")
        with open(after_file, "w", encoding="utf-8") as f:
            f.write("\n".join(after_content))
        
        # 清空function.py
        function_file = os.path.join(target_dir, "function.py")
        try:
            # 'w'模式：打开即清空，encoding=utf-8避免编码问题
            with open(function_file, 'w', encoding='utf-8') as f:
                # 无需写入任何内容，仅打开即可清空
                pass
            print(f"✅ 成功清空文件：{function_file}")
        except Exception as e:
            print(f"❌ 清空文件失败：{str(e)}") 

        # --------------------------
        # 4. 调用connect.py的main函数生成function.py
        # --------------------------
        # 方案: 相对于脚本目录的路径
        relative_path = "../"  # 当前目录下的func_convert文件夹
        target_folder = os.path.join(glb_parent_dir, relative_path)

        # 执行处理
        #connect.process_convert_folder(target_folder, 5)
        result = asyncio.run(connect.process_convert_folder(target_folder, 5))
        print(f"处理结果: {result}")
        # --------------------------
        # 5. 替换test_script中的同名函数
        # --------------------------
        # 5.1 读取function.py中的函数定义
        func_py_path = os.path.join(target_dir, "function.py")  # 假设function.py生成在该目录
        if not os.path.exists(func_py_path):
            print(f"警告：{func_py_path} 不存在，跳过函数替换")
            continue

        func_dict = parse_py_func(func_py_path)
        update_func(test_script, func_dict)

'''
        # 解析function.py，提取目标函数的代码
        with open(func_py_path, "r", encoding="utf-8") as f:
            func_py_content = f.read()
        # 使用ast模块解析Python代码（更安全的函数提取方式）
        try:
            tree = ast.parse(func_py_content)
            target_func_code = None
            # 遍历AST节点，找到目标函数
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == func_name:
                    # 提取函数的起始和结束位置
                    start_line = node.lineno - 1  # ast的行号从1开始，列表从0开始
                    end_line = node.end_lineno  # 需要Python 3.8+支持
                    # 按行拆分代码，提取函数体
                    func_lines = func_py_content.split("\n")[start_line:end_line]
                    target_func_code = "\n".join(func_lines)
                    break
            if not target_func_code:
                print(f"警告：{func_py_path} 中未找到函数 {func_name}，跳过替换")
                continue
        except Exception as e:
            print(f"解析function.py失败：{e}，跳过函数替换")
            continue
        
        # 5.2 读取并替换test_script中的同名函数
        with open(test_script, "r", encoding="utf-8") as f:
            test_lines = f.read().split("\n")
        
        # 查找test_script中目标函数的位置并替换
        new_test_lines = []
        in_target_func = False
        func_started = False
        for line in test_lines:
            # 检测函数定义行（def func_name(...):）
            if line.strip().startswith(f"def {func_name}("):
                in_target_func = True
                func_started = True
                # 添加新的函数代码
                new_test_lines.extend(target_func_code.split("\n"))
                continue
            # 退出函数体（遇到下一个def或文件结束）
            if in_target_func and line.strip().startswith("def ") and not func_started:
                in_target_func = False
            # 非目标函数行直接保留
            if not in_target_func:
                new_test_lines.append(line)
        
        # 5.3 保存修改后的测试脚本
        with open(test_script, "w", encoding="utf-8") as f:
            f.write("\n".join(new_test_lines))
        
        print(f"函数 {func_name} 处理完成：已生成前后文件，调用connect.py，并替换test_script中的同名函数")
'''


# 回写py文件，仅更新有差异的函数
def write_back_diff_func(script_file, old_command_file, new_command_file):
    global glb_parent_dir
    revert_path = f"{glb_parent_dir}/../revert"

    # 解析命令文件
    old_command_dict = extract_command_file_line(old_command_file)
    new_command_dict = extract_command_file_line(new_command_file)

    # 找到有差异的函数名称
    diff_func_list = compare_func_dicts(old_command_dict, new_command_dict)
    if len(diff_func_list) == 0:
        return

    # 创建目录
    os.makedirs(revert_path, exist_ok=True)  # 不存在则创建，存在则不报错

    # 生成原始文件备份，方便调试对比
    # copy_file_manually(script_file, f"{revert_path}/prototype_script.py")

    # 有差异的函数重新生成
    command_to_func(script_file, new_command_dict, old_command_dict, diff_func_list)

    # 更新有差异的函数
    #update_func(script_file, diff_func_dict)


# 检查文件是否存在
def check_file_exists(file_path: str) -> bool:
    """
    校验指定路径的文件是否存在（且是文件而非文件夹）
    :param file_path: 文件路径字符串
    :param param_name: 参数名（如file1/file2），用于精准错误提示
    :return: 存在且是文件返回True，否则返回False
    """
    path_obj = Path(file_path)
    
    # 情况1：路径存在且是文件 → 校验通过
    if path_obj.is_file():
        return True
    # 情况2：路径存在但不是文件（是文件夹）→ 提示错误
    elif path_obj.exists():
        print(f"错误：{file_path} 不是文件（是文件夹）")
        return False
    # 情况3：路径完全不存在 → 提示错误
    else:
        print(f"错误：{file_path} 对应的文件不存在")
        return False


def copy_file_manually(source_path, target_path):
    """
    手动读写文件实现复制（适合小文件，大文件建议分块读取）
    :param source_path: 源文件路径
    :param target_path: 目标文件路径
    """
    try:
        # 以二进制模式打开（兼容所有文件类型：文本、图片、视频等）
        # 分块读取（每次读4KB），避免一次性读取大文件占满内存
        chunk_size = 4096
        with open(source_path, "rb") as src_file, open(target_path, "wb") as dst_file:
            while True:
                chunk = src_file.read(chunk_size)
                if not chunk:  # 读取到文件末尾
                    break
                dst_file.write(chunk)
        
        print(f"文件复制成功！\n源文件：{source_path}\n目标文件：{target_path}")
    
    except FileNotFoundError:
        print(f"错误：源文件不存在或目标路径无法访问")
    except PermissionError:
        print(f"错误：没有权限读取/写入文件")
    except Exception as e:
        print(f"复制文件时发生错误：{e}")


# 解析文件路径
def parse_file_path(file_path):
    """
    解析文件路径，返回文件名和文件类型
    
    参数:
        file_path: 字符串，文件的绝对路径/相对路径
    
    返回:
        dict: {
            "full_path": 规范化的完整路径,
            "file_name_with_ext": 带扩展名的完整文件名,
            "file_name": 纯文件名（无扩展名）,
            "file_ext": 主扩展名（如txt、gz）,
            "file_ext_full": 完整扩展名（如tar.gz）,
            "parent_dir": 父目录路径
        }
    """
    # 处理路径（自动兼容Windows/Linux/Mac路径分隔符）
    path_obj = Path(file_path).resolve()  # resolve() 转换为绝对路径并规范化
    
    # 提取核心信息
    file_name_with_ext = path_obj.name  # 带扩展名的文件名（如test.txt、data.tar.gz）
    parent_dir = str(path_obj.parent)   # 父目录路径
    
    # 处理纯文件名和扩展名（兼容多扩展名、无扩展名、隐藏文件）
    # 情况1：无扩展名（如README、.gitignore）
    if not path_obj.suffix:
        file_name = file_name_with_ext
        file_ext = ""
        file_ext_full = ""
    # 情况2：有扩展名（包括多扩展名）
    else:
        # stem: 去除最后一个扩展名后的名称（如data.tar.gz → data.tar）
        # 循环去除所有扩展名，得到纯文件名
        stem = path_obj.stem
        while Path(stem).suffix:
            stem = Path(stem).stem
        file_name = stem
        
        # 主扩展名（最后一个点后的内容，如data.tar.gz → gz）
        file_ext = path_obj.suffix.lstrip(".")  # 去掉前缀的.
        
        # 完整扩展名（所有点后的内容，如data.tar.gz → tar.gz）
        file_ext_full = file_name_with_ext[len(file_name):].lstrip(".")

    return {
        "full_path": str(path_obj),
        "file_name_with_ext": file_name_with_ext,
        "file_name": file_name,
        "file_ext": file_ext,
        "file_ext_full": file_ext_full,
        "parent_dir": parent_dir
    }

def copy_temp_and_prototype(source_path):
    """
    同时复制为XXX_temp.py + prototype_script.py
    """
    # 基础校验（复用前文逻辑）
    if not os.path.exists(source_path) or os.path.isdir(source_path):
        print(f"❌ 源文件无效：{source_path}")
        return False
    if not source_path.endswith(".py"):
        return False

    #获取同级的revert目录
    current_dir =  os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    revert_dir = os.path.join(parent_dir, "revert")
    revert_dir = os.path.abspath(revert_dir)

    # 构造两个目标路径
    file_prefix = os.path.splitext(os.path.basename(source_path))[0]
    temp_path = os.path.join(current_dir, f"{file_prefix}_temp.py")
    prototype_path = os.path.join(revert_dir, "prototype_script.py")

    # 执行复制
    success = 0
    try:
        shutil.copy2(source_path, temp_path)
        print(f"✅ {file_prefix}_temp.py 复制成功")
        success += 1
    except Exception as e:
        print(f"❌ {file_prefix}_temp.py 失败：{e}")
    try:
        shutil.copy2(source_path, prototype_path)
        print(f"✅ prototype_script.py 复制成功")
        success += 1
    except Exception as e:
        print(f"❌ prototype_script.py 失败：{e}")
        return success > 0

def main():
    global glb_parent_dir
    # ========== 第一步：校验参数是否传入（参数存在性） ==========
    # sys.argv[0]是脚本名，sys.argv[1]是file1，sys.argv[2]是file2
    # 所以sys.argv的长度至少为4才表示传入了file1和file2

    if len(sys.argv) < 4:
        print("错误：缺少必要参数！")
        print("正确用法：python command_write_back.py <file1路径> <file2路径> <file3路径> [file4路径]")
        print("示例：python command_write_back.py ./test.py ./config_before.txt ./config_after.txt")
        sys.exit(1)  # 非0退出码表示执行失败

    # ========== 第二步：获取传入的file1和file2 ==========
    file1 = sys.argv[1]  # 脚本文件
    file2 = sys.argv[2]  # 修改前的配置文件
    file3 = sys.argv[3]  # 修改后的配置文件

    # file4 可选，如果未提供则使用默认路径
    if len(sys.argv) >= 5:
        file4 = sys.argv[4]  # 用户提供的 maping.json文件
    else:
        # 使用默认路径：本地 log 目录下的 map_info.json
        import getpass
        username = getpass.getuser()
        file4 = f"/opt/coder/statistics/build/aigc_tool/{username}/map_info.json"
        print(f"未提供 file4 参数，使用默认路径: {file4}")

    # 转换 Windows 路径格式为 Unix 格式（反斜杠转正斜杠）
    file4 = file4.replace('\\', '/')

    #file1 = '/home/w31815/project/12_24/func_convert/stub/test_script3.py'
    #file2 = '/home/w31815/project/12_24/func_convert/stub/test_script3_function_before_modification.md'
    #file3 = '/home/w31815/project/12_24/func_convert/stub/test_script3_function_after_modification.md'

    # ========== 第三步：校验文件是否存在 ==========
    # 校验file1
    file1_valid = check_file_exists(file1)
    # 校验file2
    file2_valid = check_file_exists(file2)
    # 校验file3
    file3_valid = check_file_exists(file3)
    # 校验file4（可选参数，如果不存在给出警告但不退出）
    file4_valid = check_file_exists(file4)
    if not file4_valid:
        print(f"⚠️  警告：file4 不存在或无法访问 ({file4})")
        print("⚠️  将继续执行，但某些功能可能受限")

    # 只要有一个必要文件（file1/file2/file3）校验失败，就退出脚本
    if not (file1_valid and file2_valid and file3_valid):
        sys.exit(1)

    # ========== 第四步：所有校验通过，正常使用参数 ==========
    print("\n所有校验通过！")
    print(f"获取到的file1：{file1}")
    print(f"获取到的file2：{file2}")
    print(f"获取到的file3：{file3}")
    print(f"获取到的file4：{file4}")

    # ========== 第五步：设置环境变量==========
    # 增加文件描述符限制
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (65536, 65536))
        print("✅ 文件描述符限制已增加")
    except Exception as e:
        print(f"⚠️  无法增加文件描述符限制: {e}")
    
    # 设置环境变量
    os.environ.update({
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_DISABLE_FILE_WATCHER": "1",
        "CHOKIDAR_USEPOLLING": "true",
        "NODE_NO_WATCHERS": "1",
        "ANTHROPIC_BASE_URL": "http://10.144.41.149:4000/",
        "ANTHROPIC_AUTH_TOKEN": 'xx'
    })

    # 要删除的代理环境变, 避免检索时使用代理
    proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]

    # 遍历并删除每个环境变量（os.environ 是字典，pop 不存在的键不会报错）
    for var in proxy_vars:
        os.environ.pop(var, None)

    print("已成功清除代理环境变量")

    glb_parent_dir = os.path.dirname(os.path.abspath(__file__))

    #复制脚本文件重新命名成指定名称
    copy_temp_and_prototype(file1)

    #提取temp文件路径用于更新差异函数
    if not os.path.exists(file1) or os.path.isdir(file1):
        print(f"❌ 源文件无效：{file1}")
        return False
    if not file1.endswith(".py"):
        return False
    current_dir =  os.path.dirname(os.path.abspath(__file__))
    file_prefix = os.path.splitext(os.path.basename(file1))[0]
    temp_path = os.path.join(current_dir, f"{file_prefix}_temp.py")

    #如果传入了mapping.json文件写入到指定目录下
    if file4_valid:
        print(f"获取到的file4：{file4}")
        parent_dir = os.path.dirname(current_dir)
        revert_dir = os.path.join(parent_dir, "revert")
        revert_dir = os.path.abspath(revert_dir)
        mapping_path = os.path.join(revert_dir, f"mapping.json")

        #拷贝mapping文件
        try:
            shutil.copy2(file4,mapping_path)
            print(f"mapping.json写入成功")
        except Exception as e:
            print(f"mapping.json写入失败：{e}")
    
    # 更新差异函数
    write_back_diff_func(temp_path, file2, file3)

    #更新完成后回写脚本
    try:
        shutil.copy2(temp_path, file1)
        print(f"回写成功")
        #删除临时文件
        os.remove(temp_path)
    except Exception as e:
        print(f"回写失败：{e}")
    
# 参数1：脚本文件
# 参数2：修改后的配置文件
if __name__ == '__main__':
    main()

