# default.topox 上传处理功能设计

**日期**: 2026-03-20
**作者**: Claude
**状态**: 已批准

## 1. 需求概述

### 1.1 功能描述

当用户通过 `POST /api/v1/files/write` 接口上传 `default.topox` 文件时，系统需要：

1. 解析上传的 topox 文件内容，提取 `device_list` 和 `link_list`
2. 将解析结果保存到 `.aigc_tool/aigc.json` 文件中
3. 重置部署状态为 `not_deployed`
4. 设置未部署原因为"通过上传 default.topox"
5. 如果存在 `executorip`，异步调用卸载组网接口（不等待卸载完成）

### 1.2 触发条件

- API 接口：`POST /api/v1/files/write`
- 文件路径：`path="default.topox"`
- 文件格式：`.topox` XML 格式

### 1.3 非功能需求

- **性能要求**：文件上传必须立即返回，不能被后续处理阻塞
- **可靠性要求**：解析失败不应影响文件保存，只记录日志
- **并发要求**：异步卸载操作在后台执行，不阻塞主流程

## 2. 架构设计

### 2.1 整体架构

```
POST /api/v1/files/write (path=default.topox)
    ↓
file_service.write_file()
    ↓
检测到 default.topox
    ↓
_handle_default_topox_upload()
    ↓
├─ 解析 topox 文件 (topo_service.parse_topox_xml)
├─ 更新 aigc.json (topo_service.save_device_list_to_aigc_json)
├─ 重置部署状态 (settings.set_deploy_status)
└─ 异步卸载组网 (asyncio.create_task → itc_service.undeploy_environment)
```

### 2.2 组件设计

#### 2.2.1 FileService 增强

**文件位置**: `app/services/file_service.py`

**新增方法**:

```python
async def _handle_default_topox_upload(self, file_path: Path, content: str) -> None:
    """处理 default.topox 文件上传

    Args:
        file_path: 上传的文件路径
        content: 文件内容（XML 格式）
    """
```

**职责**:
- 检测是否为 `default.topox` 文件
- 协调解析、状态更新、异步卸载等操作
- 错误处理和日志记录

**修改方法**:

```python
async def write_file(self, file_path: str, content: str, encoding: str = "utf-8") -> FileOperationResponse:
    # ... 现有逻辑 ...

    # 新增：检查是否为 default.topox
    if Path(file_path).name == 'default.topox' and result.success:
        await self._handle_default_topox_upload(resolved_path, content)

    return result
```

#### 2.2.2 异步卸载任务管理

**新增属性和方法**:

```python
class FileService:
    def __init__(self):
        self.path_manager = path_manager
        # 异步任务追踪
        self._undeploy_tasks: set[asyncio.Task] = set()
        # 并发控制信号量（最多同时1个卸载任务）
        self._undeploy_semaphore = asyncio.Semaphore(1)
        # 当前卸载任务引用
        self._current_undeploy_task: Optional[asyncio.Task] = None
        # 幂等性控制
        self._last_upload_hash: Optional[str] = None
        self._last_upload_time: Optional[datetime] = None

def _async_undeploy_if_needed(self) -> None:
    """如果存在 executorip，异步调用卸载组网接口

    特性：
    - 任务生命周期管理：追踪所有创建的任务
    - 并发控制：使用信号量限制并发数量
    - 任务替换：取消之前的卸载任务，创建新任务
    """

async def _execute_undeploy(self, executorip: str) -> None:
    """执行卸载操作（在后台任务中运行）"""

async def wait_for_undeploy_tasks(self, timeout: float = 5.0) -> None:
    """等待所有卸载任务完成（用于应用关闭时）"""
```

**职责**:
- 检查是否存在 `executorip`
- 创建后台异步任务调用卸载接口
- **任务生命周期管理**：追踪所有任务，支持应用关闭时等待任务完成
- **并发控制**：使用信号量限制同时运行的卸载任务数量
- **任务替换**：如果已有卸载任务在执行，取消它并创建新任务
- **幂等性保证**：短时间内的重复上传会被忽略
- 错误捕获和日志记录
- **性能监控**：记录任务执行时间

