"""
NETCONF 脚本修复模块

提供 NETCONF 测试脚本修复功能
解析运行结果，如果脚本运行失败，调用修复接口修复代码
"""

import os
import json
import logging
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions
from app.core.config import settings
from app.services.netconf.prepare_materials import get_output_dir
from app.services.claude_api.task_logger import task_logger
from app.services.netconf.json_parser import JSONParser
from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ResultMessage

logger = logging.getLogger(__name__)


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

    # ANTHROPIC_* 环境变量由 app.services.claude_api.auth.setup_claude_auth() 统一设置


# ==================== 解析脚本运行结果 ====================

async def parse_script_return_info(
    task_id: str,
    return_info: Any
) -> Dict[str, Any]:
    """
    解析脚本运行的 return_info

    当脚本运行失败时，解析 return_info 中的 JSON 数据（pytest 日志），
    提取错误信息供后续修复使用。

    Args:
        task_id: 任务ID
        return_info: return_info 数据（可能是文件路径、JSON字符串或数据结构）

    Returns:
        解析后的结果字典，包含 _error_summary 字段
    """
    try:
        if not return_info:
            task_logger.write_log(task_id, f"return_info 为空，跳过解析")
            return {
                '_error_summary': None
            }

        task_logger.write_log(task_id, f"尝试解析 return_info...")

        # 初始化 JSONParser
        parser = JSONParser()

        # 检查 return_info 是否是文件路径
        if isinstance(return_info, str) and os.path.exists(return_info):
            # 是文件路径，读取并解析 JSON
            import json
            with open(return_info, 'r', encoding='utf-8') as f:
                data = json.load(f)

            parsed_data = parser.parse_json_data(data)
            task_logger.write_log(task_id, f"JSON 文件读取并解析成功")

            # 提取错误摘要
            error_summary = parser.extract_error_summary(parsed_data)
            task_logger.write_log(task_id, f"错误摘要提取成功: {error_summary['total_failures']} 个失败")

            # 记录错误详情
            if error_summary['total_failures'] > 0:
                for group in error_summary.get("groups", [])[:2]:  # 只记录前2个组
                    group_id = group.get("group_id", "unknown")
                    description = group.get("description", "")
                    failures = group.get("failures", [])
                    task_logger.write_log(task_id, f"组 {group_id}: {len(failures)} 个失败")
                    if description:
                        task_logger.write_log(task_id, f"  描述: {description}")
                    for failure in failures[:2]:  # 每组只记录前2个错误
                        step = failure.get("step", "unknown")
                        errors = failure.get("errors", [])
                        if errors:
                            task_logger.write_log(task_id, f"  - {step}: {errors[0][:80]}")

            # 返回错误摘要
            return {
                '_error_summary': error_summary
            }

        elif isinstance(return_info, str):
            # 尝试将字符串解析为 JSON
            parsed_data = parser.parse_json_data(return_info)
            task_logger.write_log(task_id, f"JSON 字符串解析成功")

            # 提取错误摘要
            error_summary = parser.extract_error_summary(parsed_data)

            # 返回错误摘要
            return {
                '_error_summary': error_summary
            }
        else:
            # 已经是字典或列表，直接提取错误摘要
            error_summary = parser.extract_error_summary(return_info)
            task_logger.write_log(task_id, f"return_info 已是数据结构")

            # 返回错误摘要
            return {
                '_error_summary': error_summary
            }

    except Exception as e:
        error_msg = f"解析 return_info 失败: {str(e)}"
        task_logger.write_log(task_id, error_msg)
        # 即使解析失败，也返回错误信息
        return {
            '_error_summary': None,
            '_parse_error': error_msg
        }


# ==================== 修复 NETCONF 测试脚本 ====================

