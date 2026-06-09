# LLM 可观测性平台 — PRD

> 版本 v1.0 | 2026-06-07 | 面试项目

---

## 1. 项目概述

### 1.1 一句话描述

一个 LLM 调用可观测性平台——通过代理模式拦截所有 LLM API 调用，提供调用追踪和成本分析能力。

### 1.2 解决的问题

| 痛点 | 现状 | 本平台的解法 |
|------|------|-------------|
| 不知道花了多少钱 | 多个模型/多个 Key，账单混乱 | 按 Key + 模型 + 时间维度汇总成本 |
| 出问题无法追溯 | 调 LLM 是"黑盒"，错了不知道哪次调用的 | 每次调用全量记录，可查可回溯 |
| 没有用量监控 | 不知道谁在用、用多少 | Dashboard 实时显示调用次数和费用 |

### 1.3 一句话区分于 CC Switch

> CC Switch 是面向**个人开发者**的**桌面配置工具**；
> 本平台是面向**应用服务**的**后端可观测性中间件**。

---

## 2. 用户模型

### 2.1 用户画像

- **主要用户**：接入 LLM 的后端服务（通过 API Key 鉴权）
- **次要用户**：查看 Dashboard 的开发者（通过浏览器访问）

### 2.2 API Key 多租户

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ 服务 A    │     │ 服务 B    │     │ 服务 C    │
│ Key-AAA  │     │ Key-BBB  │     │ Key-CCC  │
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │
     └────────────────┼────────────────┘
                      ▼
              ┌───────────────┐
              │  LLM 观测平台  │
              │  (代理层)      │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │  Claude/GPT/..│
              └───────────────┘
```

每个 API Key 绑定一个"租户"，统计数据按 Key 完全隔离。

---

## 3. 功能模块

### 3.1 P0 — 调用追踪 (Trace)

**目标**：每一次 LLM 调用的完整记录可查。

**功能点**：
- [x] 代理 OpenAI 兼容格式的 `/v1/chat/completions` 端点
- [x] 转发请求到真实模型，返回响应（不改动内容）
- [x] 异步记录每次调用的：模型、Token 数、延迟、状态、错误信息
- [x] 请求体和响应体存入 JSONB（截断至 10000 字符）
- [x] 支持查看调用详情

### 3.2 P0 — 成本分析 (Cost Dashboard)

**目标**：知道钱花在哪了。

**功能点**：
- [x] 内存计数器：实时显示"今天花了多少钱、调了多少次"
- [x] PG 明细查询：按 Key / 模型 / 日期范围查询调用记录
- [x] 成本按模型拆分的饼图或表格
- [x] 成本随时间变化的趋势线
- [x] 异常用量检测（某 Key 短时间内调用量飙升）

### 3.3 P1 — API Key 管理

**目标**：多用户/多服务接入。

**功能点**：
- [x] 创建/启用/禁用 API Key
- [x] 每个 Key 可配置：速率限制（次/分钟）、备注名
- [x] Key 级别的用量统计

### 3.4 P2（选做）— 质量监控

- 模型响应时间超过阈值告警
- 错误率超过阈值告警
- 模型返回空内容的检测

### 3.5 P2（选做）— 链路追踪

- trace_id 串联多步调用
- chain_steps 表记录每一步的耗时

---

## 4. 数据模型

### 4.1 ER 图

```
api_keys                     trace_records
─────────────                ──────────────────────────
id (PK)          1───N      id (PK)
key (UNIQUE)                 api_key_id (FK → api_keys)
name                         model
rate_limit                   provider
is_active                    request_body (JSONB)
created_at                   response_body (JSONB)
                             token_input
                             token_output
                             cost
                             latency_ms
                             status
                             error_message
                             trace_id (UUID)
                             created_at (INDEX)
```

### 4.2 trace_records 索引策略

```sql
-- 成本分析核心查询：某 Key 在某时间段内
CREATE INDEX idx_trace_key_time ON trace_records(api_key_id, created_at DESC);

-- 链路追踪
CREATE INDEX idx_trace_trace_id ON trace_records(trace_id);
```

### 4.3 数据保留策略

- trace_records 保留最近 30 天
- 通过定时任务清理过期数据
- 聚合统计单独存储，不受清理影响

---

## 5. 技术架构

### 5.1 整体架构图

```
                        ┌─────────────────────────┐
                        │     Dashboard (HTML)     │
                        │   GET /dashboard/stats   │
                        └───────────┬─────────────┘
                                    │ 读
                                    ▼
┌──────────┐    POST      ┌───────────────┐    转发     ┌──────────────┐
│ 用户服务  │ ──────────►  │  LLM 观测平台  │ ─────────► │  Claude/GPT  │
│          │ ◄─────────── │  (FastAPI)    │ ◄───────── │  等真实模型   │
└──────────┘    响应       └───┬───┬───────┘            └──────────────┘
                               │   │
                         异步写入│   │实时更新
                               ▼   ▼
                    ┌──────────┐ ┌──────────┐
                    │PostgreSQL│ │内存计数器 │
                    │(明细数据) │ │(热点聚合) │
                    └──────────┘ └──────────┘
