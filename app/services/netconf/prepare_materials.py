"""
NETCONF 依赖材料准备模块

提供 NETCONF 生成脚本所需的依赖材料准备功能
通过调用 Claude Agent skill 自动准备材料
"""

import os
import json
import logging
import getpass
from typing import Dict, Any, Optional

from claude_agent_sdk import query, ClaudeAgentOptions
from app.core.config import settings
from app.services.claude_api.task_logger import task_logger
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage

logger = logging.getLogger(__name__)


# ==================== Claude Agent 配置 ====================

def escape_all_special_chars(text: str) -> str:
    """转义所有特殊字符

    Args:
        text: 待转义的文本

    Returns:
        转义后的文本
    """
    # 1. json.dumps 会把特殊字符转义 (例如 \n -> \\n)
    # 2. ensure_ascii=False 保证中文不会变成 \\uXXXX 乱码
    # 3. [1:-1] 是为了去掉 json.dumps 自动加在首尾的双引号
    return json.dumps(text, ensure_ascii=False)[1:-1]


# ==================== 工具函数 ====================

def get_output_dir() -> str:
    """获取 netconf_output 目录路径

    Returns:
        netconf_output 目录的绝对路径
    """
    work_dir = settings.get_work_directory()
    output_dir = os.path.join(work_dir, "netconf_output")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def get_netconf_output_dir() -> str:
    """获取 NETCONF output 目录路径（别名函数）

    Returns:
        NETCONF output 目录的绝对路径（与 get_output_dir 相同）
    """
    return get_output_dir()


# ==================== 调用 Claude Agent Skill ====================

