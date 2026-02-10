"""
NETCONF 脚本运行模块

提供 NETCONF 测试脚本运行功能
遍历 netconf_output 文件夹下的每个子文件夹，运行测试脚本
"""

import os
import json
import logging
import asyncio
import getpass
import time
from typing import Dict, Any, Optional, List
from pathlib import Path
import glob

from app.core.config import settings
from app.services.netconf.prepare_materials import get_output_dir
from app.services.claude_api.task_logger import task_logger
from app.models.itc.itc_models import RunSingleScriptRequest
from app.services.netconf.fix_scripts import parse_script_return_info, _fix_scripts_for_subdir, setup_agent_environment


# ==================== 工具函数 ====================

async def wait_for_pytestlog_json(
    log_dir: str,
    start_time: float,
    task_id: str,
    timeout: int = 360,
    check_interval: int = 5
) -> Optional[str]:
    """
    等待并获取 log 目录下在指定时间之后创建/修改的 pytestlog.json 文件内容

    Args:
        log_dir: 日志目录路径
        start_time: 开始运行脚本前的时间戳（time.time()）
        task_id: 任务ID
        timeout: 超时时间（秒），默认360秒（6分钟）
        check_interval: 检查间隔（秒），默认5秒

    Returns:
        最新的 pytestlog.json 文件内容（字符串），如果超时则返回 None
    """
    if not os.path.exists(log_dir):
        return None

    start_wait = time.time()
    pattern = os.path.join(log_dir, "*.pytestlog.json")

    while True:
        # 检查是否超时
        elapsed = time.time() - start_wait
        if elapsed >= timeout:
            task_logger.write_log(task_id,
                f"等待 pytestlog.json 文件超时（{timeout}秒），未检测到新文件")
            return None

        # 查找所有 pytestlog.json 文件
        json_files = glob.glob(pattern)

        # 筛选出在 start_time 之后修改的文件，且文件名以 test 开头
        new_files = [
            f for f in json_files
            if os.path.getmtime(f) > start_time and os.path.basename(f).startswith('test')
        ]

        if new_files:
            # 找到新文件，获取最新的
            latest_file = max(new_files, key=os.path.getmtime)
            try:
                with open(latest_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                task_logger.write_log(task_id,
                    f"检测到新的 pytestlog.json 文件: {os.path.basename(latest_file)}")
                return content
            except Exception as e:
                logging.warning(f"读取 pytestlog.json 文件失败 {latest_file}: {str(e)}")
                return None

        # 没有找到新文件，等待一段时间后再检查
        await asyncio.sleep(check_interval)


# ==================== 运行 NETCONF 测试脚本 ====================

async def run_netconf_scripts(
    task_id: str,
    subdir_path: Optional[str] = None,
    workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    运行 NETCONF 测试脚本

    Args:
        task_id: 任务ID
        subdir_path: 要运行的子文件夹路径（可选）
                    - 如果为 None，则运行 netconf_output 下所有子文件夹
                    - 如果指定路径，则只运行该子文件夹中的脚本
        workspace: 工作目录（可选，默认使用 settings.get_work_directory()）

    Returns:
        包含执行结果的字典

    Examples:
        # 运行所有子文件夹中的脚本
        result = await run_netconf_scripts(task_id="task_123")

        # 运行指定子文件夹中的脚本
        result = await run_netconf_scripts(
            task_id="task_123",
            subdir_path="/home/user/project/netconf_output/test_bgp"
        )
    """
    # 如果指定了单个子文件夹路径
    if subdir_path:
        from pathlib import Path as PathLib
        subdir = PathLib(subdir_path)

        if not subdir.exists():
            error_msg = f"路径不存在: {subdir_path}"
            return {
                "return_code": "404",
                "return_info": error_msg,
                "success": False
            }

        result = await _run_scripts_for_subdir(
            task_id=task_id,
            subdir=str(subdir)
        )

        # 包装返回值，统一格式
        success = result.get("status") == "ok"
        wrapped_result = {
            "return_code": "200" if success else "500",
            "return_info": result.get("message", ""),
            "success": success,
            "data": result.get("data"),
            "subdir_path": str(subdir),
            "subdir_name": subdir.name,
            # 保留原始结果，以防需要
            "_raw_result": result
        }

        # 如果有 stop_workflow 标记，也要传递
        if result.get("stop_workflow"):
            wrapped_result["stop_workflow"] = True

        return wrapped_result

    # 否则运行所有子文件夹
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


        # 为每个子文件夹运行测试脚本（顺序执行，一次一个）
        all_results = []
        success_count = 0
        failed_count = 0

        for idx, subdir in enumerate(subdirs, 1):

            # 运行子文件夹中的脚本（内部包含循环修复逻辑）
            result = await _run_scripts_for_subdir(
                task_id=task_id,
                subdir=str(subdir)
            )

            # 检查是否成功（BaseResponse 的 status 字段）
            success = result.get("status") == "ok"

            all_results.append({
                "subdir": subdir.name,
                "success": success,
                "result": result
            })

            if success:
                success_count += 1
            else:
                failed_count += 1


        summary = f"成功: {success_count}, 失败: {failed_count}, 总数: {len(all_results)}"

        return {
            "return_code": "200" if failed_count == 0 else "207",  # 207 表示部分成功
            "return_info": f"NETCONF 脚本运行完成，{summary}",
            "results": all_results,
            "success_count": success_count,
            "failed_count": failed_count
        }

    except Exception as e:
        error_msg = f"运行 NETCONF 脚本失败: {str(e)}"

        return {
            "return_code": "500",
            "return_info": error_msg
        }


async def _run_scripts_for_subdir(
    task_id: str,
    subdir: str
) -> Dict[str, Any]:
    """
    运行单个子文件夹中的测试脚本（包含循环修复逻辑）

    流程说明：
    -----------
    1. 无限循环，直到成功或满足退出条件
    2. 每次循环：
       - 运行脚本
       - 等待 pytestlog.json 文件（最多6分钟）
       - 判断是否成功（total_failures == 0）
       - 如果成功：返回结果
       - 如果失败：进入修复流程
    3. 修复流程：
       - 第一次失败时保存原始的 return_info（json字符串）
       - 每次都传入第一次的 return_info 给 _fix_scripts_for_subdir
       - 检查修复的函数名
       - **每个函数最多修复3次**
       - 如果是不同函数：继续下一次循环（修复后重新运行）

    Args:
        task_id: 任务ID
        subdir: 子文件夹的完整路径

    Returns:
        包含执行结果的字典，status 字段为 "ok" 表示成功
    """
    from fastapi import HTTPException
    from app.api.itc.itc_router import run_script

    # 从 subdir 路径中提取子文件夹名称
    subdir_name = os.path.basename(subdir)

    # ========== 循环修复相关变量 ==========
    first_error_summary = None  # 保存第一次的 return_info（json字符串）
    fixed_function = None  # 记录最后一次修复的函数名
    same_function_count = 0  # 记录连续修复同一函数的次数
    max_same_function_attempts = 3  # 每个函数最多修复3次

    # ========== 主循环：运行 -> 失败 -> 修复 -> 重新运行 ==========
    while True:

        # ---------- 步骤1: 记录开始时间 ----------
        start_time = time.time()

        try:
            # ---------- 步骤2: 查找测试脚本 ----------
            test_netconf_file = None

            for root, dirs, files in os.walk(subdir):
                for file in files:
                    if file.startswith('test_netconf') and file.endswith('.py'):
                        test_netconf_file = file
                        break

            if first_error_summary is None:
                task_logger.write_log(task_id, f"{subdir_name} 开始运行测试脚本")

            # ---------- 步骤3: 构造请求 ----------
            script_path = os.path.join(subdir, test_netconf_file) if test_netconf_file else ""
            request = RunSingleScriptRequest(script_path=script_path)

            # ---------- 步骤4: 调用 itc_router.run_script ----------
            response = await run_script(request)

            # ---------- 步骤5: 等待 pytestlog.json 文件 ----------
            # 等待最多6分钟，查找在 start_time 之后生成的、以 test 开头的 pytestlog.json 文件
            username = getpass.getuser()
            log_dir = settings.get_aigc_tool_local_log_dir(username)
            return_info = await wait_for_pytestlog_json(log_dir, start_time, task_id)

            if return_info is None:
                # 未检测到 pytestlog.json 文件，视为失败
                error_msg = f"{subdir_name} 未检测到 pytestlog.json 文件（等待6分钟超时）"
                task_logger.write_log(task_id, error_msg)
                return {
                    "status": "error",
                    "message": error_msg,
                    "data": None
                }

            # ---------- 步骤6: 解析并判断是否成功 ----------
            parse_result = await parse_script_return_info(task_id, return_info)
            error_summary = parse_result.get('_error_summary', {})
            total_failures = error_summary.get('total_failures', 0)

            # 如果 total_failures == 0，说明运行成功
            if total_failures == 0:
                if same_function_count > 0:
                    task_logger.write_log(task_id, f"{subdir_name} 修复后运行成功 ✓")
                else:
                    task_logger.write_log(task_id, f"{subdir_name} 首次运行成功 ✓")
                return response.model_dump()

            # ---------- 步骤7: 运行失败，进入修复流程 ----------
            task_logger.write_log(task_id,
                f"{subdir_name} 运行失败: {total_failures} 个错误")

            # 第一次失败时保存原始的 return_info（json字符串）
            if first_error_summary is None:
                first_error_summary = return_info
                groups_count = len(error_summary.get('groups', []))
                task_logger.write_log(task_id,
                    f"保存首次错误信息: {groups_count} 个错误组")

                # 打印第一组错误信息（将要修复的函数）
                first_group = error_summary.get('groups', [{}])[0] if groups_count > 0 else {}
                description = first_group.get('description', '')
                if description:
                    function_name = description.split(':')[0] if ':' in description else description
                    task_logger.write_log(task_id,
                        f"当前需要修复的函数: {function_name}")

            # ---------- 步骤8: 调用修复函数 ----------
            # 每次都传入第一次的 return_info（_fix_scripts_for_subdir 内部会解析）
            task_logger.write_log(task_id,
                f"开始调用修复函数...")

            fix_result = await _fix_scripts_for_subdir(
                task_id=task_id,
                subdir=subdir,
                error_message=first_error_summary
            )

            # ---------- 步骤9: 检查修复结果 ----------
            if not fix_result.get("fixed_scripts"):
                task_logger.write_log(task_id, f"{subdir_name} 修复失败或未修复，停止尝试")
                return response.model_dump()

            # 记录修复的函数名
            new_fixed_function = fix_result.get("function_name", "")

            # ---------- 步骤10: 检查是否连续修复同一函数 ----------
            if fixed_function == new_fixed_function:
                same_function_count += 1
                task_logger.write_log(task_id,
                    f"修复函数: {new_fixed_function}（第 {same_function_count} 次修复该函数）")
            else:
                same_function_count = 1
                fixed_function = new_fixed_function
                task_logger.write_log(task_id,
                    f"修复函数: {new_fixed_function}（第 1 次修复该函数）")
                task_logger.write_log(task_id,
                    f"切换到新的函数: {new_fixed_function}，重置计数器")

            # 如果连续3次修复同一函数，退出循环（该函数无法修复）
            if same_function_count >= max_same_function_attempts:
                task_logger.write_log(task_id,
                    f"函数 {fixed_function} 已修复 {max_same_function_attempts} 次仍然失败，停止整个流程")
                # 返回特殊标记，表示因函数修复失败而退出
                return {
                    "status": "error",
                    "message": f"函数 {fixed_function} 已修复 {max_same_function_attempts} 次仍然失败",
                    "stop_workflow": True,  # 特殊标记：停止整个工作流
                    "data": None
                }

            # ---------- 步骤11: 继续下一次循环（重新运行） ----------
            task_logger.write_log(task_id, f"准备重新运行脚本...")
            continue  # 回到循环开头，重新运行

        except HTTPException as e:
            error_msg = f"{subdir_name} HTTP异常: {e.detail}"
            task_logger.write_log(task_id, error_msg)
            return {
                "status": "error",
                "message": error_msg,
                "data": None
            }

        except Exception as e:
            error_msg = f"{subdir_name} 运行异常: {str(e)}"
            task_logger.write_log(task_id, error_msg)
            return {
                "status": "error",
                "message": error_msg,
                "data": None
            }

    # 循环结束仍未成功（实际上不会执行到这里，因为 while True 只能通过 return 或 break 退出）
    return {
        "status": "error",
        "message": f"{subdir_name} 修复失败",
        "data": None
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

    async def test_run_all_scripts():
        """测试运行所有脚本"""
        print("===== 测试1: 运行所有脚本 =====")

        import time
        task_id = f"test_{int(time.time())}"
        print(f"任务ID: {task_id}")

        output_dir = get_output_dir()
        print(f"netconf_output 目录: {output_dir}")

        if os.path.exists(output_dir):
            subdirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]
            print(f"找到 {len(subdirs)} 个子文件夹")
        else:
            print(f"⚠️  netconf_output 目录不存在")
            return

        result = await run_netconf_scripts(task_id=task_id)

        print(f"\n返回码: {result.get('return_code')}")
        print(f"返回信息: {result.get('return_info')}")

        if result.get("return_code") in ["200", "207"]:
            success_count = result.get("success_count", 0)
            failed_count = result.get("failed_count", 0)
            print(f"\n成功: {success_count}, 失败: {failed_count}")

        log_file_path = task_logger.get_log_file_path(task_id)
        print(f"日志文件: {log_file_path}")

    async def test_run_single_script():
        """测试运行单个脚本"""
        print("\n===== 测试2: 运行单个脚本 =====")

        import time
        task_id = f"test_single_{int(time.time())}"

        output_dir = get_output_dir()

        # 查找第一个子文件夹
        if os.path.exists(output_dir):
            subdirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]
            if subdirs:
                subdir_path = str(subdirs[0])
                print(f"运行路径: {subdir_path}")

                result = await run_netconf_scripts(
                    task_id=task_id,
                    subdir_path=subdir_path
                )

                print(f"\n返回码: {result.get('return_code')}")
                print(f"返回信息: {result.get('return_info')}")
                print(f"成功: {result.get('success', False)}")

                output = result.get('output', '')
                if output:
                    print(f"\n运行输出（前500字符）:")
                    print(output[:500])

                log_file_path = task_logger.get_log_file_path(task_id)
                print(f"\n日志文件: {log_file_path}")
            else:
                print("没有找到子文件夹")
        else:
            print("netconf_output 目录不存在")

    async def main():
        """运行所有测试"""
        # 测试1: 运行所有脚本
        # await test_run_all_scripts()

        # 测试2: 运行单个脚本
        await test_run_single_script()

    # 运行测试
    asyncio.run(main())