#### 2.2.3 幂等性控制

**新增方法**:

```python
def _is_duplicate_upload(self, content: str) -> bool:
    """检查是否为重复上传（2秒内相同内容）"""
```

**实现方式**:
- 计算文件内容的 MD5 哈希值
- 记录上次上传的哈希和时间
- 2秒内相同内容的上传被视为重复

### 2.3 依赖关系

**file_service.py 新增导入**:

```python
from app.services.topo_service import topo_service
from app.services.itc.itc_service import itc_service
from app.core.config import settings
import asyncio
import hashlib
from datetime import datetime
from typing import Optional, Set
```

### 2.4 配置选项

**在 config.py 中添加**:

```python
class Settings:
    # default.topox 上传处理配置
    DEFAULT_TOPOX_DEBOUNCE_SECONDS: int = 2  # 重复上传去重时间（秒）
    DEFAULT_TOPOX_ASYNC_UNDEPLOY: bool = True  # 是否启用异步卸载
    DEFAULT_TOPOX_UNDEPLOY_TIMEOUT: int = 300  # 卸载超时时间（秒）
    DEFAULT_TOPOX_MAX_CONCURRENT_UNDEPLOY: int = 1  # 最大并发卸载数
```

## 3. 数据流

### 3.1 正常流程

```
用户上传 default.topox
    ↓
[1] 文件写入成功 (content 已经在内存中)
    ↓
[2] 幂等性检查（计算内容哈希）
    ├─ 重复上传 → 记录日志，跳过处理
    └─ 新上传 → 继续
    ↓
[3] 解析 XML 内容 → Network 对象
    ├─ 成功 → 继续
    └─ 失败 → 记录日志，跳过后续步骤
    ↓
[4] 保存 device_list 和 link_list 到 aigc.json
    ├─ 成功 → 继续
    └─ 失败 → 记录日志，继续（不阻塞）
    ↓
[5] 设置 deploy_status = "not_deployed"
    ↓
[6] 设置 deploy_error_message = "通过上传 default.topox"
    ↓
[7] 检查是否有 executorip
    ├─ 有 → 检查是否有正在执行的卸载任务
    │   ├─ 有 → 取消旧任务，创建新卸载任务
    │   └─ 无 → 创建新卸载任务
    └─ 无 → 跳过
    ↓
[8] 立即返回上传成功给用户
```

### 3.2 错误流程

```
解析 topox 失败
    ↓
记录错误日志 (logger.error)
    ↓
文件仍然保存成功
    ↓
跳过 aigc.json 更新
    ↓
跳过部署状态重置
    ↓
跳过异步卸载
    ↓
返回上传成功（用户无感知）
```

## 4. 实现细节

### 4.1 topox 文件解析

**使用现有方法**: `topo_service.parse_topox_xml(content)`

**输入**: XML 格式的 topox 文件内容
**输出**: `Network` 对象，包含 `device_list` 和 `link_list`

**错误处理**:
- 捕获 `ET.ParseError` 和 `ValueError`
- 记录详细错误信息到日志
- 不抛出异常，只记录日志

### 4.2 aigc.json 更新

**使用现有方法**: `topo_service.save_device_list_to_aigc_json(network)`

**功能**:
- 解析现有的 `aigc.json`
- 合并设备列表（保留现有设备的 host、port 等属性）
- 更新 `device_list` 和 `link_list`
- 写入文件

**错误处理**:
- 该方法内部已有错误处理
- 失败只记录日志，不抛出异常

### 4.3 部署状态重置

**使用现有方法**:
- `settings.set_deploy_status("not_deployed")`
- `settings.set_deploy_error_message("通过上传 default.topox")`

**实现**:
```python
settings.set_deploy_status("not_deployed")
settings.set_deploy_error_message("通过上传 default.topox")
logger.info("已重置部署状态为 not_deployed，原因：通过上传 default.topox")
```

