# NETCONF 材料准备流程文档

## 概述

本文档描述 `prepare_materials.py` 中准备 NETCONF 测试脚本依赖材料的完整流程。

---

## 核心功能

**准备 NETCONF 测试脚本所需的依赖材料**，通过调用 Claude Agent skill 自动完成以下任务：
1. 将 Word API 文档转换为 Markdown 格式
2. 将 YANG 文件转换为 YIN 格式
3. 分析文档结构，生成 `netconf_output/` 目录及子模块

---

## 完整流程

```
┌─────────────────────────────────────────────────────────────────┐
│              准备 NETCONF 依赖材料流程                            │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤1: 设置环境变量                     │
         │ - 删除代理环境变量                     │
         │ - 设置 Anthropic API 配置             │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤2: 确定工作目录                     │
         │ - 使用传入的 workspace                │
         │ - 或使用 settings.get_work_directory()│
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤3: 配置 Claude Agent 选项          │
         │ - cwd: 工作目录                        │
         │ - setting_sources: ["user"]          │
         │ - permission_mode: bypassPermissions  │
         │ - allowed_tools: [Bash, Read, ...]   │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤4: 调用 Claude Agent               │
         │ Skill: netconf_test_script_generation │
         │        _material_preparation           │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤5: 等待 Skill 执行完成             │
         │ - 接收并处理消息流                     │
         │ - 记录每条消息到日志                   │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤6: 验证生成的目录                  │
         │ - 检查 converted_docs/ 是否生成       │
         │ - 检查 netconf_output/ 是否生成       │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤7: 返回结果                        │
         │ - return_code: "200" | "500"         │
         │ - return_info: 执行结果描述           │
         └───────────────────────────────────────┘
```

---

## 详细步骤说明

### 步骤1: 设置环境变量

**函数**: `setup_agent_environment()`

删除代理环境变量，避免检索时使用代理：
```python
proxy_vars = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
for var in proxy_vars:
    os.environ.pop(var, None)
```

设置 Anthropic 相关环境变量：
```python
os.environ["ANTHROPIC_BASE_URL"] = "http://10.144.41.149:4000/"
os.environ["ANTHROPIC_AUTH_TOKEN"] = "xx"
os.environ["ANTHROPIC_LOG"] = "debug"
```

---

### 步骤2: 确定工作目录

**优先级**：
1. 使用传入的 `workspace` 参数
2. 否则使用 `settings.get_work_directory()`

确保目录存在：
```python
if not os.path.exists(workspace):
    os.makedirs(workspace, exist_ok=True)
```

---

### 步骤3: 配置 Claude Agent 选项

**配置项**：
```python
options = ClaudeAgentOptions(
    cwd=workspace,                    # 工作目录
    setting_sources=["user"],         # 不加载 project 设置
    permission_mode="bypassPermissions",  # 绕过权限检查
    allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],  # 允许的工具
)
```

---

### 步骤4: 调用 Claude Agent

**Skill 名称**: `netconf_test_script_generation_material_preparation`

**Prompt 示例**：
```
在工作区 {workspace} 调用 skill: netconf_test_script_generation_material_preparation,

此 skill 会自动执行以下操作：
- 将 Word API 文档转换为 Markdown 格式，生成 `converted_docs/` 目录
- 将 YANG 文件转换为 YIN 格式，生成对应的转换目录
- 分析文档结构，生成 `netconf_output/` 目录及子模块
```

**调用方式**：
```python
async for message in query(prompt=prompt, options=options):
    message_count += 1
    task_logger.write_log(task_id, f"已处理 {message_count} 条消息")
```

---

### 步骤5: 等待 Skill 执行完成

- 接收消息流（`async for message`）
- 记录每条消息到日志（用于调试）
- 等待 skill 执行完成

---

### 步骤6: 验证生成的目录

**必须生成的目录**：
- `netconf_output/` - **必须存在**
  - 包含按功能模块划分的子文件夹
  - 每个子文件夹包含 YANG/YIN 文件和转换后的文档

