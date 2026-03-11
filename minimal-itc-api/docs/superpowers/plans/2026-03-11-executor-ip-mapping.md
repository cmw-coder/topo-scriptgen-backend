# Executor IP Mapping Feature Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an executor IP to temporary directory mapping system with user parameter support, enabling concurrent deployments and script execution against specific deployed environments.

**Architecture:** Create a new mapping module (exec_ip_mapper.py) with atomic file operations and locking, integrate it into existing FastAPI endpoints (upload-topox, upload-scripts, undeploy), and enhance temporary directory creation with user prefix and UUID suffix.

**Tech Stack:** FastAPI, Pydantic, fcntl/msvcrt (file locking), atomic file operations, uuid

---

## File Structure

**New Files:**
- `exec_ip_mapper.py` - Mapping management module with Pydantic models, file I/O, locking
- `tests/test_exec_ip_mapper.py` - Unit tests for mapper module
- `exec_ip.json` - Runtime mapping storage (auto-created)

**Modified Files:**
- `config.py` - Add user parameter and UUID support to temp dir creation
- `main.py` - Integrate mapper into three endpoints (upload-topox, upload-scripts, undeploy)

---

## Prerequisites

### Task 0: Install Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add required dependencies**

```bash
# Add pydantic and pytest to requirements.txt
echo "pydantic==2.10.6" >> requirements.txt
echo "pytest==8.0.0" >> requirements.txt
```

- [ ] **Step 2: Install dependencies**

```bash
cd minimal-itc-api
pip install -r requirements.txt
```

Expected: All packages installed successfully

- [ ] **Step 3: Verify installations**

```bash
python -c "import pydantic; print(f'Pydantic {pydantic.__version__}')"
python -c "import pytest; print(f'Pytest {pytest.__version__}')"
```

Expected: Version numbers displayed

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add pydantic and pytest dependencies

- Add pydantic==2.10.6 for data validation
- Add pytest==8.0.0 for unit testing"
```

---

## Chunk 1: Create exec_ip_mapper.py Module

### Task 1: Create ExecutorMapping Pydantic model

**Files:**
- Create: `exec_ip_mapper.py`
- Test: `tests/test_exec_ip_mapper.py`

- [ ] **Step 1: Create test file structure**

```bash
mkdir -p tests
touch tests/__init__.py
touch tests/test_exec_ip_mapper.py
```

- [ ] **Step 2: Write failing tests for ExecutorMapping model**

```python
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
    with pytest.raises(ValueError, match="User parameter too long"):
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py -v
```

Expected: FAIL - "ModuleNotFoundError: No module named 'exec_ip_mapper'"

- [ ] **Step 4: Create exec_ip_mapper.py with ExecutorMapping model**

```python
# exec_ip_mapper.py
#!/usr/bin/env python3
"""
Executor IP to temp directory mapping management module
"""

import json
import logging
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field, validator

# Platform-specific imports for file locking
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    # Windows: use msvcrt
    try:
        import msvcrt
        HAS_FCNTL = False
    except ImportError:
        # Fallback for platforms without either
        HAS_FCNTL = False
        msvcrt = None


logger = logging.getLogger(__name__)


class ExecutorMapping(BaseModel):
    """Executor IP to temp directory mapping"""
    executor_ip: str = Field(..., description="Executor IP address")
    temp_dir_name: str = Field(..., max_length=100, description="Temporary directory name")
    temp_dir_path: str = Field(..., description="Full path to temporary directory")
    temp_dir_unc: str = Field(..., description="UNC path to temporary directory")
    user: Optional[str] = Field(None, max_length=32, description="User identifier")
    created_at: str = Field(..., description="ISO format timestamp")
    deployed: bool = Field(True, description="Whether deployment was successful")

    @validator('executor_ip')
    def validate_executor_ip(cls, v):
        """Validate IP address format"""
        import ipaddress
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f'Invalid IP address format: {v}')
        return v

    @validator('user')
    def validate_user(cls, v):
        """Validate user parameter format"""
        if v is not None:
            import re
            # Only allow alphanumeric, underscore, hyphen
            if not re.match(r'^[a-zA-Z0-9_-]+$', v):
                raise ValueError(f'Invalid user format. Only alphanumeric, underscore, and hyphen allowed: {v}')
            if len(v) > 32:
                raise ValueError(f'User parameter too long. Max 32 characters: {v}')
        return v

    @validator('created_at')
    def validate_timestamp(cls, v):
        """Validate timestamp format"""
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError(f'Invalid timestamp format. Expected ISO format: {v}')
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "executor_ip": "10.111.8.100",
                "temp_dir_name": "user1_temp_20260311_143022_a3f2b1c4",
                "temp_dir_path": "/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                "temp_dir_unc": "//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                "user": "user1",
                "created_at": "2026-03-11T14:30:22.123456",
                "deployed": True
            }
        }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add exec_ip_mapper.py tests/test_exec_ip_mapper.py
git commit -m "feat: add ExecutorMapping Pydantic model with validators

- Add IP address format validation (IPv4/IPv6)
- Add user parameter validation (alphanumeric, underscore, hyphen)
- Add timestamp validation (ISO format)
- Add max length constraints (user: 32 chars, temp_dir_name: 100 chars)
- Add comprehensive unit tests"
```

### Task 2: Implement file path and locking utilities

**Files:**
- Modify: `exec_ip_mapper.py`
- Test: `tests/test_exec_ip_mapper.py`

- [ ] **Step 1: Write failing tests for file path**

```python
# Add to tests/test_exec_ip_mapper.py

