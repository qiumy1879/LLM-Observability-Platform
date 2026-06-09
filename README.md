# LLM Observability Platform

一个 LLM 调用的可观测性平台。以代理方式运行在你的应用和各种 LLM 服务之间，拦截每次 API 调用，记录模型、token 用量、延迟和费用，同时提供 Dashboard 查看成本分布。

## 解决的问题

在代码里直接调 OpenAI 或 Claude 的 API 有三个常见痛点：

- 费用不可见：月底看账单才发现异常调用，没有实时视图
- 无法回溯：用户反馈某次对话有问题，但查不到当时的 prompt 和 response
- Key 混用：多个服务共用一个 API Key，A 服务的 bug 可能耗尽整个配额

这个平台让每次 LLM 调用变得可追踪：

1. 请求经由平台转发，自动记录请求体和响应体
2. 通过 API Key 隔离不同服务，各自独立统计
3. 浏览器打开 Dashboard 即可看到实时用量和费用

## 与 CC Switch 的关系

[CC Switch](https://github.com/nicepkg/ccswitch) 是一个桌面应用，面向个人开发者管理多个 LLM 供应商的配置。这里解决的是另一个问题：作为后端中间件，为调用方提供统一的接入入口和观测能力。应用代码通过 HTTP 调用平台，平台负责转发、记录和统计。

## 项目结构

```
├── app/
│   ├── main.py                  # FastAPI 入口，lifespan 负责建表和启停 Worker
│   ├── config.py                # 配置项，通过环境变量控制
│   ├── core/
│   │   └── database.py          # SQLAlchemy 异步引擎，自动建表
│   ├── models/
│   │   ├── api_key.py           # API Key 表
│   │   └── trace_record.py      # 调用记录表
│   ├── schemas/
│   │   ├── api_key.py           # 请求/响应的 Pydantic 模型
│   │   └── trace.py             # Trace 和 Dashboard 的 Pydantic 模型
│   ├── api/
│   │   ├── proxy.py             # POST /v1/chat/completions 代理端点
│   │   ├── keys.py              # API Key CRUD
│   │   └── dashboard.py         # Dashboard 数据接口
│   ├── services/
│   │   ├── llm_adapter.py       # 多供应商调用适配
│   │   └── write_worker.py      # 异步写入 Worker + 内存计数器
│   ├── middleware/
│   │   └── api_key_auth.py      # Bearer Token 鉴权
│   └── static/
│       └── dashboard.html       # Dashboard 页面
├── tests/
│   ├── conftest.py              # pytest 配置，SQLite 内存数据库隔离
│   └── test_keys.py             # API Key 测试
├── docker-compose.yml           # PostgreSQL 容器
├── requirements.txt
└── pytest.ini
```

## 模块说明

### 代理端点 — `app/api/proxy.py`

暴露 `POST /v1/chat/completions`，兼容 OpenAI Chat Completions API。接入方只需把 `base_url` 改为平台地址，其余代码不变。

请求处理流程：

1. 从 `Authorization: Bearer sk-xxx` 提取 API Key，查 `api_keys` 表验证有效性
2. 解析 `model` 字段——`供应商/模型名` 格式自动拆分
3. 将请求转发给目标 LLM 服务
4. 将 token 用量、延迟、费用等观测数据放入 `asyncio.Queue`，立即返回响应
5. 同步更新内存计数器

记录观测数据不阻塞主链路。后台 Worker 负责批量写入数据库。

### 异步写入 — `app/services/write_worker.py`

分为两层：

**StatsCache（内存计数器）**：一个 dict，按 API Key 和模型维度聚合调用次数、费用和 token。代理请求完成后同步更新，Dashboard 首页直接读取，查询延迟为纳秒级。

**后台 Worker**：一个 `asyncio.Task`，从 `asyncio.Queue` 取出观测数据，攒够 50 条或间隔 5 秒后批量写入数据库。服务关闭时刷掉队列中剩余数据。

### 模型适配器 — `app/services/llm_adapter.py`

不同供应商的请求/响应格式存在差异。适配器负责将统一格式转换为各供应商要求的格式，并将响应标准化。

当前支持：

- OpenAI 兼容（GPT、DeepSeek、千问、智谱等）
- Anthropic（Claude）

### API Key 管理 — `app/api/keys.py`

为每个接入方分配独立的 API Key，生成 `sk-` 前缀的随机字符串。支持设置每分钟调用上限，以及启用/禁用操作。

### Dashboard — `app/api/dashboard.py`

提供以下接口：

| 接口 | 数据来源 | 说明 |
|------|---------|------|
| `/api/dashboard/summary` | 内存计数器 | 实时总览 |
| `/api/dashboard/cost-by-model?days=7` | 数据库 | 按模型拆分历史成本 |
| `/api/traces` | 数据库 | 调用明细，支持按 Key、模型、状态筛选 |
| `/api/traces/{id}` | 数据库 | 单条调用详情，含请求体和响应体 |

### Dashboard 页面 — `app/static/dashboard.html`

浏览器打开 `http://localhost:8000` 即可看到可视化界面，包含：

- 实时统计卡片（调用次数、费用、Token、错误率）
- 各模型费用占比（环形图）和调用次数（柱状图）
- 最近调用记录表格
- API Key 管理面板

数据每 5 秒自动刷新。

## 环境要求

- Python 3.11+
- Docker Desktop（可选，仅 PostgreSQL 模式需要）

## 启动步骤

### 1. 安装依赖

```bash
# 创建虚拟环境（名字随意，这里叫 myenv）
conda create -n myenv python=3.11 -y
conda activate myenv

# 安装依赖
pip install -r requirements.txt
```

Windows + conda 下如遇到 SSL 证书报错，先执行：

```powershell
$env:SSL_CERT_FILE = (python -c "import certifi; print(certifi.where())")
```

### 2. 启动服务

**SQLite 模式**（默认，无需 Docker，clone 下来就能跑）：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**PostgreSQL 模式**（需要 Docker Desktop）：

```bash
docker compose up -d
# 编辑 .env 文件，将 USE_SQLITE 改为 false
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如果 Docker 拉取镜像失败（国内常见），在 Docker Engine 配置中添加镜像源：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerhub.timeweb.cloud"
  ]
}
```

服务启动后：

- Dashboard 页面：http://localhost:8000
- Swagger 文档：http://localhost:8000/docs

### 3. 走一遍完整流程

**第一步 — 创建 API Key**：

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "my-app", "rate_limit": 60}'
```

返回的 `key` 字段记下来，后面鉴权要用。

**第二步 — 设置上游 API Key**：

平台需要真实的 LLM API Key 才能转发请求。根据你要用的供应商，设置对应的环境变量：

```powershell
# 供应商名称全大写，格式: LLM_KEY_<PROVIDER>
$env:LLM_KEY_OPENAI   = "sk-你的OpenAI密钥"
$env:LLM_KEY_DEEPSEEK = "sk-你的DeepSeek密钥"
$env:LLM_KEY_ANTHROPIC = "sk-ant-你的Anthropic密钥"
```

**第三步 — 发起调用**：

请求格式和 OpenAI 完全一致，只改 `base_url`。`model` 用 `供应商/模型名` 来指定走哪个供应商：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer 刚才创建的Key" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**第四步 — 查看 Dashboard**：

打开浏览器访问 `http://localhost:8000`，刚才的调用已经出现在统计里了。

或者用命令行：

```bash
curl http://localhost:8000/api/dashboard/summary
```

### 4. 运行测试

```bash
python -m pytest tests/ -v
```

测试使用 SQLite 内存数据库，每次测试前建表、测试后回滚，不影响正常数据。

## 设计选择

| 选择 | 原因 |
|------|------|
| 开发用 SQLite，生产用 PostgreSQL | 零配置即可运行；PG 的 JSONB 和窗口函数更适合统计分析 |
| 异步队列批量写入 | 观测数据写入不阻塞请求主链路 |
| 内存计数器做热点统计 | Dashboard 首页查询纳秒级，不受 Worker 写入延迟影响 |
| 直接用 httpx 调 LLM | 避免引入 LangChain 等重框架，适配器不到 200 行 |
| API Key 做多租户隔离 | 比完整用户系统轻量，隔离效果满足需求 |
| UUID 存为字符串 | SQLite 和 PG 通用，避免迁移成本 |
