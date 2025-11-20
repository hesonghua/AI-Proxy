# AI聚合工具

一个兼容OpenAI API的AI模型聚合代理，支持多个AI供应商的统一接口。

## 功能特性

- 兼容OpenAI API格式
- 支持多个AI供应商
- 模型名称格式：`供应商/模型`
- 自动获取供应商模型列表
- 配置文件管理
- 请求分发和负载均衡

## 配置格式

供应商配置格式，每行一个：
```
供应商名称|URL|API_KEY
```

示例：
```
openai|https://api.openai.com/v1|sk-xxxxxxxxxxxxx
zhipu|https://open.bigmodel.cn/api/paas/v4|your-zhipu-key-here
anthropic|https://api.anthropic.com/v1|sk-ant-xxxxxxxxxxxxx
```

## 快速开始

1. 安装依赖：`pip install -r requirements.txt`
2. 配置供应商：编辑 `providers.txt`
3. 启动服务：`python main.py`

## API端点

- `GET /` - 服务信息和可用端点
- `GET /health` - 健康检查
- `GET /v1/models` - 获取所有可用模型
- `POST /v1/chat/completions` - 聊天补全
- `POST /v1/reload` - 重新加载配置

## 使用示例

### 1. 获取模型列表
```bash
curl http://localhost:8000/v1/models
```

### 2. 聊天补全
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "zhipu/glm-4.5",
    "messages": [
      {"role": "user", "content": "你好，请介绍一下自己"}
    ],
    "temperature": 0.7,
    "max_tokens": 100
  }'
```

### 3. 健康检查
```bash
curl http://localhost:8000/health
```

## 测试

运行测试脚本验证所有功能：
```bash
python test_api.py
```

## 配置文件

### 供应商配置 (providers.txt)
格式：`供应商名称|URL|API_KEY`
```
zhipu|https://open.bigmodel.cn/api/paas/v4|your-zhipu-key-here
openai|https://api.openai.com/v1|sk-your-openai-key-here
```

### Token白名单 (tokens.txt)
格式：`token描述|token值`
```
test_token|sk-test-123456
admin_token|sk-admin-789012
readonly_token|sk-readonly-345678
```

## 特性

✅ 完全兼容OpenAI API格式  
✅ 支持多个AI供应商  
✅ 模型名称格式：`供应商/模型`  
✅ 自动获取供应商模型列表  
✅ 配置文件热重载  
✅ Token验证机制  
✅ 健康检查和监控  
✅ 统一错误处理  
✅ 异步请求支持

## Token验证

API支持Bearer Token认证：

### 使用Token访问
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-test-123456" \
  -d '{
    "model": "zhipu/glm-4.5",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

### 无Token访问
