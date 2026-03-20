import pytest
import asyncio
from unittest.mock import patch
from app.services.file_service import FileService
from pathlib import Path

# Import the global file_service instance
from app.services.file_service import file_service

@pytest.mark.asyncio
async def test_duplicate_upload_detection():
    """测试重复上传检测"""
    # 创建一个新的 FileService 实例以避免状态污染
    file_service = FileService()
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
    # 创建一个新的 FileService 实例以避免状态污染
    file_service = FileService()
    content1 = "<NETWORK><DEVICE_LIST></DEVICE_LIST></NETWORK>"
    content2 = "<NETWORK><DEVICE_LIST><DEVICE></DEVICE></DEVICE_LIST></NETWORK>"

    is_duplicate1 = file_service._is_duplicate_upload(content1)
    assert is_duplicate1 is False

    is_duplicate2 = file_service._is_duplicate_upload(content2)
    assert is_duplicate2 is False

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

@pytest.mark.asyncio
async def test_async_undeploy_if_needed():
    """测试异步卸载触发"""
    # 创建一个新的 FileService 实例以避免状态污染
    file_service = FileService()

    # Mock settings directly
    class MockSettings:
        DEFAULT_TOPOX_ASYNC_UNDEPLOY = True
        DEFAULT_TOPOX_UNDEPLOY_TIMEOUT = 30

        def get_deploy_executor_ip(self):
            return "10.0.0.1"

    # Mock itc_service
    class MockITCService:
        async def undeploy_environment(self, request):
            from unittest.mock import MagicMock
            # Simulate async operation with a small delay
            await asyncio.sleep(0.1)
            result = MagicMock()
            result.return_code = "200"
            return result

    file_service.settings = MockSettings()
    file_service.itc_service = MockITCService()

    # 调用方法
    await file_service._async_undeploy_if_needed()

    # 等待一小段时间让任务创建
    await asyncio.sleep(0.3)

    # 验证任务被创建
    print(f"当前任务数量: {len(file_service._undeploy_tasks)}")
    print(f"当前任务: {file_service._undeploy_tasks}")

    # The task should still be running or at least not yet removed from the set
    if len(file_service._undeploy_tasks) > 0:
        print("SUCCESS: Task found in set")
        assert True
    else:
        print("INFO: Task already completed and removed from set")
        # Check if the task was created and completed successfully
        assert file_service._current_undeploy_task is not None
        print(f"Task completion status: {file_service._current_undeploy_task.done()}")

@pytest.mark.asyncio
async def test_write_default_topox_triggers_processing():
    """测试写入 default.topox 触发处理流程"""
    from app.core.config import settings

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

@pytest.mark.asyncio
async def test_write_non_topox_file_no_processing():
    """测试写入非 topox 文件不触发处理流程"""
    from app.core.config import settings

    # 确保初始状态是干净的
    settings.set_deploy_status("deployed")
    settings.set_deploy_error_message("")

    # 写入普通文件
    result = await file_service.write_file("regular_file.txt", "This is a regular file")

    # 验证文件写入成功
    assert result.success is True
    assert result.size > 0

    # 验证状态没有被重置（因为不是 default.topox）
    assert settings.get_deploy_status() == "deployed"

    # 验证错误消息没有被设置
    deploy_error = settings.get_deploy_error_message()
    assert deploy_error == ""

@pytest.mark.asyncio
async def test_write_topox_case_insensitive():
    """测试大小写不敏感的 default.topox 检测"""
    from app.core.config import settings

    # 使用有效的 topox 内容
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

    # 测试第一个文件
    filename = "DEFAULT.TOPOX"

    # 确保每次测试开始前状态是干净的
    settings.set_deploy_status("deployed")
    settings.set_deploy_error_message("")
    print(f"Before write - status: {settings.get_deploy_status()}, error: '{settings.get_deploy_error_message()}'")

    # 写入文件
    result = await file_service.write_file(filename, topox_content)
    print(f"After write - result: {result}, status: {settings.get_deploy_status()}, error: '{settings.get_deploy_error_message()}'")

    # 验证文件写入成功
    assert result.success is True

    # 验证状态被重置
    assert settings.get_deploy_status() == "not_deployed"

    # 验证错误消息被设置
    assert "通过上传" in settings.get_deploy_error_message()

@pytest.mark.asyncio
async def test_write_topox_file_fails_no_processing():
    """测试写入失败的 default.topox 文件不会触发处理"""
    from app.core.config import settings

    # 确保初始状态是干净的
    settings.set_deploy_status("deployed")
    settings.set_deploy_error_message("")

    # 使用一个不存在的路径来模拟写入失败
    result = await file_service.write_file("/nonexistent/path/default.topox", "test content")

    # 验证文件写入失败（路径不安全）
    assert result.success is False

    # 验证状态没有被重置（因为写入失败）
    assert settings.get_deploy_status() == "deployed"

    # 验证错误消息没有被设置
    assert settings.get_deploy_error_message() == ""

@pytest.mark.asyncio
async def test_write_topox_file_with_unsupported_extension():
    """测试带有不支持扩展名的 default.topox 文件处理"""
    from app.core.config import settings

    # 设置初始状态为 deployed
    settings.set_deploy_status("deployed")

    # 写入一个有不支持扩展名但文件名匹配 default.topox 的文件
    result = await file_service.write_file("default.topox.bak", "test content")

    # 对于不支持扩展名，应该在结果消息中说明
    assert result.success is True

    # 检查结果消息中是否包含支持的扩展名列表
    assert "支持的类型" in result.message

    # 状态不应该被重置（因为文件扩展名不在支持列表中）
    assert settings.get_deploy_status() == "deployed"
    # 错误消息不应该被设置
    assert settings.get_deploy_error_message() == ""