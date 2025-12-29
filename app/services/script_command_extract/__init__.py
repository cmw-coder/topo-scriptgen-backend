"""
Script Command Extract Package

此包提供从日志文件中提取命令信息的功能。

AI_FingerPrint_UUID: 20251225-LqMnN8Pk
"""

# 从 agent_helper 模块导出旧版本的功能，以保持向后兼容
from app.services.script_command_extract.agent_helper import (
    ExtractCommandAgent as LegacyExtractCommandAgent,
    filename_command_mapping,
    refresh_static_variables
)

# 为了向后兼容，同时使用新的名称导出
ExtractCommandAgent = LegacyExtractCommandAgent

__all__ = [
    'ExtractCommandAgent',
    'filename_command_mapping',
    'refresh_static_variables'
]
