import asyncio
import os
import json
import sys
from datetime import datetime
import getpass
from claude_agent_sdk import (
    query, 
    ClaudeAgentOptions, 
    AssistantMessage, 
    ToolUseBlock, 
    TextBlock
)

# 添加当前目录到 Python 路径
sys.path.append(os.path.dirname(__file__))

# 导入 TodoAnalyzer 类
from todo_analyzer import TodoAnalyzer

# -------------------------------------------------------------------------
# 1. 环境配置与清理
# -------------------------------------------------------------------------

# 要删除的代理环境变量
proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
for var in proxy_vars:
    os.environ.pop(var, None)

print("已成功清除代理环境变量")

# 设置Anthropic相关环境变量
os.environ["ANTHROPIC_BASE_URL"] = "http://10.144.41.149:4000/"
os.environ["ANTHROPIC_AUTH_TOKEN"] = "xx"

def escape_all_special_chars(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)[1:-1]


# -------------------------------------------------------------------------
# 2. 本地分析函数
# -------------------------------------------------------------------------
async def stream_analyze_todo_logs(log_path: str, export_file: str = "todo_analysis.json"):
    """分析 Todo 日志并流式返回结果 (本地 Python 处理)"""
    print(f"📂 [本地分析] 扫描路径: {log_path}")
    print(f"💾 [本地分析] 导出目标: {export_file}")
    
    if not os.path.exists(log_path):
        yield f"❌ 路径不存在: {log_path}"
        return
    
    try:
        analyzer = TodoAnalyzer()
        
        # 检查是文件夹还是文件
        if os.path.isdir(log_path):
            # 保持与 todo_analyzer.py 一致的行为，扫描所有 JSONL 文件
            print(f"🔍 正在扫描文件夹中的所有 JSONL 文件...")
            analyzer.load_directory(log_path)
        elif os.path.isfile(log_path):
            # 如果是单个文件，直接加载
            print(f"📄 正在加载单个 JSONL 文件...")
            analyzer.load_log_file(log_path)
        else:
            yield f"❌ 无效的路径: {log_path}"
            return
        
        if analyzer.total_todos == 0:
            yield "⚠️  没有找到任何 Todo 数据"
            return
        
        yield f"📊 发现 {analyzer.total_todos} 条 Todo，正在导出..."
        
        # 导出数据 (路径已由调用方指定为子文件夹内)
        analyzer.export_to_json(export_file)
        
        yield f"✅ 本地分析完成！结果已保存。"
        
    except Exception as e:
        yield f"❌ 分析过程中发生错误: {e}"


# -------------------------------------------------------------------------
# 3. Agent 分析函数
# -------------------------------------------------------------------------
async def stream_analyze_todo_with_agent(log_path: str, workspace: str, export_file: str):
    """使用 Claude Agent SDK 分析 Todo 日志"""
    
    print(f"📂 [Agent分析] 工作区(CWD)切换至: {workspace}")

    # 确保工作区存在 (理论上就是日志目录本身，肯定存在)
    if not os.path.exists(workspace):
        os.makedirs(workspace, exist_ok=True)

    options = ClaudeAgentOptions(
        # 关键修改：将 CWD 直接设置为 log 的子文件夹
        cwd=workspace, 
        setting_sources=["user"], 
        permission_mode="bypassPermissions",
        allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],
    )

    print(f"📄 正在解析{log_path}目录内容...")
    try:
        log_content = ""
        with open(log_path, 'r', encoding='utf-8') as f:
            log_content = f.read()
    
    except Exception as e:
        print(f"❌ 解析日志失败: {e}")
        return

    print(f"🚀 发送 Agent 请求，要求保存为: {export_file}")
    
    
    prompt_text = f"调用skill : todo-log-analysis, 分析的todo日志\n, \n 读取{log_path}\n\n 请分析这些 Todo 日志，提供详细的分析报告。\n 【重要任务】将分析结果保存为 JSON 格式文件，文件名为: {export_file}。\n 注意：你当前的工作目录已经是 '{workspace}' 文件夹，请直接写入该文件名，不要创建任何父级目录。"

    

    prompt = escape_all_special_chars(prompt_text)
    print(prompt)
    try:
        async for message in query(
            prompt=prompt, 
            options=options
        ):
            yield message
    except Exception as e:
        print(f"❌ Agent 请求发生错误: {e}")



