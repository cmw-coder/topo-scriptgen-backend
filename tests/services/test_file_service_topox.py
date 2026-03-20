import pytest
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