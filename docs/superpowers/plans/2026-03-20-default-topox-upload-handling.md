# default.topox 上传处理功能实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标:** 当用户通过 `POST /api/v1/files/write` 接口上传 `default.topox` 文件时，自动解析文件内容、更新 aigc.json、重置部署状态，并异步调用卸载组网接口。

**架构:** 在 `file_service.write_file()` 方法中检测 `default.topox` 文件上传，调用新增的 `_handle_default_topox_upload()` 方法协调解析、状态更新和异步卸载操作。使用 asyncio 实现异步任务管理，通过信号量控制并发，通过内容哈希实现幂等性。

**技术栈:** FastAPI, asyncio, xml.etree.ElementTree, Pydantic, pytest

---

## 文件结构

**需要修改的文件：**
- `app/core/config.py` - 添加配置选项
- `app/services/file_service.py` - 添加 topox 上传处理逻辑

**需要创建的文件：**
- `tests/services/test_file_service_topox.py` - 测试 topox 上传处理

**文件职责：**
- `config.py`: 集中管理应用配置，新增 topox 上传相关配置项
- `file_service.py`: 文件操作服务，新增 default.topox 特殊处理逻辑
- `test_file_service_topox.py`: 测试 topox 上传处理的各个方面

---

## Task 1: 添加配置选项到 config.py

**文件：**
- Modify: `app/core/config.py:74-80`

**目标:** 添加 default.topox 上传处理相关的配置选项

- [ ] **Step 1: 在 Settings 类中添加配置属性**

在 `app/core/config.py` 的 `Settings` 类中，大约在第 74 行之后（`ITC_REQUEST_TIMEOUT` 之后），添加以下配置：

```python
# default.topox 上传处理配置
DEFAULT_TOPOX_DEBOUNCE_SECONDS: int = 2  # 重复上传去重时间（秒）
DEFAULT_TOPOX_ASYNC_UNDEPLOY: bool = True  # 是否启用异步卸载
DEFAULT_TOPOX_UNDEPLOY_TIMEOUT: int = 300  # 卸载超时时间（秒）
DEFAULT_TOPOX_MAX_CONCURRENT_UNDEPLOY: int = 1  # 最大并发卸载数
```

- [ ] **Step 2: 验证代码语法**

运行: `python -m py_compile app/core/config.py`
预期: 无语法错误

- [ ] **Step 3: 运行现有测试确保没有破坏现有功能**

运行: `pytest tests/ -v -k config`
预期: 所有配置相关测试通过

- [ ] **Step 4: 提交配置更改**

```bash
git add app/core/config.py
git commit -m "feat(config): add default.topox upload handling configuration

- Add debounce seconds for duplicate upload detection
- Add async undeploy toggle
- Add undeploy timeout configuration
- Add max concurrent undeploy limit"
```

---

## Task 2: 添加 FileService 构造函数属性

**文件：**
- Modify: `app/services/file_service.py:15-25`

**目标:** 在 FileService 类的构造函数中添加异步任务管理所需的属性

- [ ] **Step 1: 添加导入语句**

在文件开头的导入部分（大约第 1-13 行之后），添加以下导入：

```python
import asyncio
import hashlib
from datetime import datetime
from typing import Optional, Set
```

- [ ] **Step 2: 修改 FileService 构造函数**

在 `FileService.__init__` 方法中（大约第 20-22 行），添加以下属性：

```python
def __init__(self):
    self.path_manager = path_manager
    # 异步任务追踪
    self._undeploy_tasks: Set[asyncio.Task] = set()
    # 并发控制信号量（最多同时1个卸载任务）
    self._undeploy_semaphore = asyncio.Semaphore(1)
    # 当前卸载任务引用
    self._current_undeploy_task: Optional[asyncio.Task] = None
    # 幂等性控制
    self._last_upload_hash: Optional[str] = None
    self._last_upload_time: Optional[datetime] = None
```

- [ ] **Step 3: 验证代码语法**

