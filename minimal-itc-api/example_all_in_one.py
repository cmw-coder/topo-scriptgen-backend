#!/usr/bin/env python3
"""
示例：完整工作流程演示

演示一个完整的测试流程：
1. 上传 topox 并部署组网
2. 上传测试脚本并执行
3. 卸载组网环境

使用方式：
    python example_all_in_one.py
"""

import argparse
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库")
    print("请运行: pip install requests")
    sys.exit(1)


# API 配置
API_BASE_URL = "http://localhost:3001"


class MinimalITCAPIClient:
    """Minimal ITC API 客户端"""

    def __init__(self, api_url: str = API_BASE_URL):
        self.api_url = api_url.rstrip('/')

    def upload_topox_and_deploy(
        self,
        topox_file: str,
        version_path: str = None,
        device_type: str = "simware9cen"
    ) -> dict:
        """上传 topox 文件并部署"""
        url = f"{self.api_url}/api/v1/upload-topox"

        topox_path = Path(topox_file)
        if not topox_path.exists():
            return {"success": False, "error": f"文件不存在: {topox_file}"}

        files = {
            "topox_file": (
                topox_path.name,
                open(topox_path, "rb"),
                "application/octet-stream"
            )
        }

        data = {"device_type": device_type}
        if version_path:
            data["version_path"] = version_path

        try:
            print(f"\n📤 [步骤 1/3] 上传 topox 文件并部署组网...")
            print(f"   文件: {topox_file}")
            print(f"   设备类型: {device_type}")

            response = requests.post(url, files=files, data=data, timeout=1200)
            files["topox_file"][1].close()

            result = response.json()
            return {
                "success": response.status_code == 200 and result.get("status") == "ok",
                "data": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def upload_scripts_and_run(
        self,
        script_files: list,
        executor_ip: str
    ) -> dict:
        """上传脚本并执行"""
        url = f"{self.api_url}/api/v1/upload-scripts"

        # 验证并准备文件
        valid_files = []
        for file_path in script_files:
            path = Path(file_path)
            if path.exists():
                valid_files.append(path)

        if not valid_files:
            return {"success": False, "error": "没有有效的脚本文件"}

        # 准备文件列表
        files = []
        for script_path in valid_files:
            files.append((
                "script_files",
                (script_path.name, open(script_path, "rb"), "application/octet-stream")
            ))

        data = {"executor_ip": executor_ip}

        try:
            print(f"\n📜 [步骤 2/3] 上传测试脚本并执行...")
            print(f"   脚本数量: {len(valid_files)}")
            print(f"   执行机 IP: {executor_ip}")

            response = requests.post(url, files=files, data=data, timeout=1200)

            # 关闭所有文件
            for item in files:
                item[1][1].close()

            result = response.json()
            return {
                "success": response.status_code == 200 and result.get("status") == "ok",
                "data": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def undeploy(self, executor_ip: str) -> dict:
        """卸载组网环境"""
        url = f"{self.api_url}/api/v1/undeploy"
        data = {"executor_ip": executor_ip}

        try:
            print(f"\n🧹 [步骤 3/3] 卸载组网环境...")
            print(f"   执行机 IP: {executor_ip}")

            response = requests.post(url, data=data, timeout=300)
            result = response.json()
            return {
                "success": response.status_code == 200 and result.get("status") == "ok",
                "data": result
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


def run_complete_workflow(
    topox_file: str,
    script_files: list,
    executor_ip: str,
    version_path: str = None,
    device_type: str = "simware9cen",
    api_url: str = API_BASE_URL,
    skip_undeploy: bool = False
) -> dict:
    """
    运行完整工作流程

    Args:
        topox_file: topox 文件路径
        script_files: 脚本文件列表
        executor_ip: 执行机 IP
        version_path: 版本路径（可选）
        device_type: 设备类型
        api_url: API 地址
        skip_undeploy: 是否跳过卸载步骤

    Returns:
        dict: 工作流程结果
    """
    print(f"\n{'='*70}")
    print(f"Minimal ITC API - 完整工作流程演示")
    print(f"{'='*70}")

    client = MinimalITCAPIClient(api_url=api_url)

    # 步骤 1: 部署组网
    deploy_result = client.upload_topox_and_deploy(
        topox_file=topox_file,
        version_path=version_path,
        device_type=device_type
    )

    if not deploy_result["success"]:
        print(f"❌ 部署失败: {deploy_result.get('error', deploy_result.get('data', {}).get('message'))}")
        return {
            "success": False,
            "step": "deploy",
            "error": deploy_result.get("error")
        }

    print(f"✅ 部署成功")
    deploy_data = deploy_result["data"]
    if deploy_data.get("data"):
        temp_info = deploy_data["data"]
        print(f"   临时目录: {temp_info.get('temp_dir_name', 'N/A')}")

    # 等待部署完成
    print(f"⏳ 等待部署完成...")
    time.sleep(5)

    # 步骤 2: 执行脚本
    run_result = client.upload_scripts_and_run(
        script_files=script_files,
        executor_ip=executor_ip
    )

    if not run_result["success"]:
        print(f"❌ 脚本执行失败: {run_result.get('error', run_result.get('data', {}).get('message'))}")
        # 即使执行失败，也尝试卸载
        if not skip_undeploy:
            print(f"\n⚠️  脚本执行失败，尝试清理环境...")
            client.undeploy(executor_ip=executor_ip)
        return {
            "success": False,
            "step": "run",
            "error": run_result.get("error")
        }

    print(f"✅ 脚本执行成功")

    # 步骤 3: 卸载环境
    undeploy_result = {"success": True}
    if not skip_undeploy:
        undeploy_result = client.undeploy(executor_ip=executor_ip)

        if not undeploy_result["success"]:
            print(f"⚠️  卸载失败: {undeploy_result.get('error')}")
            print(f"   请手动卸载执行机 {executor_ip}")
        else:
            print(f"✅ 卸载成功")
    else:
        print(f"\n⏭️  跳过卸载步骤（按请求）")

    # 总结
    print(f"\n{'='*70}")
    print(f"工作流程完成！")
    print(f"{'='*70}")
    print(f"部署: {'✅ 成功' if deploy_result['success'] else '❌ 失败'}")
    print(f"执行: {'✅ 成功' if run_result['success'] else '❌ 失败'}")
    print(f"卸载: {'✅ 成功' if undeploy_result['success'] else '❌ 失败/跳过'}")

    all_success = all([
        deploy_result["success"],
        run_result["success"],
        undeploy_result["success"] or skip_undeploy
    ])

    if all_success:
        print(f"\n🎉 所有步骤都成功完成！")
    else:
        print(f"\n⚠️  部分步骤失败，请检查日志")

    return {
        "success": all_success,
        "deploy": deploy_result,
        "run": run_result,
        "undeploy": undeploy_result
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Minimal ITC API - 完整工作流程演示",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整流程（使用默认参数）
  python example_all_in_one.py --topox-file test.topox --scripts conftest.py --executor-ip 10.111.8.100

  # 完整流程（指定版本路径）
  python example_all_in_one.py --topox-file test.topox --scripts conftest.py --executor-ip 10.111.8.100 --version-path /opt/version

  # 完整流程（指定设备类型）
  python example_all_in_one.py --topox-file test.topox --scripts conftest.py --executor-ip 10.111.8.100 --device-type simware9dis

  # 完整流程但跳过卸载（用于调试）
  python example_all_in_one.py --topox-file test.topox --scripts conftest.py --executor-ip 10.111.8.100 --skip-undeploy

  # 使用自定义 API 服务器
  python example_all_in_one.py --topox-file test.topox --scripts conftest.py --executor-ip 10.111.8.100 --api-url http://10.111.8.68:3001
        """
    )

    parser.add_argument(
        "--topox-file",
        required=True,
        help="Topox 文件路径（必需）"
    )
    parser.add_argument(
        "--scripts",
        nargs="+",
        required=True,
        help="脚本文件路径列表（至少一个）"
    )
    parser.add_argument(
        "--executor-ip",
        required=True,
        help="执行机 IP 地址（必需）"
    )
    parser.add_argument(
        "--version-path",
        help="版本目录路径（可选）"
    )
    parser.add_argument(
        "--device-type",
        default="simware9cen",
        choices=["simware9cen", "simware9dis", "simware7dis"],
        help="设备类型（默认: simware9cen）"
    )
    parser.add_argument(
        "--api-url",
        default=API_BASE_URL,
        help=f"API 服务器地址（默认: {API_BASE_URL}）"
    )
    parser.add_argument(
        "--skip-undeploy",
        action="store_true",
        help="跳过卸载步骤（用于调试）"
    )

    args = parser.parse_args()

    # 运行完整工作流程
    result = run_complete_workflow(
        topox_file=args.topox_file,
        script_files=args.scripts,
        executor_ip=args.executor_ip,
        version_path=args.version_path,
        device_type=args.device_type,
        api_url=args.api_url,
        skip_undeploy=args.skip_undeploy
    )

    # 根据结果设置退出码
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
