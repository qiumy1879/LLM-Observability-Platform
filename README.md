# LLM Observability Platform

一个 LLM 调用的可观测性平台。工作方式是作为代理层挡在你的应用和各个 LLM 服务之间，拦截每次 API 调用，把模型、token 用量、延迟、费用这些信息记录下来，然后提供一个 Dashboard 让你看到成本都花在了哪里。

背景：找实习的时候需要一个能展示后端能力和 LLM 方向兴趣的项目。做了这个。

## 解决了什么问题

如果你在代码里直接调 OpenAI 或者 Claude 的 API，会遇到几个麻烦：

- **不知道花了多少钱**。到月底看账单才发现有一笔异常调用，但已经晚了。
- **出问题没法回溯**。用户反馈说某次对话答非所问，你想查一下那次调用的 prompt 和 response，发现根本没记。
- **多个服务共用一个 Key**。A 应用的 bug 导致疯狂调用，把整个 Key 的配额用光了，B 应用跟着挂。

这个平台让每次 LLM 调用都**有据可查**：

1. 所有请求经过平台转发，自动记录请求体和响应体
2. 按 API Key 隔离，每个服务发一个独立的 Key，谁的问题一目了然
3. 实时统计调用次数和费用，异常飙升能立刻发现

## 跟 CC Switch 的区别

[CC Switch](https://github.com/nicepkg/ccswitch) 是一个桌面应用，面向个人开发者，帮你切换不同 LLM 供应商的配置。它解决的问题是"在 Claude Code / Codex / Gemini CLI 这些工具之间切配置太麻烦"。

这个项目是一个后端服务，面向的是**程序**而不是人。你的应用代码通过 HTTP 调它，它转发到真实的 LLM，顺带记录观测数据。两者的定位不一样——CC Switch 是工具，这里是中间件。

## 项目结构

```
├── app/
│   ├── main.py                  # FastAPI 入口，lifespan 里做建表和启停 Worker
│   ├── config.py                # 所有配置项，通过环境变量控制
│   ├── core/
│   │   └── database.py          # SQLAlchemy 异步引擎，建表逻辑
│   ├── models/
│   │   ├── api_key.py           # API Key 的表定义
│   │   └── trace_record.py      # 调用记录的表定义
│   ├── schemas/
│   │   ├── api_key.py           # 请求/响应的数据结构
│   │   └── trace.py             # Trace 和 Dashboard 的数据结构
│   ├── api/
│   │   ├── proxy.py             # 代理端点：收请求 → 转发 → 记录
│   │   ├── keys.py              # API Key 的增删改查
│   │   └── dashboard.py         # Dashboard 数据接口
│   ├── services/
│   │   ├── llm_adapter.py       # 不同 LLM 供应商的调用适配
│   │   └── write_worker.py      # 异步写库 + 内存计数器
│   └── middleware/
│       └── api_key_auth.py      # 从 HTTP Header 里取 Key 做鉴权
├── tests/
│   ├── conftest.py              # pytest 配置，用 SQLite 内存库做隔离
│   └── test_keys.py             # API Key 的测试用例
├── docker-compose.yml           # PostgreSQL（生产模式用）
├── requirements.txt
└── pytest.ini
```

## 各个模块做了什么

### 代理端点 — `app/api/proxy.py`

这是整个平台最核心的部分。它暴露了一个 `POST /v1/chat/completions`，请求格式跟 OpenAI 的 Chat Completions API 完全一致。你的代码只需要把 `base_url` 从 `https://api.openai.com` 改成 `http://localhost:8000` 就行了，其他地方不用动。

收到请求后的流程：

1. 从 `Authorization: Bearer sk-xxx` 里取出 API Key，查 `api_keys` 表确认这个 Key 有效
2. 看请求里的 `model` 字段——支持 `openai/gpt-4o` 这种格式，自动拆成供应商和模型名
3. 把请求转发给真正的 LLM 服务，拿到响应
4. 把这次的 token 用量、延迟、费用扔进 `asyncio.Queue`，**不等写入完成就直接把响应返回给用户**
5. 同时更新内存计数器

也就是说，记录观测数据不会拖慢用户的请求。后台有个 Worker 专门负责把队列里的数据批量写进数据库。

### 异步写入 — `app/services/write_worker.py`

这块拆成了两层：

**内存计数器（StatsCache）**：一个 Python 字典，结构大概是这样：

```python
{
  "key_abc的id": {
    "calls": 42,
    "cost": 0.123,
    "tokens": 5000,
    "errors": 1,
    "by_model": {
      "gpt-4o-mini": {"calls": 30, "cost": 0.05, "tokens": 3000},
      "claude-sonnet": {"calls": 12, "cost": 0.073, "tokens": 2000}
    }
  }
}
```

每次代理转发完一笔请求，就同步更新这个字典（纳秒级）。Dashboard 的首页直接读这份内存数据，所以**永远是最新的**，不会有"刚调完但 Dashboard 看不到"的问题。

**后台 Worker**：一个 `asyncio.Task`，死循环从 `asyncio.Queue` 里取观测数据，攒够 50 条或者过了 5 秒就批量写入数据库。服务器关闭时会把队列里剩下的数据全部刷盘，不丢失。

### 模型适配器 — `app/services/llm_adapter.py`

不同 LLM 供应商的 API 格式不一样。比如 OpenAI 的请求长这样：

```json
{"model": "gpt-4o", "messages": [{"role": "user", "content": "..."}]}
```

而 Anthropic（Claude）的要求是：

```json
{"model": "claude-sonnet", "messages": [{"role": "user", "content": "..."}], "max_tokens": 4096}
```

这个适配器负责把请求转成各个供应商认的格式，并且把响应统一回来。加了新供应商就多写一个方法，不影响现有逻辑。

目前支持：
- OpenAI 兼容格式（GPT、DeepSeek、千问、智谱等）
- Anthropic（Claude）

费用估算：内置了一个价格表，不同模型按不同的输入/输出 token 单价计算。价格硬编码在代码里，后续可以挪到配置或数据库里。

### API Key 管理 — `app/api/keys.py`

每个接入的服务发一个独立的 Key。创建时生成 `sk-` 开头的随机字符串，可以设置每分钟的调用上限。禁用某个 Key 后使用它的请求会直接返回 401。

这个是实现"多租户隔离"的最小可用方案——不需要注册登录那一套，但每个 Key 的数据完全隔开。

### Dashboard — `app/api/dashboard.py`

提供三个查询接口：

- `/api/dashboard/summary` — 首页概览，数据来自内存计数器，实时返回
- `/api/dashboard/cost-by-model?days=7` — 从数据库查历史数据，按模型拆分过去 N 天的费用。面试的时候可以用来展示 SQL 聚合查询的能力
- `/api/traces` — 调用记录明细，支持按 Key、模型、状态筛选

## 环境要求

- Python 3.11 或更高
- Conda（推荐，当然 pip + venv 也一样）
- Docker Desktop（可选的，只在你需要用 PostgreSQL 替代 SQLite 时需要）

## 怎么跑起来

### 1. 装依赖

```bash
# 创建 conda 环境
conda create -n llm-obs python=3.11 -y
conda activate llm-obs

# 安装依赖
pip install -r requirements.txt
```

如果你是 Windows + conda 环境，有可能会遇到 SSL 证书找不到的问题。报错的话先执行：

```bash
$env:SSL_CERT_FILE = (python -c "import certifi; print(certifi.where())")
```

然后就可以启动服务了：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

打开 http://localhost:8000/docs 可以看到 Swagger 文档，直接在里面测试接口。

### 2. 走一遍完整流程

**创建一个 API Key**：

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "我的测试应用", "rate_limit": 60}'
```

返回：

```json
{
  "id": "c41873dc-...",
  "key": "sk-w3r6VmyvOpJRkIe5...",
  "name": "我的测试应用",
  "rate_limit": 60,
  "is_active": true
}
```

记下返回的 `key`。

**通过代理调一次 LLM**：

你需要先在系统环境变量里设置真实的 API Key：

```bash
# Windows PowerShell
$env:LLM_KEY_OPENAI = "sk-你的真实OpenAIKey"
```

然后发请求，注意 `Authorization` 用刚才创建的 Key，`model` 用 `供应商/模型名` 格式：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-w3r6VmyvOpJRkIe5..." \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "用一句话解释什么是RESTful API"}]
  }'
```