运行: `python -m py_compile app/services/file_service.py`
预期: 无语法错误

- [ ] **Step 4: 运行现有测试**

运行: `pytest tests/services/test_file_service.py -v`
预期: 所有现有文件服务测试通过

- [ ] **Step 5: 提交构造函数更改**

```bash
git add app/services/file_service.py
git commit -m "feat(file_service): add async task management attributes

- Add undeploy tasks tracking set
- Add semaphore for concurrent control
- Add current task reference
- Add idempotency control attributes"
```

---

## Task 3: 实现幂等性检查方法

**文件：**
- Modify: `app/services/file_service.py` (在 `__init__` 之后添加新方法)

**目标:** 实现重复上传检测功能

- [ ] **Step 0.5: 创建测试目录结构**

运行: `mkdir -p tests/services`

创建: `tests/__init__.py` 和 `tests/services/__init__.py`（空文件即可）

预期: 测试目录结构创建成功

- [ ] **Step 0.6: 验证 logger 导入**

确认 `app/services/file_service.py` 文件顶部有：
```python
logger = logging.getLogger(__name__)
```
如果没有，添加该行。

- [ ] **Step 1: 添加 _is_duplicate_upload 方法**

在 `FileService` 类中，`__init__` 方法之后，添加以下方法：

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
        (now - self._last_upload_time).total_seconds() <
        settings.DEFAULT_TOPOX_DEBOUNCE_SECONDS):
        logger.debug("检测到重复上传（2秒内相同内容），跳过处理")
        return True

    # 更新记录
    self._last_upload_hash = content_hash
    self._last_upload_time = now
    return False
```

- [ ] **Step 2: 验证代码语法**

运行: `python -m py_compile app/services/file_service.py`
预期: 无语法错误

- [ ] **Step 3: 编写幂等性测试**

创建测试文件 `tests/services/test_file_service_topox.py`:

```python
import pytest
from app.services.file_service import file_service
from pathlib import Path

@pytest.mark.asyncio
async def test_duplicate_upload_detection():
    """测试重复上传检测"""
    content = "<NETWORK><DEVICE_LIST></DEVICE_LIST></NETWORK>"

    # 第一次上传应该返回 False（不是重复）
    is_duplicate1 = file_service._is_duplicate_upload(content)
    assert is_duplicate1 is False

    # 立即第二次上传应该返回 True（重复）
    is_duplicate2 = file_service._is_duplicate_upload(content)
    assert is_duplicate2 is True

    # 等待3秒后应该不再是重复
    import asyncio
    await asyncio.sleep(3)
    is_duplicate3 = file_service._is_duplicate_upload(content)
    assert is_duplicate3 is False

@pytest.mark.asyncio
async def test_different_content_not_duplicate():
    """测试不同内容不被识别为重复"""
    content1 = "<NETWORK><DEVICE_LIST></DEVICE_LIST></NETWORK>"
    content2 = "<NETWORK><DEVICE_LIST><DEVICE></DEVICE></DEVICE_LIST></NETWORK>"

    is_duplicate1 = file_service._is_duplicate_upload(content1)
    assert is_duplicate1 is False

    is_duplicate2 = file_service._is_duplicate_upload(content2)
    assert is_duplicate2 is False
```

- [ ] **Step 4: 运行测试**

运行: `pytest tests/services/test_file_service_topox.py::test_duplicate_upload_detection -v`
预期: PASS

- [ ] **Step 5: 提交幂等性功能**

```bash
git add app/services/file_service.py tests/services/test_file_service_topox.py
git commit -m "feat(file_service): add duplicate upload detection

