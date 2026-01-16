#!/usr/bin/env python3
"""
Claude-Code Todo 日志分析工具
专注于提取和分析 Claude-Code 日志中的 Todo 数据
"""

import json
import os
import glob
import argparse
from datetime import datetime
from collections import Counter, defaultdict
# import matplotlib.pyplot as plt
import pandas as pd


class TodoAnalyzer:
    """Todo 数据分析师"""
    
    def __init__(self):
        self.todos = []  # 所有 Todo 条目
        self.todos_by_file = defaultdict(list)  # 按源文件分组的 Todo
        self.todos_by_log_entry = defaultdict(list)  # 按日志条目分组的 Todo
        self.sessions = defaultdict(list)  # 按会话分组的 Todo
        self.total_todos = 0
        self.status_counter = Counter()  # Todo 状态统计
        self.content_counter = Counter()  # Todo 内容统计
        self.activeform_counter = Counter()  # Todo 活跃形式统计
        self.session_todo_counts = Counter()  # 每个会话的 Todo 数量
        self.files_with_todos = set()  # 包含 Todo 的文件列表
        self.log_entry_count = 0  # 处理的日志条目数量
        
        # 会话时间跟踪
        self.session_times = defaultdict(dict)  # 记录每个会话的开始和结束时间
        self.total_session_duration = 0  # 所有会话的总时长（秒）
        
    def load_log_file(self, file_path):
        """加载单个日志文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        log_entry = json.loads(line)
                        self._process_log_entry(log_entry, file_path)
                    except json.JSONDecodeError:
                        print(f"⚠️  解析错误: {file_path} 第 {line_num} 行")
        except Exception as e:
            print(f"❌ 加载文件失败: {file_path} - {e}")
    
    def load_directory(self, directory_path):
        """加载目录下所有 JSONL 日志文件"""
        jsonl_files = glob.glob(os.path.join(directory_path, '**', '*.jsonl'), recursive=True)
        print(f"📁 发现 {len(jsonl_files)} 个日志文件")
        
        for file_path in jsonl_files:
            self.load_log_file(file_path)
    
    def _process_log_entry(self, log_entry, file_path):
        """处理单个日志条目"""
        session_id = log_entry.get('sessionId')
        if not session_id:
            return
        
        # 获取当前日志条目的时间戳
        timestamp = log_entry.get('timestamp')
        if timestamp:
            # 更新会话的开始和结束时间
            if session_id not in self.session_times:
                # 为新会话创建时间记录
                self.session_times[session_id] = {
                    'start_time': timestamp,
                    'end_time': timestamp
                }
            else:
                # 比较并更新开始时间（取最早的）
                if timestamp < self.session_times[session_id]['start_time']:
                    self.session_times[session_id]['start_time'] = timestamp
                # 比较并更新结束时间（取最晚的）
                if timestamp > self.session_times[session_id]['end_time']:
                    self.session_times[session_id]['end_time'] = timestamp
        
        # 检查是否包含 Todo 数据
        if 'message' in log_entry:
            message = log_entry['message']
            if isinstance(message, dict) and isinstance(message.get('content'), list):
                for item in message['content']:
                    if isinstance(item, dict):
                        # 只处理类型为 "tool_use" 且名称为 "TodoWrite" 的日志条目
                        if (item.get('type') == 'tool_use' and 
                            item.get('name') == 'TodoWrite'):
                            input_data = item.get('input', {})
                            todos = input_data.get('todos', [])
                            self._extract_todos(session_id, log_entry, todos, file_path)
    
    def _extract_todos(self, session_id, log_entry, todos, file_path):
        """提取 Todo 数据"""
        # 为每个日志条目分配唯一标识
        self.log_entry_count += 1
        log_entry_id = f"log_entry_{self.log_entry_count}"
        
        # 创建日志条目信息
        log_entry_info = {
            'log_entry_id': log_entry_id,
            'session_id': session_id,
            'timestamp': log_entry.get('timestamp'),
            'file_path': file_path,
            'todos': []
        }
        
        for todo in todos:
            if isinstance(todo, dict):
                todo_entry = {
                    'log_entry_id': log_entry_id,
                    'session_id': session_id,
                    'file_path': file_path,
                    'timestamp': log_entry.get('timestamp'),
                    'content': todo.get('content', ''),
                    'status': todo.get('status', 'unknown'),
                    'activeForm': todo.get('activeForm', '')
                }
                
                self.todos.append(todo_entry)
                self.sessions[session_id].append(todo_entry)
                self.todos_by_file[file_path].append(todo_entry)
                self.todos_by_log_entry[log_entry_id].append(todo_entry)
                self.files_with_todos.add(file_path)
                self.total_todos += 1
                
                # 添加到日志条目信息的 todos 列表中
                log_entry_info['todos'].append(todo_entry)
                
                # 更新统计
                self.status_counter[todo.get('status', 'unknown')] += 1
                self.content_counter[todo.get('content', 'unknown')] += 1
                self.activeform_counter[todo.get('activeForm', 'unknown')] += 1
                self.session_todo_counts[session_id] += 1
        
        # 将包含 Todo 的日志条目添加到按文件分组的列表中
        if log_entry_info['todos']:
            self.todos_by_file[file_path].append({
                'type': 'log_entry',
                'info': log_entry_info
            })
    
    def print_summary(self):
        """打印分析总结"""
        print("\n" + "="*50)
        print("📊 CLAUDE-CODE TODO 分析报告")
        print("="*50)
        
        if not self.todos:
            print("❌ 没有找到任何 Todo 数据")
            return
        
        # 计算会话持续时长
        session_durations = {}
        self.total_session_duration = 0
        for session_id, times in self.session_times.items():
            try:
                if 'start_time' in times and 'end_time' in times:
                    # 解析 ISO 格式的时间戳
                    start_dt = datetime.fromisoformat(times['start_time'].replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(times['end_time'].replace('Z', '+00:00'))
                    # 计算持续时长（秒）
                    duration = (end_dt - start_dt).total_seconds()
                    session_durations[session_id] = duration
                    self.total_session_duration += duration
            except (ValueError, TypeError):
                # 忽略格式错误的时间戳
                continue
        
        # 基本统计
        print(f"\n📋 基本统计:")
        print(f"   - 总 Todo 条目: {self.total_todos}")
        print(f"   - 涉及会话数: {len(self.sessions)}")
        
        if self.sessions:
            avg_todos_per_session = self.total_todos / len(self.sessions)
            print(f"   - 平均每个会话的 Todo 数: {avg_todos_per_session:.2f}")
        
        # Todo 状态分布
        print(f"\n🎯 Todo 状态分布:")
        for status, count in self.status_counter.most_common():
            percentage = (count / self.total_todos * 100) if self.total_todos else 0
            print(f"   - {status}: {count} ({percentage:.1f}%)")
        
        # 最常见的 Todo 内容
        print(f"\n💡 最常见的 Todo 内容:")
        for content, count in self.content_counter.most_common(10):
            print(f"   - {content[:50]}{'...' if len(content) > 50 else ''}: {count}")
        
        # 最常见的活跃形式
        print(f"\n⚡ 最常见的活跃形式:")
        for activeform, count in self.activeform_counter.most_common(10):
            print(f"   - {activeform[:50]}{'...' if len(activeform) > 50 else ''}: {count}")
        
        # 会话 Todo 数量分布
        print(f"\n📈 会话 Todo 数量分布:")
        for count_range in [(1, 5), (6, 10), (11, 20), (21, 50), (51, float('inf'))]:
            start, end = count_range
            session_count = sum(1 for c in self.session_todo_counts.values() 
                               if start <= c <= end)
            if session_count > 0:
                range_str = f"{start}-{end}" if end != float('inf') else f"{start}+"
                print(f"   - {range_str} 个 Todo: {session_count} 个会话")
        
        # 会话时间信息
        print(f"\n⏱️  会话时间统计:")
        if session_durations:
            # 格式化时间函数
            def format_duration(seconds):
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                secs = int(seconds % 60)
                if hours > 0:
                    return f"{hours}小时{minutes}分钟{secs}秒"
                elif minutes > 0:
                    return f"{minutes}分钟{secs}秒"
                else:
                    return f"{secs}秒"
            
            # 显示每个会话的时间
            print(f"   每个会话的持续时长:")
            for session_id, duration in session_durations.items():
                print(f"   - 会话 {session_id[:8]}...: {format_duration(duration)}")
            
            # 总时长
            print(f"   - 所有会话总时长: {format_duration(self.total_session_duration)}")
        
        print(f"\n📁 包含 Todo 的文件信息:")
        print(f"   - 包含 Todo 的文件数: {len(self.files_with_todos)}")
        
        # 统计每个文件的 Todo 数量
        print(f"\n   每个文件的 Todo 数量分布:")
        file_todo_counts = Counter()
        for file_path, todos_list in self.todos_by_file.items():
            file_todo_counts[file_path] = len(todos_list)
        
        for file_path, count in file_todo_counts.most_common(10):
            # 只显示文件名，避免过长路径
            filename = os.path.basename(file_path)
            print(f"   - {filename}: {count} 个 Todo")
        
        if len(file_todo_counts) > 10:
            print(f"   - ... 还有 {len(file_todo_counts) - 10} 个文件")
    
    # def plot_status_distribution(self):
    #     """绘制 Todo 状态分布图"""
    #     if not self.status_counter:
    #         print("❌ 没有状态数据可绘制")
    #         return
        
    #     plt.figure(figsize=(10, 6))
        
    #     labels, sizes = zip(*self.status_counter.items())
    #     colors = ['#4CAF50', '#2196F3', '#FF9800', '#F44336']
        
    #     plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%',
    #             shadow=True, startangle=140)
        
    #     plt.title('Todo 状态分布', fontsize=14)
    #     plt.axis('equal')  # 保持圆形
    #     plt.tight_layout()
        
    #     filename = 'todo_status_distribution.png'
    #     plt.savefig(filename, dpi=300, bbox_inches='tight')
    #     print(f"📊 状态分布图已保存: {filename}")
    #     plt.close()
    
    # def plot_content_frequency(self):
    #     """绘制 Todo 内容频率图"""
    #     if not self.content_counter:
    #         print("❌ 没有内容数据可绘制")
    #         return
        
    #     # 取前15个最常见的内容
    #     top_contents = self.content_counter.most_common(15)
    #     if not top_contents:
    #         return
        
    #     contents, counts = zip(*top_contents)
        
    #     plt.figure(figsize=(12, 8))
        
    #     # 截断长内容
    #     truncated_contents = [content[:30] + '...' if len(content) > 30 else content 
    #                          for content in contents]
        
    #     bars = plt.barh(range(len(truncated_contents)), counts, color='#2196F3')
    #     plt.yticks(range(len(truncated_contents)), truncated_contents, fontsize=10)
    #     plt.xlabel('出现次数', fontsize=12)
    #     plt.ylabel('Todo 内容', fontsize=12)
    #     plt.title('最常见的 Todo 内容', fontsize=14)
    #     plt.grid(True, alpha=0.3)
        
    #     # 在条形图上显示数值
    #     for bar in bars:
    #         width = bar.get_width()
    #         plt.text(width + 0.5, bar.get_y() + bar.get_height()/2, 
    #                 f'{int(width)}', va='center', fontsize=9)
        
    #     plt.tight_layout()
        
    #     filename = 'todo_content_frequency.png'
    #     plt.savefig(filename, dpi=300, bbox_inches='tight')
    #     print(f"📊 内容频率图已保存: {filename}")
    #     plt.close()
    
    def export_to_json(self, filename='todo_analysis.json'):
        """导出 Todo 数据到 JSON，按源文件和日志条目分组"""
        if not self.todos:
            print("❌ 没有数据可导出")
            return
        
        # 重新构建按文件组织的数据结构
        todos_by_file = {}
        for file_path in self.files_with_todos:
            todos_by_file[file_path] = {
                "file_path": file_path,
                "total_todos": 0,
                "log_entries": []
            }
        
        # 按日志条目分组的Todo数据
        for log_entry_id, todos_list in self.todos_by_log_entry.items():
            if not todos_list:
                continue
            
            # 获取文件路径
            file_path = todos_list[0].get('file_path', 'unknown')
            
            # 创建日志条目对象
            log_entry_obj = {
                "log_entry_id": log_entry_id,
                "timestamp": todos_list[0].get('timestamp'),
                "session_id": todos_list[0].get('session_id'),
                "todo_count": len(todos_list),
                "todos": todos_list
            }
            
            # 添加到文件的日志条目列表
            if file_path in todos_by_file:
                todos_by_file[file_path]["log_entries"].append(log_entry_obj)
                todos_by_file[file_path]["total_todos"] += len(todos_list)
        
        # 计算会话持续时长
        session_times_data = {}
        total_duration_seconds = 0
        for session_id, times in self.session_times.items():
            session_data = {
                "session_id": session_id,
                "start_time": times.get('start_time'),
                "end_time": times.get('end_time'),
                "duration_seconds": 0
            }
            
            try:
                if 'start_time' in times and 'end_time' in times:
                    # 解析 ISO 格式的时间戳
                    start_dt = datetime.fromisoformat(times['start_time'].replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(times['end_time'].replace('Z', '+00:00'))
                    # 计算持续时长（秒）
                    duration = (end_dt - start_dt).total_seconds()
                    session_data['duration_seconds'] = duration
                    total_duration_seconds += duration
            except (ValueError, TypeError):
                # 忽略格式错误的时间戳
                pass
            
            session_times_data[session_id] = session_data
        
        # 按源文件路径组织最终导出数据
        export_data = {
            "total_todos": self.total_todos,
            "files_with_todos": len(self.files_with_todos),
            "total_log_entries": self.log_entry_count,
            "session_times": session_times_data,
            "total_session_duration_seconds": total_duration_seconds,
            "todos_by_file": todos_by_file
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"💾 数据已导出到: {filename}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Claude-Code Todo 日志分析工具')
    parser.add_argument('path', help='日志文件或目录路径')
    parser.add_argument('--plot', action='store_true', help='生成可视化图表')
    parser.add_argument('--export', help='导出数据到 JSON 文件')
    
    args = parser.parse_args()
    
    # 创建分析器
    analyzer = TodoAnalyzer()
    
    # 加载日志
    if os.path.isdir(args.path):
        analyzer.load_directory(args.path)
    elif os.path.isfile(args.path):
        analyzer.load_log_file(args.path)
    else:
        print(f"❌ 路径不存在: {args.path}")
        return
    
    if analyzer.total_todos == 0:
        print("❌ 没有找到 Todo 数据")
        return
    
    # 生成报告
    analyzer.print_summary()
    
    # # 生成可视化
    # if args.plot:
    #     print("\n🎨 生成可视化图表...")
    #     analyzer.plot_status_distribution()
    #     analyzer.plot_content_frequency()
    
    # 导出数据
    if args.export:
        analyzer.export_to_json(args.export)
    
    print("\n✅ 分析完成!")


if __name__ == '__main__':
    main()