import os
import json
import re
import base64
import traceback
from typing import Any, Dict, List, Union
from pathlib import Path

class LOGPROCESS:
    def __init__(self, log_path:str):
        self.log_path = log_path
        self.script_commands_info = []

    def read_json_file(self, file_path) -> Any:
        """读取 JSON 文件"""
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"文件夹不存在: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)

    def get_script_name(self, file_path):
        script_name = ""
        data = self.read_json_file(file_path)
        if isinstance(data, dict):
            if "Title" in data:
                title_list = data["Title"]
                script_name = title_list[-1]
        return script_name

    def extract_and_split_commands(self, param_string):
        """
        从函数参数字符串中提取第一个括号中的内容，并按换行符分割成命令列表
        
        Args:
            param_string: 函数参数字符串，如 "函数入参：('aaa.cfg',),{}"
            
        Returns:
            list: 分割后的命令列表，每个命令已去除前后空格和单引号
        """
        try:
            # 匹配括号内的内容（包括多行）
            match = re.search(r'\(\s*(.*?)\s*\)', param_string, re.DOTALL)

            if not match:
                return []
            
            content = match.group(1).strip()
            
            # 去除外层引号（支持单引号和双引号）
            if (content.startswith("'") and content.endswith("'")) or \
               (content.startswith('"') and content.endswith('"')):
                content = content[1:-1]
            
            # 去除末尾的逗号（如果有）
            if content.endswith(','):
                content = content[:-1].strip()
            
            # 按换行符分割并处理每个命令
            commands = []
            for cmd in content.split('\n'):
                cmd = cmd.strip()
                if not cmd:
                    continue
                
                # 使用正则表达式去除所有引号（包括不匹配的）
                # 移除所有单引号和双引号
                cmd = re.sub(r"^['\"]+|['\"]+$", "", cmd)
                cmd = cmd.strip()
                
                if cmd:  # 确保不为空
                    commands.append(cmd)
            
            return commands
            
        except Exception as e:
            print(f"提取命令时出错: {e}")
            return []

    def parse_layer_info(self, input_string):
        """
        解析层信息字符串，按顺序提取信息生成列表
        
        Args:
            input_string: 格式如 "class_layer=1 step_layer=setup layer1=2 layer2=1" 的字符串
        
        Returns:
            list: 按顺序提取的值列表
        """
        result = []
        
        # 按空格分割字符串得到键值对
        pairs = input_string.split()
        
        for pair in pairs:
            # 按等号分割键值对
            if '=' in pair:
                key, value = pair.split('=', 1)
                result.append(value)
        return result
        
    def extract_dut_from_title(self, title_data):
        """
        从 Title 列表中提取 DUT 信息
        """
        if not title_data or len(title_data) < 2:
            return None
        
        # 获取第二个元素（索引为1）
        title_string = title_data[1]

        # 找到第一个左括号和右括号的位置
        left = title_string.find('(')
        right = title_string.find(')', left)  # 从left位置开始找右括号

        if left != -1 and right != -1:
            result = title_string[left+1:right]
            return result

        return None

    def get_expect_string_new(self, check_command_info):

        results = []

        cmd_start = check_command_info.find("{'cmd'")
        if cmd_start != -1:
            dict_str = check_command_info[cmd_start:]
            try:
                extracted_dict = eval(dict_str)
                if 'expect' in extracted_dict:
                    expect_list = extracted_dict['expect']
                    if expect_list:
                        for item in expect_list:
                            results.append({
                                'type': '包含',
                                'content': str(item)
                            })
                if 'not_expect' in extracted_dict:
                    expect_list = extracted_dict['expect']
                    if expect_list:
                        for item in expect_list:
                            results.append({
                                'type': '不包含',
                                'content': str(item)
                            })

            except Exception as e:
                print(f"转换失败: {e}")
        return results

    def get_expect_string(self, check_res):
        """
        从文本中提取回显信息中的包含/不包含字段内容
        
        参数:
            text: 输入的字符串文本
            
        返回:
            list: 包含所有提取结果的列表，每个元素是一个字典，包含字段类型和内容
        """
        results = []

        # 按换行符分割文本
        lines = check_res.split('\n')
        
        for line in lines:
            # 查找"回显信息"字段
            if "回显信息 包含" in line:
                # 找到"包含"后面的内容
                start_idx = line.find("包含")
                if start_idx != -1:
                    content = line[start_idx + 2:]  # 跳过"包含"两个字符
                    content = content.rstrip('！')
                    content = content.strip()
                    if content:  # 如果内容不为空
                        results.append({
                            'type': '包含',
                            'content': content
                        })
            if "回显信息 出现" in line:
                # 找到"包含"后面的内容
                start_idx = line.find("出现")
                if start_idx != -1:
                    content = line[start_idx + 2:]
                    if "的次数为" in content:
                        count_idx = content.find("的次数为")
                        if count_idx != -1:
                            content_part = content[:count_idx].strip()
                            if content_part:
                                results.append({
                                    'type': '包含',
                                    'content': content_part
                                })
            # 查找"不包含"字段
            if "回显信息 不包含" in line:
                #print(line)
                # 找到"不包含"后面的内容
                start_idx = line.find("不包含")
                if start_idx != -1:
                    content = line[start_idx + 3:]  # 跳过"不包含"三个字符
                    content = content.rstrip('！')
                    #print(f"content:{content}")
                    content = content.strip()  # 剔除前后空格
                    if content:  # 如果内容不为空
                        results.append({
                            'type': '不包含',
                            'content': content
                        })

        return results

    def get_command_exec_result(self, exec_info):
        lines = exec_info.split('\n')
        result_lines = []
        for i, line in enumerate(lines):
            if line.startswith('<') or line.startswith('['):
                command_exec_res = {}
                # 找到第一个>或]的位置
                if line.startswith('<'):
                    end_char = '>'
                else:  # line.startswith('[')
                    end_char = ']'
                
                # 提取<或[和>或]之间的内容
                start_idx = 1  # 跳过<或[
                end_idx = line.find(end_char, start_idx)
                
                if end_idx != -1:
                    content = line[end_idx + 1:]
                    if i < len(lines)-1:
                        next_line = lines[i + 1]
                        if next_line.endswith('^'):
                            command_exec_res[content] = "FAIL"
                        else:
                            command_exec_res[content] = "PASS"
                    else:
                        command_exec_res[content] = "PASS"
                    result_lines.append(command_exec_res)
        return result_lines

    def base_log_info_get(self,log_dict):
        log_info = {}
        if "Parameter" in log_dict:
            lay_list = self.parse_layer_info(log_dict["layer"])
            device_name = self.extract_dut_from_title(log_dict["Title"])
            send_commands = self.extract_and_split_commands(log_dict["Parameter"])
            exec_info = None
            if "all_cmds_response" in log_dict:
                exec_info = log_dict["all_cmds_response"]
            log_info["lay_list"] = lay_list
            log_info["device_name"] = device_name
            log_info["send_commands"] = send_commands
            log_info["exec_info"] = exec_info
        return log_info

    def send_info_get(self, send_dict):
        send_info = {}
        if isinstance(send_dict, dict):
            if "Parameter" in send_dict:
                log_info = self.base_log_info_get(send_dict)
                exec_res = send_dict["Result"]
                send_info["flag"] = "send"
                send_info["expect"] = []
                send_info["exec_res"] = exec_res
                send_info.update(log_info)
                
        return send_info

    def fill_error_check_info(self, check_log):
        check_info = {}
        check_info["lay_list"] = []
        check_info["device_name"] = None
        check_info["send_commands"] = []
        check_info["exec_info"] = check_log["Error_occurred"]
        check_info["flag"] = "check"
        check_info["expect"] = []
        check_info["exec_res"] = "FAIL"
        check_info["fail_type"] = "check_level"
        return check_info

    def check_command_info_get(self, check_log):
        check_info = {}
        is_first = 0
        expect_info_list = []
        check_res = ""
        if isinstance(check_log, dict):
            for key in check_log:
                if "Error_occurred" in key:
                    check_info = self.fill_error_check_info(check_log)
                    return check_info
                if "send" in key and is_first == 0:
                    is_first = 1
                    check_send_dict = check_log[key]
                    log_info = self.base_log_info_get(check_send_dict)
                    check_info["flag"] = "check"
                    check_info.update(log_info)
                if "Parameter" in key:
                    check_command_info = check_log[key]
                    expect_info_list = self.get_expect_string_new(check_command_info)
                    check_info["expect"] = expect_info_list
            check_info["exec_res"] = check_log["Result"]
        elif isinstance(check_log, list):
            last_check_dict = check_log[-1]
            for key in last_check_dict:
                if "send" in key and is_first == 0:
                    is_first = 1
                    check_send_dict = last_check_dict[key]
                    log_info = self.base_log_info_get(check_send_dict)
                    check_info["flag"] = "check"
                    check_info.update(log_info)
                if "Parameter" in key:
                    check_command_info = last_check_dict[key]
                    expect_info_list = self.get_expect_string_new(check_command_info)
                    check_info["expect"] = expect_info_list
            check_info["exec_res"] = last_check_dict["Result"]

        return check_info

    def conftest_command_info_get(self, info_dict, flag, teardown_send_flag = 0):
        result = []
        if "setup" == flag or 0 == teardown_send_flag:
            if isinstance(info_dict, dict):
                for key, value in info_dict.items():
                    if "send" in key:
                        send_dict = value
                        send_info = self.send_info_get(send_dict)
                        send_info["func"] = flag
                        result.append(send_info)
                    elif "CheckCommand" in key:
                        check_log = value
                        check_info = self.check_command_info_get(check_log)
                        check_info["func"] = flag
                        result.append(check_info)
                else:
                    if "all_cmds_response" in info_dict:
                        check_info = self.send_info_get(info_dict)
                        #print(check_info)
                        check_info["func"] = flag
                        result.append(check_info)
        if "teardown" == flag and 1 == teardown_send_flag:
            send_info = self.send_info_get(info_dict)
            send_info["func"] = flag
            result.append(send_info)
        return result

    def command_error_info_process(self,erro_info,func_name):
        result = []
        func_info = {}
        func_info["func"] = func_name
        func_info["flag"] = "send"
        func_info["expect"] = []
        func_info["device_name"] = None
        func_info["send_commands"] = None
        func_info["exec_res"] = "FAIL"
        func_info["exec_info"] = erro_info
        func_info["fail_type"] = "func_level"
        result.append(func_info)
        return result

    def step_command_error_info_process(self,erro_info,func_name,step_seq):
        func_info = {}
        func_info["func"] = func_name
        func_info["step_seq"] = step_seq
        func_info["flag"] = "send"
        func_info["expect"] = []
        func_info["device_name"] = None
        func_info["send_commands"] = None
        func_info["exec_res"] = "FAIL"
        func_info["exec_info"] = erro_info
        func_info["fail_type"] = "func_level"
        return func_info

    def get_setup_info(self, stepLists):
        result = []
        command_num = 0
        if not stepLists:
            return None
        if isinstance(stepLists, dict):
            item = stepLists
            if isinstance(item, dict):
                for key in item:
                    if "send" in key:
                        send_dict = item[key]
                        send_info = self.send_info_get(send_dict)
                        send_info["func"] = "setup"
                        result.append(send_info)
                    elif "CheckCommand" in key:
                        check_log = item[key]
                        check_info = self.check_command_info_get(check_log)
                        check_info["func"] = "setup"
                        result.append(check_info)
                else:
                    if "all_cmds_response" in  item:
                        send_dict = item
                        send_info = self.send_info_get(send_dict)
                        send_info["func"] = "setup"
                        result.append(send_info)
        else:
            for item in stepLists:
                if isinstance(item, dict):
                    for key in item:
                        if "send" in key:
                            send_dict = item[key]
                            send_info = self.send_info_get(send_dict)
                            send_info["func"] = "setup"
                            result.append(send_info)
                        elif "CheckCommand" in key:
                            check_log = item[key]
                            check_info = self.check_command_info_get(check_log)
                            check_info["func"] = "setup"
                            result.append(check_info)
        return result

    def get_teardown_info(self, stepLists):
        result = []
        if not stepLists:
            return None
        if isinstance(stepLists, dict):
            item = stepLists
            if isinstance(item, dict):
                if "Title" in item:
                    action = item["Title"]
                    if "METHOD" in action:
                        send_info = self.send_info_get(item)
                        send_info["func"] = "teardown"
                        result.append(send_info)
                    elif "CheckCommand" in item:
                        check_log = item["CheckCommand"]
                        check_info = self.check_command_info_get(check_log)
                        check_info["func"] = "teardown"
                        result.append(check_info)
        else:
            for item in stepLists:
                if isinstance(item, dict):
                    if "Title" in item:
                        action = item["Title"]
                        if "METHOD" in action:
                            send_info = self.send_info_get(item)
                            send_info["func"] = "teardown"
                            result.append(send_info)
                        elif "CheckCommand" in item:
                            check_log = item["CheckCommand"]
                            check_info = self.check_command_info_get(check_log)
                            check_info["func"] = "teardown"
                            result.append(check_info)
        return result

    def get_step_info(self,steps):
        result = []
        step_num = 0
        if isinstance(steps, dict):
            step = steps
            step_num = step_num + 1
            step_name_str = step["Title"][-1]
            step_func = step_name_str.split(":", 1)[0]
            if "stepLists" not in step and "Error_occurred" in step:
                error_info = self.step_command_error_info_process(step["Error_occurred"],step_func,step_num)
                result.append(error_info)
            else:
                error_info = {}
                if "stepLists" in step:
                    single_stepLists = step["stepLists"]
                    if "Error_occurred" in step:
                        error_info = self.step_command_error_info_process(step["Error_occurred"],step_func,step_num)
                    if isinstance(single_stepLists, dict):
                        item = single_stepLists
                        if "Title" in item:
                            action = item["Title"]
                            if "METHOD" in action:
                                send_info = self.send_info_get(item)
                                send_info["func"] = step_func
                                send_info["step_seq"] = step_num
                                result.append(send_info)
                            elif "CheckCommand" in item:
                                check_log = item["CheckCommand"]
                                check_info = self.check_command_info_get(check_log)
                                check_info["func"] = step_func
                                check_info["step_seq"] = step_num
                                result.append(check_info)
                    else:
                        for item in single_stepLists:
                            if "Title" in item:
                                action = item["Title"]
                                if "METHOD" in action:
                                    send_info = self.send_info_get(item)
                                    send_info["func"] = step_func
                                    send_info["step_seq"] = step_num
                                    result.append(send_info)
                                elif "CheckCommand" in item:
                                    check_log = item["CheckCommand"]
                                    check_info = self.check_command_info_get(check_log)
                                    check_info["func"] = step_func
                                    check_info["step_seq"] = step_num
                                    result.append(check_info)
                    if error_info:
                        result.append(error_info)
        else:
            for step in steps:
                step_num = step_num + 1
                step_name_str = step["Title"][-1]
                step_func = step_name_str.split(":", 1)[0]
                if "stepLists" not in step and "Error_occurred" in step:
                    error_info = self.step_command_error_info_process(step["Error_occurred"],step_func,step_num)
                    result.append(error_info)
                else:
                    error_info = {}
                    if "stepLists" in step:
                        single_stepLists = step["stepLists"]
                        if "Error_occurred" in step:
                            error_info = self.step_command_error_info_process(step["Error_occurred"],step_func,step_num)
                        if isinstance(single_stepLists, dict):
                            item = single_stepLists
                            if "Title" in item:
                                action = item["Title"]
                                if "METHOD" in action:
                                    send_info = self.send_info_get(item)
                                    send_info["func"] = step_func
                                    send_info["step_seq"] = step_num
                                    result.append(send_info)
                                elif "CheckCommand" in item:
                                    check_log = item["CheckCommand"]
                                    check_info = self.check_command_info_get(check_log)
                                    check_info["func"] = step_func
                                    check_info["step_seq"] = step_num
                                    result.append(check_info)
                        else:
                            for item in single_stepLists:
                                if "Title" in item:
                                    action = item["Title"]
                                    if "METHOD" in action:
                                        send_info = self.send_info_get(item)
                                        send_info["func"] = step_func
                                        send_info["step_seq"] = step_num
                                        result.append(send_info)
                                    elif "CheckCommand" in item:
                                        check_log = item["CheckCommand"]
                                        check_info = self.check_command_info_get(check_log)
                                        check_info["func"] = step_func
                                        check_info["step_seq"] = step_num
                                        result.append(check_info)
                        if error_info:
                            result.append(error_info)
        return result

    def process_up_or_down_list(self, data_list, func):
        """
        处理包含lay_list的字典列表，按指定规则排序
        """
        valid_items = []
        fail_data_item = {}
        for item_data in data_list:
            if item_data.get("func") == func and "fail_type" in item_data and item_data["fail_type"] == "func_level":
                fail_data_item = item_data
            elif item_data.get("func") == func:
                valid_items.append(item_data)

        if fail_data_item:
            valid_items.append(fail_data_item)
        return valid_items

    def process_single_step_list(self, data_list):
        valid_items = []
        for item in data_list:
            if 'lay_list' in item:
                valid_items.append(item)
            elif "fail_type" in item and item["fail_type"]:
                return data_list
        # 先按前两个数值排序，长度不同的情况特殊处理
        def custom_sort_key(item):
            lay_list = item['lay_list']
            sort_elements = lay_list[1:]
            
            # 将元素转换为可比较的数字
            numeric_elements = []
            for elem in sort_elements:
                try:
                    numeric_elements.append(float(elem))
                except (ValueError, TypeError):
                    numeric_elements.append(float('inf'))
            
            # 返回一个元组：前两个数值 + 长度信息（确保数值比较优先）
            return (
                numeric_elements[0] if len(numeric_elements) > 0 else float('inf'),
                numeric_elements[1] if len(numeric_elements) > 1 else float('inf'),
                len(lay_list)  # 最后考虑长度
            )
        
        sorted_items = sorted(valid_items, key=custom_sort_key)
        return sorted_items
        
    def process_step_list(self, data_list):
        """
        处理包含lay_list的列表，按指定规则排序
        
        Args:
            data_list: 包含lay_list项的列表
        
        Returns:
            list: 排序后的结果
        """
        # 筛选出符合条件的字典
        total_step_dict = {}
        for item in data_list:
            if item.get("func") != 'setup' and item.get("func") != 'teardown':
                #不是真正的step_name,而是step_1,step_2
                step_seq = item.get("step_seq")
                step_name = f"step_{step_seq}"
                if step_name in total_step_dict:
                    total_step_dict[step_name].append(item)
                else:
                    total_step_dict[step_name] = []
                    total_step_dict[step_name].append(item)

        """
        print(total_step_dict)
        step_nums = len(total_step_dict)
        for i in range(1,step_nums+1):
            step_name = f"step_{i}"
            if step_name in total_step_dict:
                step_data_list = total_step_dict[step_name]
                #if step_name == "test_step_2":
                    #print(step_data_list)
                #single_step_list = self.process_single_step_list(step_data_list)
                #print(single_step_list)
                total_step_dict[step_name] = step_data_list"""

        return total_step_dict

    def process_conftest_data_list(self, data_list,func):
        valid_items = []
        fail_data_item = {}
        for item_data in data_list:
            if item_data.get("func") == func and "fail_type" in item_data and item_data["fail_type"] == "func_level":
                fail_data_item = item_data
            elif item_data.get("func") == func:
                valid_items.append(item_data)

        if fail_data_item:
            valid_items.append(fail_data_item)
        return valid_items

    def process_conftest_list(self, data_list, flag):
        sorted_items = []
        if "setup" == flag:
            #print(data_list)
            sorted_items = self.process_conftest_data_list(data_list,"setup")
            #print(sorted_items)
        elif "teardown" == flag:
            sorted_items = self.process_conftest_data_list(data_list,"teardown")
        return sorted_items


    def match_command_and_exe_info(self, data):
        res = []
        command_seq = 0
        commands = data['send_commands']
        exec_info = data['exec_info']
        exec_res = data['exec_res']
        check_expect = data['expect']
        if not commands:
            info_dict = {}
            info_dict['cmd'] = commands
            info_dict['exec_info'] = exec_info
            info_dict['exec_res'] = exec_res
            info_dict['expect'] = check_expect
            if "fail_type" in data:
                info_dict["fail_type"] = data["fail_type"]
            res.append(info_dict)
            return res
        else:
            result_lines = self.get_command_exec_result(exec_info)
            if len(result_lines) > 0:
                for command in commands:
                    info_dict = {}
                    if command_seq < len(result_lines) and command in result_lines[command_seq]:
                        info_dict['exec_res'] = result_lines[command_seq][command]
                        command_seq = command_seq + 1
                    elif command_seq != 0 and command_seq < len(result_lines) and command not in result_lines[command_seq]:
                        info_dict['exec_res'] = exec_res
                        command_seq = command_seq + 1
                    elif 0 == command_seq and command not in result_lines[command_seq]:
                        if "end" == command or "ctrl+z" == command:
                            info_dict['exec_res'] = "PASS"
                        else:
                            info_dict['exec_res'] = exec_res
                    else:
                        info_dict['exec_res'] = exec_res
                        command_seq = command_seq + 1
                    info_dict['cmd'] = command
                    info_dict['exec_info'] = exec_info
                    info_dict['expect'] = check_expect
                    res.append(info_dict)
            else:
                for command in commands:
                    info_dict = {}
                    info_dict['cmd'] = command
                    info_dict['exec_info'] = exec_info
                    info_dict['exec_res'] = exec_res
                    info_dict['expect'] = check_expect
                    res.append(info_dict)
        return res

    def gen_command_info(self, data_list):
        res = {}
        pre_funcname = ""
        pre_dut_name = ""
        commands = []
        single_dut_command = {}
        dut_list = []
        for item in data_list:
            if not pre_funcname:
                pre_funcname = item["func"]
            elif pre_funcname != item["func"]:
                if single_dut_command:
                    dut_list.append(single_dut_command)
                    single_dut_command = {}
                    res[pre_funcname] = dut_list
                pre_dut_name = ""
                dut_list = []
                pre_funcname = item["func"]
            #if "device_name" not in item:
                #print(item)
            dut_name = item["device_name"]
            if not pre_dut_name:
                pre_dut_name = dut_name
                single_dut_command[dut_name] = []
                commands_info = self.match_command_and_exe_info(item)
                single_dut_command[dut_name].extend(commands_info)
            elif pre_dut_name == dut_name:
                commands_info = self.match_command_and_exe_info(item)
                single_dut_command[dut_name].extend(commands_info)
            else:
                dut_list.append(single_dut_command) 
                pre_dut_name = dut_name
                single_dut_command = {}
                single_dut_command[dut_name] = []
                commands_info = self.match_command_and_exe_info(item)
                single_dut_command[dut_name].extend(commands_info)
        else:
            if single_dut_command:
                dut_list.append(single_dut_command)
        res[pre_funcname] = dut_list
        return res

    def command_arrange(self, data_list):
        res = {}
        #print(data_list)
        sorted_up_lists = self.process_up_or_down_list(data_list, 'setup')
        sorted_down_lists = self.process_up_or_down_list(data_list, 'teardown')
        total_step_dict = self.process_step_list(data_list)
        #print(total_step_dict)
        setup_res = self.gen_command_info(sorted_up_lists)
        res.update(setup_res)
        down_res = self.gen_command_info(sorted_down_lists)
        res.update(down_res)
        step_nums = len(total_step_dict)
        #step需要包含执行信息
        for i in range(1,step_nums+1):
            step_name = f"step_{i}"
            if step_name in total_step_dict:
                step_res = self.gen_command_info(total_step_dict[step_name])
                tmp_step_dict = {}
                tmp_step_dict[step_name] = step_res
                #print(tmp_step_dict)
                res.update(tmp_step_dict)

        return res

    def conftest_command_arrange(self, data_list, flag):
        conftest_res = {}
        sorted_conftest_lists = self.process_conftest_list(data_list, flag)
        conftest_res = self.gen_command_info(sorted_conftest_lists)
        #print(conftest_res)
        return conftest_res

    def get_func_description(self, json_data):
        des_info = {}
        if isinstance(json_data, dict):
            for value in json_data.values():
                if isinstance(value, dict):
                    if "setup" in value:
                        setup_content = value["setup"]
                        if "Description" in setup_content:
                            setup_des = setup_content["Description"]
                            des_info["setup"] = setup_des
                    if "steps" in value:
                        steps = value["steps"]
                        if isinstance(steps, dict):
                            item = steps
                            if "Description" in item:
                                step_name = f"step_1"
                                step_des = item["Description"]
                                des_info[step_name] = step_des
                        else:
                            for index, item in enumerate(steps, start=1):
                                if "Description" in item:
                                    step_name = f"step_{index}"
                                    step_des = item["Description"]
                                    des_info[step_name] = step_des
                    if "teardown" in value:
                        setup_content = value["teardown"]
                        if "Description" in setup_content:
                            teardown_des = setup_content["Description"]
                            des_info["teardown"] = teardown_des
        return des_info

    def extract_log_content(self, file_path):
        data = self.read_json_file(file_path)
        res = []
        if isinstance(data, dict):
            for value in data.values():
                step_info = []
                if isinstance(value, dict):
                    if "setup" in value:
                        if "stepLists" in value["setup"]:
                            stepLists = value["setup"]["stepLists"]
                            step_info = self.get_setup_info(stepLists)
                        if "Error_occurred" in value["setup"]:
                            error_info = self.command_error_info_process(value["setup"]["Error_occurred"],"setup")
                            step_info.extend(error_info)
                        res.extend(step_info)
                    if "steps" in value:
                        steps = value["steps"]
                        step_info = self.get_step_info(steps)
                        res.extend(step_info)
                    if "teardown" in value:
                        if "stepLists" in value["teardown"]:
                            stepLists = value["teardown"]["stepLists"]
                            step_info = self.get_teardown_info(stepLists)
                        if "Error_occurred" in value["teardown"]:
                            error_info = self.command_error_info_process(value["teardown"]["Error_occurred"],"teardown")
                            step_info.extend(error_info)
                        res.extend(step_info)
        return data, res

    def splice_commmand_info(self, json_data, log_info):
        splice_res = ""
        func_description = self.get_func_description(json_data)
        #print(func_description)
        if isinstance(log_info, dict):
            if "setup" in log_info:
                splice_res = splice_res + "!!!func setup\n"
                if "setup" in func_description: 
                    splice_res = splice_res + "<" + func_description["setup"] + ">" + "\n"
                setup_info = log_info["setup"]
                for dut_info in setup_info:
                    for dut_key, dut_value in dut_info.items():
                        if not dut_key:
                            for dut_commond in dut_value:
                                if "fail_type" in dut_commond:
                                    fail_info = dut_commond["exec_info"]
                                    splice_res = splice_res + "命令执行失败: " + fail_info + "\n"
                            continue
                        splice_res = splice_res + f"!!device {dut_key}" + "\n"
                        for dut_commond in dut_value:
                            if dut_commond["cmd"] == "ctrl+z":
                                dut_commond["cmd"] = "return"
                            if "FAIL" == dut_commond["exec_res"] or "WARNING" == dut_commond["exec_res"]:
                                splice_res = splice_res + "命令执行失败: " + dut_commond["cmd"] + "\n"
                            else:
                                splice_res = splice_res + dut_commond["cmd"] + "\n"
                            if dut_commond['expect']:
                                include_str = ""
                                not_include_str = ""
                                for expect_info in dut_commond['expect']:
                                    if '包含' == expect_info['type']:
                                        if include_str:
                                            include_str = include_str + ',' + expect_info['content']
                                        else:
                                            include_str = include_str + "期望显示:" + expect_info['content']
                                    else:
                                        if not_include_str:
                                            not_include_str = include_str + ',' + expect_info['content']
                                        else:
                                            not_include_str = include_str + "不期望显示:" + expect_info['content']
                                if include_str and not not_include_str:
                                    splice_res = splice_res + "(" + include_str + ")" +"\n"
                                elif not_include_str and not include_str:
                                    splice_res = splice_res + "(" + not_include_str + ")" +"\n"
                                elif include_str and not_include_str:
                                    splice_res = splice_res + "(" + include_str + "," + not_include_str + ")" +"\n"
            if "teardown" in log_info:
                splice_res = splice_res + "!!!func teardown\n"
                if "teardown" in func_description: 
                    splice_res = splice_res + "<" + func_description["teardown"] + ">" + "\n"
                teardown_info = log_info["teardown"]
                for dut_info in teardown_info:
                    for dut_key, dut_value in dut_info.items():
                        if not dut_key:
                            for dut_commond in dut_value:
                                if "fail_type" in dut_commond:
                                    fail_info = dut_commond["exec_info"]
                                    splice_res = splice_res + "命令执行失败: " + fail_info + "\n"
                            continue
                        splice_res = splice_res + f"!!device {dut_key}" + "\n"
                        for dut_commond in dut_value:
                            if dut_commond["cmd"] == "ctrl+z":
                                dut_commond["cmd"] = "return"
                            if "FAIL" == dut_commond["exec_res"] or "WARNING" == dut_commond["exec_res"]:
                                splice_res = splice_res + "命令执行失败: " + dut_commond["cmd"] + "\n"
                            else:
                                splice_res = splice_res + dut_commond["cmd"] + "\n"
                            if dut_commond['expect']:
                                include_str = ""
                                not_include_str = ""
                                for expect_info in dut_commond['expect']:
                                    if '包含' == expect_info['type']:
                                        if include_str:
                                            include_str = include_str + ',' + expect_info['content']
                                        else:
                                            include_str = include_str + "期望显示:" + expect_info['content']
                                    else:
                                        if not_include_str:
                                            not_include_str = include_str + ',' + expect_info['content']
                                        else:
                                            not_include_str = include_str + "不期望显示:" + expect_info['content']
                                if include_str and not not_include_str:
                                    splice_res = splice_res + "(" + include_str + ")" +"\n"
                                elif not_include_str and not include_str:
                                    splice_res = splice_res + "(" + not_include_str + ")" +"\n"
                                elif include_str and not_include_str:
                                    splice_res = splice_res + "(" + include_str + "," + not_include_str + ")" +"\n"
            log_len = len(log_info)
            for i in range(1, log_len + 1):
                step_seq_name = f"step_{i}"
                if step_seq_name in log_info:
                    step_dict = log_info[step_seq_name]
                    for step_key, step_info in step_dict.items():
                        step_name = step_key
                        splice_res = splice_res + f"!!!func {step_name}\n"
                        if step_seq_name in func_description: 
                            splice_res = splice_res + "<" + func_description[step_seq_name] + ">" + "\n"
                        for dut_info in step_info:
                            for dut_key, dut_value in dut_info.items():
                                if not dut_key:
                                    for dut_commond in dut_value:
                                        if "fail_type" in dut_commond:
                                            fail_info = dut_commond["exec_info"]
                                            splice_res = splice_res + "命令执行失败: " + fail_info + "\n"
                                    continue
                                splice_res = splice_res + f"!!device {dut_key}" + "\n"
                                for dut_commond in dut_value:
                                    if dut_commond["cmd"] == "ctrl+z":
                                        dut_commond["cmd"] = "return"
                                    if "FAIL" == dut_commond["exec_res"] or "WARNING" == dut_commond["exec_res"]:
                                        splice_res = splice_res + "命令执行失败: " + dut_commond["cmd"] + "\n"
                                    else:
                                        splice_res = splice_res + dut_commond["cmd"] + "\n"
                                    if dut_commond['expect']:
                                        include_str = ""
                                        not_include_str = ""
                                        for expect_info in dut_commond['expect']:
                                            if '包含' == expect_info['type']:
                                                if include_str:
                                                    include_str = include_str + ',' + expect_info['content']
                                                else:
                                                    include_str = include_str + "期望显示:" + expect_info['content']
                                            else:
                                                if not_include_str:
                                                    not_include_str = include_str + ',' + expect_info['content']
                                                else:
                                                    not_include_str = include_str + "不期望显示:" + expect_info['content']
                                        if include_str and not not_include_str:
                                            splice_res = splice_res + "(" + include_str + ")" +"\n"
                                        elif not_include_str and not include_str:
                                            splice_res = splice_res + "(" + not_include_str + ")" +"\n"
                                        elif include_str and not_include_str:
                                            splice_res = splice_res + "(" + include_str + "," + not_include_str + ")" +"\n"
        return splice_res

    def splice_contest_command(self, set_command_info, teardown_command_info):
        splice_res = ""
        if isinstance(set_command_info, dict):
            if "setup" in set_command_info:
                splice_res = splice_res + "!!!func setup\n"
                setup_info = set_command_info["setup"]
                for dut_info in setup_info:
                    for dut_key, dut_value in dut_info.items():
                        if not dut_key:
                            for dut_commond in dut_value:
                                if "fail_type" in dut_commond:
                                    fail_info = dut_commond["exec_info"]
                                    splice_res = splice_res + "命令执行失败: " + fail_info + "\n"
                            continue
                        splice_res = splice_res + f"!!device {dut_key}" + "\n"
                        for dut_commond in dut_value:
                            if dut_commond["cmd"] == "ctrl+z":
                                dut_commond["cmd"] = "return"
                            if "FAIL" == dut_commond["exec_res"] or "WARNING" == dut_commond["exec_res"]:
                                splice_res = splice_res + "命令执行失败: " + dut_commond["cmd"] + "\n"
                            else:
                                splice_res = splice_res + dut_commond["cmd"] + "\n"
                            if dut_commond['expect']:
                                include_str = ""
                                not_include_str = ""
                                for expect_info in dut_commond['expect']:
                                    if '包含' == expect_info['type']:
                                        if include_str:
                                            include_str = include_str + ',' + expect_info['content']
                                        else:
                                            include_str = include_str + "期望显示:" + expect_info['content']
                                    else:
                                        if not_include_str:
                                            not_include_str = include_str + ',' + expect_info['content']
                                        else:
                                            not_include_str = include_str + "不期望显示:" + expect_info['content']
                                if include_str and not not_include_str:
                                    splice_res = splice_res + "(" + include_str + ")" +"\n"
                                elif not_include_str and not include_str:
                                    splice_res = splice_res + "(" + not_include_str + ")" +"\n"
                                elif include_str and not_include_str:
                                    splice_res = splice_res + "(" + include_str + "," + not_include_str + ")" +"\n"
            if "teardown" in teardown_command_info:
                splice_res = splice_res + "!!!func teardown\n"
                teardown_info = teardown_command_info["teardown"]
                for dut_info in teardown_info:
                    for dut_key, dut_value in dut_info.items():
                        if not dut_key:
                            for dut_commond in dut_value:
                                if "fail_type" in dut_commond:
                                    fail_info = dut_commond["exec_info"]
                                    splice_res = splice_res + "命令执行失败: " + fail_info + "\n"
                            continue
                        splice_res = splice_res + f"!!device {dut_key}" + "\n"
                        for dut_commond in dut_value:
                            if dut_commond["cmd"] == "ctrl+z":
                                dut_commond["cmd"] = "return"
                            if "FAIL" == dut_commond["exec_res"] or "WARNING" == dut_commond["exec_res"]:
                                splice_res = splice_res + "命令执行失败: " + dut_commond["cmd"] + "\n"
                            else:
                                splice_res = splice_res + dut_commond["cmd"] + "\n"
                            if dut_commond['expect']:
                                include_str = ""
                                not_include_str = ""
                                for expect_info in dut_commond['expect']:
                                    if '包含' == expect_info['type']:
                                        if include_str:
                                            include_str = include_str + ',' + expect_info['content']
                                        else:
                                            include_str = include_str + "期望显示:" + expect_info['content']
                                    else:
                                        if not_include_str:
                                            not_include_str = include_str + ',' + expect_info['content']
                                        else:
                                            not_include_str = include_str + "不期望显示:" + expect_info['content']
                                if include_str and not not_include_str:
                                    splice_res = splice_res + "(" + include_str + ")" +"\n"
                                elif not_include_str and not include_str:
                                    splice_res = splice_res + "(" + not_include_str + ")" +"\n"
                                elif include_str and not_include_str:
                                    splice_res = splice_res + "(" + include_str + "," + not_include_str + ")" +"\n"
        return splice_res

    def output_command_file(self, file_path):
        data, data_list = self.extract_log_content(file_path)
        log_info = self.command_arrange(data_list)
        splice_res = self.splice_commmand_info(data, log_info)
        return splice_res

    def extract_and_write_info(self, file_path):
        res = {}
        data, data_list = self.extract_log_content(file_path)
        res = self.command_arrange(data_list)
        # 写入JSON文件
        with open('data.json', 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=4)

    def single_conftest_func_process(self, file_path, flag):
        data = self.read_json_file(file_path)
        log_command_info = {}
        log_commands = []
        tail_error_info = []
        #teardown_commands = []
        if "setup" == flag:
            if isinstance(data, dict):
                for key, value in data.items():
                    if "create_interface" in key or "atf_retry" in key or "send" in key or "CheckCommand" in key:
                        step_info = self.conftest_command_info_get(value, flag)
                        log_commands.extend(step_info)
                    elif "Error_occurred" in key:
                        tail_error_info = self.command_error_info_process(value,"setup")
        elif "teardown" == flag:
            if isinstance(data, dict):
                for key, value in data.items():
                    if "send" in key:
                        step_info = self.conftest_command_info_get(value, flag, 1)
                        log_commands.extend(step_info)
                    elif "delete_interface" in key:
                        step_info = self.conftest_command_info_get(value, flag)
                        log_commands.extend(step_info)
                    elif "Error_occurred" in key:
                        tail_error_info = self.command_error_info_process(value,"teardown")

        log_commands.extend(tail_error_info)
        #print(log_commands)
        log_command_info = self.conftest_command_arrange(log_commands,flag)
        return log_command_info

    def conftest_log_process(self, setup_file_path, teardown_file_path):
        log_info = ""
        set_command_info = {}
        teardown_command_info = {}
        if setup_file_path:
            #print(setup_file_path)
            setup_info = self.single_conftest_func_process(setup_file_path, "setup")
            #print(setup_info)
            set_command_info.update(setup_info)
        
        if teardown_file_path:
            teardown_info = self.single_conftest_func_process(teardown_file_path,"teardown")
            teardown_command_info.update(teardown_info)
        log_info = self.splice_contest_command(set_command_info, teardown_command_info)
        return log_info

    def log_file_process(self):
        res = {}
        conftest_setup_path = ""
        conftest_teardown_path = ""
        for root, dirs, files in os.walk('.'):
            for file in files:
                if file.endswith('.pytestlog.json'):
                    log_file_path = os.path.join(root, file)
                    script_name = self.get_script_name(log_file_path)
                    if "setup" == script_name:
                        conftest_setup_path = log_file_path
                    elif "teardown" == script_name:
                        conftest_teardown_path = log_file_path
                    else:
                        splice_res = self.output_command_file(log_file_path)
                        res[script_name] = splice_res

        splice_res = self.conftest_log_process(conftest_setup_path, conftest_teardown_path)

        if splice_res:
            res["conftest.py"] = splice_res

        return res


if __name__ == "__main__":
    # 1. 实例化类，传入日志文件路径
    log_processor = LOGPROCESS("/home/y28677/w31815/tmps/new_script_extract/local/")  # 替换为实际的JSON文件路径
    
    try:
        # 2. 调用 extract_setup_content 方法提取 setup 内容
        #setup_data = log_processor.extract_and_write_info()
        #name = log_processor.get_script_name()
        outres = log_processor.log_file_process()
        for key,value in outres.items():
            with open(key, 'w', encoding='utf-8') as f:
                f.write(value)

    except FileNotFoundError as e:
        print(f"文件错误: {e}")
    except Exception as e:
        print("完整错误追踪:")
        traceback.print_exc()
        print(f"\n错误类型: {type(e).__name__}")