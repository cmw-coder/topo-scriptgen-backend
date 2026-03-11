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

from pydantic import BaseModel, Field, field_validator

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

    @field_validator('executor_ip')
    @classmethod
    def validate_executor_ip(cls, v: str) -> str:
        """Validate IP address format"""
        import ipaddress
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
            import re
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