async def call_netconf_material_preparation_skill(
    task_id: str,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    调用 netconf-test-script-generation-material-preparation skill

    此 skill 会自动执行以下操作：
    - 将 Word API 文档转换为 Markdown 格式，生成 converted_docs/ 目录
    - 将 YANG 文件转换为 YIN 格式，生成对应的转换目录
    - 分析文档结构，生成 netconf_output/ 目录及子模块

    Args:
        task_id: 任务ID
        workspace: 工作目录路径（可选，默认使用 settings.get_work_directory()）

    Returns:
        包含执行结果的字典
    """
    try:
        # 写入开始日志
        task_logger.write_log(task_id, "NETCONF 材料准备")
        task_logger.write_log(task_id, f"开始调用 netconf-test-script-generation-material-preparation skill")
        logger.info(f"Task {task_id}: 开始调用 netconf-test-script-generation-material-preparation skill")

        # 设置环境 - 从 netconf_workflow 导入避免重复定义
        from app.services.netconf.netconf_workflow import setup_agent_environment
        setup_agent_environment()

        # 确定工作目录
        if not workspace:
            workspace = settings.get_work_directory()

        task_logger.write_log(task_id, f"工作区为: {workspace}")

        # 确保目录存在
        if not os.path.exists(workspace):
            os.makedirs(workspace, exist_ok=True)

        # 配置 Claude Agent 选项
        options = ClaudeAgentOptions(
            cwd=workspace,
            setting_sources=["user"],  # 不加载 project 设置
            permission_mode="bypassPermissions",
            allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],
            max_thinking_tokens=0,
        )

        # 构造 prompt
        prompt = escape_all_special_chars(f"""在工作区 {workspace} 调用 skill: netconf-test-script-generation-material-preparation,

            此 skill 会自动执行以下操作：
            - 将 Word API 文档转换为 Markdown 格式，生成 `converted_docs/` 目录
            - 将 YANG 文件转换为 YIN 格式，生成对应的转换目录
            - 分析文档结构，生成 `netconf_output/` 目录及子模块"""
        )

        task_logger.write_log(task_id, "发送请求到 Claude Agent...")
        logger.info(f"Task {task_id}: 发送请求到 Claude Agent")

        # 调用 Claude Agent
        message_count = 0

        async for message in query(prompt=prompt, options=options):
            message_count += 1
            # 写入详细日志
            if isinstance(message, ResultMessage):
                task_logger.write_log(task_id, f"✓ 修复总结{message.result}")


        task_logger.write_log(task_id, f"skill 执行完成，共处理 {message_count} 条消息")
    
        # 检查生成的目录
        converted_docs_dir = os.path.join(workspace, "converted_docs")
        netconf_output_dir = os.path.join(workspace, "netconf_output")

        generated_dirs = []
        if os.path.exists(converted_docs_dir):
            generated_dirs.append("converted_docs/")

        # netconf_output 文件夹必须存在
        if not os.path.exists(netconf_output_dir):
            error_msg = f"材料准备失败：未生成 netconf_output 目录"
            task_logger.write_error(task_id, error_msg)
            logger.error(f"Task {task_id}: {error_msg}")
            return {
                "return_code": "500",
                "return_info": error_msg
            }

        generated_dirs.append("netconf_output/")
        task_logger.write_log(task_id, f"已生成目录: {', '.join(generated_dirs)}")
        logger.info(f"Task {task_id}: 已生成目录: {', '.join(generated_dirs)}")

        return {
            "return_code": "200",
            "return_info": "材料准备完成"
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"调用材料准备 skill 失败: {str(e)}"
        task_logger.write_error(task_id, error_msg)
        logger.error(f"Task {task_id}: {error_msg}")

        return {
            "return_code": "500",
            "return_info": error_msg
        }


# ==================== 主要接口函数 ====================

async def prepare_dependencies(
    task_id: str,
    test_point: str = "",
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    准备 NETCONF 生成脚本所需的依赖材料

    此函数通过调用 Claude Agent skill 来准备材料，skill 会自动执行：
    - 将 Word API 文档转换为 Markdown 格式
    - 将 YANG 文件转换为 YIN 格式
    - 分析文档结构，生成 netconf_output/ 目录

    Args:
        task_id: 任务ID
        test_point: 测试点描述（用于日志记录，默认为空字符串）
        workspace: 工作目录（可选，默认使用 settings.get_work_directory()）

    Returns:
        包含执行结果的字典，格式为:
        {
            "return_code": "200" | "500",
            "return_info": "执行结果描述",
            "workspace": "工作目录路径",
            "generated_dirs": ["生成的目录列表"]
        }
    """
    try:
        task_logger.write_log(task_id, "准备 NETCONF 依赖材料")
        task_logger.write_log(task_id, "开始准备 NETCONF 依赖材料")
        logger.info(f"Task {task_id}: 开始准备 NETCONF 依赖材料")

        if test_point:
            task_logger.write_log(task_id, f"测试点: {test_point[:100]}...")
            logger.info(f"Task {task_id}: 测试点: {test_point[:100]}...")

        # 调用 skill 准备材料
        result = await call_netconf_material_preparation_skill(
            task_id=task_id,
            workspace=workspace
        )

        if result.get("return_code") == "200":
            task_logger.write_log(task_id, "✓ 依赖材料准备完成")
            logger.info(f"Task {task_id}: 依赖材料准备完成")
        else:
            task_logger.write_error(task_id, "依赖材料准备失败")
            task_logger.write_end_log(task_id, "failed")
            logger.error(f"Task {task_id}: 依赖材料准备失败")

        return result

    except Exception as e:
        error_msg = f"准备依赖材料失败: {str(e)}"
        task_logger.write_error(task_id, error_msg)
        task_logger.write_end_log(task_id, "failed")
        logger.error(f"Task {task_id}: {error_msg}")

        return {
            "return_code": "500",
            "return_info": error_msg
        }


# ==================== 测试代码 ====================

if __name__ == "__main__":
    import asyncio

    # 配置日志输出到控制台
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    async def test_prepare_dependencies():
        """测试 prepare_dependencies 函数"""
        print("===== 开始测试 prepare_dependencies =====")

        # 生成测试任务ID
        import time
        task_id = f"test_{int(time.time())}"

        print(f"任务ID: {task_id}")

        # 调用 prepare_dependencies，不传入 test_point 和 workspace
        result = await prepare_dependencies(task_id=task_id)

        print(f"\n返回码: {result.get('return_code')}")
        print(f"返回信息: {result.get('return_info')}")

        # 显示日志文件路径
        log_file_path = task_logger.get_log_file_path(task_id)
        print(f"\n日志文件: {log_file_path}")

        if result.get("return_code") == "200":
            print("\n✓ 测试成功！")
        else:
            print("\n✗ 测试失败！")

        print("===== 测试结束 =====")

    # 运行测试
    asyncio.run(test_prepare_dependencies())