# -------------------------------------------------------------------------
# 3.5 单个子文件夹处理函数
# -------------------------------------------------------------------------
async def process_single_subfolder(folder_path: str, folder_name: str, index: int = None, total: int = None):
    """处理单个子文件夹中的 Todo 日志
    
    Args:
        folder_path: 子文件夹的完整路径
        folder_name: 子文件夹的名称
        index: 当前处理的子文件夹索引（可选）
        total: 子文件夹总数（可选）
    
    Returns:
        dict or bool: 如果处理成功且有Agent分析结果，则返回Agent分析的JSON数据；
                     如果处理成功但没有Agent分析结果，则返回True；
                     如果处理失败，则返回False
    """
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    if index is not None and total is not None:
        print(f"🔄 [{index}/{total}] 正在处理文件夹: {folder_name}")
    else:
        print(f"🔄 正在处理文件夹: {folder_name}")
    print(f"📂 路径: {folder_path}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # 查找文件名不包含"agent"的最新JSONL文件
    jsonl_files = []
    for file_name in os.listdir(folder_path):
        if file_name.endswith('.jsonl') and 'agent' not in file_name.lower():
            file_path = os.path.join(folder_path, file_name)
            # 获取文件的修改时间
            mtime = os.path.getmtime(file_path)
            jsonl_files.append((mtime, file_name, file_path))
    
    # 如果没有找到符合条件的文件，跳过该文件夹
    if not jsonl_files:
        print("⚠️  该文件夹中没有找到不包含 'agent' 的 JSONL 文件")
        print("\n")
        return False
    
    # 按修改时间排序，取最新的文件
    jsonl_files.sort(reverse=True)  # 最新的文件在前面
    latest_file_mtime, latest_file_name, latest_file_path = jsonl_files[0]
    
    print(f"✅ 找到最新的 JSONL 文件: {latest_file_name}")
    print(f"📅 修改时间: {datetime.fromtimestamp(latest_file_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 定义输出文件名 (为了避免混乱，我还是带上了文件夹名前缀，但您也可以改成固定的名字)
    # 例如: cc_log/folder_A/todo_analysis_local_folder_A.json
    local_filename = f"todo_analysis_local.json"
    agent_filename = f"todo_analysis_agent.json"

    # -------------------------------------------------
    # 步骤 1: 本地分析器
    # 导出路径 = folder_path + filename
    # -------------------------------------------------
    local_export_full_path = os.path.join(folder_path, local_filename)
    
    print(f"\n👉 [1] 本地分析器")
    try:
        async for result in stream_analyze_todo_logs(
            log_path=latest_file_path,  # 使用最新的文件路径而不是文件夹路径
            export_file=local_export_full_path
        ):
            print(result)
        
        # 读取生成的本地分析JSON文件
        print(f"\n📖 正在读取本地分析结果文件: {local_filename}")
        try:
            # 检查文件是否存在
            if not os.path.exists(local_export_full_path):
                print(f"⚠️  本地分析结果文件不存在，可能是因为没有找到Todo数据")
                return True  # 没有Todo数据也是一种正常情况，不应返回失败
            
            with open(local_export_full_path, 'r', encoding='utf-8') as f:
                local_analysis_data = json.load(f)
            print(f"✅ 成功读取本地分析结果，包含 {local_analysis_data.get('total_todos', 0)} 条 Todo 记录")
        except Exception as e:
            print(f"❌ 读取本地分析结果文件失败: {e}")
            return False
    except Exception as e:
        print(f"❌ 本地分析出错: {e}")
        return False
    
    # -------------------------------------------------
    # 步骤 2: Claude Agent 分析
    # 工作区(CWD) = folder_path
    # -------------------------------------------------
    print(f"\n👉 [2] Claude Agent 分析")
    try:
        async for msg in stream_analyze_todo_with_agent(
            log_path=local_export_full_path, 
            workspace=folder_path,  # <--- 核心：工作区就是当前Log文件夹
            export_file=agent_filename      # <--- 核心：只需文件名，自动保存到工作区
        ):
            if isinstance(msg, TextBlock):
                # 避免打印太多，截取前100字符
                text_preview = msg.text[:100].replace('\n', ' ') + "..." if len(msg.text) > 100 else msg.text
                print(f"🤖 Agent: {text_preview}")
            elif hasattr(msg, 'message'):
                 print(f"📥 收到消息: {type(msg).__name__}")
            else:
                 pass # 过滤掉一些不想看到的中间状态
                      
        # 读取生成的Agent分析JSON文件
        agent_export_full_path = os.path.join(folder_path, agent_filename)
        print(f"\n📖 正在读取Agent分析结果文件: {agent_filename}")
        agent_analysis_data = None
        try:
            # 检查文件是否存在
            if not os.path.exists(agent_export_full_path):
                print(f"⚠️  Agent分析结果文件不存在")
                print("\n")
                return True  # Agent分析失败也是一种正常情况，不应返回失败
            
            with open(agent_export_full_path, 'r', encoding='utf-8') as f:
                agent_analysis_data = json.load(f)
            print(f"✅ 成功读取Agent分析结果")
            # 打印Agent分析结果的基本信息
            if isinstance(agent_analysis_data, dict):
                if 'summary' in agent_analysis_data:
                    summary = agent_analysis_data['summary']
                    if isinstance(summary, str):
                        print(f"📋 Agent分析摘要: {summary[:100]}...")
                    else:
                        print(f"📋 Agent分析摘要: {summary}")
                elif 'total_todos' in agent_analysis_data:
                    print(f"📋 Agent分析结果包含 {agent_analysis_data['total_todos']} 条 Todo 记录")
        except Exception as e:
            print(f"❌ 读取Agent分析结果文件失败: {e}")
            return False
    except Exception as e:
        print(f"❌ Agent 分析出错: {e}")
        return False
    
    print("\n")
    return agent_analysis_data if agent_analysis_data is not None else True


# -------------------------------------------------------------------------
# 4. 主函数
# -------------------------------------------------------------------------
async def main():
    print("--- 开始 Todo 日志目录批量分析流程 ---")
    print("")
    
    # 基础配置
    base_log_dir = r"D:\yang_xml\claude_code_code\new_agent_log"
    
    if not os.path.exists(base_log_dir):
        print(f"❌ 错误: 日志根目录 {base_log_dir} 不存在")
        return
        
    print(f"📂 正在扫描目录: {base_log_dir}")
    
    try:
        entries = os.listdir(base_log_dir)
    except Exception as e:
        print(f"❌ 无法读取目录: {e}")
        return

    # 筛选出所有子文件夹
    subdirs = [
        d for d in entries 
        if os.path.isdir(os.path.join(base_log_dir, d))
    ]
    subdirs.sort()
    
    if not subdirs:
        print("⚠️  该目录下没有找到子文件夹。")
        return
        
    print(f"📁 找到 {len(subdirs)} 个子文件夹等待处理。\n")

    # 遍历每个子文件夹
    success_count = 0
    agent_results = []  # 存储Agent分析结果
    
    for index, folder_name in enumerate(subdirs, 1):
        # 1. 获取当前子文件夹的完整路径
        current_folder_path = os.path.join(base_log_dir, folder_name)
        
        # 2. 调用封装好的函数处理单个子文件夹
        result = await process_single_subfolder(current_folder_path, folder_name, index, len(subdirs))
        
        # 3. 处理返回结果
        if result is not False:
            success_count += 1
            if isinstance(result, dict):
                # 是Agent分析结果，添加到结果列表
                agent_results.append({
                    'folder_name': folder_name,
                    'folder_path': current_folder_path,
                    'analysis_data': result
                })
                print(f"📋 已保存 {folder_name} 的Agent分析结果")

    print("--- 所有文件夹处理结束 ---")
    print(f"✅ 成功处理 {success_count} 个文件夹")
    print(f"❌ 处理失败 {len(subdirs) - success_count} 个文件夹")
    print(f"📊 收集到 {len(agent_results)} 个Agent分析结果")
    print("")
    
    # 可以在这里选择进一步处理或保存Agent分析结果
    if agent_results:
        print("📁 Agent分析结果摘要：")
        for i, result in enumerate(agent_results, 1):
            print(f"  {i}. {result['folder_name']}")
            if isinstance(result['analysis_data'], dict):
                if 'total_todos' in result['analysis_data']:
                    print(f"     - Todo数量: {result['analysis_data']['total_todos']}")
                if 'summary' in result['analysis_data']:
                    summary = result['analysis_data']['summary']
                    if isinstance(summary, str):
                        print(f"     - 摘要: {summary[:50]}...")
                    else:
                        print(f"     - 摘要: {summary}")
        print("")


if __name__ == "__main__":
    asyncio.run(main())