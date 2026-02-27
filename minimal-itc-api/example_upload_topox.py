#!/usr/bin/env python3
"""
示例：上传 topox 文件并部署组网

使用方式：
    python example_upload_topox.py

或指定参数：
    python example_upload_topox.py --topox-file /path/to/file.topox --version-path /path/to/version
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
API_ENDPOINT = f"{API_BASE_URL}/api/v1/upload-topox"


def upload_topox_and_deploy(
    topox_file_path: str,
    version_path: str = None,
    device_type: str = "simware9cen",
    api_url: str = API_BASE_URL
) -> dict:
    """
    上传 topox 文件并部署组网

    Args:
        topox_file_path: topox 文件路径
        version_path: 版本目录路径（可选）
        device_type: 设备类型（默认: simware9cen）
        api_url: API 服务器地址

    Returns:
        dict: API 响应结果
    """
    # 验证文件是否存在
    topox_path = Path(topox_file_path)
    if not topox_path.exists():
        return {
            "success": False,
            "error": f"文件不存在: {topox_file_path}"
        }

    # 验证文件扩展名
    if not topox_path.suffix.lower() == ".topox":
        return {
            "success": False,
            "error": f"只支持 .topox 文件，当前文件: {topox_path.suffix}"
        }

    # 准备请求数据
    url = f"{api_url}/api/v1/upload-topox"

    files = {
        "topox_file": (
            topox_path.name,
            open(topox_path, "rb"),
            "application/octet-stream"
        )
    }

    data = {
        "device_type": device_type
    }

    if version_path:
        data["version_path"] = version_path

    try:
        print(f"\n{'='*60}")
        print(f"上传 topox 文件并部署组网")
        print(f"{'='*60}")
        print(f"API 地址: {url}")
        print(f"Topox 文件: {topox_file_path}")
        print(f"文件大小: {topox_path.stat().st_size} 字节")
        if version_path:
            print(f"版本路径: {version_path}")
        print(f"设备类型: {device_type}")
        print(f"{'='*60}\n")

        # 发送请求
        response = requests.post(url, files=files, data=data, timeout=1200)

        # 关闭文件
        files["topox_file"][1].close()

        # 解析响应
        result = response.json()

        if response.status_code == 200:
            print("✅ 部署成功！")
            print(f"\n响应信息:")
            print(f"  状态: {result.get('status')}")
            print(f"  消息: {result.get('message')}")

            if result.get("data"):
                data = result["data"]
                print(f"\n部署结果:")
                if "temp_dir_name" in data:
                    print(f"  临时目录名: {data['temp_dir_name']}")
                if "temp_dir_path" in data:
                    print(f"  临时目录路径: {data['temp_dir_path']}")
                if "temp_dir_unc" in data:
                    print(f"  临时目录 UNC: {data['temp_dir_unc']}")
                if "deploy_result" in data:
                    print(f"  部署结果: {data['deploy_result']}")

            return {
                "success": True,
                "data": result
            }
        else:
            print(f"❌ 部署失败！HTTP {response.status_code}")
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
            "error": "请求超时（部署可能需要较长时间）"
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
        description="上传 topox 文件并部署组网",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法
  python example_upload_topox.py --topox-file test.topox

  # 指定版本路径
  python example_upload_topox.py --topox-file test.topox --version-path /opt/version

  # 指定设备类型
  python example_upload_topox.py --topox-file test.topox --device-type simware9dis

  # 指定 API 服务器
  python example_upload_topox.py --topox-file test.topox --api-url http://10.111.8.68:3001
        """
    )

    parser.add_argument(
        "--topox-file",
        required=True,
        help="Topox 文件路径（必需）"
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

    args = parser.parse_args()

    # 调用部署函数
    result = upload_topox_and_deploy(
        topox_file_path=args.topox_file,
        version_path=args.version_path,
        device_type=args.device_type,
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
