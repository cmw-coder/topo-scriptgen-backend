# Executor IP Mapping Feature Design

**Date**: 2026-03-11
**Author**: Claude
**Status**: Draft

## Overview

Add support for mapping executor IPs to temporary directories with optional user parameter isolation. This feature enables multiple users to deploy topox files concurrently and run scripts against specific deployed environments.

## Requirements

### 1. User Parameter Support
- Add optional `user` parameter to `upload-topox` endpoint
- Include user identifier in temporary directory name when provided
- Ensure temporary directory uniqueness across concurrent deployments

### 2. Executor IP Mapping
- Save mapping between executor IP and temporary directory after deployment
- Store mapping in `exec_ip.json` file in project root directory
- Use atomic file operations to prevent corruption

### 3. Script Execution Lookup
- Query `exec_ip.json` to find temporary directory based on executor IP
- Only apply lookup when no topox file is provided in `upload-scripts`
- Return clear error if mapping not found

### 4. Mapping Cleanup
- Delete mapping from `exec_ip.json` when undeploying
- Remove mapping regardless of ITC undeploy success/failure

## Architecture

### New Components

#### 1. exec_ip_mapper.py
New module responsible for managing executor IP mappings.

**Key Functions**:
- `save_mapping(executor_ip: str, temp_dir_name: str, temp_dir_path: str, temp_dir_unc: str, user: Optional[str])` - Save new mapping
- `get_mapping(executor_ip: str) -> Optional[ExecutorMapping]` - Retrieve mapping by executor IP
- `delete_mapping(executor_ip: str)` - Delete mapping
- `atomic_write(file_path: Path, data: dict)` - Atomic file write using temp file and file locking

**Data Structure**:
```python
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime

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
        import re
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        ipv6_pattern = r'^[0-9a-fA-F:]+$'
        if not (re.match(ipv4_pattern, v) or re.match(ipv6_pattern, v)):
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

**File Concurrency Control**:
- Use `fcntl` (Unix) or `msvcrt.locking` (Windows) for file locking
- Acquire shared lock for reads, exclusive lock for writes
- Implement timeout for lock acquisition (default: 5 seconds)
- Fallback to retry mechanism if lock acquisition fails

#### 2. exec_ip.json
JSON file storing executor IP mappings, located at project root.

**Schema**:
```json
{
  "mappings": {
    "10.111.8.100": {
      "executor_ip": "10.111.8.100",
      "temp_dir_name": "user1_temp_20260311_143022_a3f2b1c4",
      "temp_dir_path": "/opt/coder/statistics/build/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
      "temp_dir_unc": "//10.144.41.149/webide/aigc_tool/w14512/user1_temp_20260311_143022_a3f2b1c4",
      "user": "user1",
      "created_at": "2026-03-11T14:30:22",
      "deployed": true
    }
  }
}
```

### Modified Components

#### 1. config.py
**Changes**:
- Modify `create_temp_dir()` to accept optional `user` parameter
- Modify `create_temp_dir_standalone()` to accept optional `user` parameter
- Add UUID suffix to ensure uniqueness across concurrent requests
- New directory naming:
  - With user: `{user}_temp_{timestamp}_{uuid}`
  - Without user: `temp_{timestamp}_{uuid}`

#### 2. main.py - upload-topox endpoint
**Changes**:
- Add optional `user` form parameter
- Pass `user` to `create_temp_dir()`
- After successful deployment, extract executor_ip from ITC response
- Call `save_mapping()` with extracted executor IP and temp directory info
- Include mapping info in response

**Executor IP Extraction Logic**:
```python
# Extract executor_ip from ITC newdeploy response
# ITC response structure:
# {
#   "return_code": "200",
#   "return_info": "Success message",
#   "result": {
#     "executorip": "10.111.8.100",
#     "terminalinfo": [...]
#   }
# }

def extract_executor_ip(itc_response: dict) -> Optional[str]:
    """Extract executor IP from ITC newdeploy response"""
    try:
        result = itc_response.get("result")
        if result and isinstance(result, dict):
            executor_ip = result.get("executorip")
            if executor_ip:
                # Validate IP format
                import re
                ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
                if re.match(ipv4_pattern, executor_ip):
                    return executor_ip
        return None
    except Exception:
        return None

