"""
NETCONF 服务模块

提供 NETCONF 测试脚本的生成、运行和调试功能
"""

# 工作流模块
from app.services.netconf.netconf_workflow import (
    execute_netconf_workflow,
    parse_and_fix_result,
    setup_agent_environment,
)

# 准备材料模块
from app.services.netconf.prepare_materials import (
    prepare_dependencies,
    call_netconf_material_preparation_skill,
    get_netconf_output_dir,
    get_output_dir,
)

# 脚本生成模块
from app.services.netconf.generate_scripts import (
    generate_netconf_scripts,
)

# 脚本运行模块
from app.services.netconf.run_scripts import (
    run_netconf_scripts,
)

# 脚本修复模块
from app.services.netconf.fix_scripts import (
    parse_script_return_info,
    _fix_scripts_for_subdir,
    _call_claude_agent_for_fix,
)

__all__ = [
    # 工作流函数
    "execute_netconf_workflow",
    "generate_netconf_scripts",
    "run_netconf_scripts",  # 新版运行函数（独立模块）
    "parse_and_fix_result",
    "parse_script_return_info",  # 解析单个脚本的 return_info
    "_fix_scripts_for_subdir",  # 修复单个子文件夹中的脚本
    "_call_claude_agent_for_fix",  # 调用 Claude Agent 进行修复
    "setup_agent_environment",

    # 准备材料函数
    "prepare_dependencies",
    "call_netconf_material_preparation_skill",
    "get_netconf_output_dir",
    "get_output_dir",
]
