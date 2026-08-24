# 数据架构升级（DATA_ARCHITECTURE）

> 本文件是「架构师 Agent」**数据管理部分**的规则与架构说明，对应 ISSUE #23「数据架构升级」。
> 数据管理**写成规则、由「架构·数据管理员」agent 统一负责**，为最大 **2500 个并发 agent**
> 的信息互通与持久化提供数据库承载。

---

## 一、背景与问题（为什么需要升级）

本仓库此前的数据承载是「单文件接力卡 / 按 agent 分片 JSON / 进程内 dict」的**简单结构**，
只能支撑单机、单实例、中小规模协作。一旦并发 agent 数上升到 **2500**，会遇到：

| 痛点 | 说明 |
|------|------|
| **信息互通不足** | 单文件接力卡只能一次一个 agent「持有」上下文，无法承载 2500 agent 互相发消息 |
| **内容存档脆弱** | 分片 JSON 无事务、无索引、易覆盖，无法可靠存档大量协作产出 |
| **进度统计困难** | 无统一进度/指标存储，各 agent 自造统计，口径混乱 |
| **任务存储缺失** | 任务分解、依赖、状态流转无数据库支撑 |
| **消息管线不可靠** | 无持久化消息队列，消息不可追踪、不可回放 |

**结论**：需要把数据承载升级为**真正的关系型数据库**，并形成**数据管理规则 + 数据管理员角色**。

---

## 二、架构拓扑（数据库分层）

```
┌────────────────────────────────────────────────────────────┐
│                  人类 / 架构·总师（二级信息俯瞰）             │
│            看板 / progress_report / task_overview / stats   │
└───────────────────────────┬────────────────────────────────┘
                            │ 只读统计 / 决策
┌───────────────────────────▼────────────────────────────────┐
│           架构·数据管理员（DataAdminRole · agent 负责）       │
│   内容存档 │ 进度统计 │ 消息管线 │ 任务存储（统一执行/统一口径）  │
└───────────────────────────┬────────────────────────────────┘
                            │ data/admin.py（职责执行）
┌───────────────────────────▼────────────────────────────────┐
│                data 数据管理层（local-agent/data/）          │
│  ┌─────────┬──────────┬──────────┬─────────┬───────────┐   │
│  │ repository │  schema   │   db     │ admin    │  cli     │   │
│  │  仓储接口   │  表结构    │ 后端抽象  │ 职责执行  │ 命令行    │   │
│  └─────────┴──────────┴──────────┴─────────┴───────────┘   │
└───────────────────────────┬────────────────────────────────┘
                            │ DB_BACKEND 切换（零依赖默认）
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
      SQLite(默认)     PostgreSQL(生产/分布式)   Redis(消息高速缓存,可选)
    单机/中小规模     支撑2500级强一致            大规模消息吞吐
```

### 模块清单

| 模块 | 职责 | 输入 | 输出 | 依赖 |
|------|------|------|------|------|
| `data/db.py` | 数据库连接层 + 后端抽象（sqlite 默认零依赖 / PG 可选） | DB_BACKEND/DB_URL | 连接/事务/查询 | 标准库 sqlite3；可选 sqlalchemy+psycopg2 |
| `data/schema.py` | 6 张数据表 DDL（agents/messages/tasks/progress/archives/stats） | — | 建表/列表 | db |
| `data/repository.py` | 各表统一 CRUD（屏蔽后端差异） | 结构化参数 | 结构化结果 | db |
| `data/admin.py` | **数据管理员职责执行**（内容存档/进度统计/消息管线/任务存储） | 业务事件 | 留痕+统计 | db/schema/repository |
| `data/cli.py` | 命令行入口（init/agent/archive/stats/report/msg/task） | CLI 参数 | 执行+输出 | data |
| `roles/data_admin.py` | **架构·数据管理员**角色（内置注册，可被 @ 召唤） | 需求/接力卡 | 数据底座产出 | data |

### 数据表设计（六表）

| 表 | 承载内容 | 用途 |
|----|----------|------|
| `agents` | agent 档案（agent_id/role/group/status/spec） | **内容存档**：每个并发 agent 的可寻址档案 |
| `messages` | 消息管线（msg_id/topic/from/to/payload/status/ts） | **消息互通**：发布/订阅/定向/广播，可追踪可回放 |
| `tasks` | 任务（task_id/title/assignee/depends_on/status/detail） | **任务存储**：任务分解与状态流转 |
| `progress` | 进度事件流水（agent_id/task_id/event/detail/ts） | **进度统计**：每个 agent/任务的状态变化 |
| `archives` | 内容存档（archive_id/kind/title/content/source） | **内容存档**：里程碑/决策/交付物归档 |
| `stats` | 聚合指标快照（metric/value/unit/ts） | **进度统计**：并发度/队列积压/活跃数等 |

---

## 三、可行性验证

| 项 | 结论 | 依据 |
|----|------|------|
| **SQLite 承载 2500 agent 档案** | ✅ 可行 | 实测 `test_data_layer.sh` 场景7：2500 agent 登记 + 2500 消息 + 进度事件全落库通过 |
| **事务/索引支持** | ✅ 可行 | SQLite WAL + busy_timeout，短事务 + 索引支撑并发读，满足单机数百级 |
| **2500 级强一致生产** | ⚠️ 有风险（需分布式） | 单机 SQLite 有写锁上限；生产 2500 级建议切 PostgreSQL（`DB_BACKEND=postgresql://...`），同一套 schema/repository 无缝切换 |
| **消息管线可回放** | ✅ 可行 | messages 表带 msg_id/status/ts，支持 topic 回放（审计/复盘） |
| **数据管理员角色** | ✅ 可行 | `roles/data_admin.py` 内置注册，输出契约明确，被 @ 可召唤 |

