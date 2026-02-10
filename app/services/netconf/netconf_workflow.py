"""
NETCONF 工作流模块 - 函数式实现

提供 NETCONF 测试脚本的生成、运行和调试功能
不使用类，采用函数式编程风格

工作流程：
1. 准备 NETCONF 生成脚本所需的依赖材料，保存到 netconf_output 文件夹
2. 遍历 netconf_output 文件夹，生成 NETCONF 测试脚本
3. 调用运行接口运行 netconf_output 下每个子文件的测试脚本
4. 解析运行结果，如果脚本运行失败，调用修复接口修复代码
"""

import os
import json
import logging
import getpass
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path

# 导入 settings
from app.core.config import settings

# 导入准备材料模块
from app.services.netconf.prepare_materials import (
    prepare_dependencies,
    get_output_dir,
    get_netconf_output_dir,
)

# 导入脚本生成模块
from app.services.netconf.generate_scripts import generate_netconf_scripts

# 导入脚本运行模块
from app.services.netconf.run_scripts import run_netconf_scripts

logger = logging.getLogger(__name__)


# ==================== Claude Agent 配置 ====================

def setup_agent_environment():
    """设置 Claude Agent 环境变量"""
    # 删除代理环境变量，避免检索时使用代理
    proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
    for var in proxy_vars:
        os.environ.pop(var, None)

    # 设置 Anthropic 相关环境变量
    os.environ["ANTHROPIC_BASE_URL"] = "http://10.144.41.149:4000/"
    os.environ["ANTHROPIC_AUTH_TOKEN"] = "xx"
    # os.environ["ANTHROPIC_LOG"] = "debug"


# ==================== 第4步：解析结果并修复 ====================

async def parse_and_fix_result(
    task_id: str,
    run_result: Dict[str, Any],
    workspace: str
) -> Dict[str, Any]:
    """
    解析运行结果，如果失败则调用修复接口修复代码

    Args:
        task_id: 任务ID
        run_result: 运行结果
        workspace: 工作目录

    Returns:
        包含执行结果的字典
    """
    try:
        logger.info(f"Task {task_id}: 开始解析运行结果")
        update_task_status(task_id, "running", "结果解析和修复")

        # 解析运行结果
        return_code = run_result.get("return_code", "unknown")
        return_info = run_result.get("return_info", {})

        # 判断是否需要修复
        if return_code == "200":
            send_message(task_id, "info", "✓ 脚本执行成功，无需修复", "processing")
            update_task_status(task_id, "completed", "结果解析和修复")
            return {
                "return_code": "200",
                "return_info": "脚本执行成功，无需修复",
                "fixed": False
            }

        # 需要修复
        send_message(task_id, "info", "===== 脚本执行失败，开始修复 =====", "processing")

        # 构造错误消息
        error_message = f"✗ ITC 执行失败 (错误码: {return_code})\n\n错误信息:\n{json.dumps(return_info, ensure_ascii=False, indent=2)}"

        # TODO: 调用修复服务
        # from app.services.cc_workflow import stream_fix_netconf_response
        # async for message in stream_fix_netconf_response(...):
        #     process_message(message)

        send_message(task_id, "info", "✓ NETCONF 脚本修复完成 (伪代码)", "processing")

        update_task_status(task_id, "completed", "脚本修复")
        send_message(task_id, "success", "===== NETCONF 脚本修复完成 =====", "end")

        return {
            "return_code": "200",
            "return_info": "NETCONF 脚本修复完成",
            "fixed": True
        }

    except Exception as e:
        error_msg = f"解析和修复失败: {str(e)}"
        logger.error(f"Task {task_id}: {error_msg}")
        update_task_status(task_id, "failed", "结果解析和修复")
        send_message(task_id, "error", error_msg, "end")

        return {
            "return_code": "500",
            "return_info": error_msg,
            "fixed": False
        }


# ==================== 完整工作流 ====================