```

### 5.2 技术栈

| 层 | 选型 | 理由 |
|----|------|------|
| Web 框架 | FastAPI | 已有经验，异步原生支持 |
| 数据库 | PostgreSQL 15 | JSONB 存请求/响应，Docker 部署 |
| ORM | SQLAlchemy 2.0 | 已有经验 |
| LLM 调用 | httpx + openai SDK | 通过 SDK 调用各个模型 |
| 异步队列 | asyncio.Queue | 零依赖解耦写入 |
| 容器化 | Docker Compose | 一键启动 PG + App |
| 测试 | pytest + httpx | 已有经验 |

### 5.3 项目目录结构（预定）

```
llm-observability/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置管理
│   ├── models/              # SQLAlchemy 模型
│   │   ├── api_key.py
│   │   └── trace_record.py
│   ├── schemas/             # Pydantic 模型
│   ├── api/                 # 路由
│   │   ├── proxy.py         # 核心代理端点 /v1/chat/completions
│   │   ├── dashboard.py     # Dashboard 数据接口
│   │   └── keys.py          # API Key 管理
│   ├── services/
│   │   ├── proxy_service.py # 转发 + 记录逻辑
│   │   ├── llm_adapter.py   # 各模型适配器
│   │   ├── stats_service.py # 统计聚合服务
│   │   └── write_worker.py  # 异步写入 Worker
│   ├── middleware/
│   │   └── api_key_auth.py  # API Key 鉴权中间件
│   └── templates/           # Dashboard HTML 模板
├── tests/
│   ├── conftest.py
│   ├── test_proxy.py
│   ├── test_dashboard.py
│   └── test_keys.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 6. 性能策略

### 6.1 异步写入（不阻塞主链路）

```
请求进入
    │
    ├── 1. 转发给模型（主链路，必须快）
    │
    ├── 2. 记录请求体 → 扔进 asyncio.Queue（不阻塞）
    │
    └── 3. 模型返回后 → 立刻返回给用户（不阻塞）
              └── 同时把响应数据扔进 Queue
                       │
                       └── BackgroundWorker 逐条写入 PG
```

### 6.2 分层统计（内存 + PG）

```
写入：内存计数器 实时更新（纳秒级）
      PG trace_records 异步落库（秒级）

查询：Dashboard 首页 → 读内存计数器（即时）
      调用明细 → 读 PG（可能有几秒延迟）
      历史数据 → 全部走 PG
```

内存计数器结构：
```python
# 每 10 秒刷盘一次，防止重启丢失
stats_cache = {
    "key_abc": {
        "total_cost": 0.15,
        "total_tokens": 5000,
        "total_calls": 3,
        "by_model": {"claude-sonnet": {"cost": 0.10, "calls": 2}}
    }
}
```

### 6.3 数据截断

- request_body 和 response_body 各截断至 10000 字符
- 不存完整对话历史，只保留足够观测用的长度

---

## 7. API 设计

### 7.1 代理端点（核心）

```
POST /v1/chat/completions
Header: Authorization: Bearer <api_key>
Body: 标准 OpenAI Chat Completions 格式

→ 转发到真实模型，返回标准响应
→ 后台异步记录观测数据
```

### 7.2 管理端点

```
POST   /api/keys                    # 创建 API Key
GET    /api/keys                    # 列出所有 Key
PATCH  /api/keys/{id}              # 启用/禁用 Key
DELETE /api/keys/{id}              # 删除 Key

GET    /api/dashboard/summary       # 总览（读内存，实时）
GET    /api/dashboard/cost-by-model # 按模型拆分成本
GET    /api/dashboard/cost-trend    # 成本趋势
GET    /api/traces                  # 调用明细列表（支持分页筛选）
GET    /api/traces/{id}             # 单条调用详情
```

---

## 8. 分阶段交付计划

### 第一阶段（第 1 周）：骨架搭建
- Docker Compose 启动 PostgreSQL
- FastAPI 项目初始化 + SQLAlchemy 模型
- api_keys 表 + CRUD
- 代理端点基础转发（先不管观测）

### 第二阶段（第 2 周）：核心观测
- asyncio.Queue + BackgroundWorker 异步写入
- 内存计数器 + 定时刷盘
- trace_records 完整记录
- Dashboard 摘要接口

### 第三阶段（第 3 周）：成本分析
- Dashboard 按模型/时间拆分
- 简单 HTML 页面展示成本图表
- 数据清理定时任务

### 第四阶段（第 4 周）：打磨 + 选做
- P2 质量监控 / 链路追踪（选做）
- 补充测试用例
- README + 面试准备材料

---

## 9. 成功标准

- [ ] 代理端点能正确转发请求到至少 2 个模型（Claude + DeepSeek）
- [ ] 每次调用自动记录到 trace_records 表
- [ ] Dashboard 能看到实时成本汇总
- [ ] API Key 隔离生效（A 用户看不到 B 用户的数据）
- [ ] 全流程 demo：创建 Key → 发起调用 → Dashboard 看到记录
- [ ] 测试覆盖率 > 70%

---

## 10. 面试话术准备方向

| 面试官问什么 | 你能怎么展开 |
|-------------|-------------|
| "这个项目是什么" | "一个 LLM 可观测性平台，代理模式拦截 API 调用，做全量追踪和成本分析" |
| "为什么不用现成的" | "CC Switch 面向个人，LangSmith 太贵。我做的是轻量级自部署方案" |
| "异步写入怎么做的" | "asyncio.Queue + 后台 Worker，不阻塞主链路，配内存计数器保证查询实时性" |
| "多租户怎么隔离" | "API Key 级别隔离，中间件鉴权，统计按 Key 分区" |
| "PostgreSQL 怎么用的" | "JSONB 存异构请求体，窗口函数做统计聚合，联合索引优化时间范围查询" |
| "最难的技术点" | "分层统计架构——热点数据内存计数 + 明细异步落库 + 定时刷盘防丢失" |
| "后续想加什么" | "语义缓存、模型 A/B 测试、告警规则引擎、OpenTelemetry 协议支持" |
