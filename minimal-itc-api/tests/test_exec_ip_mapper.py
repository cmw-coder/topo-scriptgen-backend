# tests/test_exec_ip_mapper.py
import pytest
from datetime import datetime
from exec_ip_mapper import ExecutorMapping

def test_valid_mapping_creation():
    """Test creating a valid ExecutorMapping"""
    mapping = ExecutorMapping(
        executor_ip="10.111.8.100",
        temp_dir_name="user1_temp_20260311_143022_a3f2b1c4",
        temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
        temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
        user="user1",
        created_at=datetime.utcnow().isoformat(),
        deployed=True
    )
    assert mapping.executor_ip == "10.111.8.100"
    assert mapping.user == "user1"

def test_invalid_ip_format():
    """Test that invalid IP format raises validation error"""
    with pytest.raises(ValueError, match="Invalid IP address format"):
        ExecutorMapping(
            executor_ip="invalid_ip",
            temp_dir_name="temp_20260311_143022_a3f2b1c4",
            temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            created_at=datetime.utcnow().isoformat(),
            deployed=True
        )

def test_invalid_user_format():
    """Test that invalid user format raises validation error"""
    with pytest.raises(ValueError, match="Invalid user format"):
        ExecutorMapping(
            executor_ip="10.111.8.100",
            temp_dir_name="temp_20260311_143022_a3f2b1c4",
            temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            user="../malicious",  # Path traversal attempt
            created_at=datetime.utcnow().isoformat(),
            deployed=True
        )

def test_user_too_long():
    """Test that user parameter max length is enforced"""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ExecutorMapping(
            executor_ip="10.111.8.100",
            temp_dir_name="temp_20260311_143022_a3f2b1c4",
            temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            user="a" * 33,  # 33 characters, max is 32
            created_at=datetime.utcnow().isoformat(),
            deployed=True
        )

def test_optional_user_parameter():
    """Test that user parameter is optional"""
    mapping = ExecutorMapping(
        executor_ip="10.111.8.100",
        temp_dir_name="temp_20260311_143022_a3f2b1c4",
        temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
        temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
        created_at=datetime.utcnow().isoformat(),
        deployed=True
    )
    assert mapping.user is None

def test_invalid_timestamp_format():
    """Test that invalid timestamp format raises validation error"""
    with pytest.raises(ValueError, match="Invalid timestamp format"):
        ExecutorMapping(
            executor_ip="10.111.8.100",
            temp_dir_name="temp_20260311_143022_a3f2b1c4",
            temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
            created_at="invalid-timestamp",
            deployed=True
        )
