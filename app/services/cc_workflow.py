import asyncio
import os
import json
import getpass
from typing import Optional
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions
)

# 要删除的代理环境变, 避免检索时使用代理
proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]

# 遍历并删除每个环境变量（os.environ 是字典，pop 不存在的键不会报错）
for var in proxy_vars:
    os.environ.pop(var, None)

print("已成功清除代理环境变量")

def escape_all_special_chars(text: str) -> str:
    # 1. json.dumps 会把特殊字符转义 (例如 \n -> \\n)
    # 2. ensure_ascii=False 保证中文不会变成 \uXXXX 乱码
    # 3. [1:-1] 是为了去掉 json.dumps 自动加在首尾的双引号
    return json.dumps(text, ensure_ascii=False)[1:-1]



async def stream_generate_conftest_response(test_point: str, workspace: str = "", task_id: Optional[str] = None):
    """
    生成 conftest.py 的流式响应函数，支持取消操作

    Args:
        test_point: 测试点描述
        workspace: 工作目录
        task_id: 任务ID，用于支持取消操作

    Yields:
        message: Claude Agent SDK 返回的消息对象
    """
    # 导入取消管理器（仅在有 task_id 时使用）
    from app.services.claude_api.task_cancellation_manager import task_cancellation_manager

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

        # 5. 禁用 extended thinking（兼容新旧 SDK）
        max_thinking_tokens=0,

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
            # 在每次收到消息时检查是否被取消
            if task_id and task_cancellation_manager.is_cancelled(task_id):
                print(f"⚠️ 任务 {task_id} 已被取消，中断 conftest 生成")
                # 抛出 CancelledError 来中断生成器
                raise asyncio.CancelledError(f"任务 {task_id} 已被取消")

            # 流式返回对象
            yield message

    except asyncio.CancelledError:
        print(f"⚠️ Conftest 生成任务 {task_id} 已被取消")
        # 重新抛出取消异常，让调用者处理
        raise
    except Exception as e:
        print(f"❌ 发生错误: {e}")




async def stream_test_script_response(test_point: str, workspace: str = "", task_id: Optional[str] = None):
    """
    生成测试脚本的流式响应函数，支持取消操作

    Args:
        test_point: 测试点描述
        workspace: 工作目录
        task_id: 任务ID，用于支持取消操作

    Yields:
        message: Claude Agent SDK 返回的消息对象
    """
    # 导入取消管理器（仅在有 task_id 时使用）
    from app.services.claude_api.task_cancellation_manager import task_cancellation_manager

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

        # 5. 禁用 extended thinking（兼容新旧 SDK）
        max_thinking_tokens=0,

        # system_prompt={"type": "preset", "preset": "claude_code"}
    )

    print("🚀 正在发送请求以触发 Skill...\n")
    prompt = escape_all_special_chars(f"调用 skill: test-script-generate ,生成以下测试点的测试脚本，生成的文件保存到工作区:{workspace}，测试点如下：{test_point}")

    # 处理转义字符
    try:
        async for message in query(
            prompt=prompt,
            options=options
        ):
            # 在每次收到消息时检查是否被取消
            if task_id and task_cancellation_manager.is_cancelled(task_id):
                print(f"⚠️ 任务 {task_id} 已被取消，中断测试脚本生成")
                # 抛出 CancelledError 来中断生成器
                raise asyncio.CancelledError(f"任务 {task_id} 已被取消")

            # 流式返回对象
            yield message

    except asyncio.CancelledError:
        print(f"⚠️ 测试脚本生成任务 {task_id} 已被取消")
        # 重新抛出取消异常，让调用者处理
        raise
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


