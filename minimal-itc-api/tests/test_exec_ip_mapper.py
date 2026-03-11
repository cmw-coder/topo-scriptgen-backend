# tests/test_exec_ip_mapper.py
import pytest
import tempfile
import json
from datetime import datetime, timezone
from pathlib import Path
from exec_ip_mapper import ExecutorMapping

def test_valid_mapping_creation():
    """Test creating a valid ExecutorMapping"""
    mapping = ExecutorMapping(
        executor_ip="10.111.8.100",
        temp_dir_name="user1_temp_20260311_143022_a3f2b1c4",
        temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
        temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
        user="user1",
        created_at=datetime.now(timezone.utc).isoformat(),
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
            created_at=datetime.now(timezone.utc).isoformat(),
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
            created_at=datetime.now(timezone.utc).isoformat(),
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
            created_at=datetime.now(timezone.utc).isoformat(),
            deployed=True
        )

def test_optional_user_parameter():
    """Test that user parameter is optional"""
    mapping = ExecutorMapping(
        executor_ip="10.111.8.100",
        temp_dir_name="temp_20260311_143022_a3f2b1c4",
        temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
        temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
        created_at=datetime.now(timezone.utc).isoformat(),
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

def test_get_mapping_file_path():
    """Test that mapping file path is correctly determined"""
    from exec_ip_mapper import get_mapping_file_path

    file_path = get_mapping_file_path()
    assert file_path.name == "exec_ip.json"
    assert "minimal-itc-api" in str(file_path)

def test_atomic_write_with_lock():
    """Test atomic write with file locking"""
    from exec_ip_mapper import atomic_write_with_lock

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.json"
        test_data = {"mappings": {"test_ip": {"test": "data"}}}

        # Write data
        atomic_write_with_lock(test_file, test_data)

        # Verify file was created
        assert test_file.exists()

        # Verify content
        with open(test_file, 'r') as f:
            result = json.load(f)
        assert result == test_data

def test_atomic_write_creates_backup_on_corruption():
    """Test that corrupted file is backed up"""
    from exec_ip_mapper import atomic_write_with_lock

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.json"

        # Create corrupted file
        with open(test_file, 'w') as f:
            f.write("{invalid json content")

        # This should backup the corrupted file and create new one
        test_data = {"mappings": {}}
        atomic_write_with_lock(test_file, test_data)

        # Check backup file exists
        backup_file = test_file.with_suffix('.json.backup')
        assert backup_file.exists()

        # Verify backup contains the corrupted content
        with open(backup_file, 'r') as f:
            backup_content = f.read()
        assert "{invalid json content" in backup_content

        # Verify new file has correct data
        with open(test_file, 'r') as f:
            result = json.load(f)
        assert result == test_data

def test_atomic_write_timeout_parameter():
    """Test that timeout parameter is respected"""
    from exec_ip_mapper import atomic_write_with_lock

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.json"
        test_data = {"mappings": {}}

        # Write should succeed quickly with no contention
        import time
        start_time = time.time()
        atomic_write_with_lock(test_file, test_data, timeout=1.0)
        elapsed_time = time.time() - start_time

        # Should complete well within timeout
        assert elapsed_time < 1.0, f"Write should be fast, took {elapsed_time:.2f}s"

def test_atomic_write_sequential_concurrent_writes():
    """Test that sequential writes work correctly (simulating concurrent access)"""
    from exec_ip_mapper import atomic_write_with_lock

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.json"

        # Simulate multiple sequential writes (realistic concurrent scenario)
        for i in range(5):
            test_data = {"mappings": {f"write_{i}": {"id": i, "timestamp": i}}}
            atomic_write_with_lock(test_file, test_data)

        # Final file should be valid JSON with the last write
        with open(test_file, 'r') as f:
            result = json.load(f)
        assert "mappings" in result
        assert "write_4" in result["mappings"]
        assert result["mappings"]["write_4"]["id"] == 4
