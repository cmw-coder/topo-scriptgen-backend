#!/usr/bin/env python3
"""
示例：卸载组网环境

使用方式：
    python example_undeploy.py

或指定参数：
    python example_undeploy.py --executor-ip 10.111.8.100
"""

import argparse
import sys

try:
    import requests
except ImportError:
    print("错误: 需要安装 requests 库")
    print("请运行: pip install requests")
    sys.exit(1)


# API 配置
API_BASE_URL = "http://localhost:3001"
API_ENDPOINT = f"{API_BASE_URL}/api/v1/undeploy"


def undeploy_environment(
    executor_ip: str,
    api_url: str = API_BASE_URL
) -> dict:
    """
    卸载组网环境

    Args:
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

    # 准备请求数据
    url = f"{api_url}/api/v1/undeploy"

    data = {
        "executor_ip": executor_ip
    }

    try:
        print(f"\n{'='*60}")
        print(f"卸载组网环境")
        print(f"{'='*60}")
        print(f"API 地址: {url}")
        print(f"执行机 IP: {executor_ip}")
        print(f"{'='*60}\n")

        # 发送请求
        response = requests.post(url, data=data, timeout=300)

        # 解析响应
        result = response.json()

        if response.status_code == 200:
            print("✅ 卸载成功！")
            print(f"\n响应信息:")
            print(f"  状态: {result.get('status')}")
            print(f"  消息: {result.get('message')}")

            if result.get("data"):
                data = result["data"]
                print(f"\n卸载结果:")
                if "executor_ip" in data:
                    print(f"  执行机 IP: {data['executor_ip']}")
                if "undeploy_result" in data:
                    print(f"  详细结果: {data['undeploy_result']}")

            return {
                "success": True,
                "data": result
            }
        else:
            print(f"❌ 卸载失败！HTTP {response.status_code}")
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
            "error": "请求超时（卸载可能需要较长时间）"
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
        description="卸载组网环境",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法
  python example_undeploy.py --executor-ip 10.111.8.100

  # 指定 API 服务器
  python example_undeploy.py --executor-ip 10.111.8.100 --api-url http://10.111.8.68:3001

  # 批量卸载多个执行机（bash）
  for ip in 10.111.8.100 10.111.8.101 10.111.8.102; do
    python example_undeploy.py --executor-ip $ip
  done
        """
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

    # 调用卸载函数
    result = undeploy_environment(
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
