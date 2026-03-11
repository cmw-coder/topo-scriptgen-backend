#!/usr/bin/env python3
"""
Executor IP to temp directory mapping management module
"""

import ipaddress
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

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

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


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


class ExecutorMapping(BaseModel):
    """Executor IP to temp directory mapping"""
    executor_ip: str = Field(..., description="Executor IP address")
    temp_dir_name: str = Field(..., max_length=100, description="Temporary directory name")
    temp_dir_path: str = Field(..., description="Full path to temporary directory")
    temp_dir_unc: str = Field(..., description="UNC path to temporary directory")
    user: Optional[str] = Field(None, max_length=32, description="User identifier")
    created_at: str = Field(..., description="ISO format timestamp")
    deployed: bool = Field(True, description="Whether deployment was successful")

    @field_validator('executor_ip')
    @classmethod
    def validate_executor_ip(cls, v: str) -> str:
        """Validate IP address format"""
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f'Invalid IP address format: {v}')
        return v

    @field_validator('user')
    @classmethod
    def validate_user(cls, v: Optional[str]) -> Optional[str]:
        """Validate user parameter format"""
        if v is not None:
            # Only allow alphanumeric, underscore, hyphen
            if not re.match(r'^[a-zA-Z0-9_-]+$', v):
                raise ValueError(f'Invalid user format. Only alphanumeric, underscore, and hyphen allowed: {v}')
        return v

    @field_validator('created_at')
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate timestamp format"""
        try:
            datetime.fromisoformat(v.replace('Z', '+00:00'))
        except ValueError:
            raise ValueError(f'Invalid timestamp format. Expected ISO format: {v}')
        return v

    model_config = {
        "json_schema_extra": {
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
    }