async def _call_claude_agent_for_fix(
    task_id: str,
    subdir: str,
    subdir_name: str,
    function_name: str,
    first_group: Dict[str, Any]
) -> Dict[str, Any]:
    """
    调用 Claude Agent 修复脚本

    Args:
        task_id: 任务ID
        subdir: 子文件夹的完整路径
        subdir_name: 子文件夹名称
        function_name: 要修复的函数名
        first_group: 第一组错误信息

    Returns:
        包含修复结果的字典
    """
    error_json_file = ""
    try:
        task_logger.write_log(task_id, f"配置 Claude Agent 选项，工作区: {subdir}")
        logger.info(f"Task {task_id}: 配置 Claude Agent 选项，工作区: {subdir}")

        # ========== 第1步：保存错误信息到 JSON 文件 ==========
        error_json_file = os.path.join(subdir, "error_info.json")
        task_logger.write_log(task_id, f"保存错误信息到: {error_json_file}")

        with open(error_json_file, 'w', encoding='utf-8') as f:
            json.dump(first_group, f, ensure_ascii=False, indent=2)

        task_logger.write_log(task_id, f"错误信息已保存到 {error_json_file}")

        # ========== 第2步：配置 Claude Agent 选项 ==========
        options = ClaudeAgentOptions(
            cwd=subdir,  # 使用子文件夹作为工作区
            setting_sources=["user"],  # 不加载 project 设置
            permission_mode="bypassPermissions",
            allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],
        )

        # 构造 prompt - 调用 netconf-repair 子 agent
        prompt = escape_all_special_chars(
            f"""调用子 agent: netconf-repair，修复 NETCONF 测试脚本。

                工作区: {subdir}
                要修复的函数: {function_name}

                错误信息已保存到文件: error_info.json

                请读取 error_info.json 文件，分析错误并修复代码。
                """
        )

        task_logger.write_log(task_id, f"发送修复请求到 Claude Agent")
        logger.info(f"Task {task_id}: 发送修复请求到 Claude Agent")

        # ========== 第3步：调用 Claude Agent ==========
        message_count = 0
        async for message in query(prompt=prompt, options=options):
            message_count += 1
            if isinstance(message, ResultMessage):
                task_logger.write_log(task_id, f"✓ 修复总结{message.result}")
        task_logger.write_log(task_id, f"✓ {subdir_name} 修复完成，共处理 {message_count} 条消息")
        logger.info(f"Task {task_id}: {subdir_name} 修复完成，共处理 {message_count} 条消息")

        # ========== 第4步：删除错误信息 JSON 文件 ==========
        if os.path.exists(error_json_file):
            os.remove(error_json_file)
            task_logger.write_log(task_id, f"已删除错误信息文件: {error_json_file}")
            logger.info(f"Task {task_id}: 已删除 {error_json_file}")

        return {
            "return_code": "200",
            "return_info": f"{subdir_name} 脚本修复完成",
            "fixed_scripts": True,
            "message_count": message_count
        }

    except Exception as e:
        error_msg = f"{subdir_name} 修复脚本失败: {str(e)}"
        task_logger.write_error(task_id, error_msg)
        logger.error(f"Task {task_id}: {error_msg}")

        # 即使失败，也尝试删除 JSON 文件
        if error_json_file and os.path.exists(error_json_file):
            try:
                os.remove(error_json_file)
                task_logger.write_log(task_id, f"已删除错误信息文件: {error_json_file}")
            except Exception as e2:
                task_logger.write_log(task_id, f"删除错误信息文件失败: {str(e2)}")

        return {
            "return_code": "500",
            "return_info": error_msg,
            "fixed_scripts": False
        }


