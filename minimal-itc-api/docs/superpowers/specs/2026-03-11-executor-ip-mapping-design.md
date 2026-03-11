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
- `save_mapping(executor_ip: str, temp_dir_name: str, user: Optional[str])` - Save new mapping
- `get_mapping(executor_ip: str) -> Optional[Mapping]` - Retrieve mapping by executor IP
- `delete_mapping(executor_ip: str)` - Delete mapping
- `atomic_write(file_path: Path, data: dict)` - Atomic file write using temp file

**Data Structure**:
```python
@dataclass
class ExecutorMapping:
    executor_ip: str
    temp_dir_name: str
    temp_dir_path: str
    temp_dir_unc: str
    user: Optional[str]
    created_at: str
    deployed: bool
```

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
- After successful deployment, call `save_mapping()` with executor IP from result
- Include mapping info in response

#### 3. main.py - upload-scripts endpoint
**Changes**:
- When no topox file provided:
  1. Call `get_mapping(executor_ip)`
  2. If found: use `temp_dir_unc` from mapping
  3. If not found: return error "未找到 executor_ip 对应的临时目录，请先调用 upload-topox 进行部署"
- When topox file provided: keep existing logic (create standalone temp dir)

#### 4. main.py - undeploy endpoint
**Changes**:
- Call `delete_mapping(executor_ip)` after ITC undeploy
- Delete mapping regardless of ITC response

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
- **File read errors**: Log warning, return None (treat as not found)
- **File write errors**: Log error, raise exception
- **Invalid JSON**: Log warning, reinitialize with empty structure

### upload-scripts endpoint
- **Mapping not found**: Return 400 error with clear message
- **Invalid executor_ip format**: Return 400 error

### File concurrency
- Use atomic write (temp file + rename) to prevent corruption
- No locking needed due to atomic operations

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

- Validate user parameter format (alphanumeric, underscore, hyphen only)
- Sanitize executor_ip format
- Ensure exec_ip.json file permissions are appropriate
- Log all mapping operations for audit trail

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

- Use Python's `uuid.uuid4()` for UUID generation
- Use `datetime.utcnow().isoformat()` for timestamps
- Atomic write: write to `.tmp` file, then `os.replace()`
- File location: `Path(__file__).parent.parent / "exec_ip.json"`
