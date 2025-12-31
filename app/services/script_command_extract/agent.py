import os 
import json
import re
import base64
import traceback
from typing import Any, Dict, List, Union
from pathlib import Path
import shutil
from log_decode import JSONProcessor
from log_process import LOGPROCESS

class ExtractCommandAgent(object):
    def __init__(self, input_path: str):
        self.input_path = input_path

    def get_log_command_info(self):
        if not os.path.isdir(self.input_path):
            print(f"这不是一个文件夹: {self.input_path}")
            return
        print("11")
        folder_name = "local"
        # 获取脚本文件所在的绝对路径
        script_path = os.path.abspath(__file__)

        # 获取脚本所在目录
        current_dir = os.path.dirname(script_path)

        folder_path = os.path.join(current_dir, folder_name)
        if os.path.exists(folder_path):
            print("local文件夹存在先删除")
            shutil.rmtree(folder_path) 
        try:
            os.makedirs(folder_path, exist_ok=True)  # 使用 os.makedirs
            absolute_path = os.path.abspath(folder_path)
            print(f"文件夹已创建/确认存在: {absolute_path}")
        except Exception as e:
            print(f"创建文件夹失败: {e}")
            traceback.print_exc()
            return 

        for root, dirs, files in os.walk(self.input_path):
            for file in files:
                if file.endswith('.pytestlog.json'):
                    input_file = os.path.join(root, file)
                    filename = os.path.basename(file)
                    output_file = os.path.join(folder_path, filename)
                    decode_processor = JSONProcessor(input_file,output_file)
                    decode_data = decode_processor.process()
        log_processor = LOGPROCESS(folder_path)
        log_command_info = log_processor.log_file_process()
        return log_command_info

if __name__ == "__main__":
    path = "/home/y28677/w31815/tmps/1/"
    agent = ExtractCommandAgent(path)
    res = agent.get_log_command_info()
    print(res)
    for key,value in res.items():
        with open(key, 'w', encoding='utf-8') as f:
            f.write(value)