async def _fix_scripts_for_subdir(
    task_id: str,
    subdir: str,
    error_message: Any
) -> Dict[str, Any]:
    """
    修复单个子文件夹中的测试脚本

    Args:
        task_id: 任务ID
        subdir: 子文件夹的完整路径
        error_message: 错误信息（可能是文件路径、JSON 字符串、数据结构或已解析的 error_summary）

    Returns:
        包含执行结果的字典
    """
    # 从 subdir 路径中提取子文件夹名称
    subdir_name = os.path.basename(subdir)

    try:
        task_logger.write_log(task_id, f"开始解析 {subdir_name} 的错误信息")
        logger.info(f"Task {task_id}: 开始解析 {subdir_name} 的错误信息")

        # ========== 第1步：解析 error_message（复用 parse_script_return_info）==========
        parse_result = await parse_script_return_info(task_id, error_message)

        # separators 保持默认，避免压缩换行
        formatted_json = json.dumps(parse_result, indent=2, ensure_ascii=False)

        # 检查解析是否成功
        if parse_result.get('_parse_error'):
            error_msg = parse_result.get('_parse_error')
            task_logger.write_error(task_id, error_msg)
            return {
                "return_code": "500",
                "return_info": error_msg,
                "fixed_scripts": False
            }

        # 提取解析结果
        error_summary = parse_result.get('_error_summary')

        if not error_summary:
            task_logger.write_log(task_id, f"未提取到错误摘要，可能没有失败")
            return {
                "return_code": "200",
                "return_info": f"{subdir_name} 没有需要修复的错误",
                "fixed_scripts": False,
                "_error_summary": None
            }

        # ========== 第2步：记录错误摘要信息 ==========
        total_failures = error_summary.get('total_failures', 0)
        groups_count = len(error_summary.get('groups', []))

        task_logger.write_log(task_id, f"错误摘要: {total_failures} 个失败, {groups_count} 个组")
        logger.info(f"Task {task_id}: 错误摘要: {total_failures} 个失败, {groups_count} 个组")

        # 只处理第一组错误（因为测试步骤之间有依赖关系，需要逐个解决）
        first_group = error_summary.get('groups', [])[0] if groups_count > 0 else None

        if not first_group:
            task_logger.write_log(task_id, f"没有找到错误信息")
            return {
                "return_code": "200",
                "return_info": f"{subdir_name} 没有需要修复的错误",
                "fixed_scripts": False,
                "_error_summary": None
            }

        # 提取第一组的信息
        group_id = first_group.get('group_id', 'unknown')
        description = first_group.get('description', '')
        failures = first_group.get('failures', [])

        # 从 description 中提取函数名（使用 : 分割，获取第一部分）
        # 例如: "test_step_2:测试点编号2: 2、create操作测试" -> "test_step_2"
        function_name = description.split(':')[0] if description else ''

        task_logger.write_log(task_id, f"第一组错误: {group_id}")
        if description:
            task_logger.write_log(task_id, f"  描述: {description}")
        if function_name:
            task_logger.write_log(task_id, f"  函数名: {function_name}")
        task_logger.write_log(task_id, f"  失败数: {len(failures)}")

        # 记录第一组的全部错误信息
        for failure in failures:  # 记录全部错误
            step = failure.get('step', 'unknown')
            errors = failure.get('errors', [])
            if errors:
                # 记录完整的错误信息
                task_logger.write_log(task_id, f"    - {step}: {errors[0]}")

        # ========== 第3步：调用 Claude Agent 进行修复 ==========
        task_logger.write_log(task_id, f"开始调用 Claude Agent 修复 {function_name}")
        logger.info(f"Task {task_id}: 开始调用 Claude Agent 修复 {function_name}")

        # 临时测试标志：如果为 True，则跳过实际修复
        ENABLE_FIX = True  # 设置为 True 启用修复，False 仅测试解析

        if ENABLE_FIX:
            fix_result = await _call_claude_agent_for_fix(
                task_id=task_id,
                subdir=subdir,
                subdir_name=subdir_name,
                function_name=function_name,
                first_group=first_group
            )
        else:
            # 测试模式：模拟修复结果
            task_logger.write_log(task_id, f"测试模式：跳过 Claude Agent 调用")
            logger.info(f"Task {task_id}: 测试模式：跳过修复")
            fix_result = {
                "return_code": "200",
                "return_info": f"{subdir_name} 错误解析完成（测试模式，未实际修复）",
                "fixed_scripts": False
            }

        # 合并修复结果
        return {
            "return_code": fix_result.get("return_code", "500"),
            "return_info": fix_result.get("return_info", ""),
            "fixed_scripts": fix_result.get("fixed_scripts", False),
            "function_name": function_name,
            "first_group": {
                "group_id": group_id,
                "description": description,
                "failures": failures
            },
            "_error_summary": error_summary,
            "_fix_result": fix_result
        }

    except Exception as e:
        error_msg = f"{subdir_name} 解析错误信息失败: {str(e)}"
        task_logger.write_error(task_id, error_msg)
        logger.error(f"Task {task_id}: {error_msg}")

        return {
            "return_code": "500",
            "return_info": error_msg,
            "fixed_scripts": False
        }