- Add MD5 hash-based content comparison
- Add time-based debounce (2 seconds)
- Add comprehensive tests for idempotency"
```

---

## Task 4: 实现 topox 文件处理主方法

**文件：**
- Modify: `app/services/file_service.py` (添加新方法)

**目标:** 实现 _handle_default_topox_upload 方法，协调解析、状态更新和异步卸载

- [ ] **Step 1: 添加 _handle_default_topox_upload 方法**

在 `FileService` 类中添加以下方法（在 `_is_duplicate_upload` 之后）：

```python
async def _handle_default_topox_upload(self, file_path: Path, content: str) -> None:
    """处理 default.topox 文件上传

    Args:
        file_path: 上传的文件路径
        content: 文件内容（XML 格式）
    """
    import time
    start_time = time.time()

    logger.info("检测到 default.topox 上传，开始处理")

    try:
        # 幂等性检查
        if self._is_duplicate_upload(content):
            return

        # 解析 topox 文件
        from app.services.topo_service import topo_service
        network = topo_service.parse_topox_xml(content)
        logger.debug(f"成功解析 topox，设备数: {len(network.device_list)}, 链路数: {len(network.link_list)}")

        # 更新 aigc.json
        topo_service.save_device_list_to_aigc_json(network)

        # 重置部署状态
        from app.core.config import settings
        settings.set_deploy_status("not_deployed")
        settings.set_deploy_error_message("通过上传 default.topox")
        logger.info("已重置部署状态为 not_deployed，原因：通过上传 default.topox")

        # 异步卸载
        self._async_undeploy_if_needed()

        elapsed = time.time() - start_time
        logger.info(f"default.topox 处理完成，耗时 {elapsed:.2f} 秒")

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"处理 default.topox 失败: {str(e)}，耗时 {elapsed:.2f} 秒", exc_info=True)
        # 不抛出异常，允许文件保存成功
```

- [ ] **Step 2: 添加导入语句（如果还没有）**

确保文件顶部有以下导入：

```python
from app.services.topo_service import topo_service
from app.services.itc.itc_service import itc_service
```

- [ ] **Step 3: 验证代码语法**

运行: `python -m py_compile app/services/file_service.py`
预期: 无语法错误

- [ ] **Step 4: 编写测试（临时测试，稍后会被完整测试替代）**

```python
@pytest.mark.asyncio
async def test_handle_default_topox_upload_basic():
    """测试基本的 topox 处理流程"""
    # 准备测试数据
    valid_topox_content = """<?xml version="1.0" encoding="utf-8"?>
<NETWORK>
    <DEVICE_LIST>
        <DEVICE>
            <PROPERTY>
                <NAME>device1</NAME>
                <LOCATION>location1</LOCATION>
            </PROPERTY>
        </DEVICE>
    </DEVICE_LIST>
    <LINK_LIST>
    </LINK_LIST>
</NETWORK>"""

    from pathlib import Path
    from app.core.config import settings
    import tempfile

    # 创建临时文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.topox', delete=False) as f:
        f.write(valid_topox_content)
        temp_path = Path(f.name)

    try:
        # 调用处理方法
        await file_service._handle_default_topox_upload(temp_path, valid_topox_content)

        # 验证部署状态被重置
        assert settings.get_deploy_status() == "not_deployed"
        assert settings.get_deploy_error_message() == "通过上传 default.topox"

    finally:
        # 清理临时文件
        temp_path.unlink()
```

- [ ] **Step 5: 运行测试**

运行: `pytest tests/services/test_file_service_topox.py::test_handle_default_topox_upload_basic -v`
预期: PASS（可能需要 mock 一些依赖）

- [ ] **Step 6: 提交主处理方法**

```bash
git add app/services/file_service.py tests/services/test_file_service_topox.py
git commit -m "feat(file_service): add default.topox upload handler

