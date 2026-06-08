# LLM Observability Platform

LLM 调用可观测性平台 — 代理模式拦截所有 LLM API 调用，提供全量追踪和成本分析。

## 一句话说清楚

> 你的代码调这个网关 → 网关转发给真实模型 → 记录每次调用 → Dashboard 看成本

## 项目结构

```
├── app/
│   ├── main.py                    # FastAPI 入口，注册路由，lifespan 启动/关闭
│   ├── config.py                  # 统一配置（数据库、队列、截断阈值等）
│   ├── core/
│   │   └── database.py            # 异步 SQLAlchemy 引擎，自动建表
│   ├── models/
│   │   ├── api_key.py             # API Key 表（多租户隔离）
│   │   └── trace_record.py        # 调用追踪表（JSON 字段存请求/响应）
│   ├── schemas/
│   │   ├── api_key.py             # Key CRUD 的 Pydantic 模型
│   │   └── trace.py               # Trace/Dashboard 的 Pydantic 模型
│   ├── api/
│   │   ├── proxy.py               # POST /v1/chat/completions 核心代理端点
│   │   ├── keys.py                # CRUD /api/keys 管理 API Key
│   │   └── dashboard.py           # GET /api/dashboard/* 成本分析接口
│   ├── services/
│   │   ├── llm_adapter.py         # 模型适配器：OpenAI/DeepSeek/Anthropic 统一调用
│   │   └── write_worker.py        # 异步写入 Worker + 内存计数器
│   └── middleware/
│       └── api_key_auth.py        # Bearer Token 鉴权中间件
├── tests/
│   ├── conftest.py                # pytest 配置（SQLite 内存数据库隔离）
│   └── test_keys.py               # API Key 管理接口测试
├── docker-compose.yml             # PostgreSQL 容器（需要 Docker Desktop）
├── requirements.txt               # Python 依赖
├── pytest.ini                     # pytest 配置
└── .gitignore
```

## 各模块是干什么的

### 核心链路：代理端点 `app/api/proxy.py`

收到用户的 LLM 请求后做三件事：
1. **鉴权** — 从 `Authorization: Bearer sk-xxx` 中取 Key，查数据库验证
2. **转发** — 把请求发给真正的模型（OpenAI/Claude/DeepSeek）
3. **记录** — 异步把这次调用的 token、耗时、成本写进数据库

用户收到响应的速度不受第 3 步影响——记录是后台异步做的。

### 异步写入 + 内存计数器 `app/services/write_worker.py`

两个组件：
- **StatsCache（内存计数器）** — 一个 Python dict，记录每个 Key 的实时调用次数/费用。纳秒级读写，Dashboard 查这个瞬间出结果
- **WriteWorker（后台写入）** — 从 `asyncio.Queue` 取出观测数据，攒够一批（默认 50 条或 5 秒）后批量 `INSERT` 进数据库

### 模型适配器 `app/services/llm_adapter.py`

统一不同模型的差异。目前支持：
- **OpenAI 兼容格式**：GPT、DeepSeek、千问、智谱等
- **Anthropic**：Claude（自动转换 OpenAI 格式 → Anthropic Messages 格式）

增加新模型只需多加一个方法。

### API Key 管理 `app/api/keys.py`

标准的 CRUD：创建 Key（`sk-` 前缀随机字符串）、列出、启用/禁用、删除。每个 Key 可以设速率限制（每分钟最多多少次）。

### Dashboard `app/api/dashboard.py`

三个接口：
- `/api/dashboard/summary` — 实时总览（读内存计数器，瞬间返回）
- `/api/dashboard/cost-by-model` — 按模型拆分历史成本（查 DB）
- `/api/traces` / `/api/traces/{id}` — 调用明细查询

### 鉴权中间件 `app/middleware/api_key_auth.py`

从 HTTP Header 中提取 `Bearer <key>`，查 `api_keys` 表，有效就放行并把 `api_key_id` 注入 `request.state`。

---

## 环境要求

- **Python 3.11+**
- **Conda**（推荐）或 venv
- **Docker Desktop**（可选，仅 PostgreSQL 模式需要）

## 快速开始（SQLite 模式，无需 Docker）

```bash
# 1. 创建并激活 conda 环境
conda create -n llm-obs python=3.11 -y
conda activate llm-obs

# 2. 安装依赖
pip install -r requirements.txt

# 3. 修复 SSL 证书（Windows conda 环境常见问题）
# 如果启动时报 SSL 错误，先执行：
# $env:SSL_CERT_FILE = (python -c "import certifi; print(certifi.where())")

# 4. 启动服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 5. 验证
curl http://localhost:8000/health
# → {"status":"healthy","version":"0.1.0"}
```

服务启动后：
- **API 文档（Swagger）**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/health

## 切换到 PostgreSQL 模式

> 前置条件：Docker Desktop 已启动，且能正常拉取镜像。

```bash
# 1. 启动 PostgreSQL
docker compose up -d

# 2. 修改 .env 中的配置
# USE_SQLITE=false

# 3. 重启服务
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

如果 Docker Hub 连不上（国内常见），在 Docker Desktop 设置中配置镜像加速器：
- `Settings → Docker Engine → 添加 "registry-mirrors"`

## 运行测试

```bash
python -m pytest tests/ -v
```

测试使用 SQLite 内存数据库，不会影响开发/生产数据。

## API 速查

### 管理接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/keys` | 创建 API Key |
| `GET` | `/api/keys` | 列出所有 Key |
| `PATCH` | `/api/keys/{id}` | 启用/禁用 Key |
| `DELETE` | `/api/keys/{id}` | 删除 Key |

### 代理端点（核心）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/chat/completions` | 代理 LLM 调用（需 Bearer Token） |

请求格式兼容 OpenAI Chat Completions API。模型字段支持 `provider/model` 格式：
```json
{
  "model": "openai/gpt-4o-mini",
  "messages": [{"role": "user", "content": "hello"}]
}
```

### Dashboard

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/dashboard/summary` | 实时总览（内存） |
| `GET` | `/api/dashboard/cost-by-model?days=7` | 按模型成本拆分（DB） |
| `GET` | `/api/traces?limit=50` | 调用明细列表 |
| `GET` | `/api/traces/{id}` | 单条调用详情 |

## 架构决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 数据库（开发） | SQLite | 零配置，新成员 clone 即可运行 |
| 数据库（生产） | PostgreSQL | JSONB、窗口函数、更好的并发 |
| 写入模式 | 异步队列 + 批量 INSERT | 不阻塞主链路 |
| 实时统计 | 内存计数器 | 纳秒级读，Dashboard 瞬时返回 |
| 多租户 | API Key 表 | 轻量但隔离明确 |
| LLM 接入 | httpx 直接调用 | 不用 LangChain，代码可控 |
| UUID 存储 | String(36) | 兼容 SQLite 和 PG |

## 使用流程 Demo

```bash
# 1. 创建一个 API Key
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{"name":"my-app","rate_limit":60}'
# → {"id":"...","key":"sk-xxxx","name":"my-app",...}

# 2. 通过代理调 LLM（需先设置真实 API Key 到环境变量）
# export LLM_KEY_OPENAI=sk-your-real-key
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-xxxx" \
  -d '{"model":"openai/gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}'

# 3. 看 Dashboard
curl http://localhost:8000/api/dashboard/summary
# → {"total_calls_today":1,"total_cost_today":0.00015,...}
```

## 面试相关

这个项目的 PRD 文档在 [`docs/prd-llm-observability-platform.md`](docs/prd-llm-observability-platform.md)。PRD 中包含了面试话术准备方向。
