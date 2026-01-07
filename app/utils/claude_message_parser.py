"""
Claude Agent 消息解析工具
用于从 Claude Agent SDK 返回的消息中提取关键信息，过滤冗余内容
"""
import re
from typing import Any, Dict, List, Optional
from datetime import datetime


class ClaudeMessageParser:
    """Claude Agent 消息解析器"""

    def __init__(self):
        """初始化解析器"""
        self.step_count = 0
        self.tool_call_count = 0

    def parse_message(self, message: Any, stage: str = "") -> Dict[str, Any]:
        """
        解析 Claude Agent 返回的消息，提取关键信息

        Args:
            message: Claude Agent 返回的消息对象
            stage: 当前阶段 (conftest生成/测试脚本生成)

        Returns:
            包含关键信息的字典
        """
        message_type = type(message).__name__
        parsed_info = {
            "message_type": message_type,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "stage": stage,
            "should_log": False,
            "log_level": "info",
            "summary": "",
            "details": {}
        }

        # 根据消息类型处理
        if message_type == "AssistantMessage":
            parsed_info.update(self._parse_assistant_message(message))
        elif message_type == "ToolUseBlock":
            parsed_info.update(self._parse_tool_use_block(message))
        elif "Result" in message_type:
            parsed_info.update(self._parse_result_message(message))
        elif message_type == "TextBlock":
            parsed_info.update(self._parse_text_block(message))
        else:
            # 未知消息类型，转换为字符串并截断
            parsed_info.update({
                "should_log": True,
                "log_level": "debug",
                "summary": f"收到消息类型: {message_type}",
                "details": {"content_preview": str(message)[:200]}
            })

        return parsed_info

    def _parse_assistant_message(self, message: Any) -> Dict[str, Any]:
        """解析 AssistantMessage 消息"""
        result = {
            "should_log": False,
            "log_level": "debug"
        }

        try:
            if hasattr(message, 'content'):
                content = message.content

                # 提取文本内容
                text_content = self._extract_text_from_content(content)

                # 检查是否包含关键信息
                keywords = [
                    "正在", "开始", "完成", "成功", "失败", "错误",
                    "generating", "generated", "completed", "error", "failed"
                ]

                has_keyword = any(keyword in text_content.lower() for keyword in keywords)

                # 提取关键动作
                action = self._extract_action(text_content)

                if action or has_keyword:
                    result.update({
                        "should_log": True,
                        "log_level": "info",
                        "summary": action or "Claude 思考中...",
                        "details": {
                            "content_preview": text_content[:150] if len(text_content) > 150 else text_content
                        }
                    })
                else:
                    # 不记录完整的思考过程
                    result.update({
                        "should_log": False,
                        "summary": "思考中..."
                    })

        except Exception as e:
            result.update({
                "should_log": True,
                "log_level": "warning",
                "summary": f"解析 AssistantMessage 失败: {str(e)}"
            })

        return result

    def _parse_tool_use_block(self, message: Any) -> Dict[str, Any]:
        """解析 ToolUseBlock 消息（工具调用）"""
        result = {
            "should_log": True,
            "log_level": "info"
        }

        try:
            self.tool_call_count += 1

            tool_name = "未知工具"
            tool_input = {}

            if hasattr(message, 'name'):
                tool_name = message.name

            if hasattr(message, 'input'):
                tool_input = message.input

            # 格式化工具调用信息
            summary = f"[工具调用 #{self.tool_call_count}] {tool_name}"

            # 提取关键参数
            important_params = self._extract_important_params(tool_name, tool_input)

            result.update({
                "summary": summary,
                "details": {
                    "tool_name": tool_name,
                    "params": important_params,
                    "call_count": self.tool_call_count
                }
            })

        except Exception as e:
            result.update({
                "log_level": "warning",
                "summary": f"解析工具调用失败: {str(e)}"
            })

        return result

    def _parse_result_message(self, message: Any) -> Dict[str, Any]:
        """解析 ResultMessage 消息（工具执行结果）"""
        result = {
            "should_log": True,
            "log_level": "info"
        }

        try:
            is_error = False
            error_msg = ""

            if hasattr(message, 'is_error'):
                is_error = message.is_error

            if hasattr(message, 'result'):
                result_content = str(message.result)
                error_msg = result_content

            if is_error:
                result.update({
                    "log_level": "error",
                    "summary": f"[工具执行失败] {error_msg[:100]}",
                    "details": {"error": error_msg}
                })
            else:
                # 成功的结果，简要记录
                result.update({
                    "summary": "[工具执行完成]",
                    "details": {"status": "success"}
                })

        except Exception as e:
            result.update({
                "log_level": "warning",
                "summary": f"解析结果消息失败: {str(e)}"
            })

        return result

    def _parse_text_block(self, message: Any) -> Dict[str, Any]:
        """解析 TextBlock 消息"""
        result = {
            "should_log": False,
            "log_level": "debug"
        }

        try:
            if hasattr(message, 'text'):
                text = message.text

                # 只记录包含关键信息的文本
                if any(keyword in text.lower() for keyword in ["完成", "成功", "generated", "completed", "文件", "file"]):
                    result.update({
                        "should_log": True,
                        "log_level": "info",
                        "summary": text[:100],
                        "details": {"text": text[:200]}
                    })

        except Exception as e:
            result.update({
                "should_log": True,
                "log_level": "warning",
                "summary": f"解析文本块失败: {str(e)}"
            })

        return result

    def _extract_text_from_content(self, content: Any) -> str:
        """从 content 中提取文本内容"""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            texts = []
            for item in content:
                if hasattr(item, 'text'):
                    texts.append(item.text)
                elif isinstance(item, str):
                    texts.append(item)
            return '\n'.join(texts)
        else:
            return str(content)

    def _extract_action(self, text: str) -> Optional[str]:
        """从文本中提取关键动作"""
        # 定义动作模式
        action_patterns = [
            r'(正在|开始)(.*?)？',
            r'(调用|使用|执行)(.*?)工具',
            r'(生成|创建|写入|保存)(.*?)文件',
            r'(读取|分析)(.*?)文件',
            r'(Generated|Creating|Writing|Saving) (.+)',
        ]

        for pattern in action_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)

        return None

    def _extract_important_params(self, tool_name: str, tool_input: Dict) -> Dict[str, Any]:
        """提取重要的工具参数"""
        important_params = {}

        # 根据工具类型提取重要参数
        if tool_name == "Write":
            # Write 工具：记录文件路径
            if "path" in tool_input:
                important_params["file"] = tool_input["path"]
            if "content" in tool_input:
                content = tool_input["content"]
                # 只记录内容长度，不记录完整内容
                important_params["size"] = f"{len(content)} bytes"

        elif tool_name == "Read":
            # Read 工具：记录文件路径
            if "path" in tool_input:
                important_params["file"] = tool_input["path"]

        elif tool_name == "Bash":
            # Bash 工具：记录命令（不记录完整输出）
            if "command" in tool_input:
                important_params["command"] = tool_input["command"]

        elif tool_name == "Edit":
            # Edit 工具：记录文件路径和编辑操作
            if "path" in tool_input:
                important_params["file"] = tool_input["path"]
            if "operation" in tool_input:
                important_params["operation"] = tool_input["operation"]

        else:
            # 其他工具：记录所有键（但不记录值）
            important_params["keys"] = list(tool_input.keys())

        return important_params

    def format_log_entry(self, parsed_info: Dict[str, Any]) -> str:
        """
        将解析后的信息格式化为日志条目

        Args:
            parsed_info: parse_message 返回的解析结果

        Returns:
            格式化的日志字符串
        """
        if not parsed_info["should_log"]:
            return ""

        stage_prefix = f"[{parsed_info['stage']}] " if parsed_info['stage'] else ""
        level_icon = {
            "info": "ℹ️",
            "warning": "⚠️",
            "error": "❌",
            "debug": "🔍"
        }.get(parsed_info["log_level"], "•")

        log_parts = [f"{level_icon} {parsed_info['summary']}"]

        # 添加详细信息
        details = parsed_info.get("details", {})
        if details:
            if "tool_name" in details:
                log_parts.append(f"  工具: {details['tool_name']}")
            if "params" in details and details["params"]:
                params_str = ", ".join(f"{k}={v}" for k, v in details["params"].items())
                log_parts.append(f"  参数: {params_str}")
            if "content_preview" in details:
                preview = details["content_preview"]
                if len(preview) > 100:
                    preview = preview[:100] + "..."
                log_parts.append(f"  内容: {preview}")
            if "error" in details:
                log_parts.append(f"  错误: {details['error']}")

        return '\n'.join(log_parts)

    def reset_counters(self):
        """重置计数器"""
        self.step_count = 0
        self.tool_call_count = 0