# Error handling:
# - If executor_ip not found in response: Log warning, don't save mapping
# - If executor_ip format invalid: Log error, don't save mapping
# - If save_mapping() fails: Log error, return partial success with warning
```

#### 3. main.py - upload-scripts endpoint
**Changes**:
- When no topox file provided:
  1. Call `get_mapping(executor_ip)`
  2. If found: validate temp directory exists, then use `temp_dir_unc` from mapping
  3. If not found: return error "未找到 executor_ip 对应的临时目录，请先调用 upload-topox 进行部署"
  4. If mapping file doesn't exist: return error "映射文件不存在，请先调用 upload-topox 进行部署"
  5. If mapping file corrupted: return error "映射文件损坏，请联系管理员"
  6. If temp directory doesn't exist: return error "临时目录不存在，请重新部署"
- When topox file provided: keep existing logic (create standalone temp dir)

**Error Scenarios**:
```python
def get_temp_directory_for_scripts(executor_ip: str, has_topox: bool) -> tuple[str, str]:
    """Get temp directory for script execution"""
    if has_topox:
        # Create standalone temp directory (existing logic)
        temp_dir_name, temp_dir = settings.create_temp_dir_standalone(user=None)
        scripts_unc_path = f"{settings.BASE_UNC_DIR}/{temp_dir_name}"
        return scripts_unc_path, temp_dir_name

    # No topox file - query mapping
    try:
        mapping = exec_ip_mapper.get_mapping(executor_ip)
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

        return mapping.temp_dir_unc, mapping.temp_dir_name

    except FileNotFoundError:
        # Mapping file doesn't exist
        raise HTTPException(
            status_code=400,
            detail="映射文件不存在，请先调用 upload-topox 进行部署"
        )
    except json.JSONDecodeError:
        # Mapping file corrupted
        raise HTTPException(
            status_code=500,
            detail="映射文件损坏，请联系管理员"
        )
```

#### 4. main.py - undeploy endpoint
**Changes**:
- Call `delete_mapping(executor_ip)` after ITC undeploy
- Delete mapping regardless of ITC response
- Optionally clean up temporary directory (if configured)

**Temporary Directory Cleanup Strategy**:
- **Default behavior**: Keep temporary directory after undeploy for debugging
- **Optional cleanup**: Add config flag `CLEANUP_TEMP_DIR_ON_UNDEPLOY`
  - If enabled: Delete temp directory after successful undeploy
  - If disabled: Keep temp directory for manual inspection
- **Cleanup implementation**:
  ```python
  if settings.CLEANUP_TEMP_DIR_ON_UNDEPLOY:
      try:
          mapping = exec_ip_mapper.get_mapping(executor_ip)
          if mapping and Path(mapping.temp_dir_path).exists():
              shutil.rmtree(mapping.temp_dir_path)
              logger.info(f"已删除临时目录: {mapping.temp_dir_path}")
      except Exception as e:
          logger.warning(f"删除临时目录失败: {e}")
  ```

**Orphaned Directory Handling**:
- Add periodic cleanup job (optional, not in v1)
- Scan `BASE_DIR` for temp directories older than 24 hours
- Check if directory exists in mappings
- Delete if not in mappings and older than threshold

## Data Flow

### Deployment Flow (upload-topox)
```
1. Receive topox file + optional user parameter
2. Create temp directory with user prefix and UUID suffix
3. Save topox file to temp directory
4. Call ITC newdeploy
5. If success:
   - Extract executor_ip from ITC response
   - Save mapping (executor_ip -> temp_dir) to exec_ip.json
6. Return deployment result
```

### Script Execution Flow (upload-scripts)
```
1. Receive script files + executor_ip
2. Check if topox file included
3. If no topox:
   - Query exec_ip.json for executor_ip
   - If found: use mapped temp_dir_unc
   - If not found: return error
