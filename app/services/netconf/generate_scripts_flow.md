# NETCONF 脚本生成流程文档

## 概述

本文档描述 `generate_scripts.py` 中生成 NETCONF 测试脚本的完整流程。

---

## 核心功能

**遍历 netconf_output 文件夹，为每个子模块生成 NETCONF 测试脚本**：
1. 遍历 `netconf_output/` 下的每个子文件夹
2. 对每个子文件夹调用 Claude Agent
3. 调用 `netconf_generator` 子 agent 生成测试脚本
4. 生成 `test_netconf_*.py` 和 `conftest.py` 文件

---

## 完整流程

```
┌─────────────────────────────────────────────────────────────────┐
│              生成 NETCONF 测试脚本流程                            │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤1: 检查 netconf_output 目录        │
         │ - 验证目录是否存在                     │
         │ - 获取所有子文件夹列表                 │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤2: 并发处理每个子文件夹            │
         │ - 使用 Semaphore 限制并发数=1        │
         │ - 为每个子文件夹调用生成函数           │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤3: 处理单个子文件夹                │
         │ (对每个子文件夹执行以下步骤)           │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤3.1: 配置 Claude Agent 选项        │
         │ - cwd: 子文件夹路径                    │
         │ - setting_sources: ["user"]          │
         │ - allowed_tools: [Bash, Read, ...]   │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤3.2: 调用 netconf_generator       │
         │ 子 agent 生成测试脚本                 │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤3.3: 等待生成完成                  │
         │ - 接收并处理消息流                     │
         │ - 每10条消息记录一次日志               │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤3.4: 查找生成的脚本文件            │
         │ - 扫描子文件夹中的 test_*.py 文件     │
         │ - 记录到结果列表                      │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤4: 汇总所有子文件夹的结果          │
         │ - 统计成功/失败数量                   │
         │ - 收集所有生成的脚本路径               │
         └───────────────────────────────────────┘
                           │
                           ▼
         ┌───────────────────────────────────────┐
         │ 步骤5: 返回总结果                      │
         │ - return_code: "200" | "404" | "500" │
         │ - generated_scripts: 脚本路径列表     │
         │ - success_count: 成功数量             │
         │ - failed_count: 失败数量             │
         └───────────────────────────────────────┘
```

---

## 详细步骤说明

### 步骤1: 检查 netconf_output 目录

**验证逻辑**：
```python
output_dir = get_output_dir()

# 检查目录是否存在
if not os.path.exists(output_dir):
    return {
        "return_code": "404",
        "return_info": f"netconf_output 目录不存在"
    }

# 获取所有子文件夹
subdirs = [d for d in Path(output_dir).iterdir() if d.is_dir()]

if not subdirs:
    return {
        "return_code": "404",
        "return_info": f"netconf_output 目录下没有子文件夹"
    }
```

---

### 步骤2: 并发处理每个子文件夹

**并发控制**：
- 使用 `asyncio.Semaphore(1)` 限制并发数为 1（顺序执行）
- 使用 `asyncio.gather()` 并发执行所有任务

**代码结构**：
```python
semaphore = asyncio.Semaphore(1)

async def process_subdir(subdir):
    async with semaphore:
        return await _generate_scripts_for_subdir(task_id, subdir)

tasks = [process_subdir(subdir) for subdir in subdirs]
results = await asyncio.gather(*tasks)
```

---

### 步骤3: 处理单个子文件夹

#### 步骤3.1: 配置 Claude Agent 选项

**关键配置**：
```python
options = ClaudeAgentOptions(
    cwd=subdir,                     # 使用子文件夹作为工作区
    setting_sources=["user"],        # 不加载 project 设置
    permission_mode="bypassPermissions",
    allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],
)
```

**工作目录**: 每个子文件夹作为独立的工作区

---

#### 步骤3.2: 调用 netconf_generator 子 agent

**子 Agent 名称**: `netconf_generator`

**Prompt 示例**：
```
调用 子agent : netconf_generator , 在工作区 {subdir} 生成 NETCONF 测试脚本
```

**调用方式**：
```python
prompt = escape_all_special_chars(
    f"""调用 子agent : netconf_generator , 在工作区 {subdir} 生成 NETCONF 测试脚本"""
)

async for message in query(prompt=prompt, options=options):
    message_count += 1
    if message_count % 10 == 0:
        task_logger.write_log(task_id, f"{subdir_name} 已处理 {message_count} 条消息")
```

---

#### 步骤3.3: 等待生成完成

- 接收消息流
- 每 10 条消息记录一次日志（避免日志过多）
- 等待 agent 执行完成

---

#### 步骤3.4: 查找生成的脚本文件