### 4.4 幂等性控制

**实现方式**:

```python
def _is_duplicate_upload(self, content: str) -> bool:
    """检查是否为重复上传（2秒内相同内容）

    Args:
        content: 文件内容

    Returns:
        bool: True 表示重复上传，False 表示新上传
    """
    content_hash = hashlib.md5(content.encode()).hexdigest()
    now = datetime.now()

    if (self._last_upload_hash == content_hash and
        self._last_upload_time and
        (now - self._last_upload_time).total_seconds() < settings.DEFAULT_TOPOX_DEBOUNCE_SECONDS):
        logger.debug("检测到重复上传（2秒内相同内容），跳过处理")
        return True

    # 更新记录
    self._last_upload_hash = content_hash
    self._last_upload_time = now
    return False
```

### 4.5 文件路径判断

**实现方式**:

```python
async def write_file(self, file_path: str, content: str, encoding: str = "utf-8") -> FileOperationResponse:
    # ... 现有逻辑 ...

    # 修改：使用 lower() 处理大小写问题
    if Path(file_path).name.lower() == 'default.topox' and result.success:
        await self._handle_default_topox_upload(resolved_path, content)

    return result
```

### 4.6 异步卸载（完整版）

**实现方式**:

```python
def _async_undeploy_if_needed(self) -> None:
    """如果存在 executorip，异步调用卸载组网接口

    特性：
    - 任务生命周期管理：追踪所有创建的任务
    - 并发控制：使用信号量限制并发数量
    - 任务替换：取消之前的卸载任务，创建新任务
    """
    try:
        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            logger.info("不存在 executorip，跳过卸载组网")
            return

        # 检查配置是否启用异步卸载
        if not settings.DEFAULT_TOPOX_ASYNC_UNDEPLOY:
            logger.info("异步卸载功能未启用，跳过")
            return

        # 如果已有卸载任务在执行，取消它
        if self._current_undeploy_task and not self._current_undeploy_task.done():
            logger.info("取消之前的卸载任务")
            self._current_undeploy_task.cancel()

        logger.info(f"检测到 executorip: {executorip}，创建异步卸载任务")

        # 创建新的卸载任务
        self._current_undeploy_task = asyncio.create_task(
            self._execute_undeploy_with_semaphore(executorip)
        )

        # 添加到任务追踪集合
        self._undeploy_tasks.add(self._current_undeploy_task)

        # 任务完成时自动从集合中移除
        self._current_undeploy_task.add_done_callback(self._undeploy_tasks.discard)

    except Exception as e:
        logger.error(f"创建异步卸载任务失败: {str(e)}", exc_info=True)

async def _execute_undeploy_with_semaphore(self, executorip: str) -> None:
    """执行卸载操作（带并发控制和性能监控）

    Args:
        executorip: 执行器 IP 地址
    """
    async with self._undeploy_semaphore:
        await self._execute_undeploy(executorip)

async def _execute_undeploy(self, executorip: str) -> None:
    """执行卸载操作（在后台任务中运行）

    Args:
        executorip: 执行器 IP 地址
    """
    import time
    start_time = time.time()

    try:
        logger.info(f"开始异步卸载组网，executorip: {executorip}")

        from app.models.itc.itc_models import ExecutorRequest
        request = ExecutorRequest(executorip=executorip)

        # 使用超时控制
        result = await asyncio.wait_for(
            itc_service.undeploy_environment(request),
            timeout=settings.DEFAULT_TOPOX_UNDEPLOY_TIMEOUT
        )

        elapsed = time.time() - start_time

        if result.return_code == "200":
            logger.info(f"异步卸载成功: {executorip}，耗时 {elapsed:.2f} 秒")
        else:
            logger.warning(f"异步卸载失败: {result.return_info}，耗时 {elapsed:.2f} 秒")

    except asyncio.TimeoutError:
        elapsed = time.time() - start_time
        logger.error(f"异步卸载超时（{settings.DEFAULT_TOPOX_UNDEPLOY_TIMEOUT}秒），耗时 {elapsed:.2f} 秒")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"异步卸载异常: {str(e)}，耗时 {elapsed:.2f} 秒", exc_info=True)

async def wait_for_undeploy_tasks(self, timeout: float = 5.0) -> None:
    """等待所有卸载任务完成（用于应用关闭时）

    Args:
        timeout: 等待超时时间（秒）
    """
    if self._undeploy_tasks:
        logger.info(f"等待 {len(self._undeploy_tasks)} 个卸载任务完成...")
        tasks = list(self._undeploy_tasks)
        done, pending = await asyncio.wait(tasks, timeout=timeout)

        if pending:
            logger.warning(f"有 {len(pending)} 个卸载任务未完成，强制退出")
        else:
            logger.info("所有卸载任务已完成")
```

