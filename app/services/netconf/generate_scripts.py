"""
NETCONF 脚本生成模块

提供 NETCONF 测试脚本生成功能
遍历 netconf_output 文件夹下的每个子文件夹，调用 claude_agent_sdk 生成测试脚本
"""

import os
import json
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions
from app.core.config import settings
from app.services.netconf.prepare_materials import get_output_dir
from app.services.claude_api.task_logger import task_logger
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage


# ==================== 工具函数 ====================

def escape_all_special_chars(text: str) -> str:
    """转义所有特殊字符

    Args:
        text: 待转义的文本

    Returns:
        转义后的文本
    """
    # 1. json.dumps 会把特殊字符转义 (例如 \n -> \\n)
    # 2. ensure_ascii=False 保证中文不会变成 \uXXXX 乱码
    # 3. [1:-1] 是为了去掉 json.dumps 自动加在首尾的双引号
    return json.dumps(text, ensure_ascii=False)[1:-1]


def setup_agent_environment():
    """设置 Claude Agent 环境变量"""
    # 删除代理环境变量，避免检索时使用代理
    proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
    for var in proxy_vars:
        os.environ.pop(var, None)

    # 设置 Anthropic 相关环境变量
    os.environ["ANTHROPIC_BASE_URL"] = "http://10.144.41.149:4000/"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "xx"
    os.environ["ANTHROPIC_LOG"] = "debug"


# ==================== 生成 NETCONF 测试脚本 ====================