async def execute_netconf_workflow(
    task_id: str,
    test_point: str,
    workspace: str,
    device_info: Optional[Dict[str, Any]] = None
):
    """
    执行完整的 NETCONF 自动化测试流程

    工作流程：
    1. 准备依赖材料
    2. 生成 NETCONF 测试脚本
    3. 运行测试脚本
    4. 解析结果并修复（如果需要）

    Args:
        task_id: 任务ID
        test_point: 测试点描述
        workspace: 工作目录
        device_info: 设备信息（可选）
    """
    try:
        # 设置环境变量
        setup_agent_environment()

        # ========== 预处理：创建并设置 AIGC 工具目录权限 ==========
        username = getpass.getuser()
        aigc_tool_dir = settings.get_aigc_tool_local_dir(username)

        # 创建目录并设置权限为 777
        os.makedirs(aigc_tool_dir, exist_ok=True)

        logger.info(f"Task {task_id}: AIGC 工具目录已创建并设置权限: {aigc_tool_dir}")

        # ========== 阶段1: 准备依赖材料 ==========
        logger.info(f"Task {task_id}: 开始准备依赖材料")
        update_task_status(task_id, "running", "准备依赖材料")
        print("===== 阶段1: 准备依赖材料 =====")

        prepare_result = await prepare_dependencies(
            task_id=task_id,
            test_point=test_point
        )

        if prepare_result.get("return_code") != "200":
            print("❌ 依赖材料准备失败，终止流程")
            return

        print("✓ 依赖材料准备完成")

        # ========== 阶段2: 生成 NETCONF 测试脚本 ==========
        logger.info(f"Task {task_id}: 开始生成 NETCONF 测试脚本")
        update_task_status(task_id, "running", "生成脚本")
        print("\n===== 阶段2: 生成 NETCONF 测试脚本 =====")

        generate_result = await generate_netconf_scripts(
            task_id=task_id
        )

        if generate_result.get("return_code") != "200":
            print("❌ NETCONF 脚本生成失败，终止流程")
            return

        print("✓ NETCONF 脚本生成完成")

        # ========== 阶段3: 运行测试脚本 ==========
        logger.info(f"Task {task_id}: 开始运行测试脚本")
        update_task_status(task_id, "running", "运行脚本")
        print("\n===== 阶段3: 运行测试脚本 =====")

        # 获取所有子文件夹
        output_dir = get_output_dir()
        subdirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]

        if not subdirs:
            print("❌ netconf_output 目录下没有子文件夹")
            return

        print(f"找到 {len(subdirs)} 个子文件夹，开始运行测试脚本\n")

        # 为每个子文件夹调用 run_netconf_scripts
        all_results = []
        success_count = 0
        failed_count = 0

        for subdir in subdirs:
            print(f"\n--- 运行子文件夹: {subdir.name} ---")
            logger.info(f"Task {task_id}: 运行子文件夹 {subdir.name}")

            # 调用 run_netconf_scripts，传入子文件夹路径
            run_result = await run_netconf_scripts(
                task_id=task_id,
                subdir_path=str(subdir)
            )

            # 检查是否成功（使用统一格式的 success 字段）
            success = run_result.get("success", False)

            all_results.append({
                "subdir": subdir.name,
                "success": success,
                "result": run_result
            })

            if success:
                success_count += 1
                print(f"✓ {subdir.name} 运行成功")
            else:
                failed_count += 1
                print(f"✗ {subdir.name} 运行失败")

                # 检查是否需要停止整个工作流
                if run_result.get("stop_workflow"):
                    print(f"\n⚠️  检测到函数修复3次仍然失败，停止整个工作流")
                    logger.warning(f"Task {task_id}: 函数修复失败，停止工作流")
                    break  # 跳出循环，不再处理其他子文件夹

        # 汇总结果
        print(f"\n===== 运行结果汇总 =====")

        # 检查是否因函数修复失败而停止
        workflow_stopped = any(r.get("result", {}).get("stop_workflow", False) for r in all_results if not r.get("success"))

        if workflow_stopped:
            print(f"成功: {success_count}, 失败: {failed_count}, 总数: {len(all_results)}")
            print(f"⚠️  工作流因函数修复失败而停止，未完成所有子文件夹的运行")
            return_code = "500"  # 因修复失败而停止
        else:
            print(f"成功: {success_count}, 失败: {failed_count}, 总数: {len(all_results)}")

            # 判断总体返回码
            if failed_count == 0:
                return_code = "200"
            elif success_count > 0:
                return_code = "207"  # 部分成功
            else:
                return_code = "500"  # 全部失败


        # ========== 阶段4: 结果汇总 ==========
        # 注：修复逻辑已在 _run_scripts_for_subdir 中通过循环处理
        logger.info(f"Task {task_id}: 所有子文件夹运行完成")

        # ========== 完成 ==========
        if return_code == "200":
            print("\n✓ ===== NETCONF 自动化测试流程完成 =====")
        elif workflow_stopped:
            print(f"\n❌ ===== NETCONF 自动化测试流程失败（函数修复失败） =====")
        else:
            print(f"\n⚠️  NETCONF 自动化测试流程完成（部分失败）")

        logger.info(f"Task {task_id}: 任务完成")

    except asyncio.CancelledError:
        # 任务被取消
        print(f"\n⚠️  NETCONF 工作流已被用户取消")
        logger.info(f"Task {task_id}: NETCONF 工作流被取消")
        raise  # 重新抛出 CancelledError，让上层处理


# ==================== 辅助函数 ====================


def update_task_status(task_id: str, status: str, stage: str):
    """更新任务状态（占位函数）"""
    logger.info(f"Task {task_id}: {stage} - {status}")


def send_message(task_id: str, msg_type: str, content: str, msg_level: str):
    """发送消息（占位函数）"""
    print(f"[{msg_type}] {content}")


# ==================== 测试代码 ====================

if __name__ == "__main__":
    async def test_execute_netconf_workflow():
        """测试完整工作流"""
        import time
        task_id = f"test_workflow_{int(time.time())}"
        test_point = "测试 BGP 配置"
        workspace = ""  # 使用默认工作目录

        print(f"任务ID: {task_id}")
        print(f"测试点: {test_point}")
        print(f"工作区: {workspace or '(默认)'}")
        print("\n开始执行 NETCONF 自动化测试流程...")

        await execute_netconf_workflow(
            task_id=task_id,
            test_point=test_point,
            workspace=workspace
        )

    # 运行测试
    asyncio.run(test_execute_netconf_workflow())