## 5. 错误处理策略

### 5.1 分层错误处理

| 层级 | 错误类型 | 处理策略 |
|------|---------|---------|
| 文件写入 | 文件系统错误 | 返回失败响应，不触发后续处理 |
| XML 解析 | 格式错误 | 记录日志，跳过后续处理，文件已保存 |
| aigc.json 更新 | 文件操作错误 | 记录日志，继续状态重置 |
| 状态更新 | 内存操作错误 | 记录日志，继续异步卸载 |
| 异步卸载 | 网络错误 | 只记录日志，不影响上传结果 |

### 5.2 日志记录

**关键日志点**:

1. **开始处理**: `logger.info("检测到 default.topox 上传，开始处理")`
2. **解析成功**: `logger.debug(f"成功解析 topox，设备数: {len(device_list)}, 链路数: {len(link_list)})")`
3. **解析失败**: `logger.error(f"解析 topox 失败: {str(e)}，跳过后续处理")`
4. **状态重置**: `logger.info("已重置部署状态为 not_deployed")`
5. **异步卸载**: `logger.info(f"创建异步卸载任务，executorip: {executorip}")`
6. **卸载结果**: `logger.info/warning("异步卸载完成")`

## 6. 测试考虑

### 6.1 单元测试

**测试用例**:

1. **正常流程测试**
   - 上传有效的 default.topox 文件
   - 验证 aigc.json 更新
   - 验证部署状态重置
   - 验证异步卸载任务创建

2. **解析失败测试**
   - 上传格式错误的 topox 文件
   - 验证文件仍然保存
   - 验证日志记录
   - 验证状态未改变

3. **无 executorip 测试**
   - 上传 default.topox（无 executorip）
   - 验证不创建卸载任务

4. **有 executorip 测试**
   - 上传 default.topox（有 executorip）
   - 验证创建卸载任务
   - 验证不阻塞主流程

5. **幂等性测试**
   - 短时间内（2秒内）上传相同内容
   - 验证第二次上传被跳过
   - 验证只有一次处理

6. **并发上传测试**
   - 同时上传多个 default.topox
   - 验证只有一个卸载任务执行
   - 验证其他上传被取消或跳过

7. **文件路径大小写测试**
   - 上传 `Default.topox`（大小写不同）
   - 验证仍然被识别为 default.topox

8. **超时测试**
   - 模拟卸载接口超时
   - 验证超时后被记录但不影响主流程

9. **应用关闭测试**
   - 在卸载任务执行时关闭应用
   - 验证 wait_for_undeploy_tasks 正确等待
   - 验证任务被正确清理

### 6.2 集成测试

1. **端到端测试**
   - 通过 API 上传 default.topox
   - 检查 aigc.json 内容
   - 检查部署状态
   - 检查卸载是否执行

2. **并发测试**
   - 同时上传多个文件
   - 验证状态一致性
   - 验证无竞态条件

### 6.3 手动测试

**测试步骤**:

1. 准备测试用的 default.topox 文件
2. 通过 `POST /api/v1/files/write` 上传
3. 检查日志输出
4. 验证 `.aigc_tool/aigc.json` 更新
5. 验证部署状态变化
6. 如果有 executorip，验证卸载执行

