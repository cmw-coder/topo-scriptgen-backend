"""
Claude Agent 消息解析工具
用于从 Claude Agent SDK 返回的消息中提取关键信息，过滤冗余内容

优化策略：
1. 完全过滤 UserMessage/SystemMessage 等底层消息
2. 只记录有意义的工具调用和执行结果
3. 提取并展示关键进度信息和总结内容
"""
import re
from typing import Any, Dict, List, Optional
from datetime import datetime


class ClaudeMessageParser:
    """Claude Agent 消息解析器 - 优化版"""

    # 定义需要完全过滤的消息类型
    FILTERED_MESSAGE_TYPES = {
        "UserMessage", "SystemMessage", "InitMessage",
        "request", "response"
    }

    # 定义需要提取总结的关键词
    SUMMARY_KEYWORDS = [
        "任务完成", "完成总结", "生成完成", "创建完成",
        "✓", "✗", "成功", "失败", "Phase", "阶段",
        "已完成", "successfully", "completed", "finished",
        "任务完成总结", "执行结果"
    ]

    def __init__(self):
        """初始化解析器"""
        self.step_count = 0
        self.tool_call_count = 0
        self.last_assistant_content = ""

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

        # 完全过滤底层消息类型
        if message_type in self.FILTERED_MESSAGE_TYPES:
            return {
                **parsed_info,
                "should_log": False
            }

        # 根据消息类型处理
        if message_type == "AssistantMessage":
            parsed_info.update(self._parse_assistant_message(message))
        elif message_type == "ToolUseBlock":
            parsed_info.update(self._parse_tool_use_block(message))
        elif "Result" in message_type or "ToolResultBlock" in message_type:
            parsed_info.update(self._parse_result_message(message))
        elif message_type == "TextBlock":
            parsed_info.update(self._parse_text_block(message))
        else:
            # 其他未知消息类型，默认不记录
            parsed_info.update({
                "should_log": False
            })

        return parsed_info

    def _parse_assistant_message(self, message: Any) -> Dict[str, Any]:
        """解析 AssistantMessage 消息 - 保留思考过程"""
        result = {
            "should_log": False,
            "log_level": "info"
        }

        try:
            if hasattr(message, 'content'):
                content = message.content

                # 提取文本内容
                text_content = self._extract_text_from_content(content)
                self.last_assistant_content = text_content

                # 检查是否包含总结性信息
                if self._contains_summary_keywords(text_content):
                    # 提取总结内容
                    summary_lines = self._extract_summary_content(text_content)
                    if summary_lines:
                        result.update({
                            "should_log": True,
                            "log_level": "info",
                            "summary": "📊 阶段总结",
                            "details": {
                                "summary_text": summary_lines
                            }
                        })
                        return result

                # 提取有意义的思考内容（过滤过于简短或无意义的内容）
                meaningful_text = self._extract_meaningful_content(text_content)
                if meaningful_text:
                    result.update({
                        "should_log": True,
                        "log_level": "info",
                        "summary": "💭 思考中...",
                        "details": {
                            "thought_content": meaningful_text
                        }
                    })

        except Exception as e:
            # 解析失败也记录，避免丢失信息
            result.update({
                "should_log": True,
                "log_level": "warning",
                "summary": "⚠️ 消息解析异常",
                "details": {"error": str(e)}
            })

        return result

    def _parse_tool_use_block(self, message: Any) -> Dict[str, Any]:
        """解析 ToolUseBlock 消息（工具调用）- 优化版"""
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

            # 只记录重要的工具调用
            if not self._is_important_tool(tool_name):
                result["should_log"] = False
                return result

            # 格式化工具调用信息 - 简洁版
            summary = self._format_tool_call_summary(tool_name, tool_input)

            # 提取关键参数
            important_params = self._extract_important_params(tool_name, tool_input)

            result.update({
                "summary": summary,
                "details": {
                    "tool_name": tool_name,
                    "params": important_params
                }
            })

        except Exception as e:
            # 工具调用失败也不记录
            result["should_log"] = False

        return result

    def _parse_result_message(self, message: Any) -> Dict[str, Any]:
        """解析 ResultMessage 消息（工具执行结果）- 优化版"""
        result = {
            "should_log": False,  # 默认不记录
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

            # 只记录错误结果
            if is_error:
                result.update({
                    "should_log": True,
                    "log_level": "error",
                    "summary": f"❌ 工具执行失败",
                    "details": {"error": self._truncate_text(error_msg, 200)}
                })
            # 成功的结果不再记录，减少日志冗余

        except Exception as e:
            # 解析失败也不记录
            result["should_log"] = False

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

    def _contains_summary_keywords(self, text: str) -> bool:
        """检查文本是否包含总结关键词"""
        text_lower = text.lower()
        return any(keyword.lower() in text_lower for keyword in self.SUMMARY_KEYWORDS)

    def _extract_summary_content(self, text: str) -> Optional[str]:
        """提取总结内容"""
        lines = text.split('\n')
        summary_lines = []

        # 查找包含总结关键词的部分
        in_summary = False
        for line in lines:
            # 检查是否进入总结部分
            if any(keyword in line for keyword in self.SUMMARY_KEYWORDS):
                in_summary = True

            if in_summary:
                summary_lines.append(line)

                # 如果遇到空行或明显的分隔符，可以考虑停止
                if line.strip() == '' and len(summary_lines) > 3:
                    break

        if summary_lines:
            return '\n'.join(summary_lines[:20])  # 最多20行
        return None

    def _is_important_action(self, text: str) -> bool:
        """判断是否是重要的动作"""
        important_patterns = [
            r'生成.*文件', r'创建.*文件', r'写入.*文件',
            r'已完成', r'✓', r'成功',
            r'Phase \d+:', r'阶段\d+'
        ]

        return any(re.search(pattern, text) for pattern in important_patterns)

    def _is_important_tool(self, tool_name: str) -> bool:
        """判断工具是否重要（需要记录）"""
        # 这些工具调用不重要，不记录
        unimportant_tools = {
            "Grep", "Glob",  # 搜索类工具
        }

        # 这些工具重要，需要记录
        important_tools = {
            "Write", "Read", "Edit", "Bash"
        }

        return tool_name in important_tools

    def _format_tool_call_summary(self, tool_name: str, tool_input: Dict) -> str:
        """格式化工具调用摘要"""
        if tool_name == "Write":
            file_path = tool_input.get("path", "")
            file_name = file_path.split("/")[-1] if file_path else "文件"
            return f"📝 正在生成 {file_name}"

        elif tool_name == "Read":
            file_path = tool_input.get("path", "")
            file_name = file_path.split("/")[-1] if file_path else "文件"
            return f"📖 读取 {file_name}"

        elif tool_name == "Edit":
            file_path = tool_input.get("path", "")
            return f"✏️ 编辑文件"

        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            return f"⚡ 执行命令: {command[:50]}..."

        return f"🔧 调用工具: {tool_name}"

    def _truncate_text(self, text: str, max_length: int) -> str:
        """截断文本"""
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    def _extract_meaningful_content(self, text: str) -> Optional[str]:
        """提取有意义的思考内容"""
        # 移除过短的内容
        if len(text.strip()) < 20:
            return None

        # 分割成行
        lines = text.split('\n')
        meaningful_lines = []

        for line in lines:
            line = line.strip()

            # 跳过空行
            if not line:
                continue

            # 跳过单字符或符号行
            if len(line) <= 2:
                continue

            # 跳过纯标点符号或特殊符号
            if line in ['...', '---', '***', '===']:
                continue

            meaningful_lines.append(line)

        # 如果没有有意义的行，返回None
        if not meaningful_lines:
            return None

        # 限制行数，避免过长
        result_text = '\n'.join(meaningful_lines[:10])

        # 如果总文本长度太长，截断
        if len(result_text) > 500:
            result_text = result_text[:500] + "\n..."

        return result_text

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
        将解析后的信息格式化为日志条目 - 保留思考过程版

        Args:
            parsed_info: parse_message 返回的解析结果

        Returns:
            格式化的日志字符串
        """
        if not parsed_info["should_log"]:
            return ""

        details = parsed_info.get("details", {})
        log_parts = []
        summary = parsed_info.get("summary", "")

        # 如果是总结内容，特殊格式化
        if "summary_text" in details:
            summary_text = details["summary_text"]
            log_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            log_parts.append(f"📊 {summary}")
            log_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # 将总结内容格式化
            lines = summary_text.split('\n')
            for line in lines[:15]:  # 最多15行
                if line.strip():
                    log_parts.append(f"  {line.strip()}")

            log_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            return '\n'.join(log_parts)

        # 如果是思考内容，格式化显示
        if "thought_content" in details:
            thought = details["thought_content"]
            log_parts.append(f"{summary}")

            # 格式化思考内容，保持可读性
            lines = thought.split('\n')
            for line in lines:
                if line.strip():
                    log_parts.append(f"   {line}")

            return '\n'.join(log_parts)

        # 如果是错误信息
        if parsed_info["log_level"] == "error":
            log_parts.append(f"❌ {summary}")
            if "error" in details:
                log_parts.append(f"   {details['error']}")
            return '\n'.join(log_parts)

        # 普通信息（工具调用等）
        log_parts.append(summary)

        # 添加简要详情
        if "params" in details and details["params"]:
            if "file" in details["params"]:
                log_parts.append(f"   📄 {details['params']['file']}")
            elif "command" in details["params"]:
                cmd = details["params"]["command"]
                if len(cmd) > 60:
                    cmd = cmd[:60] + "..."
                log_parts.append(f"   💻 {cmd}")

        return '\n'.join(log_parts)

    def reset_counters(self):
        """重置计数器"""
        self.step_count = 0
        self.tool_call_count = 0
