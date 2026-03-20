# Release Notes - v1.1.0

## New Features

### default.topox 上传自动处理

当用户上传 `default.topox` 文件时，系统现在会：

1. **自动解析** topox 文件内容，提取设备和链路信息
2. **更新配置** 将解析结果保存到 `.aigc_tool/aigc.json`
3. **重置状态** 将部署状态设置为 "not_deployed"
4. **异步卸载** 如果之前已部署，自动调用卸载组网接口

**特性：**
- ✅ 幂等性保证：2秒内重复上传会被忽略
- ✅ 并发控制：最多同时执行1个卸载任务
- ✅ 性能监控：记录处理时间和卸载时间
- ✅ 优雅关闭：应用关闭时等待后台任务完成
- ✅ 错误容错：解析失败不影响文件保存

**配置选项：**
```python
DEFAULT_TOPOX_DEBOUNCE_SECONDS = 2  # 重复上传去重时间
DEFAULT_TOPOX_ASYNC_UNDEPLOY = True  # 是否启用异步卸载
DEFAULT_TOPOX_UNDEPLOY_TIMEOUT = 300  # 卸载超时时间
```

## Technical Improvements

### 代码质量提升
- 修复异步协程警告，提高代码健壮性
- 完善错误处理和日志记录
- 添加全面的单元测试覆盖
- 优化配置项注释说明

### 测试覆盖
- 新增12个专门针对 default.topox 处理的测试用例
- 覆盖重复上传检测、并发处理、错误场景等
- 所有测试通过，无警告

### 文档完善
- 添加详细的API注释
- 改进配置选项说明
- 提供完整的使用示例

## API Changes

### 新增配置参数
- `DEFAULT_TOPOX_DEBOUNCE_SECONDS`: 控制重复上传去重时间
- `DEFAULT_TOPOX_ASYNC_UNDEPLOY`: 是否启用异步卸载
- `DEFAULT_TOPOX_UNDEPLOY_TIMEOUT`: 卸载操作超时时间
- `DEFAULT_TOPOX_MAX_CONCURRENT_UNDEPLOY`: 最大并发卸载数

### 行为变化
- 上传 `default.topox` 文件时自动触发网络解析和配置更新
- 自动检测并触发异步卸载（如果已部署）
- 2秒内重复相同文件内容会被忽略

## Testing

- 所有12个新增测试用例通过
- 测试覆盖以下场景：
  - 重复上传检测
  - 异步卸载触发
  - 大小写敏感处理
  - 并发上传处理
  - 错误场景处理

## Performance

- 处理时间监控：记录完整的处理耗时
- 异步任务管理：使用信号量控制并发
- 内存优化：及时清理已完成的任务引用

## Compatibility

- 向后兼容：不影响现有功能
- 配置默认值：保持合理的默认配置
- 错误容错：处理失败不影响文件保存