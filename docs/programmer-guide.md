# LLM Observability Platform — 程序员操作手册

> 写给刚接触后端开发的纯小白。这篇文档不讲废话，每一步都解释清楚"是什么"和"为什么"。

---

## 目录

1. [这个项目是什么](#1-这个项目是什么)
2. [环境篇：你的电脑上需要装什么](#2-环境篇你的电脑上需要装什么)
3. [架构篇：一个后端项目是怎么组织的](#3-架构篇一个后端项目是怎么组织的)
4. [文件篇：每个文件做什么、为什么这样写](#4-文件篇每个文件做什么为什么这样写)
5. [数据流篇：一次请求的完整旅程](#5-数据流篇一次请求的完整旅程)
6. [操作篇：怎么跑起来、怎么用](#6-操作篇怎么跑起来怎么用)
7. [API 篇：每个接口怎么用、Swagger 怎么看](#7-api-篇每个接口怎么用swagger-怎么看)
8. [概念篇：通过这个项目学到的后端知识](#8-概念篇通过这个项目学到的后端知识)

---

## 1. 这个项目是什么

### 一句话版本

你写了一个网站/App，里面要用 ChatGPT。每次调 ChatGPT 都要花钱。这个项目帮你**记录每一次调用花了多少钱、用了多少 token、有没有出错**，并且有一个网页 Dashboard 可以实时看到这些数据。

### 它怎么工作

这个项目把自己"塞"在你的应用和 ChatGPT/Claude 之间：

```
你的代码 ──→ 本平台（代理） ──→ ChatGPT / Claude
                │
                └── 顺便记录：谁调的、花了多少钱、用了多少 token
```

你的代码本来直接调 `https://api.openai.com`，现在改成调 `http://localhost:8000`，本平台收到请求后转发给 OpenAI。这个转发过程对你透明，返回的数据格式一模一样。相当于快递员帮你跑腿，顺便记了个账。

### 和 CC Switch 的区别

CC Switch 是桌面软件，你手动点来点去切换配置。这个项目是一个**后端服务**，程序调它，不是人调它。

---

## 2. 环境篇：你的电脑上需要装什么

### Python（运行代码的语言）

这个项目用 Python 写。你需要 Python 3.11 或更新版本。

怎么看自己装了没有：

```bash
python --version
```

如果显示 `Python 3.11.x` 或 `Python 3.12.x`，说明已经装了。低于 3.11 的需要升级。

### Conda（环境管理器）

你可能会同时做多个 Python 项目。项目 A 用 `fastapi==1.0`，项目 B 用 `fastapi==2.0`，装在同一个地方会打架。

Conda 解决这个问题：给每个项目创建**独立的虚拟环境**，互不干扰。

```bash
# 创建一个叫 myenv 的虚拟环境，指定 Python 3.11
conda create -n myenv python=3.11 -y

# 进入这个环境
conda activate myenv

# 现在 pip install 的所有东西都只在 myenv 里面
pip install -r requirements.txt
```

### Docker（跑数据库用的容器）

数据库（PostgreSQL）需要安装和配置。传统方式很麻烦：下载安装包、配置端口、创建用户、设置权限……

Docker 把这一切打包成一个"集装箱"（容器）。你只需要一条命令，数据库就跑起来了，而且和你的电脑环境完全隔离。

```bash
docker compose up -d    # 启动数据库
docker compose down     # 关闭数据库
```

本项目的 Docker 只用来跑 PostgreSQL。如果不启动 Docker，项目会自动使用 SQLite，一样可以开发。

---

## 3. 架构篇：一个后端项目是怎么组织的

### 分层的概念

后端项目最重要的设计原则是**分层**。每一层只管自己的事，不越界。

这个项目分了这几层：

```
┌─────────────────────────────────┐
│  API 层（api/）                  │  ← 接收 HTTP 请求，返回 HTTP 响应
│  proxy.py  keys.py  dashboard.py│
├─────────────────────────────────┤
│  服务层（services/）              │  ← 业务逻辑：转发请求、写数据库、统计
│  llm_adapter.py  write_worker.py│
├─────────────────────────────────┤
│  模型层（models/）                │  ← 数据库表的结构定义
│  api_key.py  trace_record.py    │
├─────────────────────────────────┤
│  数据库（PostgreSQL / SQLite）    │  ← 真正存数据的地方
└─────────────────────────────────┘
```

为什么要分层？举个例子：Dashboard 接口要返回统计数据。它不需要知道数据怎么存的——是 PostgreSQL 还是 SQLite？不重要。它只管从服务层拿数据，然后返回 JSON。将来哪怕换数据库，Dashboard 的代码一行都不用改。

### 这个项目用了哪些库

| 库 | 干什么用 |
|----|---------|
| **FastAPI** | Web 框架。帮你写 HTTP 接口（`@app.get("/xxx")` 这种） |
| **uvicorn** | 服务器。让 FastAPI 应用跑起来，接收网络请求 |
| **SQLAlchemy** | ORM。让你用 Python 类操作数据库，不用手写 SQL |
| **asyncpg / aiosqlite** | 数据库驱动。SQLAlchemy 底层靠它们真正连接数据库 |
| **httpx** | HTTP 客户端。本项目用它转发请求给 LLM |
| **Pydantic** | 数据校验。定义请求和响应的格式，不符合就自动报错 |
| **pytest** | 测试框架 |

---

## 4. 文件篇：每个文件做什么、为什么这样写

### `app/main.py` — 程序的入口

```python
app = FastAPI(...)  # 创建一个 Web 应用
```

这个文件做三件事：

1. **启动时**（`lifespan` 函数）：自动建数据库表、启动后台 Worker
2. **注册路由**：把下面三个模块的接口挂到 app 上
3. **定义首页**：`GET /` 返回 Dashboard HTML 页面

"注册路由"的意思：你在 `api/proxy.py` 里写了一个 `@router.post("/v1/chat/completions")`，但这个路由得"装到"app 上才能生效。`app.include_router(proxy.router)` 就是在做这件事。

### `app/config.py` — 所有配置的集中地

```python
class Settings(BaseSettings):
    use_sqlite: bool = True   # 默认用 SQLite
    app_port: int = 8000      # 端口号
```

任何需要配置的东西都在这里定义，然后别的地方 `from app.config import settings` 统一引用。好处是：

- 要改端口？只改这一处
- 环境变量可以覆盖默认值（Pydantic Settings 自动读 `.env` 文件）

### `app/core/database.py` — 数据库连接

创建一个 SQLAlchemy "引擎"，它是和数据库之间的那条连接。

关键代码：

```python
engine = create_async_engine(settings.database_url)
async_session = async_sessionmaker(engine, ...)
```

- `async_engine`：异步的。不阻塞程序的其他部分
- `async_sessionmaker`：一个"会话工厂"，每次需要操作数据库就找它要一个会话

`get_db()` 函数：FastAPI 的依赖注入。路由函数声明 `db: AsyncSession = Depends(get_db)`，FastAPI 自动帮你创建会话 → 执行操作 → 提交或回滚。

### `app/models/api_key.py` 和 `trace_record.py` — 数据库表定义

这两个文件做的事：用 Python 类描述数据库表长什么样。

```python
class ApiKey(Base):
    __tablename__ = "api_keys"       # 表名
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # 主键
    key: Mapped[str] = mapped_column(String(64), unique=True)      # 唯一键
    name: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

SQLAlchemy 会根据这个类定义，自动在数据库里建对应的表。你不用手写 `CREATE TABLE` 语句。

**api_keys 表**：存所有的 API Key。每个接入方一个 Key。

**trace_records 表**：存每一次 LLM 调用的记录。核心字段：

| 字段 | 含义 |
|------|------|
| `api_key_id` | 哪个 Key 发起的调用（外键，指向 api_keys 表） |
| `model` | 调了哪个模型 |
| `provider` | 走的哪个供应商（openai / anthropic / deepseek） |
| `request_body` | 用户发了什么（JSON 格式存） |
| `response_body` | 模型回了什么（JSON 格式存） |
| `token_input` | 输入 token 数量 |
| `token_output` | 输出 token 数量 |
| `cost` | 花了多少钱（美元） |
| `latency_ms` | 响应花了多少毫秒 |
| `status` | success 还是 error |

### `app/schemas/` — 数据格式定义

Pydantic 模型，定义"请求长什么样、响应长什么样"。

```python
class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    rate_limit: int = Field(60, ge=0)
```

如果请求发来的 JSON 不符合这个格式（比如 `name` 为空），FastAPI 会自动返回 422 错误，你在路由函数里拿到的数据一定是合法的。这叫**数据校验**。

### `app/middleware/api_key_auth.py` — 鉴权中间件

"中间件"是介于 HTTP 请求和路由处理之间的一层。每个请求到达路由之前，先经过中间件。

这个中间件做的事：

1. 从 HTTP Header 里取出 `Authorization: Bearer sk-xxx`
2. 提取 `sk-xxx`，去 `api_keys` 表查这个 Key 是否存在、是否启用
3. 有效 → 把 Key 的 ID 注入 `request.state`，放行
4. 无效 → 直接返回 401，请求到此为止

### `app/api/proxy.py` — 核心代理端点

整个项目最重要的文件。暴露 `POST /v1/chat/completions`。

流程：

```
收到请求
  │
  ├─ 1. 鉴权（中间件已完成）
  ├─ 2. 解析 model 字段 → 拆出供应商和模型名
  ├─ 3. 转发给真正的 LLM（通过 llm_adapter）
  ├─ 4. 响应立即返回给调用方
  ├─ 5. 观测数据扔进 asyncio.Queue（不等写入）
  └─ 6. 更新内存计数器
```

第 4、5、6 步是并行的。第 4 步不等待第 5 步完成。这就是"异步"的意义——用户收到响应的速度不受观测记录的影响。

### `app/services/llm_adapter.py` — 模型适配器

不同 LLM 厂商的 API 格式不一样。OpenAI 的请求格式和 Anthropic（Claude）的请求格式不同。这个适配器负责：

1. 接收统一格式的请求（OpenAI 格式）
2. 转成目标厂商的格式
3. 发出请求
4. 把响应转回统一格式
5. 根据 token 用量计算费用

这样 proxy.py 不需要知道 OpenAI 和 Claude 的差异。加一个新厂商？在适配器里加一个方法就行，proxy.py 不动。

### `app/services/write_worker.py` — 异步写入和内存统计

两点设计：

**为什么用队列而不是直接写库？**

如果每次调完 LLM 都执行一条 `INSERT`，凭空多出来几十毫秒延迟。队列解耦后，主链路只负责"把数据扔进队列"（微秒级），写入交给后台慢慢做。

**为什么又加了一层内存计数器？**

队列写入数据库有延迟（批量攒到 50 条或 5 秒才写）。用户刚调完就去 Dashboard 看，数据可能还没落库。内存计数器在主链路中**同步**更新（纳秒级），Dashboard 读它永远是实时的。

这就是"最终一致性"——数据库最终会有数据（几秒延迟），但用户查看时总能看到最新值。

### `app/api/keys.py` — API Key 管理

标准的增删改查（CRUD）。没什么特别的逻辑，就是操作 `api_keys` 表。

### `app/api/dashboard.py` — Dashboard 数据接口

三个查询接口：

- `summary`：读内存计数器，实时。给 Dashboard 首页卡片用
- `cost-by-model`：查数据库，按模型聚合一笔 SQL 查询。给图表用
- `traces`：查调用明细，支持筛选

### `app/static/dashboard.html` — 可视化页面

一个纯 HTML 文件，包含 CSS 和 JavaScript。浏览器加载后：

1. 用 `fetch()` 调平台的 API 拿数据
2. 用 Chart.js 画图表
3. 每 5 秒自动重新请求一次

### `tests/conftest.py` — 测试配置

每个测试用独立的 SQLite 内存数据库，测试完自动清空。不会影响正常开发数据。

### `docker-compose.yml` — Docker 容器定义

告诉 Docker 怎么启动 PostgreSQL：用什么镜像、暴露什么端口、用户名密码是什么。

### `.env` — 环境变量

数据库连接信息、模式开关（SQLite/PG）。不提交到 Git（在 `.gitignore` 里），因为每台机器的配置不一样。

### `.gitignore` — Git 忽略规则

告诉 Git 哪些文件不要提交：虚拟环境、数据库文件、IDE 配置、`.env` 等。

---

## 5. 数据流篇：一次请求的完整旅程

以用户通过代理调 ChatGPT 为例，跟踪数据的完整路径。

### 第一步：HTTP 请求到达

```
POST /v1/chat/completions
Host: localhost:8000
Authorization: Bearer sk-abc123
Content-Type: application/json

{
  "model": "openai/gpt-4o-mini",
  "messages": [{"role": "user", "content": "什么是闭包"}]
}
```

uvicorn 监听 8000 端口，收到这个 TCP 包，解析成 HTTP 请求，交给 FastAPI。

### 第二步：中间件鉴权

请求到达路由之前，先走 `api_key_auth.py`：

1. 取 Header `Authorization: Bearer sk-abc123`
2. 提取 `sk-abc123`
3. 查 `api_keys` 表：`SELECT * FROM api_keys WHERE key='sk-abc123' AND is_active=true`
4. 找到了 → `request.state.api_key_id = "uuid-of-this-key"`
5. 没找到 → 返回 `401 Unauthorized`

### 第三步：路由匹配

FastAPI 根据 URL 和方法匹配到 `proxy.py` 的 `proxy_chat_completions` 函数。

### 第四步：代理处理

```python
body = await request.json()       # 拿到请求体
raw_model = body.get("model")     # "openai/gpt-4o-mini"
provider, model = raw_model.split("/", 1)  # provider="openai", model="gpt-4o-mini"
user_llm_key = os.getenv("LLM_KEY_OPENAI")  # 从环境变量取上游 Key
result = await adapter.call(provider, model, body, user_llm_key)  # 调真的 LLM
```

### 第五步：适配器转发

`llm_adapter.py` 看到 `provider="openai"`，走 `_call_openai_compatible`：

```python
url = "https://api.openai.com/v1/chat/completions"
headers = {"Authorization": f"Bearer {user_llm_key}"}
resp = await client.post(url, json=body, headers=headers)
```

OpenAI 返回：

```json
{
  "choices": [{"message": {"content": "闭包是指..."}}],
  "usage": {"prompt_tokens": 15, "completion_tokens": 80, "total_tokens": 95}
}
```

适配器解析出 token 用量，查价格表算出费用。

### 第六步：返回 + 记录（并行）

```python
# 这两件事同时发生，互不等待

# 主线：返回给用户
return result["response_body"]

# 支线：记录观测数据
await write_queue.put({
    "api_key_id": "xxx",
    "model": "gpt-4o-mini",
    "provider": "openai",
    "token_input": 15,
    "token_output": 80,
    "cost": 0.000065,
    "latency_ms": 850,
    "status": "success",
    "request_body": {...},
    "response_body": {...}
})

# 支线：更新内存计数
stats_cache.record(api_key_id="xxx", model="gpt-4o-mini", cost=0.000065, ...)
```

### 第七步：后台 Worker 写库

Worker 从 `asyncio.Queue` 取数据，攒够 50 条（或 5 秒到了）批量 INSERT 进 `trace_records` 表。

### 第八步：Dashboard 查询

用户打开 `http://localhost:8000`，页面 JavaScript 调 `GET /api/dashboard/summary`。

`dashboard.py` 的 `get_summary()` 读 `stats_cache`（内存 dict），组装成 JSON 返回。这个查询从不过数据库，所以永远瞬间返回。

---

## 6. 操作篇：怎么跑起来、怎么用

### 前置条件

- Python 3.11+
- Git
- （可选）Docker Desktop

### 克隆项目

```bash
git clone https://github.com/qiumy1879/LLM-Observability-Platform.git
cd LLM-Observability-Platform
```

### 创建虚拟环境并安装依赖

```bash
conda create -n myenv python=3.11 -y
conda activate myenv
pip install -r requirements.txt
```

### 启动服务

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

参数说明：
- `app.main:app`：模块路径 `app/main.py`，变量名 `app`
- `--host 0.0.0.0`：允许局域网内其他设备访问
- `--port 8000`：端口号
- `--reload`：代码改了自动重启（开发用）

### 验证服务是否启动

```bash
curl http://localhost:8000/health
# 返回 {"status":"healthy","version":"0.1.0"}
```

或者浏览器打开 http://localhost:8000/docs 看到 Swagger 页面。

### 创建你的第一个 API Key

在 Swagger 页面里点 `POST /api/keys` → "Try it out" → 修改 name → Execute。

或者用终端：

```bash
curl -X POST http://localhost:8000/api/keys \
  -H "Content-Type: application/json" \
  -d '{"name": "我的第一个Key", "rate_limit": 60}'
```

返回结果里的 `key` 字段（`sk-` 开头的那串）记下来。

### 设置上游 API Key

要让平台能调真正的 LLM，你需要设置真实的 API Key：

**Windows PowerShell：**

```powershell
$env:LLM_KEY_OPENAI = "sk-你的OpenAI密钥"
```

**Mac / Linux：**

```bash
export LLM_KEY_OPENAI="sk-你的OpenAI密钥"
```

平台会根据 `model` 字段里的供应商名，自动找对应的环境变量。调用 `openai/gpt-4o` 就取 `LLM_KEY_OPENAI`，调 `deepseek/chat` 就取 `LLM_KEY_DEEPSEEK`。

### 发起一次代理调用

Swagger 里找到 `POST /v1/chat/completions` → Try it out，或者终端：

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你刚才创建的Key" \
  -d '{
    "model": "openai/gpt-4o-mini",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

### 看 Dashboard

浏览器打开 http://localhost:8000，能看到：

- 顶部四张卡片（调用次数、费用、Token、错误率）
- 各模型费用占比（环形图）
- 各模型调用次数（柱状图）
- 最近调用的记录表格
- API Key 管理面板

### 跑测试

```bash
python -m pytest tests/ -v
```

---

## 7. API 篇：每个接口怎么用、Swagger 怎么看

### 什么是 Swagger

Swagger 是一个**交互式 API 文档**。打开 http://localhost:8000/docs 你会看到所有接口的列表。每个接口可以点开，看到它需要什么参数、返回什么数据，还能**直接在页面试用**。

### 页面结构怎么看

打开 `/docs` 后，页面分为三个分组（Tags）：

**Proxy 分组** — 核心代理功能

| 接口 | 说明 |
|------|------|
| `POST /v1/chat/completions` | 代理 LLM 调用。格式和 OpenAI 完全一致 |

**API Keys 分组** — Key 管理

| 接口 | 说明 |
|------|------|
| `POST /api/keys` | 创建一个新的 API Key |
| `GET /api/keys` | 列出所有 Key |
| `PATCH /api/keys/{key_id}` | 启用或禁用某个 Key |
| `DELETE /api/keys/{key_id}` | 删除某个 Key |

**Dashboard 分组** — 数据和统计

| 接口 | 说明 |
|------|------|
| `GET /api/dashboard/summary` | 实时总览（数据来自内存，瞬间返回） |
| `GET /api/dashboard/cost-by-model` | 按模型拆分的成本（可选 `?days=7` 参数） |
| `GET /api/traces` | 调用明细列表（支持 `?api_key_id=xxx&model=xxx&status=error` 筛选） |
| `GET /api/traces/{trace_id}` | 某条调用的完整详情（含请求体和响应体） |

### Swagger 怎么试用

以 `POST /api/keys` 为例：

1. 找到这个接口，点一下展开
2. 点右侧的 **"Try it out"** 按钮
3. Request body 区域会显示一个可编辑的 JSON 模板：

   ```json
   {
     "name": "string",
     "rate_limit": 60
   }
   ```

4. 把 `"string"` 改成你想用的名字，比如 `"my-test-key"`
5. 点下面蓝色的 **"Execute"** 按钮
6. 页面下方显示服务器返回的结果：

   ```json
   {
     "id": "abc123-...",
     "key": "sk-XYZ...",
     "name": "my-test-key",
     "rate_limit": 60,
     "is_active": true,
     "created_at": "2026-06-09T..."
   }
   ```

7. 记下 `key` 字段的值

### 用 Swagger 调代理端点

测试代理端点需要两步，因为需要鉴权。

**第一步：设置 API Key**

在 Swagger 页面的右上角有一个 **"Authorize"** 按钮，点开后：输入 `Bearer sk-你的Key`，点 Authorize，Close。这下所有请求都会自动带上这个 Header。

**第二步：试用代理接口**

找到 `POST /v1/chat/completions` → Try it out → 修改 model 和 messages → Execute。

不需要手动填 Authorization Header，Swagger 已经帮你加好了。

### 用 Swagger 看统计数据

试用代理端点之后，去 `GET /api/dashboard/summary` → Try it out → Execute。你会看到刚才的调用已经出现在统计里了。

### 接口参数详解

**`GET /api/dashboard/cost-by-model`**

可选参数 `days`，默认 7。改成 30 就是查过去 30 天的数据。

**`GET /api/traces`**

四个可选参数，可以组合使用：

| 参数 | 类型 | 作用 | 示例 |
|------|------|------|------|
| `skip` | int | 跳过前 N 条（分页） | `?skip=50` |
| `limit` | int | 最多返回 N 条 | `?limit=20` |
| `api_key_id` | string | 只看某个 Key 的调用 | `?api_key_id=abc123` |
| `model` | string | 只看某个模型 | `?model=gpt-4o-mini` |
| `status` | string | 只看成功或失败的 | `?status=error` |

组合示例：只看 `gpt-4o-mini` 的失败记录：

```
GET /api/traces?model=gpt-4o-mini&status=error&limit=10
```

---

## 8. 概念篇：通过这个项目学到的后端知识

### Web 框架（FastAPI）

一个 Web 框架帮你处理 HTTP 请求的"脏活"：解析 URL、解析 Header、序列化 JSON、生成文档。你只需要写业务逻辑函数，用装饰器 `@app.get("/xxx")` 标记一下，框架自动把 URL 和函数关联起来。

### ORM（SQLAlchemy）

ORM = Object-Relational Mapping，对象关系映射。翻译成人话：**用 Python 类操作数据库，不用手写 SQL**。

```python
# 不用 ORM（手写 SQL）
cursor.execute("SELECT * FROM api_keys WHERE is_active = true")

# 用 ORM（Python 对象）
result = await session.execute(select(ApiKey).where(ApiKey.is_active == True))
```

好处：
- 换数据库不用改代码（SQLite 和 PostgreSQL 的 SQL 有细微差异，ORM 帮你抹平了）
- 防止 SQL 注入攻击
- 代码可读性更好

### 依赖注入

FastAPI 的 `Depends()` 机制。你在路由函数里声明"我需要数据库会话"：

```python
async def list_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey))
    return result.scalars().all()
```

FastAPI 自动调用 `get_db()`，创建会话，传给你的函数。函数执行完后，如果有异常就回滚，正常就提交。你不用在每一个函数里写"创建连接 → try → commit → except → rollback"的样板代码。

### 异步编程（async/await）

Python 的异步不是多线程。它在一个线程里"跳来跳去"：

```python
result = await adapter.call(...)
```

执行到 `await` 时，Python 暂停这个函数，去处理其他请求。等 `adapter.call()` 有结果了再切回来继续。

为什么重要？如果不用异步，代理端点转发请求给 LLM 时要等 1 秒（网络延迟），这 1 秒里整个程序都不能处理其他请求。用异步，这 1 秒里去处理了 1000 个其他请求。

### 中间件模式

中间件 = 请求的"安检口"。在请求到达业务逻辑之前做一些通用检查（鉴权、日志、限流）。业务逻辑不需要重复写这些检查代码。

### 生产者-消费者模式

`write_worker.py` 用的就是这种模式：

- **生产者**：代理端点，制造观测数据，扔进队列
- **消费者**：后台 Worker，从队列取数据，写入数据库
- **队列**：asyncio.Queue，缓冲区

好处：生产和消费解耦。生产者不用等消费者完成，只管扔数据。消费者可以攒一批一起写入（批量操作比逐条快得多）。

### 最终一致性

内存计数器和数据库之间存在短暂的不一致（几秒延迟）。这叫做"最终一致性"——不追求实时完全同步，但保证最终会一致。

你查 Dashboard 首页时，数据来自内存（可能比数据库快几秒），查历史明细时数据来自数据库。两者最终是一致的，只是有时间差。很多大型系统（银行、电商）都用这个思路，不追求强一致性来换取更高的性能。

### RESTful API 设计

这个项目的接口遵循 REST 风格：

- `GET /api/keys` → 获取资源列表
- `POST /api/keys` → 创建资源
- `PATCH /api/keys/{id}` → 修改资源
- `DELETE /api/keys/{id}` → 删除资源

用 HTTP 方法（GET/POST/PATCH/DELETE）表达操作意图，而不是把动词写在 URL 里（像 `/api/create-key` 这种）。这是业界的通用做法。
