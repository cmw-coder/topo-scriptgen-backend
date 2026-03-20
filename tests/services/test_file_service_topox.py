import pytest
from app.services.file_service import FileService
from pathlib import Path

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