- Add main processing method for default.topox uploads
- Integrate parsing, aigc.json update, and status reset
- Add performance monitoring (execution time)
- Add error handling with logging"
```

---

## Task 5: 实现异步卸载方法

**文件：**
- Modify: `app/services/file_service.py` (添加新方法)

**目标:** 实现异步卸载相关方法

- [ ] **Step 1: 添加 _async_undeploy_if_needed 方法**

在 `FileService` 类中添加以下方法：

```python
def _async_undeploy_if_needed(self) -> None:
    """如果存在 executorip，异步调用卸载组网接口

    特性：
    - 任务生命周期管理：追踪所有创建的任务
    - 并发控制：使用信号量限制并发数量
    - 任务替换：取消之前的卸载任务，创建新任务
    """
    try:
        from app.core.config import settings

        # 检查配置是否启用异步卸载
        if not settings.DEFAULT_TOPOX_ASYNC_UNDEPLOY:
            logger.info("异步卸载功能未启用，跳过")
            return

        executorip = settings.get_deploy_executor_ip()

        if not executorip:
            logger.info("不存在 executorip，跳过卸载组网")
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
```

- [ ] **Step 2: 添加 _execute_undeploy_with_semaphore 方法**

```python
async def _execute_undeploy_with_semaphore(self, executorip: str) -> None:
    """执行卸载操作（带并发控制）

    Args:
        executorip: 执行器 IP 地址
    """
    async with self._undeploy_semaphore:
        await self._execute_undeploy(executorip)
```

- [ ] **Step 3: 添加 _execute_undeploy 方法**

```python
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
        from app.core.config import settings
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
```

- [ ] **Step 4: 添加 wait_for_undeploy_tasks 方法**

```python
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

- [ ] **Step 5: 验证代码语法**

运行: `python -m py_compile app/services/file_service.py`
预期: 无语法错误

- [ ] **Step 6: 编写异步卸载测试**

```python
@pytest.mark.asyncio
async def test_async_undeploy_if_needed():
    """测试异步卸载触发"""
    # Mock settings
    from unittest.mock import patch, MagicMock

    with patch('app.services.file_service.settings') as mock_settings:
        mock_settings.DEFAULT_TOPOX_ASYNC_UNDEPLOY = True
        mock_settings.get_deploy_executor_ip.return_value = "10.0.0.1"

        # Mock itc_service
        with patch('app.services.file_service.itc_service') as mock_itc:
            mock_itc.undeploy_environment = MagicMock(return_value=MagicMock(return_code="200"))

            # 调用方法
            file_service._async_undeploy_if_needed()

            # 等待一小段时间让任务创建
            import asyncio
            await asyncio.sleep(0.1)

            # 验证任务被创建
            assert len(file_service._undeploy_tasks) > 0
```

- [ ] **Step 7: 运行测试**

运行: `pytest tests/services/test_file_service_topox.py::test_async_undeploy_if_needed -v`
预期: PASS

- [ ] **Step 8: 提交异步卸载方法**

```bash
git add app/services/file_service.py tests/services/test_file_service_topox.py
git commit -m "feat(file_service): add async undeploy methods

- Add async undeploy trigger with executorip check
- Add semaphore-based concurrent control
- Add task replacement (cancel old, create new)
- Add task lifecycle management
- Add timeout handling for undeploy operations
- Add wait_for_undeploy_tasks for graceful shutdown"
```

---

## Task 6: 修改 write_file 方法集成 topox 处理

**文件：**
- Modify: `app/services/file_service.py:153-210`

**目标:** 在 write_file 方法中添加 default.topox 检测和处理逻辑

- [ ] **Step 1: 找到 write_file 方法的返回语句**

在 `write_file` 方法中，找到所有返回成功响应的地方（大约在第 194-200 行）

- [ ] **Step 2: 在返回成功响应之前添加 topox 检测**

修改代码，在返回成功响应之前添加 topox 处理：