async def stream_fix_script_response(return_msg: str = "", workspace: str = "", task_id: Optional[str] = None):
    """
    修复脚本的流式响应函数，支持取消操作

    Args:
        return_msg: 脚本运行返回的错误消息
        workspace: 工作目录
        task_id: 任务ID，用于支持取消操作

    Yields:
        message: Claude Agent SDK 返回的消息对象
    """
    # 导入取消管理器（仅在有 task_id 时使用）
    from app.services.claude_api.task_cancellation_manager import task_cancellation_manager

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

        # 5. 禁用 extended thinking（兼容新旧 SDK）
        max_thinking_tokens=0,

        # system_prompt={"type": "preset", "preset": "claude_code"}
    )

    print("🚀 正在发送请求以触发 Skill...\n")
    prompt = escape_all_special_chars(f"请分析脚本运行日志：{return_msg}中的错误，调用 skill: script-fix 修复工作区:{workspace}内的conftest.py和pytest脚本")
    print("========================")
    print(prompt)
    # 处理转义字符
    try:
        async for message in query(
            prompt=prompt,
            options=options
        ):
            # 在每次收到消息时检查是否被取消
            if task_id and task_cancellation_manager.is_cancelled(task_id):
                print(f"⚠️ 任务 {task_id} 已被取消，中断脚本修复")
                # 抛出 CancelledError 来中断生成器
                raise asyncio.CancelledError(f"任务 {task_id} 已被取消")

            # 流式返回对象
            yield message

    except asyncio.CancelledError:
        print(f"⚠️ 脚本修复任务 {task_id} 已被取消")
        # 重新抛出取消异常，让调用者处理
        raise
    except Exception as e:
        print(f"❌ 发生错误: {e}")


if __name__ == "__main__":
    # 使用 async for 来消费上面定义的生成器
    asyncio.run(main())


async def stream_claude_chat_response(prompt: str, workspace: str = "", task_id: Optional[str] = None):
    """
    直接调用 Claude Code SDK 处理用户输入，不预设 prompt 模板

    Args:
        prompt: 用户输入的prompt
        workspace: 工作目录
        task_id: 任务ID，用于支持取消操作

    Yields:
        message: Claude Agent SDK 返回的消息对象
    """
    # 导入取消管理器（仅在有 task_id 时使用）
    from app.services.claude_api.task_cancellation_manager import task_cancellation_manager

    if not workspace:
        current_user = getpass.getuser()
        workspace = f"/home/{current_user}/project"
    print(f"📂 设置工作区为: {workspace}")

    # 确保目录存在
    if not os.path.exists(workspace):
        os.makedirs(workspace, exist_ok=True)

    # 配置选项
    options = ClaudeAgentOptions(
        # 1. 设置当前工作目录 (Current Working Directory)
        cwd=workspace,

        # 2. 启用项目设置加载，不加project, 避免读取项目下的claude.md
        setting_sources=["user"],

        # 3. 权限模式 (自动接受以演示流程)
        permission_mode="bypassPermissions",

        # 4. 允许的工具
        allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],

        # system_prompt={"type": "preset", "preset": "claude_code"}
    )

    print("🚀 正在发送请求到 Claude Code SDK...\n")

    # 不预设prompt模板，直接使用用户输入
    processed_prompt = escape_all_special_chars(prompt)
    print("========================")
    print(f"Prompt: {processed_prompt[:200]}...")
    print("========================")

    try:
        async for message in query(
            prompt=processed_prompt,
            options=options
        ):
            # 在每次收到消息时检查是否被取消
            if task_id and task_cancellation_manager.is_cancelled(task_id):
                print(f"⚠️ 任务 {task_id} 已被取消，中断 Claude SDK 调用")
                # 抛出 CancelledError 来中断生成器
                raise asyncio.CancelledError(f"任务 {task_id} 已被取消")

            # 流式返回对象
            yield message

    except asyncio.CancelledError:
        print(f"⚠️ Claude Chat 任务 {task_id} 已被取消")
        # 重新抛出取消异常，让调用者处理
        raise
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        # 返回错误消息
        yield type('Error', (), {'error': True, 'content': str(e)})()