async def generate_netconf_scripts(
    task_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    遍历 netconf_output 文件夹生成 NETCONF 测试脚本

    此函数会：
    1. 遍历 netconf_output 文件夹下的每个子文件夹
    2. 对每个子文件夹调用 claude_agent_sdk
    3. 在 prompt 中写明工作区路径
    4. 调用 netconf_generator 子 agent 生成测试脚本

    Args:
        task_id: 任务ID
        workspace: 工作目录（可选，默认使用 settings.get_work_directory()）

    Returns:
        包含执行结果的字典
    """
    try:


        # 确定工作目录
        if not workspace:
            workspace = settings.get_work_directory()


        # 获取 netconf_output 目录
        output_dir = get_output_dir()

        # 检查 netconf_output 目录是否存在
        if not os.path.exists(output_dir):
            error_msg = f"netconf_output 目录不存在: {output_dir}，请先调用准备依赖材料接口"
            return {
                "return_code": "404",
                "return_info": error_msg
            }

        # 遍历 netconf_output 目录下的所有子文件夹
        subdirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]

        if not subdirs:
            error_msg = f"netconf_output 目录下没有子文件夹: {output_dir}"
            return {
                "return_code": "404",
                "return_info": error_msg
            }


        # 为每个子文件夹生成测试脚本（异步并发，最多同时2个）
        all_generated_scripts = []
        success_count = 0
        failed_count = 0

        # 使用 Semaphore 限制并发数为 2
        semaphore = asyncio.Semaphore(1)

        async def process_subdir(subdir):
            """处理单个子文件夹"""
            async with semaphore:

                # 调用子 agent 生成脚本
                result = await _generate_scripts_for_subdir(
                    task_id=task_id,
                    subdir=str(subdir)
                )

                if result.get("return_code") == "200":
                    scripts = result.get("generated_scripts", [])
                    return subdir.name, scripts, True, None
                else:
                    error_info = result.get('return_info')
                    return subdir.name, [], False, error_info

        # 并发处理所有子文件夹（最多同时2个）
        tasks = [process_subdir(subdir) for subdir in subdirs]
        results = await asyncio.gather(*tasks)

        # 汇总结果
        for subdir_name, scripts, success, error_info in results:
            if success:
                all_generated_scripts.extend(scripts)
                success_count += 1
            else:
                failed_count += 1

        summary = f"成功: {success_count}, 失败: {failed_count}, 总脚本数: {len(all_generated_scripts)}"

        return {
            "return_code": "200",
            "return_info": f"NETCONF 脚本生成完成，{summary}",
            "generated_scripts": all_generated_scripts,
            "success_count": success_count,
            "failed_count": failed_count
        }

    except Exception as e:
        error_msg = f"生成 NETCONF 脚本失败: {str(e)}"

        return {
            "return_code": "500",
            "return_info": error_msg
        }


async def _generate_scripts_for_subdir(
    task_id: str,
    subdir: str
) -> Dict[str, Any]:
    """
    为单个子文件夹生成 NETCONF 测试脚本

    Args:
        task_id: 任务ID
        subdir: 子文件夹的完整路径

    Returns:
        包含执行结果的字典
    """
    # 从 subdir 路径中提取子文件夹名称
    subdir_name = os.path.basename(subdir)

    try:

        # 配置 Claude Agent 选项
        options = ClaudeAgentOptions(
            cwd=subdir,  # 使用子文件夹作为工作区
            setting_sources=["user"],  # 不加载 project 设置
            permission_mode="bypassPermissions",
            allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],
        )
        
        # 构造 prompt - 调用 netconf_generator 子 agent
        prompt = escape_all_special_chars(
            f"""调用 子agent : netconf_generator , 在工作区 {subdir} 生成 NETCONF 测试脚本"""
        )
        # 调用 Claude Agent
        message_count = 0
        async for message in query(prompt=prompt, options=options):
            message_count += 1
            if isinstance(message, ResultMessage):
                task_logger.write_log(task_id, f"✓ 生成总结{message.result}")
            if message_count % 10 == 0:  # 每10条消息记录一次
                task_logger.write_log(task_id, f"{subdir_name} 已处理 {message_count} 条消息")

        task_logger.write_log(task_id, f"{subdir_name} skill 执行完成，共处理 {message_count} 条消息")

        # 查找生成的测试脚本文件
        generated_scripts = []
        for root, dirs, files in os.walk(subdir):
            for file in files:
                if file.startswith('test_') and file.endswith('.py'):
                    generated_scripts.append(os.path.join(root, file))


        return {
            "return_code": "200",
            "return_info": f"{subdir_name} 脚本生成完成，共 {len(generated_scripts)} 个文件",
            "generated_scripts": generated_scripts
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"{subdir_name} 生成脚本失败: {str(e)}"

        return {
            "return_code": "500",
            "return_info": error_msg,
            "generated_scripts": []
        }


# ==================== 测试代码 ====================

if __name__ == "__main__":
    import asyncio

    # 设置环境变量
    setup_agent_environment()

    async def test_generate_netconf_scripts():
        """测试 generate_netconf_scripts 函数"""
        print("===== 开始测试 generate_netconf_scripts =====")

        # 生成测试任务ID
        import time
        task_id = f"test_{int(time.time())}"

        print(f"任务ID: {task_id}")

        # 获取 netconf_output 目录
        output_dir = get_output_dir()
        print(f"netconf_output 目录: {output_dir}")

        # 检查目录是否存在
        if os.path.exists(output_dir):
            subdirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]
            print(f"找到 {len(subdirs)} 个子文件夹:")
            for subdir in subdirs:
                print(f"  - {subdir.name}")
        else:
            print(f"⚠️  netconf_output 目录不存在: {output_dir}")
            print("请先运行 prepare_materials 生成测试数据")

        # 调用 generate_netconf_scripts，不传入 workspace
        result = await generate_netconf_scripts(task_id=task_id)

        print(f"\n返回码: {result.get('return_code')}")
        print(f"返回信息: {result.get('return_info')}")

        if result.get("return_code") == "200":
            success_count = result.get("success_count", 0)
            failed_count = result.get("failed_count", 0)
            generated_scripts = result.get("generated_scripts", [])

            print(f"\n成功: {success_count}, 失败: {failed_count}")
            print(f"生成的脚本文件:")
            for script in generated_scripts:
                print(f"  - {script}")

            # 显示日志文件路径
            log_file_path = task_logger.get_log_file_path(task_id)
            print(f"\n日志文件: {log_file_path}")

            print("\n✓ 测试成功！")
        else:
            print("\n✗ 测试失败！")

        print("===== 测试结束 =====")

    # 运行测试
    asyncio.run(test_generate_netconf_scripts())