```python
async def write_file(self, file_path: str, content: str, encoding: str = "utf-8") -> FileOperationResponse:
    """写入文件内容"""
    try:
        # 解析路径并检查安全性
        resolved_path = self.path_manager.resolve_path(file_path)
        if not self.path_manager.is_safe_path(resolved_path):
            return FileOperationResponse(
                path=file_path,
                operation="write",
                success=False,
                message="路径不安全或超出项目范围"
            )

        # 检查内容大小
        content_size = len(content.encode(encoding))
        if content_size > settings.MAX_FILE_SIZE:
            return FileOperationResponse(
                path=file_path,
                operation="write",
                success=False,
                message=f"文件内容过大，最大支持 {settings.MAX_FILE_SIZE} 字节"
            )

        # 确保父目录存在
        parent_dir = resolved_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        # 异步写入文件
        async with aiofiles.open(resolved_path, 'w', encoding=encoding) as file:
            await file.write(content)

        # 检查文件扩展名
        if resolved_path.suffix.lower() not in settings.ALLOWED_EXTENSIONS:
            result = FileOperationResponse(
                path=file_path,
                operation="write",
                success=True,
                size=content_size,
                message=f"文件写入成功，但文件类型不在支持列表中。支持的类型: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )
        else:
            result = FileOperationResponse(
                path=file_path,
                operation="write",
                success=True,
                size=content_size,
                message="文件写入成功"
            )

        # ========== 新增：default.topox 特殊处理 ==========
        # 使用 lower() 处理大小写问题
        if Path(file_path).name.lower() == 'default.topox' and result.success:
            await self._handle_default_topox_upload(resolved_path, content)
        # ========== 新增结束 ==========

        return result

    except Exception as e:
        logger.error(f"写入文件失败: {file_path}, 错误: {str(e)}")
        return FileOperationResponse(
            path=file_path,
            operation="write",
            success=False,
            message=f"写入文件失败: {str(e)}"
        )
```

- [ ] **Step 3: 验证代码语法**

运行: `python -m py_compile app/services/file_service.py`
预期: 无语法错误

- [ ] **Step 4: 运行所有文件服务测试**

运行: `pytest tests/services/test_file_service.py -v`
预期: 所有测试通过

- [ ] **Step 5: 编写集成测试**

```python
@pytest.mark.asyncio
async def test_write_default_topox_triggers_processing():
    """测试写入 default.topox 触发处理流程"""
    from app.core.config import settings
    import tempfile

    # 准备 topox 内容
    topox_content = """<?xml version="1.0" encoding="utf-8"?>
<NETWORK>
    <DEVICE_LIST>
        <DEVICE>
            <PROPERTY>
                <NAME>test_device</NAME>
                <LOCATION>test_location</LOCATION>
            </PROPERTY>
        </DEVICE>
    </DEVICE_LIST>
    <LINK_LIST>
    </LINK_LIST>
</NETWORK>"""

    # 设置初始状态为 deployed
    settings.set_deploy_status("deployed")

    # 写入 default.topox 文件
    result = await file_service.write_file("default.topox", topox_content)

    # 验证文件写入成功
    assert result.success is True

    # 验证状态被重置
    assert settings.get_deploy_status() == "not_deployed"

    # 验证错误消息被设置
    assert "通过上传 default.topox" in settings.get_deploy_error_message()
```

- [ ] **Step 6: 运行集成测试**

运行: `pytest tests/services/test_file_service_topox.py::test_write_default_topox_triggers_processing -v`
预期: PASS

- [ ] **Step 7: 提交集成更改**

```bash
git add app/services/file_service.py tests/services/test_file_service_topox.py
git commit -m "feat(file_service): integrate default.topox handling into write_file

- Add default.topox detection in write_file method
- Trigger processing on successful write
- Handle case-insensitive filename matching
- Add integration test for end-to-end flow"
```

---

## Task 7: 添加应用关闭时的任务清理

**文件：**
- Modify: `app/main.py` (应用关闭时调用任务清理)

**目标:** 确保应用关闭时等待异步任务完成

- [ ] **Step 1: 找到 lifespan 关闭处理逻辑**

在 `app/main.py` 的 `lifespan` 函数中，找到 `yield` 之后的关闭处理部分（大约在第 203-204 行）

- [ ] **Step 2: 添加任务清理调用**

在 yield 之后、logger.info 之前添加：