4. If topox included:
   - Create standalone temp directory
   - Save files and run (existing logic)
5. Call ITC run_scripts
6. Return result
```

### Undeploy Flow
```
1. Receive executor_ip
2. Call ITC undeploy
3. Delete mapping from exec_ip.json
4. Return result
```

## File Structure

```
minimal-itc-api/
├── exec_ip_mapper.py          # New: mapping management module
├── exec_ip.json               # New: mapping data file (auto-created)
├── main.py                     # Modified: API endpoints
├── config.py                   # Modified: temp directory creation
├── itc_client.py              # Unchanged
├── models.py                  # Unchanged
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-11-executor-ip-mapping-design.md  # This file
```

## Error Handling

### exec_ip_mapper.py

**File Read Errors**:
- `FileNotFoundError`: Treat as no mappings found, return empty dict
- `PermissionError`: Log error, re-raise with clear message
- `JSONDecodeError`: Log warning, backup corrupted file, reinitialize with empty structure
- `IOError`: Log error, re-raise with clear message

**File Write Errors**:
- `PermissionError`: Log error, re-raise with clear message
- `LockTimeoutError`: Log warning, retry up to 3 times with exponential backoff
- `IOError`: Log error, re-raise with clear message

**Invalid Data**:
- Invalid IP format: Return None from `get_mapping()`, log warning
- Invalid user format: Raise validation error
- Invalid timestamp: Raise validation error

### upload-scripts endpoint

**Mapping Lookup Errors**:
- Mapping file doesn't exist: Return 400 with "映射文件不存在，请先调用 upload-topox 进行部署"
- Mapping file corrupted: Return 500 with "映射文件损坏，请联系管理员"
- Executor IP not found: Return 400 with "未找到 executor_ip 对应的临时目录，请先调用 upload-topox 进行部署"
- Temp directory doesn't exist: Return 400 with "临时目录不存在，请重新部署"
- Invalid executor IP format: Return 400 with "无效的 executor_ip 格式"

**Distict Error Messages**:
Each error scenario has a unique message to help users understand the issue:
- First run vs. corrupted file vs. not found
- File-level vs. record-level errors
- Validation errors vs. lookup failures

### File Concurrency

**Locking Strategy**:
- Use `fcntl.flock()` for Unix systems
- Use `msvcrt.locking()` for Windows systems
- Acquire shared lock (LOCK_SH) for read operations
- Acquire exclusive lock (LOCK_EX) for write operations
- Lock timeout: 5 seconds
- Retry mechanism: 3 attempts with exponential backoff (1s, 2s, 4s)

**Atomic Write**:
- Write to temporary file (`exec_ip.json.tmp`)
- Sync to disk
- Atomic rename to final file name
- This prevents partial writes and corruption

**Example Implementation**:
```python
import fcntl
import os

def atomic_write_with_lock(file_path: Path, data: dict):
    """Atomic write with file locking"""
    temp_path = file_path.with_suffix('.json.tmp')

    for attempt in range(3):
        try:
            with open(temp_path, 'w') as f:
                # Acquire exclusive lock
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

                try:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                finally:
                    # Release lock
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            # Atomic rename
            temp_path.replace(file_path)
            return

        except BlockingIOError:
            # Lock acquisition failed, retry
            time.sleep(2 ** attempt)
        except Exception as e:
            temp_path.unlink(missing_ok=True)
            raise