返回的就是 OpenAI 的标准响应，跟直连没区别：

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "choices": [{"message": {"content": "RESTful API 是一种..."}}],
  "usage": {"prompt_tokens": 20, "completion_tokens": 80, "total_tokens": 100}
}
```

**看 Dashboard**：

```bash
curl http://localhost:8000/api/dashboard/summary
```

你会看到刚才的调用已经被统计进去了：

```json
{
  "total_calls_today": 1,
  "total_cost_today": 0.000065,
  "total_tokens_today": 100,
  "error_rate_today": 0.0,
  "active_keys": 1,
  "by_model": [
    {
      "model": "gpt-4o-mini",
      "calls": 1,
      "total_cost": 0.000065,
      "total_tokens": 100
    }
  ]
}
```

### 3. 跑测试

```bash
python -m pytest tests/ -v
```

测试用的是 SQLite 内存数据库，每次测试前重建表，测试后回滚，不影响你的开发数据。

## 数据库切换

开发的时候默认用 SQLite，clone 下来就能跑，不用配置任何东西。

如果你想切到 PostgreSQL（比如面试时想展示 SQL 优化能力），操作步骤：

1. 启动 Docker Desktop
2. `docker compose up -d`（启动 PostgreSQL 容器）
3. 修改 `.env` 文件中的 `USE_SQLITE=false`
4. 重启服务

如果 Docker Desktop 拉不下镜像（国内环境常见），在 Settings → Resources → Proxies 里配置 HTTP 代理，或者用阿里云的容器镜像服务。

## 一些设计选择

| 做了什么 | 为什么这样做 |
|----------|------------|
| 开发用 SQLite，生产用 PG | clone 下来零配置跑起来，真正上线时 PG 的 JSONB 和窗口函数更适合统计分析 |
| 异步队列写库 | 不想让观测数据的写入拖慢请求响应。队列解耦后主链路不受影响 |
| 内存做热点统计 | 用户刚调完查 Dashboard 应该是瞬间看到最新数据，不用等 Worker 写完 PG |
| 直接用 httpx 调 LLM | 不想引入 LangChain 那一套。适配器加起来不到 200 行，逻辑完全在自己手里 |
| API Key 做多租户 | 比完整的用户系统轻量太多，但隔离效果够用 |
| UUID 存成字符串 | SQLite 和 PG 都认，不用担心迁移问题 |

## TODO（按优先级）

- [ ] Dashboard HTML 页面，用 Chart.js 画成本趋势图
- [ ] 数据自动清理（trace_records 只保留 30 天）
- [ ] 模型配置页面（价格、供应商、fallback 规则）
- [ ] 链路追踪（trace_id 串联多步调用）
- [ ] 质量告警（响应变慢、错误率高时提醒）
