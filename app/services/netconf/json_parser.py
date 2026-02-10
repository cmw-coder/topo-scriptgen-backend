import json
import base64
import re

class JSONParser:
    def decode_base64_in_json(self, data):
        """递归解码 JSON 中的 Base64 编码字段"""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    # 匹配 _HTML:b'...' 或 _CMD:b'...'
                    match = re.match(r'^_(HTML|CMD):b\'(.*?)\'$', value)
                    if match:
                        b64_str = match.group(2)
                        try:
                            decoded = base64.b64decode(b64_str).decode('utf-8')
                            data[key] = decoded
                        except Exception:
                            pass
                else:
                    self.decode_base64_in_json(value)
        elif isinstance(data, list):
            for item in data:
                self.decode_base64_in_json(item)

    def check_contains_fail(self, data):
        """检查数据结构中是否包含FAIL或ERROR信息"""
        if isinstance(data, dict):
            for key, value in data.items():
                if key == "Result" and value in ["FAIL", "ERROR"]:
                    return True
                if self.check_contains_fail(value):
                    return True
        elif isinstance(data, list):
            for item in data:
                if self.check_contains_fail(item):
                    return True
        return False

    def filter_pass_results(self, data):
        """过滤掉详细的成功执行步骤，但保留测试框架和主要信息
        保留FAIL和ERROR信息，过滤PASS信息"""
        # 对于字符串，检查是否需要Base64解码
        if isinstance(data, str):
            match = re.match(r'^_(HTML|CMD):b\'(.*?)\'$', data)
            if match:
                b64_str = match.group(2)
                try:
                    decoded = base64.b64decode(b64_str).decode('utf-8')
                    return decoded
                except Exception:
                    return data
            return data

        if isinstance(data, dict):
            # 保留顶层的关键信息，不进行过滤
            if data.get("Title") and isinstance(data.get("Title"), list) and len(data.get("Title", [])) >= 2:
                # 这是主要的测试结构，保留基本结构但过滤执行细节
                filtered_dict = {}
                for key, value in data.items():
                    # 对于特定字段进行特殊处理
                    if key in ["start_time", "end_time", "elapsed_time", "all_cmds_response", "last_cmd_response"]:
                        continue  # 跳过执行时间戳和命令响应
                    elif key == "stepLists" and isinstance(value, list):
                        # 对于stepLists，只保留包含FAIL或ERROR信息的步骤
                        filtered_steps = []
                        for step in value:
                            # 递归检查这个步骤是否包含FAIL或ERROR信息
                            step_has_fail_or_error = self.check_contains_fail(step)
                            if step_has_fail_or_error:
                                # 保留这个步骤，但进行适当的过滤
                                filtered_step = self.filter_pass_results(step)
                                if filtered_step:
                                    filtered_steps.append(filtered_step)
                        if filtered_steps:
                            filtered_dict[key] = filtered_steps
                        continue
                    elif key.startswith("CheckCommand") or key.startswith("send_"):
                        # 对于检查和发送命令，检查是否包含FAIL或ERROR信息
                        if self.check_contains_fail(value):
                            # 保留包含FAIL或ERROR信息的命令
                            filtered_value = self.filter_pass_results(value)
                            if filtered_value is not None:
                                filtered_dict[key] = filtered_value
                        continue
                    elif key in ["Custom_check", "Device_screen", "Output_Path"]:
                        # 跳过这些字段及其所有内容
                        continue
                    elif key == "Result" and value == "PASS":
                        # 跳过成功结果
                        continue
                    else:
                        # 递归处理其他字段
                        filtered_value = self.filter_pass_results(value)
                        if filtered_value is not None:
                            # 如果是字符串且包含Base64编码，进行解码
                            if isinstance(filtered_value, str):
                                match = re.match(r'^_(HTML|CMD):b\'(.*?)\'$', filtered_value)
                                if match:
                                    b64_str = match.group(2)
                                    try:
                                        decoded = base64.b64decode(b64_str).decode('utf-8')
                                        filtered_dict[key] = decoded
                                    except Exception:
                                        filtered_dict[key] = filtered_value
                                else:
                                    filtered_dict[key] = filtered_value
                            else:
                                filtered_dict[key] = filtered_value

                return filtered_dict if filtered_dict else None

            # 如果当前字典包含 "Result": "PASS" 且不是主要结构，跳过
            if data.get("Result") == "PASS":
                return None
            # 如果包含 "Result": "FAIL" 或 "ERROR"，保留并继续处理
            if data.get("Result") in ["FAIL", "ERROR"]:
                return data  # 直接返回，保留完整结构

            # 对于其他字典，递归处理
            filtered_dict = {}
            for key, value in data.items():
                # 如果是需要跳过的字段，直接跳过
                if key in ["Custom_check", "Device_screen", "Output_Path"]:
                    continue

                filtered_value = self.filter_pass_results(value)
                if filtered_value is not None:
                    filtered_dict[key] = filtered_value

            return filtered_dict if filtered_dict else None

        elif isinstance(data, list):
            # 递归处理列表，但过滤掉一些不必要的项
            filtered_list = []
            for item in data:
                filtered_item = self.filter_pass_results(item)
                if filtered_item is not None:
                    filtered_list.append(filtered_item)
            return filtered_list if filtered_list else None

        # 对于其他类型，直接返回
        return data

    def replace_newlines(self, obj):
        """递归遍历对象，把字符串里的 '\\n' 转成真实换行"""
        if isinstance(obj, dict):
            return {k: self.replace_newlines(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.replace_newlines(v) for v in obj]
        elif isinstance(obj, str):
            return obj.replace('\\n', '\r\n')
        else:
            return obj

    def parse_json_data(self, data):
        """解析JSON数据并返回处理后的结果

        Args:
            data: JSON数据（字典、列表或JSON字符串）

        Returns:
            解析后的JSON数据
        """
        try:
            # 如果是字符串，先解析为字典
            if isinstance(data, str):
                data = json.loads(data)

            # 第一步：Base64解码
            self.decode_base64_in_json(data)

            # 第二步：过滤结果
            filtered_data = self.filter_pass_results(data)

            # 如果过滤后为空，返回解码后的原始数据
            if filtered_data is None:
                return data

            # 第三步：处理换行符
            result = self.replace_newlines(filtered_data)

            return result

        except json.JSONDecodeError as e:
            raise Exception(f"JSON解析失败: {str(e)}")
        except Exception as e:
            raise Exception(f"解析过程出错: {str(e)}")

    def extract_error_summary(self, data):
        """从解析后的数据中提取错误摘要信息

        Args:
            data: 解析后的JSON数据

        Returns:
            dict: 错误摘要，包含 total_failures 和 groups
        """
        error_summary = {
            "total_failures": 0,
            "groups": []
        }

        # 判断结果是否为fail
        if isinstance(data, dict) and data.get("Result") == "FAIL":

            # 递归查找stepLists下与Result相关的logger错误日志
            def find_fail_steps_and_errors(data):
                # 调整返回结构：返回组列表，每个组包含该stepLists下的所有失败步骤
                groups = []
                processed_steps = set()

                def traverse(data, parent_description=None):
                    if isinstance(data, dict):
                        # 检查是否是包含stepLists的字典
                        if "stepLists" in data:
                            # 为这个stepLists创建一个新的组
                            group_id = "stepLists_group"
                            # 提取当前层级或父级的 description
                            description = data.get("Description", parent_description or "")

                            new_group = {
                                "group_id": group_id,
                                "description": description,
                                "steps": []
                            }

                            # 处理stepLists
                            if isinstance(data["stepLists"], list):
                                for item in data["stepLists"]:
                                    process_item(item, new_group)

                            # 如果组不为空，添加到结果中
                            if new_group["steps"]:
                                groups.append(new_group)

                        # 递归检查其他子节点
                        for key, value in data.items():
                            if key not in ["Result", "Title"]:
                                # 如果当前字段是 Description，传递给子节点
                                if key == "Description":
                                    traverse(value, value)
                                else:
                                    traverse(value, parent_description)

                    elif isinstance(data, list):
                        # 递归检查列表中的每个元素
                        for item in data:
                            traverse(item)

                def process_item(item, group):
                    """处理单个项目，提取错误信息并添加到组中"""
                    if isinstance(item, dict):
                        # 检查当前项是否包含Result字段且为FAIL
                        if item.get("Result") == "FAIL":
                            # 获取步骤名称
                            title = item.get("Title", [])
                            description = item.get("Description", "")
                            step_name = ""
                            if title:
                                step_name = title[1] if len(title) > 1 else title[0]
                            elif description:
                                step_name = description

                            # 生成步骤唯一标识
                            step_identifier = f"{step_name}"

                            # 检查是否已经处理过这个步骤
                            if step_identifier not in processed_steps:
                                processed_steps.add(step_identifier)

                                # 获取该步骤的logger
                                step_errors = []
                                for key, value in item.items():
                                    if key.startswith("logger_") and isinstance(value, dict):
                                        message = value.get("Title", [])
                                        if message and len(message) > 1:
                                            log_message = message[1]
                                            # 提取错误信息，去除首尾的引号和换行符
                                            if log_message.startswith("''") and log_message.endswith("''"):
                                                log_message = log_message[2:-2]
                                            step_errors.append(log_message)

                                # 如果有错误信息，添加到组中
                                if step_errors:
                                    step_info = {
                                        "step": step_name,
                                        "errors": step_errors
                                    }
                                    group["steps"].append(step_info)

                        # 递归检查子节点
                        for key, value in item.items():
                            if key not in ["Result", "Title", "Description"]:
                                process_item(value, group)

                    elif isinstance(item, list):
                        # 递归检查列表中的每个元素
                        for sub_item in item:
                            process_item(sub_item, group)

                # 首先处理顶层数据
                traverse(data)

                return groups

            # 查找所有失败的测试步骤和错误日志
            fail_info = find_fail_steps_and_errors(data)

            # 处理分组的错误信息
            for group in fail_info:
                group_id = group.get("group_id", "unknown")
                description = group.get("description", "")
                steps = group.get("steps", [])

                if steps:
                    # 创建组结构
                    group_info = {
                        "group_id": group_id,
                        "description": description,
                        "failures": []
                    }

                    for step_info in steps:
                        step_name = step_info["step"]
                        errors = step_info["errors"]

                        # 保存到组信息
                        group_info["failures"].append({
                            "step": step_name,
                            "errors": errors
                        })
                        error_summary["total_failures"] += 1

                    # 将组添加到error_summary
                    error_summary["groups"].append(group_info)

        return error_summary

# 便捷函数


def parse_json_data(data):
    """便捷函数：解析JSON数据并返回处理后的结果

    Args:
        data: JSON数据（字典、列表或JSON字符串）

    Returns:
        解析后的JSON数据
    """
    parser = JSONParser()
    return parser.parse_json_data(data)


def extract_error_summary(data):
    """便捷函数：从解析后的数据中提取错误摘要信息

    Args:
        data: 解析后的JSON数据

    Returns:
        dict: 错误摘要，包含 total_failures 和 groups
    """
    parser = JSONParser()
    return parser.extract_error_summary(data)


if __name__ == "__main__":
    """直接运行脚本时执行的测试代码"""
    import sys

    print("JSON Parser Test Tool")
    print("=" * 50)
    print("使用说明：")
    print("  从文件读取并解析 JSON 数据")
    print("=" * 50)

    # 测试文件路径
    default_json_path = "/opt/coder/statistics/build/aigc_tool/m31660/proj_26020309_9a8cbe44/log/test_netconf_case_2026-02-05_17-12-56_51724.pytestlog.json"
    json_path = sys.argv[1] if len(sys.argv) > 1 else default_json_path

    print(f"测试文件: {json_path}")
    print("=" * 50)

    try:
        # 创建解析器
        parser = JSONParser()

        # 读取 JSON 文件（仅用于测试，实际使用时直接传入数据）
        print("\n1. 读取 JSON 文件...")
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    
        print(f"   ✓ 读取成功")

        # 解析数据
        print("\n2. 解析 JSON 数据...")
        parsed_data = parser.parse_json_data(data)
        print(f"   ✓ 解析完成")

        # 提取错误摘要
        print("\n3. 提取错误摘要...")
        error_summary = parser.extract_error_summary(parsed_data)
        print(error_summary)
        total_failures = error_summary.get('total_failures', 0)
        num_groups = len(error_summary.get('groups', []))
        exit()
        print(f"   ✓ 失败数量: {total_failures}")
        print(f"   ✓ 组数量: {num_groups}")

        # 打印详细错误信息
        if total_failures > 0:
            print("\n4. 错误详情:")
            print("-" * 50)

            for idx, group in enumerate(error_summary.get('groups', []), 1):
                group_id = group.get('group_id', 'unknown')
                description = group.get('description', '')
                failures = group.get('failures', [])

                print(f"\n【组 {idx}】{group_id}")
                if description:
                    print(f"  描述: {description}")
                print(f"  失败数: {len(failures)}")

                for failure in failures:
                    step = failure.get('step', 'unknown')
                    errors = failure.get('errors', [])

                    print(f"\n  步骤: {step}")
                    for i, error in enumerate(errors, 1):
                        print(f"    错误 {i}: {error}")
        else:
            print("\n4. ✅ 测试结果为 PASS，所有测试用例都通过")

        # 可选：输出完整 JSON
        if '--json' in sys.argv or '-j' in sys.argv:
            print("\n" + "=" * 50)
            print("完整 JSON 输出:")
            print("=" * 50)
            result_json = {
                'parsed_data': parsed_data,
                'error_summary': error_summary
            }
            print(json.dumps(result_json, ensure_ascii=False, indent=2))

        print("\n" + "=" * 50)
        print("✓ 测试完成！")

    except FileNotFoundError:
        print(f"\n✗ 错误: 文件不存在: {json_path}")
        print("\n提示：本工具仅用于测试，实际使用时请调用 parse_json_data() 或 extract_error_summary()")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"\n✗ 错误: JSON 解析失败: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 错误: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    print("=" * 50)
    print("测试结束")
