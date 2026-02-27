#!/usr/bin/env python3
"""
示例：批量上传脚本文件并执行

使用方式：
    python example_upload_scripts.py

或指定参数：
    python example_upload_scripts.py --scripts conftest.py test_demo.py --executor-ip 10.111.8.100
"""

import argparse
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库")
    print("请运行: pip install requests")
    sys.exit(1)


# API 配置
API_BASE_URL = "http://localhost:3001"
API_ENDPOINT = f"{API_BASE_URL}/api/v1/upload-scripts"


def upload_scripts_and_run(
    script_files: list,
    executor_ip: str,
    api_url: str = API_BASE_URL
) -> dict:
    """
    批量上传脚本文件并执行

    Args:
        script_files: 脚本文件路径列表
        executor_ip: 执行机 IP 地址
        api_url: API 服务器地址

    Returns:
        dict: API 响应结果
    """
    # 验证执行机 IP
    if not executor_ip:
        return {
            "success": False,
            "error": "必须提供执行机 IP 地址"
        }

    # 验证脚本文件
    valid_files = []
    for file_path in script_files:
        path = Path(file_path)
        if not path.exists():
            print(f"警告: 文件不存在，跳过: {file_path}")
            continue

        valid_files.append(path)

    if not valid_files:
        return {
            "success": False,
            "error": "没有有效的脚本文件"
        }

    # 准备请求数据
    url = f"{api_url}/api/v1/upload-scripts"

    # 准备文件列表
    files = []
    for script_path in valid_files:
        files.append((
            "script_files",
            (
                script_path.name,
                open(script_path, "rb"),
                "application/octet-stream"
            )
        ))

    data = {
        "executor_ip": executor_ip
    }

    try:
        print(f"\n{'='*60}")
        print(f"批量上传脚本文件并执行")
        print(f"{'='*60}")
        print(f"API 地址: {url}")
        print(f"执行机 IP: {executor_ip}")
        print(f"脚本文件数量: {len(valid_files)}")
        print(f"脚本文件列表:")
        for i, script_path in enumerate(valid_files, 1):
            print(f"  {i}. {script_path.name} ({script_path.stat().st_size} 字节)")
        print(f"{'='*60}\n")

        # 发送请求
        response = requests.post(url, files=files, data=data, timeout=1200)

        # 关闭所有文件
        for item in files:
            item[1][1].close()

        # 解析响应
        result = response.json()

        if response.status_code == 200:
            print("✅ 脚本执行成功！")
            print(f"\n响应信息:")
            print(f"  状态: {result.get('status')}")
            print(f"  消息: {result.get('message')}")

            if result.get("data"):
                data = result["data"]
                print(f"\n执行结果:")

                if "temp_dir_name" in data:
                    print(f"  临时目录名: {data['temp_dir_name']}")
                if "temp_dir_path" in data:
                    print(f"  临时目录路径: {data['temp_dir_path']}")
                if "temp_dir_unc" in data:
                    print(f"  临时目录 UNC: {data['temp_dir_unc']}")

                if "saved_files" in data:
                    print(f"  已保存文件:")
                    for saved_file in data["saved_files"]:
                        print(f"    - {saved_file['filename']} ({saved_file['size']} 字节)")

                if "run_result" in data:
                    print(f"  运行结果: {data['run_result']}")

            return {
                "success": True,
                "data": result
            }
        else:
            print(f"❌ 脚本执行失败！HTTP {response.status_code}")
            print(f"\n错误信息:")
            print(f"  状态: {result.get('status')}")
            print(f"  消息: {result.get('message')}")
            if result.get("data"):
                print(f"  详细信息: {result['data']}")

            return {
                "success": False,
                "error": result.get("message", "未知错误"),
                "data": result
            }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "请求超时（脚本执行可能需要较长时间）"
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"无法连接到 API 服务器: {api_url}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"请求异常: {str(e)}"
        }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="批量上传脚本文件并执行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 上传单个脚本
  python example_upload_scripts.py --scripts conftest.py --executor-ip 10.111.8.100

  # 上传多个脚本
  python example_upload_scripts.py --scripts conftest.py test_demo.py --executor-ip 10.111.8.100

  # 使用通配符（bash）
  python example_upload_scripts.py --scripts *.py --executor-ip 10.111.8.100

  # 指定 API 服务器
  python example_upload_scripts.py --scripts conftest.py --executor-ip 10.111.8.100 --api-url http://10.111.8.68:3001
        """
    )

    parser.add_argument(
        "--scripts",
        nargs="+",
        required=True,
        help="脚本文件路径（至少一个，支持多个）"
    )
    parser.add_argument(
        "--executor-ip",
        required=True,
        help="执行机 IP 地址（必需）"
    )
    parser.add_argument(
        "--api-url",
        default=API_BASE_URL,
        help=f"API 服务器地址（默认: {API_BASE_URL}）"
    )

    args = parser.parse_args()

    # 调用执行函数
    result = upload_scripts_and_run(
        script_files=args.scripts,
        executor_ip=args.executor_ip,
        api_url=args.api_url
    )

    # 根据结果设置退出码
    if result.get("success"):
        sys.exit(0)
    else:
        print(f"\n错误: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
