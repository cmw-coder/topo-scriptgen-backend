# NETCONF 自动化测试模块

## 概述

本模块提供 NETCONF 协议自动化测试的完整工作流程，包括：
- 准备测试材料
- 生成测试脚本
- 运行测试脚本
- 自动修复失败的脚本

---

## 模块结构

```
netconf/
├── prepare_materials.py      # 准备测试依赖材料
├── generate_scripts.py        # 生成 NETCONF 测试脚本
├── run_scripts.py             # 运行测试脚本（含自动修复逻辑）
├── fix_scripts.py             # 修复失败的测试脚本
├── json_parser.py             # 解析 pytestlog.json 文件
├── netconf_workflow.py        # 完整工作流程编排
└── run_scripts_flow.md        # 运行流程详细文档
```

---

## 核心功能

### 1. 准备材料 (`prepare_materials.py`)

将 YANG 文件、Word 需求文档等材料转换为测试脚本生成所需的依赖文件。

**主要函数**：
- `prepare_dependencies(task_id, test_point)`: 准备依赖材料

**输出**：
- 将材料保存到 `netconf_output` 目录

---

### 2. 生成脚本 (`generate_scripts.py`)

根据准备的材料，自动生成 NETCONF 测试脚本。

**主要函数**：
- `generate_netconf_scripts(task_id)`: 生成所有测试脚本

**输出**：
- 在每个子文件夹生成 `test_netconf_*.py` 和 `conftest.py`

---

### 3. 运行脚本 (`run_scripts.py`)

运行测试脚本，并在失败时自动修复。

**主要函数**：
- `run_netconf_scripts(task_id, subdir_path=None)`: 运行脚本入口
- `_run_scripts_for_subdir(task_id, subdir)`: 运行单个子文件夹的脚本

**核心逻辑**：
1. 调用 `itc_router.run_script` 运行脚本
2. 等待 pytestlog.json 文件生成（最多6分钟）
3. 解析文件判断是否成功
4. 如果失败，调用修复函数
5. 修复后重新运行
6. **每个函数最多修复3次**
7. 如果是不同函数，重置计数器继续修复

**判断成功的标准**：
- 通过 pytestlog.json 文件的 `total_failures` 判断
- `total_failures == 0`：成功
- `total_failures > 0`：失败

**退出条件**：
1. 运行成功
2. 连续3次修复同一函数仍然失败 → **停止整个工作流**
3. 修复函数本身失败

**重要**：如果某个函数修复3次仍然失败，整个工作流会停止，不再处理其他子文件夹。

---

### 4. 修复脚本 (`fix_scripts.py`)

分析失败原因，调用 Claude Agent 自动修复代码。

**主要函数**：
- `_fix_scripts_for_subdir(task_id, subdir, error_message)`: 修复单个子文件夹的脚本

**修复流程**：
1. 解析错误信息（从 pytestlog.json）
2. 提取第一组错误（因为测试步骤有依赖关系）
3. 调用 Claude Agent 修复代码
4. 保存修复后的脚本

---

### 5. 解析结果 (`json_parser.py`)

解析 pytestlog.json 文件，提取错误信息。

**主要函数**：
- `parse_script_return_info(task_id, return_info)`: 解析运行结果

**输出**：
- `error_summary`: 包含失败信息、分组、错误详情等

---

### 6. 完整工作流 (`netconf_workflow.py`)

编排完整的测试流程。

**主要函数**：
- `execute_netconf_workflow(task_id, test_point, workspace)`: 执行完整流程

**流程**：
1. 准备依赖材料
2. 生成测试脚本
3. 运行测试脚本（每个子文件夹单独运行）
4. 汇总结果

---

## 使用示例

### 执行完整工作流

```python
from app.services.netconf.netconf_workflow import execute_netconf_workflow

await execute_netconf_workflow(
    task_id="task_123",
    test_point="测试 BGP 配置",
    workspace="/path/to/workspace"
)
```

### 单独运行脚本

```python
from app.services.netconf.run_scripts import run_netconf_scripts

# 运行所有子文件夹
result = await run_netconf_scripts(task_id="task_123")

# 运行指定子文件夹
result = await run_netconf_scripts(
    task_id="task_123",
    subdir_path="/path/to/subdir"
)
```

---

## 日志输出

运行过程中会输出详细的日志信息：

```
[Base] 开始运行测试脚本
[Base] 运行失败: 3 个错误
[Base] 保存首次错误信息: 2 个错误组
[Base] 当前需要修复的函数: test_step_2
[Base] 开始调用修复函数...
[Base] 修复函数: test_step_2（第 1 次修复该函数）
[Base] 准备重新运行脚本...
[Base] 修复函数: test_step_2（第 2 次修复该函数）
...
[Base] 修复后运行成功 ✓
```

---

## 文件说明

### pytestlog.json 文件

脚本运行后生成的日志文件，包含：
- 测试结果
- 失败信息
- 耗时统计

**文件名格式**：`test_netconf_case_2026-02-06_15-31-35_59174.pytestlog.json`

**筛选条件**：
- 文件名以 `test` 开头
- 在脚本运行开始时间之后生成
- 如果有多个，选择最新的

---

## 相关文档

- **[prepare_materials_flow.md](./prepare_materials_flow.md)**: 材料准备流程详细文档
- **[generate_scripts_flow.md](./generate_scripts_flow.md)**: 脚本生成流程详细文档
- **[run_scripts_flow.md](./run_scripts_flow.md)**: 脚本运行和修复的详细流程文档
- **[fix_scripts.py](./fix_scripts.py)**: 修复逻辑实现
- **[json_parser.py](./json_parser.py)**: 解析逻辑实现

---

## 注意事项

1. **判断成功的标准**：不依赖 `response.status`，而是通过 pytestlog.json 文件判断

2. **修复策略**：
   - 每个函数最多修复3次
   - 无总次数限制
   - 不同函数可以继续修复

3. **等待时间**：最多等待6分钟获取 pytestlog.json 文件

4. **日志记录**：所有操作都会记录到 task_logger 中，使用 task_id 标识

---

## 环境变量

运行前会设置以下环境变量：

```python
os.environ["ANTHROPIC_BASE_URL"] = "http://10.144.41.149:4000/"
os.environ["ANTHROPIC_AUTH_TOKEN"] = "xx"
os.environ["ANTHROPIC_LOG"] = "debug"
```

并在调用 Claude Agent 前删除代理环境变量，避免使用代理。

---

## 依赖项

- FastAPI
- Pydantic
- pytest
- Claude Agent SDK

---

## 更新日志

### 2026-02-07
- 修改修复逻辑：从总次数限制改为按函数限制
- 每个函数最多修复3次，无总次数限制
- 增加详细的日志输出，显示当前修复的函数和次数
- 统一使用 task_id 进行日志记录
- 统一 `run_netconf_scripts()` 的返回格式
- 添加材料准备流程文档（prepare_materials_flow.md）
- 添加脚本生成流程文档（generate_scripts_flow.md）

### 2026-02-06
- 初始版本
- 实现基本的运行和修复逻辑