# ==================== 测试代码 ====================

if __name__ == "__main__":
    import asyncio
    setup_agent_environment()
    # 配置日志输出到控制台
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )

    async def test_fix_scripts_for_subdir():
        """测试 _fix_scripts_for_subdir 函数 - 解析 JSON 并提取错误信息"""
        print("===== 开始测试 _fix_scripts_for_subdir =====")

        # 生成测试任务ID
        import time
        task_id = f"test_{int(time.time())}"

        # 指定的测试文件路径和工作区
        json_file = "/opt/coder/statistics/build/aigc_tool/m31660/proj_26020309_9a8cbe44/log/test_netconf_case_2026-02-05_20-56-49_76233.pytestlog.json"
        workspace = "/home/m31660/project/netconf_output/Base"

        print(f"任务ID: {task_id}")
        print(f"JSON 文件: {json_file}")
        print(f"工作区: {workspace}")

        # 检查文件是否存在
        if not os.path.exists(json_file):
            print(f"\n✗ 错误: JSON 文件不存在: {json_file}")
            return

        # 检查工作区是否存在
        if not os.path.exists(workspace):
            print(f"\n⚠️  警告: 工作区不存在: {workspace}")
            print("继续测试，但修复代码时可能会失败")

        print(f"\n开始解析错误信息...")

        # 调用 _fix_scripts_for_subdir 函数
        result = await _fix_scripts_for_subdir(
            task_id=task_id,
            subdir=workspace,
            error_message=json_file  # 传入 JSON 文件路径
        )

        # 显示结果
        print(f"\n===== 解析结果 =====")
        print(f"返回码: {result.get('return_code')}")
        print(f"返回信息: {result.get('return_info')}")

        # 显示函数名
        function_name = result.get('function_name', '')
        if function_name:
            print(f"\n===== 修复目标 =====")
            print(f"函数名: {function_name}")

        # 显示第一组错误
        first_group = result.get('first_group', {})
        if first_group:
            print(f"\n===== 第一组错误详情 =====")
            print(f"描述: {first_group.get('description', '')}")
            print(f"失败数: {len(first_group.get('failures', []))}")
            print(f"错误列表:")

            # 显示第一组的全部错误
            for failure in first_group.get('failures', []):
                step = failure.get('step', 'unknown')
                errors = failure.get('errors', [])
                if errors:
                    # 显示完整错误
                    error_msg = errors[0]
                    print(f"\n  步骤: {step}")
                    print(f"  错误: {error_msg}")

        # 显示错误摘要
        error_summary = result.get('_error_summary', {})
        if error_summary:
            total_failures = error_summary.get('total_failures', 0)
            groups_count = len(error_summary.get('groups', []))

            print(f"\n===== 错误摘要（全部组） =====")
            print(f"总失败数: {total_failures}")
            print(f"组数量: {groups_count}")

            # 显示每个组的简要信息
            groups = error_summary.get('groups', [])
            for idx, group in enumerate(groups, 1):
                group_id = group.get('group_id', 'unknown')
                description = group.get('description', '')
                failures = group.get('failures', [])

                print(f"\n【组 {idx}】{group_id}")
                if description:
                    func_name = description.split(':')[0]
                    print(f"  函数名: {func_name}")
                print(f"  失败数: {len(failures)}")

        # 显示日志文件路径
        log_file_path = task_logger.get_log_file_path(task_id)
        print(f"\n日志文件: {log_file_path}")

        print("\n✓ 测试完成！")
        print("===== 测试结束 =====")

    # 运行测试
    asyncio.run(test_fix_scripts_for_subdir())