```python
# 等待卸载任务完成
from app.services.file_service import file_service
await file_service.wait_for_undeploy_tasks(timeout=5.0)
```

- [ ] **Step 3: 验证代码语法**

运行: `python -m py_compile app/main.py`
预期: 无语法错误

- [ ] **Step 4: 运行应用测试**

运行: `pytest tests/ -k main -v`
预期: 所有 main 相关测试通过

- [ ] **Step 5: 提交清理逻辑**

```bash
git add app/main.py
git commit -m "feat(main): add undeploy task cleanup on shutdown

- Wait for pending undeploy tasks before shutdown
- Add 5 second timeout for task completion
- Ensure graceful application exit"
```

---

## Task 8: 完善测试覆盖

**文件：**
- Modify: `tests/services/test_file_service_topox.py`

**目标:** 添加缺失的测试用例

- [ ] **Step 1: 添加文件路径大小写测试**

```python
@pytest.mark.asyncio
async def test_default_topox_case_insensitive():
    """测试文件路径大小写不敏感"""
    topox_content = "<?xml version='1.0'?><NETWORK></NETWORK>"

    # 测试不同大小写
    for filename in ["default.topox", "Default.topox", "DEFAULT.TOPOX"]:
        result = await file_service.write_file(filename, topox_content)
        assert result.success is True
```

- [ ] **Step 2: 添加并发上传测试**

```python
@pytest.mark.asyncio
async def test_concurrent_default_topox_upload():
    """测试并发上传 default.topox"""
    import asyncio

    topox_content = "<?xml version='1.0'?><NETWORK></NETWORK>"

    # 并发上传5次
    tasks = [
        file_service.write_file("default.topox", topox_content)
        for _ in range(5)
    ]

    results = await asyncio.gather(*tasks)

    # 所有上传都应该成功
    assert all(r.success for r in results)

    # 验证只有一个卸载任务在执行（通过检查 _undeploy_tasks 集合）
    await asyncio.sleep(0.5)  # 等待任务创建
    assert len(file_service._undeploy_tasks) <= 1, "应该最多只有一个活跃的卸载任务"
```

- [ ] **Step 3: 添加解析失败测试**

```python
@pytest.mark.asyncio
async def test_invalid_topox_still_saves_file():
    """测试无效的 topox 文件仍然被保存"""
    from app.core.config import settings
    import tempfile

    # 无效的 XML
    invalid_content = "this is not valid xml"

    # 设置初始状态
    initial_status = settings.get_deploy_status()

    # 写入文件
    result = await file_service.write_file("default.topox", invalid_content)

    # 文件应该保存成功
    assert result.success is True

    # 状态不应该改变（因为解析失败）
    assert settings.get_deploy_status() == initial_status
```

- [ ] **Step 4: 运行所有测试**

运行: `pytest tests/services/test_file_service_topox.py -v`
预期: 所有测试通过

- [ ] **Step 5: 提交测试完善**

```bash
git add tests/services/test_file_service_topox.py
git commit -m "test(file_service): add comprehensive topox upload tests

- Add case-insensitive filename test
- Add concurrent upload test
- Add invalid XML handling test
- Improve test coverage for edge cases"
```

---

## Task 9: 文档和代码审查

**目标:** 确保代码质量和文档完整

- [ ] **Step 1: 检查代码格式**

运行: `flake8 app/services/file_service.py app/core/config.py app/main.py`
预期: 无格式错误（或仅有一些可忽略的警告）

- [ ] **Step 2: 运行类型检查（如果配置了 mypy）**

运行: `mypy app/services/file_service.py`
预期: 无类型错误

- [ ] **Step 3: 运行完整测试套件**

运行: `pytest tests/ -v`
预期: 所有测试通过

- [ ] **Step 4: 检查日志输出**

手动测试：上传一个 default.topox 文件，查看日志输出是否清晰完整

- [ ] **Step 5: 更新 API 文档（如果需要）**

如果 API 文档需要更新，更新相关文档

