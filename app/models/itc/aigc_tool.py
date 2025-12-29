import argparse
import requests
import os
import json
from datetime import datetime
import shutil
import getpass
import stat
import base64
import re
from pprint import pprint
import glob
import queue
import threading

class AIGCClient:
    def __init__(self, base_url="http://10.111.8.68:8000"):
        self.base_url = base_url

    def decode_base64_in_json(self, data):
        """递归解码 JSON 中的 Base64 编码字段
        AI_FingerPrint_UUID: 20251128-wH7yz8Qk
        """
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
        """检查数据结构中是否包含FAIL或ERROR信息
        AI_FingerPrint_UUID: 20251128-wH7yz8Qk
        """
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
        保留FAIL和ERROR信息，过滤PASS信息
        AI_FingerPrint_UUID: 20251128-wH7yz8Qk
        """
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
    
    def deploy_environment(self, topofile, versionpath=None, devicetype=None):
        if not topofile:
            return {"return_code": "400", "return_info": "请求参数为空"}
        url = f"{self.base_url}/aigc/deploy"
        topofile=topofile.replace('\\', '/')
        versionpath=versionpath.replace('\\', '/')

        data = {"topofile": f"{topofile}"}
        if versionpath:
            data["versionpath"] = f"{versionpath}"
        if devicetype:
            data["devicetype"] = f"{devicetype}"
        try:
            print(data)
            response = requests.post(url, json=data, proxies={"http": None, "https": None})
            return response.json()
            # return {"return_code": "200", "return_info": "环境部署OK", "result": "10.123.1.1"}
        except Exception as e:
            return {"return_code": "500", "return_info": f"环境部署失败,错误详情：{str(e)}"}
    def _get_executorip_from_config(self):
        # return "10.144.42.25", None, None
        config_path = os.path.expanduser("~/project/.aigc_tool/aigc.json")
        
        # 检查配置文件是否存在
        if not os.path.exists(config_path):
            return None, f"运行环境未配置，请退出重新输入topx等文件配置环境后运行", None
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                # 读取前检查文件内容是否为空
                content = f.read().strip()
                if not content:
                    return None, f"配置文件为空: {config_path}", None
                    
                cfg = json.loads(content)
                
                # 检查配置是否是字典类型
                if not isinstance(cfg, dict):
                    return None, f"配置文件内容格式错误: 应为字典类型", None
                
                # 获取executorip字段
                executorip = cfg.get("exec_ip")
                conftestFile = cfg.get("conftest_file")
                # 检查executorip是否存在且非空
                if not executorip:
                    return None, f"配置文件中未找到 executorip 字段", None
                
                # 检查executorip是否为字符串
                if not isinstance(executorip, str):
                    return None, f"executorip 应为字符串类型", None
                
                # 检查IP地址格式是否有效
                import re
                ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
                if not re.match(ip_pattern, executorip):
                    return None, f"目前组网正在配置中，请稍后再试", None
                
                # 验证IP地址各段数字是否在0-255之间
                octets = executorip.split('.')
                for octet in octets:
                    if not 0 <= int(octet) <= 255:
                        return None, f"IP地址段超出范围(0-255): {executorip}", None
                
                return executorip, None, conftestFile
                
        except json.JSONDecodeError as e:
            return None, f"配置文件JSON解析失败: {str(e)}", None
        except UnicodeDecodeError as e:
            return None, f"配置文件编码错误(应为UTF-8): {str(e)}", None
        except Exception as e:
            return None, f"读取配置文件失败: {str(e)}", None
            
    def set_permissions_recursive(self, path, mode):
        """递归设置目录及其所有内容的权限"""
        for root, dirs, files in os.walk(path):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                os.chmod(dir_path, mode)
            for file_name in files:
                file_path = os.path.join(root, file_name)
                os.chmod(file_path, mode)
        # 最后设置顶层目录的权限
        os.chmod(path, mode)

    def replace_newlines(self, obj):
        """
        递归遍历对象，把字符串里的 '\n' 转成真实换行
        """
        if isinstance(obj, dict):
            return {k: self.replace_newlines(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.replace_newlines(v) for v in obj]
        elif isinstance(obj, str):
            return obj.replace('\\n', '\r\n')
        else:
            return obj

    def run_script(self, scriptspath):
        if not scriptspath:
            return {"return_code": "400", "return_info": "请求参数为空"}

        # 检查本地路径是否存在
        if not os.path.exists(scriptspath):
            return {"return_code": "404", "return_info": f"脚本路径不存在: {scriptspath}"}

        executorip, err, conftestFile = self._get_executorip_from_config()
        # if err:
        #     return {"return_code": "400", "return_info": err}

        if not conftestFile:
            # 脚本所在目录
            base_dir = os.path.dirname(os.path.abspath(scriptspath))

            # 先在本目录匹配 *conftest*.py
            pattern = os.path.join(base_dir, "*conftest*.py")
            matches = glob.glob(pattern)
            if matches:
                conftestFile = matches[0]          # 取第一个命中
            else:
                # 本目录没有，再查上一级目录
                parent_dir = os.path.dirname(base_dir)
                pattern = os.path.join(parent_dir, "*conftest*.py")
                matches = glob.glob(pattern)
                if matches:
                    conftestFile = matches[0]
                else:
                    return {"return_code": "404",
                            "return_info": "未找到任何满足 *conftest*.py 的文件（已检索脚本同级及上级目录）"} 
            # 2. 读旧配置（若无则新建空字典）
            run_config_path = "~/project/.aigc_tool/aigc.json"
            if os.path.isfile(run_config_path):
                with open(run_config_path, encoding="utf-8") as f:
                    cfg = json.load(f)

                # 3. 仅更新 conftest_file 字段
                cfg["conftest_file"] = conftestFile
                with open(run_config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=4, ensure_ascii=False)

        try:
            # 目标目录（部署服务器本地路径）
            username = getpass.getuser()
            target_dir = "/opt/coder/statistics/build/aigc_tool/"+username
            os.makedirs(target_dir, exist_ok=True)
            py_files = glob.glob(os.path.join(target_dir, "*.py"))
            # 删除所有.py文件
            for py_file in py_files:
                try:
                    if "aigc_tool" in str(py_file):
                        continue
                    os.remove(py_file)
                    print(f"已删除: {py_file}")
                except Exception as e:
                    print(f"删除文件 {py_file} 失败: {str(e)}")
                    continue
            # 确定目标文件路径
            script_name = os.path.basename(scriptspath)
            target_path = os.path.join(target_dir, script_name)
            conftest_name = os.path.join(target_dir, "conftest.py")

            # 如果是目录，拷贝整个目录；否则拷贝文件
            shutil.copy2(conftestFile, conftest_name)
            shutil.copy2(scriptspath, target_path)
            # 确保有__init__.py文件（如果需要的话）
            init_file = os.path.join(target_dir, "__init__.py")
            if not os.path.exists(init_file):
                open(init_file, 'a').close()
            # 递归设置 777 权限
            self.set_permissions_recursive(target_dir, 0o777)  # 等同于 0o777
            # 转换成 UNC 路径
            # 注意：在 Python 字符串里必须转义 \，最终结果是 Windows 能识别的 \\
            unc_path = f"\\\\10.144.41.149\\webide\\aigc_tool\\{username}"
            unc_path=unc_path.replace('\\', '/')

            # 请求参数
            url = f"{self.base_url}/aigc/run"
            data = {
                "scriptspath": f"{unc_path}",        # 使用UNC路径传到接口
                "executorip": f"{executorip}"
            }
            result_q = queue.Queue(maxsize=1)

            def _call_bg():
                try:
                    resp = requests.post(
                        f"{self.base_url}/aigc/run",
                        json=data,
                        proxies={"http": None, "https": None},
                        timeout=600          # 允许 5 min 长耗时
                    )
                    result_q.put(resp.json())
                except Exception as e:
                    result_q.put({"return_code": "500", "return_info": f"后台请求异常：{e}"})

            bg_thread = threading.Thread(target=_call_bg, daemon=True)
            bg_thread.start()
            print("start thread")
            # 2. 主线程负责心跳
            heartbeat_cnt = 0
            while True:
                try:
                    # 每 10 s 轮询一次
                    result = result_q.get(timeout=10)
                    # 取到了最终结果，进行后续过滤/落盘逻辑
                    break
                except queue.Empty:
                    # 10 s 内没拿到结果，发心跳
                    heartbeat_cnt += 1
                    print(f"脚本正在远端执行中，已等待 {heartbeat_cnt * 10} s …")
            # # 调用接口（这里用模拟返回，如需真实调用取消下面注释）
            # response = requests.post(url, json=data, proxies={"http": None, "https": None})
            # result = response.json()

            # 应用过滤逻辑到返回的结果
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                os.makedirs(f'/home/{username}/project/RUN_LOG', exist_ok=True)
                log_file=f'/home/{username}/project/RUN_LOG/{script_name}_{timestamp}.json'
                # 创建结果的深拷贝以避免修改原始数据
                if result.get('return_code') == '200':
                    return_info = result.get('return_info', {})
                else:
                    with open(log_file, 'a+') as f:
                        f.write(json.dumps(result, ensure_ascii=False)+'\r\n')
                    return result
                import copy
                result_copy = copy.deepcopy(return_info)

                # 检查返回结果是否包含需要过滤的数据
                # 首先检查是否为JSON字符串，如果是则先解析
                if isinstance(result_copy, str):
                    try:
                        result_copy = json.loads(result_copy)
                    except (json.JSONDecodeError, ValueError) as e:
                        with open(log_file, 'a+') as f:
                            f.write(result_copy+'\r\n')
                        print(f"JSON字符串解析失败: {e}")
                        return result_copy

                # 现在检查是否为字典类型
                if isinstance(result_copy, dict):
                    # 第一步：先进行完整的Base64解码
                    self.decode_base64_in_json(result_copy)

                    # 第二步：应用过滤逻辑
                    filtered_result = self.filter_pass_results(result_copy)
                    # 如果过滤后为空，返回解码后的原始结果
                    if filtered_result is None:
                        with open(log_file, 'a+') as f:
                            f.write(result_copy+'\r\n')
                        return result_copy
                    else:
                        with open(log_file, 'a+') as f:
                            text = json.dumps(filtered_result, ensure_ascii=False, indent=4)
                            # 把 JSON 里的转义的 "\n" 转成真实换行
                            text = text.replace("\\n", "\r\n")
                            f.write(text)

                        return filtered_result
                else:
                    with open(log_file, 'a+') as f:
                        f.write(result_copy+'\r\n')
                    return result_copy
            except Exception as e:
                # 如果过滤过程出错，返回原始结果
                print(f"过滤结果时出错，返回原始结果: {str(e)}")
                return result

            # return {
            #     "return_code": "200",
            #     "return_info": "脚本已拷贝并执行OK",
            #     "result": unc_path
            # }

        except Exception as e:
            return {
                "return_code": "500",
                "return_info": f"脚本执行失败，错误详情：{str(e)}"
            }
    
    def undeploy_environment(self):
        executorip, err, conftestFile = self._get_executorip_from_config()
        if err:
            return {"return_code": "400", "return_info": err}
        url = f"{self.base_url}/aigc/undeploy"
        data = {"executorip": f"{executorip}"}
        try:
            print(data)
            response = requests.post(url, json=data,proxies={"http": None, "https": None})
            return response.json()
            # return {"return_code": "200", "return_info": "环境释放OK"}
        except Exception as e:
            return {"return_code": "500", "return_info": f"环境释放失败,错误详情：{str(e)}"}
    
    def restore_configuration(self):
        executorip, err, conftestFile = self._get_executorip_from_config()
        if err:
            return {"return_code": "400", "return_info": err}
        url = f"{self.base_url}/aigc/restoreconfiguration"
        data = {"executorip": f"{executorip}"}
        print(data)
        try:
            response = requests.post(url, json=data, proxies={"http": None, "https": None})
            return response.json()
        except Exception as e:
            return {"return_code": "500", "return_info": f"配置回滚失败,错误详情：{str(e)}"}

def main():
    parser = argparse.ArgumentParser(description="AIGC 环境管理工具")
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # deploy 子命令
    parser_deploy = subparsers.add_parser("deploy", help="部署测试环境")
    parser_deploy.add_argument("--topofile", required=True, help="topox 文件路径")
    parser_deploy.add_argument("--versionpath", help="版本路径，可选")
    parser_deploy.add_argument("--devicetype", help="设备类型")

    # run 子命令
    parser_run = subparsers.add_parser("run", help="执行脚本")
    parser_run.add_argument("--scriptspath", required=True, help="脚本路径")

    # undeploy 子命令
    parser_undeploy = subparsers.add_parser("undeploy", help="释放测试环境")

    # restore 子命令
    parser_restore = subparsers.add_parser("restore", help="回滚配置")

    args = parser.parse_args()

    client = AIGCClient()

    if args.command == "deploy":
        result = client.deploy_environment(args.topofile, args.versionpath, args.devicetype)
    elif args.command == "run":
        result = client.run_script(args.scriptspath)
    elif args.command == "undeploy":
        result = client.undeploy_environment()
    elif args.command == "restore":
        result = client.restore_configuration()
    else:
        parser.print_help()
        return

    print(result)

if __name__ == "__main__":
    main()
