# Minimal ITC API

一个最小化的 FastAPI 应用，用于 topox 文件部署和脚本执行。

需求方 weiyongqiang  部署在149服务器本地执行



## 功能

- **上传 topox 并部署组网**: 上传 `.topox` 文件，每次部署创建新的临时目录，调用 ITC newdeploy 接口
- **批量上传脚本并执行**: 上传多个脚本文件到当前临时目录，调用 ITC 运行接口
- **卸载组网环境**: 根据执行机 IP 卸载已部署的组网环境

## 特性

- **临时目录机制**: 每次部署时自动创建新的临时目录（格式: `temp_YYYYMMDD_HHMMSS`）
- **权限自动设置**: 自动设置临时目录及其所有文件为 777 权限（任意用户可读写）
- **使用 newdeploy 接口**: 使用 ITC 的 newdeploy 接口，自动查找工作目录中的 topox 文件

## 安装

```bash
# 安装依赖
pip install -r requirements.txt
```

## 运行

```bash
# 基本运行
python main.py

# 指定端口运行
python main.py --port 8000

# 开发模式（自动重载）
python main.py --reload

# 指定主机和端口
python main.py --host 0.0.0.0 --port 3001
```

## API 端点

### 1. 上传 topox 并部署

**POST** `/api/v1/upload-topox`

**请求参数（multipart/form-data）:**
- `topox_file`: Topox 文件（必需）
- `version_path`: 版本目录路径（可选）
- `device_type`: 设备类型（可选，默认: simware9cen）

**示例（curl）:**
```bash
curl -X POST "http://localhost:3001/api/v1/upload-topox" \
  -F "topox_file=@/path/to/file.topox" \
  -F "version_path=/path/to/version" \
  -F "device_type=simware9cen"
```

**示例（Python requests）:**
```python
import requests

url = "http://localhost:3001/api/v1/upload-topox"
files = {"topox_file": open("file.topox", "rb")}
data = {
    "version_path": "/path/to/version",
    "device_type": "simware9cen"
}
response = requests.post(url, files=files, data=data)
print(response.json())
```

### 2. 批量上传脚本并执行

**POST** `/api/v1/upload-scripts`

**请求参数（multipart/form-data）:**
- `script_files`: 脚本文件列表（必需，支持多个）
- `executor_ip`: 执行机 IP 地址（必需）

**示例（curl）:**
```bash
curl -X POST "http://localhost:3001/api/v1/upload-scripts" \
  -F "script_files=@conftest.py" \
  -F "script_files=@test_demo.py" \
  -F "executor_ip=10.111.8.100"
```

**示例（Python requests）:**
```python
import requests

url = "http://localhost:3001/api/v1/upload-scripts"
files = [
    ("script_files", open("conftest.py", "rb")),
    ("script_files", open("test_demo.py", "rb"))
]
data = {"executor_ip": "10.111.8.100"}
response = requests.post(url, files=files, data=data)
print(response.json())
```

### 3. 卸载组网环境

**POST** `/api/v1/undeploy`

**请求参数（multipart/form-data）:**
- `executor_ip`: 执行机 IP 地址（必需）

**示例（curl）:**
```bash
curl -X POST "http://localhost:3001/api/v1/undeploy" \
  -F "executor_ip=10.111.8.100"
```

**示例（Python requests）:**
```python
import requests

url = "http://localhost:3001/api/v1/undeploy"
data = {"executor_ip": "10.111.8.100"}
response = requests.post(url, data=data)
print(response.json())
```

### 4. 健康检查

**GET** `/health`

返回应用状态信息。

## 配置

编辑 `config.py` 修改配置：

- `ITC_SERVER_URL`: ITC 服务器地址
- `TARGET_DIR`: 文件保存目标目录
- `MAX_FILE_SIZE`: 最大文件大小限制
- `ITC_REQUEST_TIMEOUT`: 请求超时时间

## 项目结构

```
minimal-itc-api/
├── main.py              # FastAPI 应用入口
├── models.py            # 数据模型
├── itc_client.py        # ITC 客户端
├── config.py            # 配置管理
├── requirements.txt     # 依赖列表
├── README.md            # 项目说明
└── .gitignore          # Git 忽略文件
```

## API 文档

启动服务后访问:
- Swagger UI: http://localhost:3001/docs
- ReDoc: http://localhost:3001/redoc

## 许可证

MIT