**查找逻辑**：
```python
generated_scripts = []
for root, dirs, files in os.walk(subdir):
    for file in files:
        if file.startswith('test_') and file.endswith('.py'):
            generated_scripts.append(os.path.join(root, file))
```

**生成的文件类型**：
- `test_netconf_*.py` - 测试脚本
- `conftest.py` - pytest 配置文件

---

### 步骤4: 汇总所有子文件夹的结果

**汇总逻辑**：
```python
all_generated_scripts = []
success_count = 0
failed_count = 0

for subdir_name, scripts, success, error_info in results:
    if success:
        all_generated_scripts.extend(scripts)
        success_count += 1
    else:
        failed_count += 1

summary = f"成功: {success_count}, 失败: {failed_count}, 总脚本数: {len(all_generated_scripts)}"
```

---

### 步骤5: 返回总结果

**成功返回**：
```python
{
    "return_code": "200",
    "return_info": f"NETCONF 脚本生成完成，{summary}",
    "generated_scripts": [...],  # 所有生成的脚本路径
    "success_count": 1,
    "failed_count": 0
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

## 输出文件结构

执行完成后，每个子文件夹的结构如下：

```
netconf_output/
├── Base/                     # 子模块1
│   ├── test_netconf_base.py  # 生成的测试脚本
│   └── conftest.py           # pytest 配置
├── BGP/                      # 子模块2
│   ├── test_netconf_bgp.py
│   └── conftest.py
└── ...                       # 其他子模块
```

---

## 关键要点

### 1. 前置依赖

**必须先完成**：
- 调用 `prepare_dependencies()` 生成 `netconf_output/` 目录
- 每个子文件夹包含 YANG/YIN 文件和转换后的文档

### 2. 并发控制

- **并发数**: 1（顺序执行）
- **原因**: 避免资源竞争，确保稳定性

### 3. 子 Agent

**调用的子 agent**: `netconf_generator`

**功能**: 根据子文件夹中的材料生成测试脚本

### 4. 生成文件类型

- `test_netconf_*.py` - 测试脚本
- `conftest.py` - pytest 配置文件

### 5. 日志记录

- 使用 `task_logger` 记录操作
- 每 10 条消息记录一次（减少日志量）

### 6. 错误处理

- 单个子文件夹失败不影响其他文件夹
- 最终结果会统计成功/失败数量

---

## 使用示例

### 基本调用

```python
from app.services.netconf.generate_scripts import generate_netconf_scripts

result = await generate_netconf_scripts(
    task_id="task_123",
    workspace="/path/to/workspace"  # 可选
)

if result.get("return_code") == "200":
    print("脚本生成成功")
    print(f"生成脚本数: {len(result.get('generated_scripts', []))}")
    print(f"成功: {result.get('success_count')}")
    print(f"失败: {result.get('failed_count')}")
else:
    print(f"脚本生成失败: {result.get('return_info')}")
```

---

## 相关函数

| 函数 | 作用 |
|------|------|
| `generate_netconf_scripts()` | 主入口函数，生成所有脚本 |
| `_generate_scripts_for_subdir()` | 为单个子文件夹生成脚本 |
| `get_output_dir()` | 获取 netconf_output 目录路径 |
| `escape_all_special_chars()` | 转义特殊字符 |
| `setup_agent_environment()` | 设置环境变量 |

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
- `asyncio`
- FastAPI
- Pydantic

---

## 注意事项

1. **必须先运行材料准备**，才能运行脚本生成
2. **并发数限制为 1**，避免资源竞争
3. **每个子文件夹独立处理**，单个失败不影响其他
4. **日志按比例记录**，每 10 条消息记录一次

---

## 故障排查

### 问题1: netconf_output 目录不存在

**原因**: 未先调用 `prepare_dependencies()`

**解决**:
1. 先调用 `prepare_dependencies()` 准备材料
2. 确认 `netconf_output/` 目录已生成

### 问题2: 某个子文件夹生成失败

**原因**: 子文件夹材料缺失或不完整

**解决**:
1. 检查该子文件夹是否包含 YANG/YIN 文件
2. 查看日志文件了解详细错误
3. 检查 Claude Agent 连接

### 问题3: 生成的脚本文件为空

**原因**: netconf_generator 子 agent 执行失败

**解决**:
1. 检查子文件夹中的材料是否完整
2. 查看 Claude Agent 日志
3. 手动测试 netconf_generator 子 agent

---

## 与其他模块的关系

### 输入来源

- **材料准备模块** (`prepare_materials.py`)
  - 提供 `netconf_output/` 目录
  - 提供每个子文件夹的材料

### 输出目标

- **脚本运行模块** (`run_scripts.py`)
  - 使用生成的测试脚本
  - 运行并修复失败的脚本

---

## 更新日志

### 2026-02-07
- 初始版本
- 实现基本的脚本生成功能
- 支持并发处理多个子文件夹