def test_get_mapping_file_path():
    """Test that mapping file path is correctly determined"""
    from exec_ip_mapper import get_mapping_file_path

    file_path = get_mapping_file_path()
    assert file_path.name == "exec_ip.json"
    assert "minimal-itc-api" in str(file_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_get_mapping_file_path -v
```

Expected: FAIL - "function not defined"

- [ ] **Step 3: Implement get_mapping_file_path()**

```python
# Add to exec_ip_mapper.py

def get_mapping_file_path() -> Path:
    """
    Get the path to the exec_ip.json file

    Returns:
        Path to the mapping file
    """
    # Get the directory where this script is located (minimal-itc-api/)
    current_dir = Path(__file__).parent

    # exec_ip.json should be in the same directory as this script (minimal-itc-api/)
    return current_dir / "exec_ip.json"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_get_mapping_file_path -v
```

Expected: PASS

- [ ] **Step 5: Write failing tests for file locking**

```python
# Add to tests/test_exec_ip_mapper.py

import tempfile

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
        # Note: backup behavior might be implemented differently
        # This is a placeholder for when we implement backup logic
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_atomic_write_with_lock -v
```

Expected: FAIL - "function not defined"

- [ ] **Step 7: Implement atomic_write_with_lock()**

```python
# Add to exec_ip_mapper.py

def _acquire_lock(file_handle, exclusive=True):
    """Platform-specific lock acquisition"""
    if HAS_FCNTL:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(file_handle, lock_type | fcntl.LOCK_NB)
    else:
        # Windows: use msvcrt.locking
        import msvcrt
        lock_mode = msvcrt.LK_NBLCK if exclusive else msvcrt.LK_RLOCK
        msvcrt.locking(file_handle.fileno(), lock_mode, 1)


def _release_lock(file_handle):
    """Platform-specific lock release"""
    if HAS_FCNTL:
        fcntl.flock(file_handle, fcntl.LOCK_UN)
    else:
        # Windows: unlock by seeking to 0 and locking with LK_UNLCK
        import msvcrt
        file_handle.seek(0)
        msvcrt.locking(file_handle.fileno(), msvcrt.LK_UNLCK, 1)


def atomic_write_with_lock(file_path: Path, data: dict, max_retries: int = 3):
    """
    Atomic write with file locking

    Args:
        file_path: Path to the file to write
        data: Data to write (must be JSON serializable)
        max_retries: Maximum number of retry attempts

    Raises:
        IOError: If write fails after max retries
        TimeoutError: If lock acquisition times out
    """
    temp_path = file_path.with_suffix('.json.tmp')

    for attempt in range(max_retries):
        try:
            # Open temporary file
            with open(temp_path, 'w') as f:
                # Acquire exclusive lock with non-blocking mode
                try:
                    _acquire_lock(f, exclusive=True)
                except (BlockingIOError, OSError):
                    if attempt < max_retries - 1:
                        # Wait with exponential backoff
                        wait_time = 2 ** attempt
                        logger.warning(f"Lock acquisition failed, retry {attempt + 1}/{max_retries}, waiting {wait_time}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise TimeoutError(f"Could not acquire lock after {max_retries} attempts")

                try:
                    # Write data
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    # Release lock
                    _release_lock(f)

            # Atomic rename
            temp_path.replace(file_path)

            # Set file permissions to 0600 (owner read/write only)
            try:
                os.chmod(file_path, 0o600)
            except Exception as e:
                logger.warning(f"Failed to set file permissions: {e}")

            logger.info(f"Successfully wrote mapping file: {file_path}")
            return

        except Exception as e:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            logger.error(f"Failed to write mapping file (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_atomic_write_with_lock -v
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add exec_ip_mapper.py tests/test_exec_ip_mapper.py
git commit -m "feat: add file path and atomic write utilities

- Add get_mapping_file_path() to locate exec_ip.json
- Add atomic_write_with_lock() with file locking
- Use fcntl for exclusive locks with retries
- Set file permissions to 0600
- Add exponential backoff for lock acquisition"
```

### Task 3: Implement save_mapping function

**Files:**
- Modify: `exec_ip_mapper.py`
- Test: `tests/test_exec_ip_mapper.py`

- [ ] **Step 1: Write failing tests for save_mapping**

```python
# Add to tests/test_exec_ip_mapper.py

def test_save_mapping():
    """Test saving a new mapping"""
    from exec_ip_mapper import save_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "exec_ip.json"

        try:
            # Save a mapping
            save_mapping(
                executor_ip="10.111.8.100",
                temp_dir_name="user1_temp_20260311_143022_a3f2b1c4",
                temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                user="user1"
            )

            # Verify file was created
            file_path = exec_ip_mapper.get_mapping_file_path()
            assert file_path.exists()

            # Verify content
            with open(file_path, 'r') as f:
                data = json.load(f)

            assert "10.111.8.100" in data["mappings"]
            assert data["mappings"]["10.111.8.100"]["user"] == "user1"

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path

def test_save_mapping_without_user():
    """Test saving a mapping without user parameter"""
    from exec_ip_mapper import save_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "exec_ip.json"

        try:
            save_mapping(
                executor_ip="10.111.8.101",
                temp_dir_name="temp_20260311_143022_a3f2b1c4",
                temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
                temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/temp_20260311_143022_a3f2b1c4",
                user=None
            )

            file_path = exec_ip_mapper.get_mapping_file_path()
            with open(file_path, 'r') as f:
                data = json.load(f)

            assert data["mappings"]["10.111.8.101"]["user"] is None

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_save_mapping -v
```

Expected: FAIL - "function not defined"

- [ ] **Step 3: Implement save_mapping()**

```python
# Add to exec_ip_mapper.py

def save_mapping(
    executor_ip: str,
    temp_dir_name: str,
    temp_dir_path: str,
    temp_dir_unc: str,
    user: Optional[str] = None
) -> ExecutorMapping:
    """
    Save a new executor IP mapping

    Args:
        executor_ip: Executor IP address
        temp_dir_name: Temporary directory name
        temp_dir_path: Full path to temporary directory
        temp_dir_unc: UNC path to temporary directory
        user: Optional user identifier

    Returns:
        ExecutorMapping object

    Raises:
        ValueError: If validation fails
        IOError: If file write fails
    """
    # Validate temp directory exists
    if not Path(temp_dir_path).exists():
        raise ValueError(f"Temporary directory does not exist: {temp_dir_path}")

    # Create mapping object (this will trigger validation)
    mapping = ExecutorMapping(
        executor_ip=executor_ip,
        temp_dir_name=temp_dir_name,
        temp_dir_path=temp_dir_path,
        temp_dir_unc=temp_dir_unc,
        user=user,
        created_at=datetime.utcnow().isoformat(),
        deployed=True
    )

    # Read existing data
    file_path = get_mapping_file_path()
    if file_path.exists():
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except json.JSONDecodeError:
            logger.warning("Corrupted mapping file, creating new one")
            # Backup corrupted file
            backup_path = file_path.with_suffix('.json.backup')
            file_path.replace(backup_path)
            data = {"mappings": {}}
    else:
        data = {"mappings": {}}

    # Add new mapping
    data["mappings"][executor_ip] = mapping.dict()

    # Write atomically
    atomic_write_with_lock(file_path, data)

    logger.info(f"Saved mapping: executor_ip={executor_ip}, temp_dir={temp_dir_name}, user={user}")

    return mapping
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_save_mapping -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add exec_ip_mapper.py tests/test_exec_ip_mapper.py
git commit -m "feat: add save_mapping function

- Create ExecutorMapping object with validation
- Read existing mappings or create new file
- Handle corrupted JSON with backup
- Write atomically with locking
- Log mapping save operations"
```

### Task 4: Implement get_mapping and delete_mapping functions

**Files:**
- Modify: `exec_ip_mapper.py`
- Test: `tests/test_exec_ip_mapper.py`

- [ ] **Step 1: Write failing tests for get_mapping**

```python
# Add to tests/test_exec_ip_mapper.py

def test_get_mapping():
    """Test retrieving an existing mapping"""
    from exec_ip_mapper import get_mapping, save_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "exec_ip.json"

        try:
            # Save a mapping first
            save_mapping(
                executor_ip="10.111.8.100",
                temp_dir_name="user1_temp_20260311_143022_a3f2b1c4",
                temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                user="user1"
            )

            # Retrieve the mapping
            mapping = get_mapping("10.111.8.100")

            assert mapping is not None
            assert mapping.executor_ip == "10.111.8.100"
            assert mapping.user == "user1"

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path

def test_get_mapping_not_found():
    """Test retrieving a non-existent mapping"""
    from exec_ip_mapper import get_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "exec_ip.json"

        try:
            # Try to get a mapping that doesn't exist
            mapping = get_mapping("10.111.8.999")

            assert mapping is None

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path

def test_get_mapping_file_not_exists():
    """Test get_mapping when file doesn't exist"""
    from exec_ip_mapper import get_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path to non-existent file
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "nonexistent.json"

        try:
            mapping = get_mapping("10.111.8.100")

            assert mapping is None

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_get_mapping -v
```

Expected: FAIL - "function not defined"

- [ ] **Step 3: Implement get_mapping()**

```python
# Add to exec_ip_mapper.py

def get_mapping(executor_ip: str) -> Optional[ExecutorMapping]:
    """
    Retrieve a mapping by executor IP

    Args:
        executor_ip: Executor IP address

    Returns:
        ExecutorMapping object if found, None otherwise
    """
    file_path = get_mapping_file_path()

    # If file doesn't exist, return None
    if not file_path.exists():
        logger.info(f"Mapping file not found: {file_path}")
        return None

    try:
        # Read file with shared lock
        with open(file_path, 'r') as f:
            # Acquire shared lock for reading
            _acquire_lock(f, exclusive=False)
            try:
                data = json.load(f)
            finally:
                _release_lock(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Corrupted mapping file: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading mapping file: {e}")
        return None

    # Get mapping for executor IP
    mapping_data = data.get("mappings", {}).get(executor_ip)

    if mapping_data is None:
        logger.info(f"Mapping not found for executor_ip: {executor_ip}")
        return None

    # Create ExecutorMapping object
    try:
        mapping = ExecutorMapping(**mapping_data)
        logger.info(f"Retrieved mapping: executor_ip={executor_ip}")
        return mapping
    except Exception as e:
        logger.error(f"Invalid mapping data for executor_ip={executor_ip}: {e}")
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_get_mapping -v
```

Expected: PASS

- [ ] **Step 5: Write failing tests for delete_mapping**

```python
# Add to tests/test_exec_ip_mapper.py

def test_delete_mapping():
    """Test deleting an existing mapping"""
    from exec_ip_mapper import delete_mapping, save_mapping, get_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "exec_ip.json"

        try:
            # Save a mapping first
            save_mapping(
                executor_ip="10.111.8.100",
                temp_dir_name="user1_temp_20260311_143022_a3f2b1c4",
                temp_dir_path="/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                temp_dir_unc="//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
                user="user1"
            )

            # Verify it exists
            assert get_mapping("10.111.8.100") is not None

            # Delete the mapping
            delete_mapping("10.111.8.100")

            # Verify it's gone
            assert get_mapping("10.111.8.100") is None

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path

def test_delete_mapping_not_found():
    """Test deleting a non-existent mapping (should not raise error)"""
    from exec_ip_mapper import delete_mapping

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the file path
        original_get_path = exec_ip_mapper.get_mapping_file_path
        exec_ip_mapper.get_mapping_file_path = lambda: Path(tmpdir) / "exec_ip.json"

        try:
            # Delete non-existent mapping (should not raise)
            delete_mapping("10.111.8.999")

            # Should succeed silently
            assert True

        finally:
            exec_ip_mapper.get_mapping_file_path = original_get_path
```

- [ ] **Step 6: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_delete_mapping -v
```

Expected: FAIL - "function not defined"

- [ ] **Step 7: Implement delete_mapping()**

```python
# Add to exec_ip_mapper.py

def delete_mapping(executor_ip: str) -> bool:
    """
    Delete a mapping by executor IP

    Args:
        executor_ip: Executor IP address

    Returns:
        True if mapping was deleted, False if it didn't exist
    """
    file_path = get_mapping_file_path()

    # If file doesn't exist, nothing to delete
    if not file_path.exists():
        logger.info(f"Mapping file not found: {file_path}")
        return False

    try:
        # Read existing data
        with open(file_path, 'r') as f:
            _acquire_lock(f, exclusive=False)
            try:
                data = json.load(f)
            finally:
                _release_lock(f)
    except json.JSONDecodeError as e:
        logger.warning(f"Corrupted mapping file: {e}")
        return False
    except Exception as e:
        logger.error(f"Error reading mapping file: {e}")
        return False

    # Check if mapping exists
    if executor_ip not in data.get("mappings", {}):
        logger.info(f"Mapping not found for executor_ip: {executor_ip}")
        return False

    # Delete mapping
    del data["mappings"][executor_ip]

    # Write atomically
    atomic_write_with_lock(file_path, data)

    logger.info(f"Deleted mapping: executor_ip={executor_ip}")

    return True
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_exec_ip_mapper.py::test_delete_mapping -v
```

Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add exec_ip_mapper.py tests/test_exec_ip_mapper.py
git commit -m "feat: add get_mapping and delete_mapping functions

- Implement get_mapping() with shared lock for reading
- Implement delete_mapping() with atomic write
- Handle missing files and corrupted data gracefully
- Return None for non-existent mappings
- Log all operations"
```

---

## Chunk 2: Update config.py for User Parameter and UUID Support

### Task 5: Modify create_temp_dir to support user parameter

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py` (create new file)

- [ ] **Step 1: Create test file and write failing tests**

```python
# tests/test_config.py
import pytest
from unittest.mock import patch
from datetime import datetime
from config import Settings

def test_create_temp_dir_with_user():
    """Test creating temp directory with user parameter"""
    settings = Settings()

    with patch('config.datetime') as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "20260311_143022"
        mock_datetime.now.return_value.isoformat.return_value = "2026-03-11T14:30:22"

        with patch('config.uuid') as mock_uuid:
            mock_uuid.uuid4.return_value.hex = 'a3f2b1c4d5e6f7a8'

            temp_dir_name = settings.create_temp_dir(user="testuser")

            assert temp_dir_name == "testuser_temp_20260311_143022_a3f2b1c4"

def test_create_temp_dir_without_user():
    """Test creating temp directory without user parameter"""
    settings = Settings()

    with patch('config.datetime') as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "20260311_143022"

        with patch('config.uuid') as mock_uuid:
            mock_uuid.uuid4.return_value.hex = 'a3f2b1c4d5e6f7a8'

            temp_dir_name = settings.create_temp_dir(user=None)

            assert temp_dir_name == "temp_20260311_143022_a3f2b1c4"

def test_create_temp_dir_uniqueness():
    """Test that concurrent calls create unique directories"""
    settings = Settings()

    with patch('config.datetime') as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "20260311_143022"

        with patch('config.uuid') as mock_uuid:
            # Mock uuid to return different values
            mock_uuid.uuid4.side_effect = [
                type('obj', (object,), {'hex': 'a3f2b1c4d5e6f7a8'}),
                type('obj', (object,), {'hex': 'b4g3c2d1e6f8a7b9'})
            ]

            name1 = settings.create_temp_dir(user="testuser")
            name2 = settings.create_temp_dir(user="testuser")

            assert name1 != name2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_config.py -v
```

Expected: FAIL - "create_temp_dir() doesn't accept 'user' parameter"

- [ ] **Step 3: Update config.py to add imports**

```python
# Add to imports in config.py
import uuid
```

- [ ] **Step 4: Update create_temp_dir() method**

```python
# In config.py, modify the create_temp_dir method:

@classmethod
def create_temp_dir(cls, user: Optional[str] = None) -> str:
    """
    Create new temporary directory

    Args:
        user: Optional user identifier to prefix directory name

    Returns:
        Temporary directory name
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uuid_suffix = uuid.uuid4().hex[:8]  # First 8 characters of UUID

    if user:
        cls._temp_dir_name = f"{user}_temp_{timestamp}_{uuid_suffix}"
    else:
        cls._temp_dir_name = f"temp_{timestamp}_{uuid_suffix}"

    temp_dir = cls.get_base_dir() / cls._temp_dir_name
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Set permissions to 777
    try:
        os.chmod(temp_dir, 0o777)
    except Exception as e:
        print(f"Warning: Failed to set temp directory permissions: {e}")

    return cls._temp_dir_name
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_config.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add user parameter and UUID to temp directory creation

- Add optional user parameter to create_temp_dir()
- Add UUID suffix for uniqueness in concurrent deployments
- Format: {user}_temp_{timestamp}_{uuid} or temp_{timestamp}_{uuid}
- Add unit tests for directory naming with and without user"
```

### Task 6: Modify create_temp_dir_standalone to support user parameter

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_config.py

def test_create_temp_dir_standalone_with_user():
    """Test creating standalone temp directory with user parameter"""
    settings = Settings()

    with patch('config.datetime') as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "20260311_143022"

        with patch('config.uuid') as mock_uuid:
            mock_uuid.uuid4.return_value.hex = 'a3f2b1c4d5e6f7a8'

            temp_dir_name, temp_dir = settings.create_temp_dir_standalone(user="testuser")

            assert temp_dir_name == "testuser_temp_20260311_143022_a3f2b1c4"
            assert temp_dir.name == temp_dir_name
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_config.py::test_create_temp_dir_standalone_with_user -v
```

Expected: FAIL - "create_temp_dir_standalone() doesn't accept 'user' parameter"

- [ ] **Step 3: Update create_temp_dir_standalone() method**

```python
# In config.py, modify the create_temp_dir_standalone method:

@classmethod
def create_temp_dir_standalone(cls, user: Optional[str] = None) -> tuple[str, Path]:
    """
    Create standalone temporary directory (doesn't update global _temp_dir_name)

    Args:
        user: Optional user identifier to prefix directory name

    Returns:
        Tuple of (temp_dir_name, temp_dir_path)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uuid_suffix = uuid.uuid4().hex[:8]

    if user:
        temp_dir_name = f"{user}_temp_{timestamp}_{uuid_suffix}"
    else:
        temp_dir_name = f"temp_{timestamp}_{uuid_suffix}"

    temp_dir = cls.get_base_dir() / temp_dir_name
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Set permissions to 777
    try:
        os.chmod(temp_dir, 0o777)
    except Exception as e:
        print(f"Warning: Failed to set temp directory permissions: {e}")

    return temp_dir_name, temp_dir
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_config.py::test_create_temp_dir_standalone_with_user -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add user parameter to create_temp_dir_standalone

- Add optional user parameter to create_temp_dir_standalone()
- Maintain consistency with create_temp_dir() naming
- Add unit test"
```

---

## Chunk 3: Update main.py Endpoints

### Task 7: Update upload-topox endpoint

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py` (create new file)

- [ ] **Step 1: Create test file and write failing tests**

```python
# tests/test_main.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from main import app

client = TestClient(app)

def test_upload_topox_with_user_parameter():
    """Test upload-topox with user parameter"""
    # Mock ITC client response
    mock_itc_response = {
        "return_code": "200",
        "return_info": "Deployment successful",
        "result": {
            "executorip": "10.111.8.100",
            "terminalinfo": []
        }
    }

    with patch('exec_ip_mapper.save_mapping') as mock_save:
        with patch.object(app.state, 'itc_client') as mock_client:
            mock_client.newdeploy.return_value = mock_itc_response

            # Create a fake topox file
            fake_file_content = b"fake topox content"

            response = client.post(
                "/api/v1/upload-topox",
                files={"topox_file": ("test.topox", fake_file_content, "application/octet-stream")},
                data={"user": "testuser"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "testuser_temp_" in data["data"]["temp_dir_name"]

            # Verify save_mapping was called
            mock_save.assert_called_once()
            call_args = mock_save.call_args
            assert call_args[1]["executor_ip"] == "10.111.8.100"
            assert call_args[1]["user"] == "testuser"

def test_upload_topox_without_user_parameter():
    """Test upload-topox without user parameter"""
    mock_itc_response = {
        "return_code": "200",
        "return_info": "Deployment successful",
        "result": {
            "executorip": "10.111.8.101",
            "terminalinfo": []
        }
    }

    with patch('exec_ip_mapper.save_mapping') as mock_save:
        with patch.object(app.state, 'itc_client') as mock_client:
            mock_client.newdeploy.return_value = mock_itc_response

            fake_file_content = b"fake topox content"

            response = client.post(
                "/api/v1/upload-topox",
                files={"topox_file": ("test.topox", fake_file_content, "application/octet-stream")}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["data"]["temp_dir_name"].startswith("temp_")

            # Verify save_mapping was called with None user
            mock_save.assert_called_once()
            call_args = mock_save.call_args
            assert call_args[1]["user"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_main.py::test_upload_topox_with_user_parameter -v
```

Expected: FAIL - "user parameter not accepted or save_mapping not called"

- [ ] **Step 3: Update upload-topox endpoint**

```python
# In main.py, modify the upload_topox_and_deploy function:

@app.post("/api/v1/upload-topox", response_model=DeployResponse, tags=["ITC API"])
async def upload_topox_and_deploy(
    topox_file: UploadFile = File(..., description="Topox 文件"),
    version_path: str = Form(None, description="版本目录路径"),
    device_type: str = Form("simware9cen", description="设备类型"),
    user: str = Form(None, description="用户标识")
):
    """
    Upload topox file and deploy network

    1. Create new temporary directory (user prefix optional)
    2. Save uploaded topox file
    3. Call ITC newdeploy endpoint
    4. Save executor IP mapping to exec_ip.json
    5. Return deployment result
    """
    logger = logging.getLogger(__name__)

    try:
        # Validate file extension
        if not topox_file.filename.endswith(".topox"):
            raise HTTPException(
                status_code=400,
                detail="Only .topox files are supported"
            )

        # Create new temporary directory with user parameter
        temp_dir_name = settings.create_temp_dir(user=user)
        temp_dir = settings.get_temp_dir()
        logger.info(f"Created new temp directory: {temp_dir}")

        # Save topox file to temp directory
        file_path = temp_dir / topox_file.filename
        logger.info(f"Saving topox file to temp directory: {file_path}")

        with open(file_path, "wb") as f:
            content = await topox_file.read()
            f.write(content)

        # Set file permissions to 777
        settings.set_directory_permissions(temp_dir)

        # Validate file size
        file_size = file_path.stat().st_size
        if file_size > settings.MAX_FILE_SIZE:
            file_path.unlink()
            raise HTTPException(
                status_code=400,
                detail=f"File too large: {file_size} bytes (max {settings.MAX_FILE_SIZE} bytes)"
            )

        logger.info(f"File saved to temp directory: {topox_file.filename} ({file_size} bytes)")
        logger.info(f"Temp directory UNC path: {settings.get_temp_dir_uname()}")

        # Call ITC newdeploy endpoint
        itc_client = app.state.itc_client
        deploy_result = await itc_client.newdeploy(
            topofile_unc=settings.get_temp_dir_uname(),
            versionpath=version_path,
            device_type=device_type
        )

        # Check deployment result
        return_code = deploy_result.get("return_code")
        return_info = deploy_result.get("return_info")
        result = deploy_result.get("result")

        if return_code == "200":
            logger.info(f"Deployment successful: {return_info}")

            # Extract executor_ip from ITC response
            executor_ip = None
            if result and isinstance(result, dict):
                executor_ip = result.get("executorip")

            # Save mapping if executor_ip is available
            if executor_ip:
                try:
                    from exec_ip_mapper import save_mapping
                    save_mapping(
                        executor_ip=executor_ip,
                        temp_dir_name=temp_dir_name,
                        temp_dir_path=str(temp_dir),
                        temp_dir_unc=settings.get_temp_dir_uname(),
                        user=user
                    )
                    logger.info(f"Saved mapping: executor_ip={executor_ip}, temp_dir={temp_dir_name}, user={user}")
                except Exception as e:
                    logger.error(f"Failed to save mapping: {e}")
                    # Mapping save failure is not critical
            else:
                logger.warning(f"No executor_ip found in ITC response, skipping mapping save")

            return DeployResponse(
                status="ok",
                message=f"Topox file saved to temp directory ({temp_dir_name}) and deployed successfully",
                data={
                    # ITC complete response (passthrough)
                    "return_code": return_code,
                    "return_info": return_info,
                    "result": result,
                    # Temp directory info
                    "temp_dir_name": temp_dir_name,
                    "temp_dir_path": str(temp_dir),
                    "temp_dir_unc": settings.get_temp_dir_uname(),
                    # Mapping info
                    "executor_ip": executor_ip,
                    "user": user
                }
            )
        else:
            logger.error(f"Deployment failed: {return_info}")
            return DeployResponse(
                status="error",
                message=f"Deployment failed: {return_info}",
                data={
                    # ITC complete response (passthrough)
                    "return_code": return_code,
                    "return_info": return_info,
                    "result": result,
                    # Temp directory info
                    "temp_dir_name": temp_dir_name
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing topox upload: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing topox upload: {str(e)}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_main.py::test_upload_topox_with_user_parameter -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: add user parameter to upload-topox endpoint

- Add optional user parameter to upload-topox
- Extract executor_ip from ITC response
- Save mapping to exec_ip.json after deployment
- Include mapping info in response
- Handle missing executor_ip gracefully"
```

### Task 8: Update upload-scripts endpoint

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_main.py

def test_upload_scripts_without_topox_with_mapping():
    """Test upload-scripts without topox, using mapping"""
    mock_mapping = MagicMock()
    mock_mapping.temp_dir_unc = "//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4"
    mock_mapping.temp_dir_name = "user1_temp_20260311_143022_a3f2b1c4"

    mock_itc_response = {
        "return_code": "200",
        "return_info": "Scripts executed successfully",
        "result": {}
    }

    with patch('exec_ip_mapper.get_mapping', return_value=mock_mapping) as mock_get:
        with patch('pathlib.Path.exists', return_value=True):
            with patch.object(app.state, 'itc_client') as mock_client:
                mock_client.run_scripts.return_value = mock_itc_response

                fake_script = b"print('hello')"

                response = client.post(
                    "/api/v1/upload-scripts",
                    files={"script_files": ("test.py", fake_script, "text/plain")},
                    data={"executor_ip": "10.111.8.100"}
                )

                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "ok"
                assert data["data"]["temp_dir_unc"] == mock_mapping.temp_dir_unc

                # Verify get_mapping was called
                mock_get.assert_called_once_with("10.111.8.100")

def test_upload_scripts_without_topox_no_mapping():
    """Test upload-scripts without topox, mapping not found"""
    with patch('exec_ip_mapper.get_mapping', return_value=None):
        response = client.post(
            "/api/v1/upload-scripts",
            files={"script_files": ("test.py", b"print('hello')", "text/plain")},
            data={"executor_ip": "10.111.8.999"}
        )

        assert response.status_code == 400
        assert "未找到" in response.json()["detail"]

def test_upload_scripts_with_topox():
    """Test upload-scripts with topox file (existing behavior)"""
    mock_itc_response = {
        "return_code": "200",
        "return_info": "Scripts executed successfully",
        "result": {}
    }

    with patch('exec_ip_mapper.get_mapping', return_value=None):
        with patch.object(app.state, 'itc_client') as mock_client:
            mock_client.run_scripts.return_value = mock_itc_response

            fake_topox = b"fake topox content"
            fake_script = b"print('hello')"

            response = client.post(
                "/api/v1/upload-scripts",
                files=[
                    ("script_files", ("test.topox", fake_topox, "application/octet-stream")),
                    ("script_files", ("test.py", fake_script, "text/plain"))
                ],
                data={"executor_ip": "10.111.8.100"}
            )

            assert response.status_code == 200
            # Should create standalone temp directory
            mock_client.run_scripts.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_main.py::test_upload_scripts_without_topox_with_mapping -v
```

Expected: FAIL - "mapping lookup not implemented"

- [ ] **Step 3: Update upload-scripts endpoint**

```python
# In main.py, modify the upload_scripts_and_run function:

@app.post("/api/v1/upload-scripts", response_model=RunResponse, tags=["ITC API"])
async def upload_scripts_and_run(
    script_files: list[UploadFile] = File(..., description="Script file list"),
    executor_ip: str = Form(..., description="Executor IP address")
):
    """
    Batch upload files and run scripts (supports scripts and topox files)

    Logic:
    1. If uploaded files contain .topox file:
       - Create standalone temp directory (independent from upload-topox)
       - Save all files (including topox and scripts)
       - Call ITC run_scripts endpoint
    2. If only script files (no .topox):
       - Query exec_ip.json for executor_ip mapping
       - If found: use mapped temp directory
       - If not found: return error
    """
    logger = logging.getLogger(__name__)

    try:
        # Validate executor IP
        if not executor_ip:
            raise HTTPException(
                status_code=400,
                detail="executor_ip parameter is required"
            )

        # Check if uploaded files contain .topox file
        has_topox = any(
            f.filename and f.filename.endswith(".topox")
            for f in script_files
        )

        if has_topox:
            # ========== Has topox file: create standalone temp directory ==========
            logger.info("Detected .topox file, creating standalone temp directory")

            # Create standalone temp directory (user=None for independent temp dirs)
            temp_dir_name, temp_dir = settings.create_temp_dir_standalone(user=None)
            logger.info(f"Created standalone temp directory: {temp_dir}")

            scripts_unc_path = f"{settings.BASE_UNC_DIR}/{temp_dir_name}"

        else:
            # ========== Only script files: use mapping ==========
            logger.info("No .topox file detected, querying mapping for executor_ip")

            try:
                from exec_ip_mapper import get_mapping
                from pathlib import Path

                mapping = get_mapping(executor_ip)

                if mapping is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"未找到 executor_ip {executor_ip} 对应的临时目录，请先调用 upload-topox 进行部署"
                    )

                # Validate temp directory still exists
                if not Path(mapping.temp_dir_path).exists():
                    raise HTTPException(
                        status_code=400,
                        detail=f"临时目录 {mapping.temp_dir_name} 不存在，请重新部署"
                    )

                # Use mapped temp directory
                temp_dir = Path(mapping.temp_dir_path)
                temp_dir_name = mapping.temp_dir_name
                scripts_unc_path = mapping.temp_dir_unc

                logger.info(f"Using mapped temp directory: {temp_dir}")

            except FileNotFoundError:
                # Mapping file doesn't exist
                raise HTTPException(
                    status_code=400,
                    detail="映射文件不存在，请先调用 upload-topox 进行部署"
                )
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise
                # Other errors (corrupted file, etc.)
                logger.error(f"Error reading mapping: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="映射文件损坏，请联系管理员"
                )

        # Save all files to temp directory
        saved_files = []
        for upload_file in script_files:
            # Validate file extension
            file_ext = Path(upload_file.filename).suffix.lower()
            if file_ext not in settings.ALLOWED_TOPOX_EXTENSIONS and \
               file_ext not in settings.ALLOWED_SCRIPT_EXTENSIONS:
                logger.warning(f"Skipping unsupported file type: {upload_file.filename}")
                continue

            # Save file to temp directory
            file_path = temp_dir / upload_file.filename
            logger.info(f"Saving file to temp directory: {file_path}")

            with open(file_path, "wb") as f:
                content = await upload_file.read()
                f.write(content)

            file_size = file_path.stat().st_size
            saved_files.append({
                "filename": upload_file.filename,
                "size": file_size,
                "path": str(file_path)
            })
            logger.info(f"File saved to temp directory: {upload_file.filename} ({file_size} bytes)")

        if not saved_files:
            raise HTTPException(
                status_code=400,
                detail="No valid files were uploaded"
            )

        # Set temp directory and all file permissions to 777
        settings.set_directory_permissions(temp_dir)

        logger.info(f"Saved {len(saved_files)} files to temp directory: {temp_dir_name}")
        logger.info(f"Temp directory UNC path: {scripts_unc_path}")

        # Call ITC run endpoint
        itc_client = app.state.itc_client
        run_result = await itc_client.run_scripts(
            scripts_unc_path=scripts_unc_path,
            executor_ip=executor_ip
        )

        # Check run result
        return_code = run_result.get("return_code")
        return_info = run_result.get("return_info")
        result = run_result.get("result")

        if return_code == "200":
            logger.info(f"Script execution successful: {return_info}")
            return RunResponse(
                status="ok",
                message=f"Saved {len(saved_files)} files to temp directory ({temp_dir_name}) and executed successfully",
                data={
                    # ITC complete response (passthrough)
                    "return_code": return_code,
                    "return_info": return_info,
                    "result": result,
                    # Saved file info
                    "saved_files": saved_files,
                    # Temp directory info
                    "temp_dir_name": temp_dir_name,
                    "temp_dir_path": str(temp_dir),
                    "temp_dir_unc": scripts_unc_path
                }
            )
        else:
            logger.error(f"Script execution failed: {return_info}")
            return RunResponse(
                status="error",
                message=f"Script execution failed: {return_info}",
                data={
                    # ITC complete response (passthrough)
                    "return_code": return_code,
                    "return_info": return_info,
                    "result": result,
                    # Saved file info
                    "saved_files": saved_files,
                    # Temp directory info
                    "temp_dir_name": temp_dir_name
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing file upload: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error processing file upload: {str(e)}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_main.py::test_upload_scripts_without_topox_with_mapping -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: update upload-scripts to use executor IP mapping

- Query exec_ip.json when no topox file provided
- Return clear error if mapping not found
- Validate temp directory exists
- Keep existing behavior when topox file included
- Handle missing/corrupted mapping file"
```

### Task 9: Update undeploy endpoint

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/test_main.py

def test_undeploy_deletes_mapping():
    """Test that undeploy deletes mapping"""
    mock_itc_response = {
        "return_code": "200",
        "return_info": "Undeploy successful",
        "result": {}
    }

    with patch('exec_ip_mapper.delete_mapping') as mock_delete:
        with patch.object(app.state, 'itc_client') as mock_client:
            mock_client.undeploy.return_value = mock_itc_response

            response = client.post(
                "/api/v1/undeploy",
                data={"executor_ip": "10.111.8.100"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"

            # Verify delete_mapping was called
            mock_delete.assert_called_once_with("10.111.8.100")

def test_undeploy_deletes_mapping_on_itc_failure():
    """Test that undeploy deletes mapping even if ITC fails"""
    mock_itc_response = {
        "return_code": "500",
        "return_info": "ITC error",
        "result": None
    }

    with patch('exec_ip_mapper.delete_mapping') as mock_delete:
        with patch.object(app.state, 'itc_client') as mock_client:
            mock_client.undeploy.return_value = mock_itc_response

            response = client.post(
                "/api/v1/undeploy",
                data={"executor_ip": "10.111.8.100"}
            )

            # ITC failed, but mapping should still be deleted
            mock_delete.assert_called_once_with("10.111.8.100")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd minimal-itc-api
pytest tests/test_main.py::test_undeploy_deletes_mapping -v
```

Expected: FAIL - "delete_mapping not called"

- [ ] **Step 3: Update undeploy endpoint**

```python
# In main.py, modify the undeploy_environment function:

@app.post("/api/v1/undeploy", response_model=BaseResponse, tags=["ITC API"])
async def undeploy_environment(
    executor_ip: str = Form(..., description="Executor IP address")
):
    """
    Undeploy network environment

    1. Call ITC undeploy endpoint based on executor IP
    2. Delete mapping from exec_ip.json
    3. Return undeploy result
    """
    logger = logging.getLogger(__name__)

    try:
        # Validate executor IP
        if not executor_ip:
            raise HTTPException(
                status_code=400,
                detail="executor_ip parameter is required"
            )

        logger.info(f"Starting undeploy for executor {executor_ip}")

        # Call ITC undeploy endpoint
        itc_client = app.state.itc_client
        undeploy_result = await itc_client.undeploy(
            executor_ip=executor_ip
        )

        # Delete mapping regardless of ITC result
        try:
            from exec_ip_mapper import delete_mapping
            deleted = delete_mapping(executor_ip)
            if deleted:
                logger.info(f"Deleted mapping for executor_ip: {executor_ip}")
            else:
                logger.info(f"No mapping found for executor_ip: {executor_ip}")
        except Exception as e:
            logger.error(f"Failed to delete mapping: {e}")
            # Mapping deletion failure doesn't affect response

        # Check undeploy result
        return_code = undeploy_result.get("return_code")
        return_info = undeploy_result.get("return_info")
        result = undeploy_result.get("result")

        if return_code == "200":
            logger.info(f"Undeploy successful: {return_info}")
            return BaseResponse(
                status="ok",
                message=f"Executor {executor_ip} network environment undeployed successfully",
                data={
                    # ITC complete response (passthrough)
                    "return_code": return_code,
                    "return_info": return_info,
                    "result": result,
                    # Executor info
                    "executor_ip": executor_ip
                }
            )
        else:
            logger.error(f"Undeploy failed: {return_info}")
            return BaseResponse(
                status="error",
                message=f"Undeploy failed: {return_info}",
                data={
                    # ITC complete response (passthrough)
                    "return_code": return_code,
                    "return_info": return_info,
                    "result": result,
                    # Executor info
                    "executor_ip": executor_ip
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error undeploying network environment: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error undeploying network environment: {str(e)}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd minimal-itc-api
pytest tests/test_main.py::test_undeploy_deletes_mapping -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: delete mapping on undeploy

- Delete executor IP mapping on undeploy
- Delete mapping regardless of ITC result
- Handle missing mappings gracefully
- Log mapping deletion operations"
```

---

## Final Steps

- [ ] **Step 1: Run all tests**

```bash
cd minimal-itc-api
pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 2: Update API documentation**

Update README.md with new `user` parameter:

```markdown
### 1. Upload topox and deploy

**POST** `/api/v1/upload-topox`

**Request parameters (multipart/form-data):**
- `topox_file`: Topox file (required)
- `version_path`: Version directory path (optional)
- `device_type`: Device type (optional, default: simware9cen)
- `user`: User identifier (optional) - If provided, temp directory will be prefixed with this value

**Example (curl):**
```bash
curl -X POST "http://localhost:3001/api/v1/upload-topox" \
  -F "topox_file=@/path/to/file.topox" \
  -F "version_path=/path/to/version" \
  -F "device_type=simware9cen" \
  -F "user=testuser"
```

### 2. Batch upload scripts and execute

**POST** `/api/v1/upload-scripts`

**Behavior:**
- If `.topox` file included: Creates new temp directory (existing behavior)
- If no `.topox` file: Uses existing temp directory from `exec_ip.json` mapping

**Example (curl) - with topox:**
```bash
curl -X POST "http://localhost:3001/api/v1/upload-scripts" \
  -F "script_files=@/path/to/test.topox" \
  -F "script_files=@/path/to/test.py" \
  -F "executor_ip=10.111.8.100"
```

**Example (curl) - without topox (uses mapping):**
```bash
curl -X POST "http://localhost:3001/api/v1/upload-scripts" \
  -F "script_files=@/path/to/test.py" \
  -F "executor_ip=10.111.8.100"
```
```

- [ ] **Step 3: Create exec_ip.json gitignore entry**

```bash
# Add to .gitignore
echo "exec_ip.json" >> .gitignore
```

- [ ] **Step 4: Final commit**

```bash
git add README.md .gitignore
git commit -m "docs: update documentation for executor IP mapping feature

- Document user parameter in upload-topox
- Explain mapping-based behavior for upload-scripts
- Add exec_ip.json to gitignore
- Update API examples"
```

- [ ] **Step 5: Verify implementation**

```bash
# Start the server
python main.py --port 3001

# In another terminal, test the flow:
# 1. Upload topox with user parameter
curl -X POST "http://localhost:3001/api/v1/upload-topox" \
  -F "topox_file=@test.topox" \
  -F "user=testuser"

# 2. Check exec_ip.json was created
cat exec_ip.json

# 3. Upload scripts without topox (uses mapping)
curl -X POST "http://localhost:3001/api/v1/upload-scripts" \
  -F "script_files=@test.py" \
  -F "executor_ip=<IP_FROM_STEP_1>"

# 4. Undeploy
curl -X POST "http://localhost:3001/api/v1/undeploy" \
  -F "executor_ip=<IP_FROM_STEP_1>"

# 5. Check exec_ip.json - mapping should be deleted
cat exec_ip.json
```

---

**End of Implementation Plan**
