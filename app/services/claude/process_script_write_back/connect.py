# complete_code.py

import os
import re
import asyncio
import shutil
import threading
import time
import datetime
import pandas as pd
import subprocess
import resource
from typing import List, Dict, Any
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, AssistantMessage, ResultMessage

# --- 获取当前脚本所在目录 ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 添加缺失的函数定义 ---
class ThreadSafeLogger:
    """线程安全日志记录器：既打印到控制台，也写入文件"""
    def __init__(self, log_file_path: str):
        self.log_file_path = log_file_path
        self.lock = threading.Lock()
        # 确保目录存在
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] [{level}] {message}"

        with self.lock:
            # 打印到控制台
            print(log_message)

            # 追加写入文件
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(log_message + "\n")

    def error(self, message: str):
        self.log(message, "ERROR")


async def run_claude_step(
    client: ClaudeSDKClient,
    prompt: str,
    task_start_time: float,
    timeout_seconds: int,
    logger: ThreadSafeLogger,
) -> Dict[str, Any]:
    result_data = {'success': False, 'error': None, 'cost': 0, 'analysis': ''}

    try:
        logger.log("=== Claude step start ===")
        logger.log(f"Prompt:\n{prompt}\n")

        await client.query(prompt)
        logger.log("已发送 query，开始接收响应...\n")

        response_parts = []

        async for message in client.receive_response():
            msg_type = type(message).__name__
            logger.log(f"[message] type={msg_type}")

            # 打印整个 message 对象，便于调试（可选，日志会比较多）
            # logger.log(f"[message raw] {message!r}")

            if isinstance(message, AssistantMessage):
                # 遍历所有内容块
                for block in message.content:
                    # 先打印 block 的原始结构
                    logger.log(f"[assistant block raw] {block!r}")
                    # 如果有 __dict__，打印字段
                    if hasattr(block, "__dict__"):
                        logger.log(f"[assistant block dict] {block.__dict__}")

                    # 可能的工具调用（伪字段，根据 SDK 实际调整）
                    block_type = getattr(block, "type", None)
                    if block_type == "tool_use":
                        name = getattr(block, "name", None)
                        args = getattr(block, "input", None)
                        logger.log(f"[tool_use] name={name} args={args}")
                    elif block_type == "tool_result":
                        name = getattr(block, "name", None)
                        output = getattr(block, "output", None)
                        logger.log(f"[tool_result] name={name} output={output}")

                    # 文本内容（对话/解释）
                    if hasattr(block, "text"):
                        text = block.text
                        response_parts.append(text)
                        logger.log(f"[assistant text]\n{text}\n")

            elif isinstance(message, ResultMessage):
                result_data['success'] = not message.is_error
                result_data['cost'] = message.total_cost_usd
                logger.log(
                    f"[result] success={not message.is_error}, "
                    f"cost={message.total_cost_usd}, "
                    f"is_error={message.is_error}"
                )
                if message.is_error:
                    result_data['error'] = message.result
                    logger.log(f"[error result]\n{message.result}\n")

        result_data['analysis'] = ''.join(response_parts)
        logger.log("=== Claude step end ===\n")

    except Exception as e:
        result_data['error'] = str(e)
        logger.log(f"[exception] {e!r}")

    return result_data

async def process_convert_folder(folder_path: str, timeout_minutes: int) -> Dict[str, Any]:
    """
    处理单个文件夹的函数生成任务
    """
    start_time = time.time()  
    # 确保路径是绝对路径
    if not os.path.isabs(folder_path):
        folder_path = os.path.abspath(folder_path)

    function_path = os.path.join(folder_path, "function.py")

    folder_name = os.path.basename(folder_path)
    result = {
        'folder': folder_name,
        'success': False,
        'cost': 0,
        'duration': 0,
        'error': None
    }

    try:
        # 检查文件夹是否存在
        if not os.path.exists(folder_path):
            result['error'] = f"文件夹不存在: {folder_path}"
            return result
        
        # 检查指导文件是否存在
        guide_file = os.path.join(folder_path, "SKILL.md")
        if not os.path.exists(guide_file):
            result['error'] = f"指导文件不存在: {guide_file}"
            return result
        
        print(f"开始处理文件夹: {folder_name}")
        print(f"完整路径: {folder_path}")

        # 配置Claude客户端
        options = ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code"},
            allowed_tools=["Bash", "Edit", "Glob", "Grep", "Read", "Write"],
            permission_mode="bypassPermissions", 
            cwd=folder_path,
            max_turns = 20
        )
        log_path = os.path.join(folder_path, "claude_run.log")
        logger = ThreadSafeLogger(log_path)
        # 执行函数生成
        async with ClaudeSDKClient(options=options) as client:
            prompt = "按照文件 @SKILL.md指导处理"
            api_result = await run_claude_step(
                client, 
                prompt, 
                start_time, 
                timeout_minutes * 60, 
                logger
            )
        
            if api_result.get('success'):
                result['success'] = True
                result['cost'] = api_result.get('cost', 0)
                print(f"✅ 处理成功: {folder_name}")
            else:
                result['error'] = api_result.get('error', 'API调用失败')
                print(f"❌ 处理失败: {folder_name} - {result['error']}")
                
    except Exception as e:
        result['error'] = str(e)
        print(f"⚠️  处理异常: {folder_name} - {e}")
    
    result['duration'] = time.time() - start_time

    with open(function_path, 'r', encoding='utf-8') as f:
        cont = f.read()
        if cont:
            logger.log("生成的函数文件不为空")
        else:
            logger.log("生成的函数文件为空")

    return result



if __name__ == "__main__":
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
    
    print(f"当前脚本路径: {__file__}")
    print(f"脚本所在目录: {SCRIPT_DIR}")
    
    # 使用相对路径 - 多种选择
    
    # 方案: 相对于脚本目录的路径
    relative_path = "../"  # 当前目录下的func_convert文件夹
    target_folder = os.path.join(SCRIPT_DIR, relative_path)

    # 执行处理
    try:
        result = asyncio.run(process_convert_folder(target_folder, 5))
        print(f"处理结果: {result}")
    except KeyboardInterrupt:
        print("\n用户中断操作")
    except Exception as e:
        print(f"程序执行出错: {e}")