- [ ] **Step 6: 提交任何小的修复**

```bash
git add .
git commit -m "chore: fix code quality issues found during review"
```

---

## Task 10: 最终验证和部署

**目标:** 验证功能完整性和准备部署

- [ ] **Step 1: 手动端到端测试**

1. 启动应用
2. 通过 API 上传一个有效的 default.topox 文件
3. 检查 aigc.json 是否更新
4. 检查部署状态是否重置
5. 检查是否触发卸载（如果有 executorip）
6. 验证日志输出正确

- [ ] **Step 2: 性能测试**

上传大的 topox 文件，验证：
- 响应时间在可接受范围内
- 异步卸载不阻塞主流程
- 内存使用正常

- [ ] **Step 3: 错误场景测试**

1. 上传格式错误的 topox - 应该保存文件但跳过处理
2. 上传时网络故障 - 应该优雅降级
3. 并发上传多个文件 - 应该正确处理

- [ ] **Step 4: 创建功能标记**

如果需要，创建功能开关来控制这个新功能

- [ ] **Step 5: 准备部署**

```bash
# 确保所有更改已提交
git status

# 创建部署标签（如果需要）
git tag -a v1.1.0 -m "Add default.topox upload handling feature"

# 推送到远程
git push origin main --tags
```

- [ ] **Step 6: 编写发布说明**

创建 `RELEASE_NOTES.md` 描述新功能：

```markdown
# Release Notes - v1.1.0

## New Features

### default.topox 上传自动处理

当用户上传 `default.topox` 文件时，系统现在会：

1. **自动解析** topox 文件内容，提取设备和链路信息
2. **更新配置** 将解析结果保存到 `.aigc_tool/aigc.json`
3. **重置状态** 将部署状态设置为 "not_deployed"
4. **异步卸载** 如果之前已部署，自动调用卸载组网接口

**特性：**
- ✅ 幂等性保证：2秒内重复上传会被忽略
- ✅ 并发控制：最多同时执行1个卸载任务
- ✅ 性能监控：记录处理时间和卸载时间
- ✅ 优雅关闭：应用关闭时等待后台任务完成
- ✅ 错误容错：解析失败不影响文件保存

**配置选项：**
```python
DEFAULT_TOPOX_DEBOUNCE_SECONDS = 2  # 重复上传去重时间
DEFAULT_TOPOX_ASYNC_UNDEPLOY = True  # 是否启用异步卸载
DEFAULT_TOPOX_UNDEPLOY_TIMEOUT = 300  # 卸载超时时间
```
```

- [ ] **Step 7: 最终提交**

```bash
git add RELEASE_NOTES.md
git commit -m "docs: add release notes for v1.1.0"
```

---

## 测试策略

### 单元测试
- ✅ 幂等性检查
- ✅ 文件路径大小写处理
- ✅ 异步任务创建
- ✅ 并发控制

### 集成测试
- ✅ 端到端上传流程
- ✅ aigc.json 更新
- ✅ 部署状态重置
- ✅ 异步卸载触发

### 手动测试
- ✅ 正常场景
- ✅ 错误场景
- ✅ 性能测试
- ✅ 并发场景

---

## 滚回计划

如果出现问题，按以下步骤回滚：

1. **禁用功能**：在 config.py 中设置 `DEFAULT_TOPOX_ASYNC_UNDEPLOY = False`
2. **移除触发逻辑**：删除 write_file 中的 topox 检测代码
3. **清理任务**：调用 `file_service.wait_for_undeploy_tasks(timeout=0)`
4. **Git 回滚**：`git revert <commit-hash>`

---

## 完成标准

- [ ] 所有测试通过
- [ ] 代码审查通过
- [ ] 手动测试验证
- [ ] 文档完整
- [ ] 性能满足要求
- [ ] 无已知的严重bug

---

**预计完成时间:** 2-3小时
**难度等级:** 中等
**依赖:** 无外部依赖，使用现有服务