## 7. 实施计划

### 7.1 实施步骤

1. **修改 file_service.py**
   - 添加 `_handle_default_topox_upload()` 方法
   - 添加 `_async_undeploy_if_needed()` 方法
   - 添加 `_execute_undeploy()` 方法
   - 修改 `write_file()` 方法，添加 topox 检测逻辑

2. **添加导入**
   - 导入 `topo_service`
   - 导入 `itc_service`
   - 导入 `asyncio`

3. **测试**
   - 编写单元测试
   - 进行集成测试
   - 手动验证

### 7.2 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 异步卸载失败 | 用户无感知，但环境未清理 | 详细日志记录，监控卸载任务 |
| 解析失败频繁 | 功能不可用 | 改进错误提示，指导用户 |
| aigc.json 损坏 | 状态管理异常 | 现有方法已有保护，继续使用 |
| 并发上传冲突 | 状态不一致 | 文件操作已有锁保护 |

### 7.3 回滚计划

如果出现问题，可以通过以下方式回滚：

1. 移除 `write_file()` 中的 topox 检测逻辑
2. 保留新增的方法（不影响现有功能）
3. 清理可能产生的异步任务

## 8. 后续优化

### 8.1 性能优化

- 考虑缓存解析结果，避免重复解析
- 优化异步任务管理，避免任务泄漏

### 8.2 功能增强

- 支持其他 .topox 文件的上传处理
- 添加上传历史记录
- 提供更详细的错误信息给用户

### 8.3 监控改进

- 添加指标收集（解析成功率、卸载成功率）
- 添加告警机制（卸载失败告警）

## 9. 参考资料

- **现有代码**:
  - `app/services/file_service.py` - 文件服务
  - `app/services/topo_service.py` - topox 解析服务
  - `app/services/itc/itc_service.py` - ITC 服务
  - `app/core/config.py` - 配置和状态管理
  - `app/services/auto_undeploy_service.py` - 自动卸载服务参考

- **相关文档**:
  - FastAPI 异步任务文档
  - asyncio 官方文档

## 10. 评审修改记录

### v2 (2026-03-20)

**评审结论**: 需要修改后批准

**主要修改**:

1. **添加异步任务生命周期管理**
   - 新增 `_undeploy_tasks` 集合追踪所有任务
   - 新增 `wait_for_undeploy_tasks()` 方法支持应用关闭时等待任务完成
   - 任务完成时自动从集合中移除

2. **添加并发控制机制**
   - 新增 `_undeploy_semaphore` 信号量限制并发数量
   - 新增 `_current_undeploy_task` 追踪当前任务
   - 新任务创建时取消旧任务

3. **添加幂等性保证**
   - 新增 `_is_duplicate_upload()` 方法
   - 计算文件内容 MD5 哈希值
   - 2秒内相同内容的上传被视为重复

4. **优化文件路径判断**
   - 使用 `Path(file_path).name.lower()` 处理大小写问题

5. **调整日志级别**
   - 解析成功改为 debug 级别
   - 添加性能监控日志

6. **完善测试用例**
   - 添加幂等性测试
   - 添加并发上传测试
   - 添加文件路径大小写测试
   - 添加超时测试
   - 添加应用关闭测试

7. **添加配置选项**
   - `DEFAULT_TOPOX_DEBOUNCE_SECONDS`: 重复上传去重时间
   - `DEFAULT_TOPOX_ASYNC_UNDEPLOY`: 是否启用异步卸载
   - `DEFAULT_TOPOX_UNDEPLOY_TIMEOUT`: 卸载超时时间
   - `DEFAULT_TOPOX_MAX_CONCURRENT_UNDEPLOY`: 最大并发卸载数

8. **添加性能监控**
   - 记录任务执行时间
   - 记录总处理时间

**待解决的问题**:
- 日志级别调整（待手动修改）
- 考虑使用任务队列（可选优化）

### v1 (2026-03-20)

**初始版本**
- 完成基本设计
- 提交评审