```

## Testing Considerations

### Unit Tests
- Test `exec_ip_mapper` functions with various scenarios
- Test temp directory name generation with/without user
- Test UUID uniqueness

### Integration Tests
- Test full flow: upload-topox -> save mapping -> upload-scripts (no topox) -> undeploy
- Test concurrent deployments with same user
- Test error cases: upload-scripts with invalid executor_ip
- Test backward compatibility: upload-scripts with topox file

### Edge Cases
- Concurrent writes to exec_ip.json
- Empty/corrupted exec_ip.json file
- Undeploy with non-existent executor_ip

## Security Considerations

### Input Validation

**User Parameter**:
- Format: Only alphanumeric, underscore, and hyphen allowed
- Regex: `^[a-zA-Z0-9_-]+$`
- Max length: 32 characters
- Path traversal protection: Reject `..`, `/`, `\` in user parameter
- Example valid values: `user1`, `test_user`, `user-123`

**Executor IP Parameter**:
- IPv4 format: `^(\d{1,3}\.){3}\d{1,3}$`
- IPv6 format: `^[0-9a-fA-F:]+$`
- Max length: 45 characters (IPv6)
- Validation using Pydantic validators in ExecutorMapping model

### File Security

**exec_ip.json File**:
- Location: Project root directory (minimal-itc-api/exec_ip.json)
- Permissions: 0600 (read/write for owner only)
- Automatic permission setting on file creation
- Atomic write operations (temp file + rename)
- File locking for concurrent access

**Temporary Directory**:
- Permissions: 0777 (existing behavior, maintained for compatibility)
- User parameter sanitization prevents directory traversal
- UUID suffix prevents directory name prediction

### Audit Logging

All mapping operations are logged:
- `save_mapping`: Log with executor_ip, temp_dir_name, user
- `get_mapping`: Log with executor_ip
- `delete_mapping`: Log with executor_ip
- Error cases: Log with full context

Example log format:
```
[2026-03-11 14:30:22] INFO [exec_ip_mapper] Saved mapping: executor_ip=10.111.8.100, temp_dir=user1_temp_20260311_143022_a3f2b1c4, user=user1
[2026-03-11 14:35:10] INFO [exec_ip_mapper] Retrieved mapping: executor_ip=10.111.8.100
[2026-03-11 14:40:05] INFO [exec_ip_mapper] Deleted mapping: executor_ip=10.111.8.100
```

## Backward Compatibility

- Existing `upload-topox` calls without `user` parameter continue to work
- Existing `upload-scripts` calls with topox file continue to work
- New `upload-scripts` behavior (no topox) requires prior deployment

## Future Enhancements

- Add TTL for mappings (auto-cleanup after N hours)
- Add API endpoint to query all active mappings
- Support batch undeploy by user prefix
- Add metrics/statistics for mapping usage

## Implementation Notes

- Use Python's `uuid.uuid4()` for UUID generation (first 8 characters: `uuid.uuid4().hex[:8]`)
- Use `datetime.utcnow().isoformat()` for timestamps (ISO 8601 format)
- Atomic write: write to `.tmp` file, then `os.replace()`
- File location: Use `settings.BASE_DIR` parent directory: `Path(settings.BASE_DIR).parent.parent / "minimal-itc-api" / "exec_ip.json"`
- File permissions: Set `exec_ip.json` to 0600 (owner read/write only)
- Lock timeout: 5 seconds
- Retry attempts: 3 with exponential backoff
- Configurable cleanup: Add `CLEANUP_TEMP_DIR_ON_UNDEPLOY` flag to config.py (default: False)

## Migration Strategy

**For Existing Deployments**:
- This feature is backward compatible
- Existing deployments without user parameter continue to work
- New deployments with user parameter create user-prefixed directories
- No migration needed for existing data

**First Run**:
- If `exec_ip.json` doesn't exist, it will be created automatically
- Initial file structure: `{"mappings": {}}`
- No error if file is missing (treated as empty mappings)

**Rollout Plan**:
1. Deploy new code with feature behind feature flag (optional)
2. Test with user parameter in staging environment
3. Enable in production
4. Monitor logs for mapping operations
5. Collect feedback from users

## API Documentation Updates

Update OpenAPI/Swagger documentation:

**upload-topox**:
- Add `user` parameter (optional, string)
- Update response to include mapping info
- Add example with user parameter

**upload-scripts**:
- Update description to clarify mapping lookup behavior
- Add error response examples for mapping not found

**undeploy**:
- Update description to mention mapping cleanup

## Monitoring and Observability

Add metrics for:
- Number of active mappings (from exec_ip.json)
- Mapping save/delete operations count
- Mapping lookup success/failure rate
- Lock acquisition failures
- Temp directory cleanup operations