**可选生成的目录**：
- `converted_docs/` - 转换后的文档

**验证逻辑**：
```python
if not os.path.exists(netconf_output_dir):
    error_msg = f"材料准备失败：未生成 netconf_output 目录"
    return {"return_code": "500", "return_info": error_msg}
```

---

### 步骤7: 返回结果

**成功返回**：
```python
{
    "return_code": "200",
    "return_info": "材料准备完成"
}
```

**失败返回**：
```python
{
    "return_code": "500",
    "return_info": "错误描述信息"
}
```

---

## 输出目录结构

执行完成后，工作区目录结构如下：

```
workspace/
├── converted_docs/           # 转换后的文档（可选）
│   └── *.md
├── netconf_output/           # 必须生成
│   ├── Base/                 # 子模块1
│   │   ├── *.yang
│   │   ├── *.yin
│   │   └── *.md
│   ├── BGP/                  # 子模块2
│   │   ├── *.yang
│   │   ├── *.yin
│   │   └── *.md
│   └── ...                   # 其他子模块
└── yang/                     # 原始 YANG 文件（输入）
    └── *.yang
```

---

## 关键要点

### 1. 必需的输入

在调用前，工作区应包含：
- **Word API 文档**（.docx）
- **YANG 文件**（.yang）

### 2. 核心依赖

- **Claude Agent SDK**: 用于调用 skill
- **netconf_test_script_generation_material_preparation skill**: 执行材料准备

### 3. 输出要求

- **必须生成**: `netconf_output/` 目录
- **可选生成**: `converted_docs/` 目录

### 4. 错误处理

- 如果未生成 `netconf_output/` 目录，返回错误
- 所有异常都会捕获并记录到日志

### 5. 日志记录

- 使用 `task_logger` 记录所有操作
- 记录每条消息的处理情况
- 记录生成的目录

---

## 使用示例

### 基本调用

```python
from app.services.netconf.prepare_materials import prepare_dependencies

result = await prepare_dependencies(
    task_id="task_123",
    test_point="测试 BGP 配置",
    workspace="/path/to/workspace"  # 可选
)

if result.get("return_code") == "200":
    print("材料准备成功")
else:
    print(f"材料准备失败: {result.get('return_info')}")
```

---

## 相关函数

| 函数 | 作用 |
|------|------|
| `prepare_dependencies()` | 主入口函数，准备依赖材料 |
| `call_netconf_material_preparation_skill()` | 调用 Claude Agent skill |
| `get_output_dir()` | 获取 netconf_output 目录路径 |
| `escape_all_special_chars()` | 转义特殊字符 |

---

## 环境要求

### 环境变量

```bash
ANTHROPIC_BASE_URL="http://10.144.41.149:4000/"
ANTHROPIC_AUTH_TOKEN="xx"
ANTHROPIC_LOG="debug"
```

### 代理设置

调用前会删除以下环境变量：
- `http_proxy`
- `https_proxy`
- `HTTP_PROXY`
- `HTTPS_PROXY`

---

## 依赖项

- `claude_agent_sdk`
- FastAPI
- Pydantic

---

## 注意事项

1. **必须先运行材料准备**，才能运行脚本生成
2. **netconf_output 目录必须存在**，否则脚本生成会失败
3. **工作目录必须包含** Word 文档和 YANG 文件
4. **Skill 执行时间**取决于文档数量和大小

---

## 故障排查

### 问题1: netconf_output 目录未生成

**原因**: Skill 执行失败或输入文件缺失

**解决**:
1. 检查工作目录是否包含 Word 文档和 YANG 文件
2. 查看日志文件，了解 Skill 执行详情
3. 检查 Claude Agent 连接是否正常

### 问题2: Skill 执行超时

**原因**: 文档过多或网络问题

**解决**:
1. 检查网络连接
2. 减少输入文件数量
3. 查看 Claude Agent 日志

---

## 更新日志

### 2026-02-07
- 初始版本
- 实现基本的材料准备功能