**规避方案**：默认 SQLite 零依赖开箱即用；规模声明 `spec.resource_estimate()` 判定超 `LOCAL_CAP`（默认 64）时建议切换 PostgreSQL/Redis 后端，同一套接口无缝迁移。

---

## 四、数据管理规则（数据管理员 agent 负责）

以下规则写入 `AGENTS.md` 与 `data/admin.py`，由「架构·数据管理员」统一执行：

1. **数据先行**：每个 agent / 任务 / 消息在进入业务逻辑前，必须先由数据管理员登记入库。
2. **统一口径**：所有指标统计以 `stats` / `progress` 为准，禁止各 agent 自造统计口径。
3. **可回溯留痕**：任何协作产出必须写入 `archives`，禁止无痕产出；进度变化必须写 `progress`。
4. **消息可回放**：消息管线（`messages`）可重放，供审计与复盘，不吞异常、不静默丢失。
5. **唯一负责**：数据写入 / 校验 / 统计 / 归档由「架构·数据管理员」统一执行，
   人类 / 架构·总师只通过二级信息（`progress_report` / `task_overview` / `snapshot_stats` / 看板）俯瞰。

---

## 五、工程实施方案（目录与接口）

### 目录结构

```
local-agent/
├── data/                        # 🆕 数据管理层（数据库承载）
│   ├── __init__.py              #   统一入口（db/schema/repository/admin）
│   ├── db.py                    #   数据库连接层 + 后端抽象（sqlite 默认/PG 可选）
│   ├── schema.py                #   6 张数据表 DDL
│   ├── repository.py            #   各表统一 CRUD（屏蔽后端差异）
│   ├── admin.py                 #   ⭐ 数据管理员职责执行
│   └── cli.py                   #   命令行入口
├── roles/
│   └── data_admin.py            # 🆕 架构·数据管理员角色（内置注册）
└── scale/
    └── engine.py                # 🆕 规模化流水线接入数据底座
```

### 接口契约

```python
# data/admin.py —— 数据管理员职责执行（唯一数据入口）
init()                      # 建表 + 登记数据管理员
register_agent(agent_id, role, group_id, status, spec)   # 内容存档：登记 agent
archive(archive_id, kind, title, content, source)        # 内容存档：产出归档
record_event(agent_id, event, detail, task_id)           # 进度统计：事件流水
snapshot_stats() / progress_report()                     # 进度统计：指标快照 / 报告
post_message/deliver/broadcast/consume/pending/replay    # 消息管线
assign_task/update_task/task_overview                    # 任务存储
```

### 后端切换

```bash
export DB_BACKEND=sqlite                # 默认：零依赖，单机/中小规模
export DB_BACKEND=postgresql            # 生产/2500级：需 psycopg2 + DB_URL
export DB_URL="postgresql://user:pass@host:5432/db"
export DB_BACKEND=redis                 # 消息队列高速缓存（大规模吞吐增强）
```

---

## 六、分工与协作规则

| 角色 | 与数据层的关系 |
|------|----------------|
| **架构·数据管理员** | 数据底座唯一负责人：统一执行内容存档/进度统计/消息管线/任务存储 |
| 架构·总师 | 通过 `progress_report`/`task_overview`/`snapshot_stats` 俯瞰决策，不直接碰原始库 |
| 架构·开发/评审/测试 | 产出先经数据管理员归档（archives）再流转，进度通过 progress 留痕 |
| scale 引擎 | 规模化流水线把 agent 档案/任务/消息落数据库（见 `engine.py` 数据底座集成） |

**接力**：数据管理员受三层触发（显式 `[触发:架构·数据管理员]` / 语义"数据/存档/进度/消息/任务" / rules 固定）强制唤起，输出契约见 `roles/data_admin.py`。

---

## 七、进度对齐（里程碑 + 测试信号灯）

| 里程碑 | 内容 | 验证 |
|--------|------|------|
| M1 数据层骨架 | db/schema/repository/admin 六表 | `test_data_layer.sh` 场景1-5 |
| M2 数据管理员角色 | roles/data_admin.py 内置注册 | `test_data_layer.sh` 场景6 |
| M3 2500 并发承载 | 2500 agent/消息/进度数据库承载 | `test_data_layer.sh` 场景7 |
| M4 scale 集成 | engine 规模化流水线接入数据底座 | `test_scale.sh` 场景7 |

**测试信号灯**：`.cnb.yml` test 阶段新增 `bash local-agent/tests/test_data_layer.sh`，未通过即红灯阻塞不放行。

---

## 八、索引

| 产物 | 位置 |
|------|------|
| 数据层代码 | `local-agent/data/` |
| 数据管理员角色 | `local-agent/roles/data_admin.py` |
| 数据层测试 | `local-agent/tests/test_data_layer.sh` |
| 流水线接入 | `local-agent/scale/engine.py` |
| 规则落地 | `AGENTS.md` / 本文档 |
| 调用示例 | `local-agent/data/cli.py` |
