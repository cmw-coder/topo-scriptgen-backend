import asyncio
import os
import json
import getpass
from claude_agent_sdk import (
    query, 
    ClaudeAgentOptions, 
    AssistantMessage, 
    ToolUseBlock, 
    TextBlock
)

import os

# 要删除的代理环境变, 避免检索时使用代理
proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]

# 遍历并删除每个环境变量（os.environ 是字典，pop 不存在的键不会报错）
for var in proxy_vars:
    os.environ.pop(var, None)

print("已成功清除代理环境变量")

import os

# 设置Anthropic相关环境变量
os.environ["ANTHROPIC_BASE_URL"] = "http://10.144.41.149:4000/"
os.environ["ANTHROPIC_AUTH_TOKEN"] = "xx"

# 验证是否设置成功
print("ANTHROPIC_BASE_URL:", os.getenv("ANTHROPIC_BASE_URL"))
print("ANTHROPIC_AUTH_TOKEN:", os.getenv("ANTHROPIC_AUTH_TOKEN"))

def escape_all_special_chars(text: str) -> str:
    # 1. json.dumps 会把特殊字符转义 (例如 \n -> \\n)
    # 2. ensure_ascii=False 保证中文不会变成 \uXXXX 乱码
    # 3. [1:-1] 是为了去掉 json.dumps 自动加在首尾的双引号
    return json.dumps(text, ensure_ascii=False)[1:-1]



async def stream_generate_conftest_response(test_point: str, workspace: str = ""):
    if not workspace:
        current_user = getpass.getuser()
        workspace = f"/home/{current_user}/project"
    print(f"📂 设置工作区为: {workspace}")

    # 确保目录存在（可选，仅用于演示）
    if not os.path.exists(workspace):
        os.makedirs(workspace, exist_ok=True)

    # 配置选项
    options = ClaudeAgentOptions(
        # 1. 设置当前工作目录 (Current Working Directory)
        # Claude 会在这个目录下执行命令，并在该目录的 .claude/skills 中寻找 Project Skills
        cwd=workspace,

        # 2. 启用项目设置加载，不加project, 避免读取项目下的claude.md
        setting_sources=["user"], 
        
        # 3. 权限模式 (自动接受以演示流程)
        permission_mode="bypassPermissions",
        
        # 4. 允许的工具
        allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],

        # system_prompt={"type": "preset", "preset": "claude_code"}
    )

    print("🚀 正在发送请求以触发 Skill...\n")
    prompt = escape_all_special_chars(f"调用 skill: network-conftest-generator 为以下测试点生成conftest.py文件,生成的文件保存到工作区:{workspace}，工作区内只能有一份conftest.py.: {test_point}")
    print("========================")
    print(prompt)
    # 处理转义字符
    try:
        async for message in query(
            prompt=prompt, 
            options=options
        ):
            # 流式返回对象
            yield message

    except Exception as e:
        print(f"❌ 发生错误: {e}")




async def stream_test_script_response(test_point: str, workspace: str = ""):
    if not workspace:
        current_user = getpass.getuser()
        workspace = f"/home/{current_user}/project"
    print(f"📂 设置工作区为: {workspace}")

    # 确保目录存在（可选，仅用于演示）
    if not os.path.exists(workspace):
        os.makedirs(workspace, exist_ok=True)

    # 配置选项
    options = ClaudeAgentOptions(
        # 1. 设置当前工作目录 (Current Working Directory)
        # Claude 会在这个目录下执行命令，并在该目录的 .claude/skills 中寻找 Project Skills
        cwd=workspace,

        # 2. 启用项目设置加载，不加project, 避免读取项目下的claude.md
        setting_sources=["user"], 
        
        # 3. 权限模式 (自动接受以演示流程)
        permission_mode="bypassPermissions",
        
        # 4. 允许的工具
        allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],

        # system_prompt={"type": "preset", "preset": "claude_code"}
    )

    print("🚀 正在发送请求以触发 Skill...\n")
    prompt = escape_all_special_chars(f"调用 skill: test_script_generate ,生成以下测试点的测试脚本，生成的文件保存到工作区:{workspace}，测试点如下：{test_point}")

    # 处理转义字符
    try:
        async for message in query(
            prompt=prompt, 
            options=options
        ):
            # 流式返回对象
            yield message

    except Exception as e:
        print(f"❌ 发生错误: {e}")






async def main():
    print("--- 开始接收流 ---")
    test_point = """测试BGP IPv4地址族发送的Add-Path优选路由的最大条数 
    前置背景： 
        3台设备DUT1分别和DUT2、DUT3建立直连IBGP邻居，DUT2引入静态路由 
    测试步骤： 
        1、DUT1和DUT3使能Add-Path能力，DUT1上设置BGPIPv4地址族发送的Add-Path优选路由的最大条数，检查DUT3上收到Add-Path路由，路由条数正确 
        2、DUT1修改Add-Path发送路由条数参数，检查DUT3上收到Add-Path路由，路由条数正确。
"""
    # 使用 async for 来消费上面定义的生成器
    async for msg in stream_test_script_response(test_point=test_point, workspace="C:\\Users\\m31660\\Desktop\\conftest_generate"):
        # 这里的 msg 就是上面 yield 出来的对象
        print(f"📥 收到: {type(msg).__name__}")
        print(msg) 


async def stream_fix_script_response(return_msg: str = "",workspace: str = ""):
    if not workspace:
        current_user = getpass.getuser()
        workspace = f"/home/{current_user}/project"
    print(f"📂 设置工作区为: {workspace}")

    # 确保目录存在（可选，仅用于演示）
    if not os.path.exists(workspace):
        os.makedirs(workspace, exist_ok=True)

    # 配置选项
    options = ClaudeAgentOptions(
        # 1. 设置当前工作目录 (Current Working Directory)
        # Claude 会在这个目录下执行命令，并在该目录的 .claude/skills 中寻找 Project Skills
        cwd=workspace,

        # 2. 启用项目设置加载，不加project, 避免读取项目下的claude.md
        setting_sources=["user"], 
        
        # 3. 权限模式 (自动接受以演示流程)
        permission_mode="bypassPermissions",
        
        # 4. 允许的工具
        allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],

        # system_prompt={"type": "preset", "preset": "claude_code"}
    )

    print("🚀 正在发送请求以触发 Skill...\n")
    prompt = escape_all_special_chars(f"请分析脚本运行日志：{return_msg}中的错误，调用 skill: script_fix 修复工作区:{workspace}内的conftest.py和pytest脚本")
    print("========================")
    print(prompt)
    # 处理转义字符
    try:
        async for message in query(
            prompt=prompt, 
            options=options
        ):
            # 流式返回对象
            yield message

    except Exception as e:
        print(f"❌ 发生错误: {e}")


if __name__ == "__main__":
    # 使用 async for 来消费上面定义的生成器
    asyncio.run(main())