# 协作运作机制（COLLAB_ENGINE）

> 本文件是 ISSUE #23「数据架构升级」的**协作运作机制**设计说明。
> 核心结论：光有数据库（DATA_ARCHITECTURE 六张表）是不够的——那只是一堆**孤立的点**。
> 要让 2500 个并发 agent 真正协作、不混乱、不互踩，必须有一套**运作机制**：
> **实体解耦 + 位置寻址 + 层级结构 + 权限空间 + 版本整合 + 小组提交**。
>
> 参考对象：DeepSeek harness 中「需求/任务/agent/skill/记忆 解除耦合、依赖数据库管理、
> 灵活移交、声明数据库位置编号即可协作」的思路，把它落成本仓库可执行、可核验、可留痕的机制。

---

## 一、问题诊断：为什么「只有数据库」不够

现有 `data/` 层已经能存档/统计/收发消息/存任务（六表）。但用户指出关键缺陷：

| 用户原话要点 | 现状缺陷 | 缺什么 |
|--------------|----------|--------|
| 「需求/任务/agent/skill/记忆 解除耦合，靠数据库管理，灵活移交」 | 六表只覆盖 agents/messages/tasks/progress/archives/stats；**需求、skill、记忆不是一等实体**；任务按 assignee 名字字符串引用，无法「声明位置编号即协作」 | **实体解耦 + 位置寻址** |
| 「只需要声明数据库位置编号，就能跟其他 agent 协作」 | 没有统一地址注册表；移交靠接力卡里手写名字 | **loc:// 地址注册** |
| 「要有层级结构，父子关系，共享权限和空间」 | `agents.group_id`、`tasks.depends_on` 是**平铺字符串**，无父子层级；无「空间」概念 | **层级空间** |
| 「哪个 AI 访问哪个任务位置、哪个记忆位置，需要规则声明」 | 无任何访问控制；谁都能读写任何数据 | **权限空间（ACL）** |
| 「不是只有数据库，而是一套运作机制」 | 数据层只是 CRUD，无强制规则、无寻址、无权限校验 | **运作引擎** |
| 「多个对同一个东西修改时如何确保版本、issue 合并不冲突」 | ISSUE_MANAGEMENT 有模块/agent 双版本**概念**，但**无落库的版本实体、无冲突检测、无合并整合机制** | **版本整合 + 小组提交** |

**一句话**：DATA_ARCHITECTURE 回答了「数据放哪」；本文件回答「**数据怎么被有序地访问、交接、协同修改、整合**」。

---

## 二、运作机制总体设计（协作引擎）

```
┌────────────────────────────────────────────────────────────────┐
│  人类 / 架构·总师（俯瞰：按空间/版本看板做决策，不碰原始库）       │
└───────────────────────────┬────────────────────────────────────┘
┌───────────────────────────▼────────────────────────────────────┐
│          collab 协作运作引擎（local-agent/collab/）              │
│                                                               │
│  ① 实体注册表（loc:// 地址）   需求/任务/agent/skill/记忆        │
│  ② 层级空间（spaces 父子树）   命名空间 + 归属关系              │
│  ③ 权限空间（ACL）           谁可访问哪个位置（任务/记忆）        │
│  ④ 版本整合（versioned）      模块粒度修改 + 冲突检测 + 合并      │
│  ⑤ 小组提交（group commit）  小组统一向上整合交付               │
└───────────────────────────┬────────────────────────────────────┘
┌───────────────────────────▼────────────────────────────────────┐
│          data 数据层（DATA_ARCHITECTURE 六表 + 本次扩展表）       │
│  entities / spaces / acl / versions / commits / skills         │
│  memory / requirements（新增一等实体）                          │
└───────────────────────────┬────────────────────────────────────┘
                            │ DB_BACKEND 切换
              SQLite(默认) / PostgreSQL(2500级) / Redis(消息缓存)
```

### 五个机制支柱

| 支柱 | 承载 | 解决的用户诉求 |
|------|------|----------------|
| **① 实体解耦 + 位置寻址** | `entities` 统一注册表 + `loc://` 地址 | 需求/任务/agent/skill/记忆解耦、灵活移交、声明编号即协作 |
| **② 层级结构** | `spaces` 空间表 + 父子关系 | 父子层级、归属、嵌套小组 |
| **③ 权限空间** | `acl` 访问控制表 | 哪个 AI 访问哪个任务/记忆位置，规则声明 |
| **④ 版本整合** | `versions` 版本实体 + 冲突检测 + `commits` 合并 | 多 agent 改同一东西不冲突、issue 合并不失效 |
| **⑤ 小组提交** | `commits` 小组整合提交 | 以小组为单位向上统一交付 |

---

## 三、① 实体解耦 + 位置寻址（Entities Registry）

### loc:// 地址协议

所有协作对象（需求/任务/agent/skill/记忆/空间/归档）都通过一个**统一地址**被引用：

```
loc://<entity_type>.<namespace>/<id>[@<version>]
      │              │           │        └ 可选版本（指向某版本快照）
      │              │           └ 对象 id（实体实例）
      │              └ 命名空间/空间（归属域，如 team-A / g1）
      └ 实体类型：req|task|agent|skill|mem|space|archive
```

示例：
```
loc://task.g1/t1               # 小组 g1 下的任务 t1
loc://agent.g1/agent_a         # 小组 g1 的 agent agent_a
loc://mem.team-A/login_ctx     # team-A 空间的记忆 login_ctx
loc://req.v2/login_feature@2   # 需求 login_feature 的第 2 版
```

### entities 注册表

```sql
CREATE TABLE entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    etype         TEXT NOT NULL,            -- req|task|agent|skill|mem|space|archive
    namespace     TEXT DEFAULT '',          -- 归属空间
    entity_id     TEXT NOT NULL,            -- 对象 id（空间内唯一）
    loc           TEXT NOT NULL,            -- loc:// 规范地址（唯一索引）
    parent_loc    TEXT DEFAULT '',          -- 父实体地址（层级归属）
    acl_key       TEXT DEFAULT '',          -- 权限键（关联 acl 规则，''=公开）
    payload       TEXT DEFAULT '{}',        -- 实体内容（JSON）
    version       INTEGER DEFAULT 1,        -- 当前版本号
    owner         TEXT DEFAULT '',          -- 创建者/当前持有者（可移交）
    status        TEXT DEFAULT 'active',    -- active/archived/merged
    created_at    TEXT,
    updated_at    TEXT,
    UNIQUE(loc)
);
```

**灵活移交**：只改 `owner` 字段即可把某实体的「当前持有权」交给其他 agent——协作双方只需声明 `loc://` 编号，不用把内容拷来拷去。交接写入 `progress` 留痕。

---

## 四、② 层级结构（Spaces 父子树）

`spaces` 表承载命名空间树，形成「根空间 → 小组 → 子小组 → …」的父子层级：

```sql
CREATE TABLE spaces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    space_id    TEXT NOT NULL,          -- 空间 id
    parent_id   TEXT DEFAULT '',        -- 父空间 id（''=根空间）
    name        TEXT DEFAULT '',
    kind        TEXT DEFAULT 'group',   -- root/group/team/area
    loc         TEXT NOT NULL,          -- loc://space.<space_id>
    owner       TEXT DEFAULT '',
    created_at  TEXT,
    UNIQUE(space_id)
);
```

- **父子归属**：`parent_id` 形成树；子空间默认继承父空间可访问的实体，也可显式覆盖。
- **共享空间**：多个 agent / 小组可被授权访问同一空间（见 ACL），实现「共享权限和空间」。

---

## 五、③ 权限空间（ACL 访问控制）

`acl` 表声明「**哪个 AI / 哪个小组，可访问哪个位置，读还是写**」：

```sql
CREATE TABLE acl (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    principal  TEXT NOT NULL,          -- 主体：agent_id 或 group/space 名
    ptype      TEXT DEFAULT 'agent',   -- agent|group|role|public
    loc_pattern TEXT NOT NULL,         -- 位置匹配模式：loc://task.g1/* 或 loc://mem.*/*
    access     TEXT DEFAULT 'r',       -- r|w|rw|none
    created_at TEXT
);
```

**运作规则（强制，由 collab 引擎校验）**：
1. `access='none'` / 无匹配规则 → **拒绝访问**（读都不行）。
2. `ptype='public'` 且 `access='rw'` → 全公开（共享空间用）。
3. 主体自身创建的实体默认 `owner` 有 `rw`；协作者需被显式授权。
4. 写操作（`update_entity` / `commit` / `handover`）必须校验主体 `w` 权限。
5. 规则按 `principal + loc_pattern` 最具体优先；`*` 为通配符。

> 例：`(agent_a, group, loc://task.g1/*, rw)` 表示 agent_a 能读写 g1 小组全部任务位置；
> `(any, public, loc://mem.shared/*, r)` 表示任何 AI 可读共享记忆。

---

## 六、④ 版本整合 + ⑤ 小组提交

这是「多 agent 改同一东西不冲突、issue 合并不失效」的核心机制。

### versions 版本实体

每个可被多 agent 修改的实体（任务/需求/归档/skill/记忆）都可带版本：

```sql
CREATE TABLE versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_loc TEXT NOT NULL,          -- 被版本的实体 loc
    vno        INTEGER NOT NULL,       -- 主线 1..n；冲突提案用负数编号（-1,-2,…），不推进主线
    payload    TEXT DEFAULT '{}',      -- 该版本快照内容
    author     TEXT DEFAULT '',        -- 谁提交的这版
    branch     TEXT DEFAULT 'main',    -- 分支（多 agent 并行修改用小组分支）
    parent_vno INTEGER DEFAULT 0,      -- 基于哪一版（冲突检测关键）
    status     TEXT DEFAULT 'open',    -- open/merged/conflict/discarded
    created_at TEXT,
    UNIQUE(entity_loc, branch, vno)    -- 含 branch：不同分支各自的 vno 空间互不挤占
);
```

**多 agent 并发修改如何不冲突**：
1. 每个 agent 修改前 **checkout** 当前 `version`；
2. 各自在自己的小组 **branch** 上写新版本（`parent_vno = 所基于版本`）；
3. 提交时**冲突检测**：若 `parent_vno != 主干最新版本` → 判定 `conflict`，提示基于最新版 rebase，不盲目覆盖；
4. `commits` 负责把多个小组分支**整合**成主线（见下）。

#### 写路径原子性（写时状态中介 · 差距 D 修复）

冲突检测的**有效性**依赖「读 latest → 写新版本」是一个原子步骤——否则两个 agent 都读到
`latest=3`、都写 `vno=4`，冲突检测形同虚设。落地三件套：

1. **事务包裹**：`update_entity_with_base()` / `update_entity()` 的读-改-写整体进
   `db.transaction()`（sqlite 下最外层用 `BEGIN IMMEDIATE` 立即取写锁）；
2. **冲突提案独立编号**：冲突版本写**负数 vno**（`add_conflict_version`），
   `latest_version()` 只认 `vno>0 AND status!='conflict'` 的主线——
   **一次冲突不会把该实体永久卡死**，也不抬高主线基准；
3. **受理闸门直查**：`conflicts()` 按 `status='conflict'` 直查（带 `idx_versions_status`），
   不走 `versions_of` 的 `vno DESC LIMIT 50` 窗口——主线版本 ≥50 后负数提案不会被截掉而静默丢失。

旧库（旧唯一键 `(entity_loc, vno)`、冲突占正数 vno）由 `data/migrate.py` 幂等迁移，
并**下沉到 `schema.init_schema()`**：全仓入口只要走建表就都会升级既有库，
不依赖各自记得先调 `admin.init()`（详见 ADR-0013）。

**热路径纪律（复评 🔴5）**：`init_schema()` 是读热路径的必经点（webui 每请求 /
gid 每操作 / sentinel / dispatcher…），**迁移检查必须只读**：
`_run_migrations()` 带**健康库快路径**——M1/M2 标记均已应用即直接返回，
**不开写事务、不跑 DDL**；只在确有 pending 时才开 `db.transaction()` 取写锁。
否则已迁移完的库也会每次抢 `BEGIN IMMEDIATE`，把只读语义的操作串行化、
他人持写锁时被阻塞到 `busy_timeout` 抛 `database is locked`。
`data-cli migrate --dry-run` 只报告待迁移项、不落写。
由 `test_data_layer.sh` 第 9 组 + feature-verify `collab/写时状态中介` Then-5 双处锁死。

**远程后端（PG/MySQL）写路径收口（复评 🔴 返工）**：`db.execute()` 在远程后端每次都在
新连接上另开事务，**无法复用当前事务连接**（真 PG 17.11 实测：事务内 `db.execute(INSERT)`
+ raise → 残留 1 行）。本轮**不实现完整 PG 写路径**（非默认后端、CI 全走 sqlite），
而是**显式收口**——远程后端在事务内调 `db.execute()` / 嵌套 `db.transaction()` **直接
fail-loud 抛错**（拒绝静默半工作），事务内一律走 `tx.execute()`；文档「无缝切换」表述
一并修正为「接口层已抽象、**写路径闭环为跟踪项**」（ADR-0013 跟踪项）。

### commits 小组整合提交

小组内部/跨小组的修改统一**以小组为单位向上整合交付**：

```sql
CREATE TABLE commits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id   TEXT NOT NULL,          -- commit-<uuid>
    group_loc   TEXT DEFAULT '',        -- 提交的小组/空间
    scope       TEXT DEFAULT '',        -- 提交涉及的最小模块范围（模块粒度拆分）
    entity_locs TEXT DEFAULT '[]',      -- 本提交包含的实体地址清单
    base_versions TEXT DEFAULT '[]',    -- 各实体的父版本（合并依据）
    status      TEXT DEFAULT 'open',    -- open/merged/conflict
    submitter   TEXT DEFAULT '',
    created_at  TEXT,
    UNIQUE(commit_id)
);
```

**小组提交流程**：
1. 小组长把本组完成的实体版本，打一个 `commit`（声明 scope 为**最小模块粒度**，避免跨模块大提交）；
2. 提交前校验：本 commit 内各实体**基于最新主线版本**，否则标 `conflict` 打回（对应回转协议）；
3. 提交后由「架构·对齐/评审」做冲突检测 + 合并；合并成功标 `merged`；
4. 主线版本号随每个 commit 递增，保证「**每个 Issue 只落一个最小模块粒度**」，与 ISSUE_MANAGEMENT 双版本线对齐。

**与 ISSUE_MANAGEMENT 的衔接**：commit 的 `scope` = module 维度、`entity` = agent 维度，天然对应「模块版本 + agent 版本」双线；合并按 commit 顺序（先到先合），冲突即打回 rebase。

---

## 七、新增一等实体（skill / memory / requirements）

### requirements 需求

```sql
CREATE TABLE requirements (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    req_id     TEXT NOT NULL,
    title      TEXT DEFAULT '',
    space      TEXT DEFAULT '',
    detail     TEXT DEFAULT '{}',      -- 澄清后的结构化需求
    status     TEXT DEFAULT 'open',    -- open/refined/assigned/closed
    parent_req TEXT DEFAULT '',        -- 需求父子拆分
    owner      TEXT DEFAULT '',
    created_at TEXT,
    UNIQUE(req_id)
);
```

### skills

```sql
CREATE TABLE skills (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id   TEXT NOT NULL,
    name       TEXT DEFAULT '',
    space      TEXT DEFAULT '',
    desc       TEXT DEFAULT '',
    playbook   TEXT DEFAULT '',        -- SKILL.md 内容/路径
    version    INTEGER DEFAULT 1,
    owner      TEXT DEFAULT '',
    created_at TEXT,
    UNIQUE(skill_id)
);
```

### memory 记忆

记忆与任务/需求解耦，按空间共享，受 ACL 管控：

```sql
CREATE TABLE memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mem_id     TEXT NOT NULL,
    space      TEXT DEFAULT '',
    kind       TEXT DEFAULT 'context', -- context/decision/log/learned
    content    TEXT DEFAULT '',
    owner      TEXT DEFAULT '',
    version    INTEGER DEFAULT 1,
    created_at TEXT,
    UNIQUE(mem_id)
);
```

> 记忆通过 `loc://mem.<space>/<id>` 被其他 agent 读取；写入受 ACL 约束；`owner` 可移交。
> 这样「哪个 AI 访问哪个记忆位置」由 ACL 声明，记忆与 agent 解耦、可在空间内共享。

---

## 八、collab 运作引擎接口契约

`local-agent/collab/engine.py` 提供统一入口（数据管理员角色负责执行，遵循 DATA_ARCHITECTURE 规则）：

```python
# ① 实体注册 / 寻址
register_entity(etype, namespace, entity_id, payload, parent_loc, owner, acl_key)
resolve(loc)                          # 按 loc 解析实体
handover(loc, new_owner, principal)   # 灵活移交（校验权限 + 留痕）

# ② 层级空间
create_space(space_id, parent_id, name, owner)
space_tree(root=None)                 # 父子树俯视图

# ③ 权限空间
grant(principal, ptype, loc_pattern, access, by)
check_access(principal, loc, access)  # 访问校验（强制调用）
revoke(principal, loc_pattern, by)

# ④ 版本
checkout(loc, principal)              # 返回当前版本 + 基线 vno
update_entity(loc, payload, principal, branch='main')  # 写新版本（冲突检测，事务内）
update_entity_with_base(loc, payload, base_vno, ...)  # 带基线写入（并发冲突检测核心）
versions_of(loc)                      # 版本历史

# ⑤ 小组提交
commit(group_loc, scope, entity_locs, base_versions, submitter)
merge_commit(commit_id)               # 合并进主线（冲突检测 + 标 merged）
conflicts()                           # 待处理冲突清单
```

---

## 九、可行性验证

| 关键假设 | 验证方式 | 结论 |
|----------|----------|------|
| loc:// 地址可唯一寻址 + 灵活移交 | collab 单测：注册→resolve→handover | ✅ 通过 |
| 空间父子树 + 共享授权 | create_space + grant + tree | ✅ 通过 |
| ACL 权限强制（未授权拒绝读写） | check_access 单测（rw/none/public） | ✅ 通过 |
| 多 agent 并发修改冲突检测 | 基于旧版本提交 → 标 conflict | ✅ 通过 |
| 小组提交整合 + 最小模块粒度 | commit + merge_commit | ✅ 通过 |
| 不破坏既有六表数据层 | test_data_layer.sh + 新 collab 测试 | ✅ 全绿 |
| 并发写不产生重复 vno（写时状态中介） | 16 线程同基提交 + feature-verify `collab/写时状态中介` | ✅ ok=1 / conflict=15 / err=0，主线 vno 无重复 |
| 旧库经任意建表入口自动升级 | 造旧库（旧唯一键+冲突占正数）→ 只走 `schema.init_schema()` | ✅ 约束升级 / 主线可写 / 冲突不丢 |
| 健康库读热路径不被写锁阻塞 | 另连接持写锁 → 纯读 gid / `init_schema()` / `migrate()` | ✅ 0.00s 返回（快路径不开写事务） |

**测试信号灯**：新增 `local-agent/tests/test_collab.sh`，未通过即红灯阻塞不放行。

---

## 十、与既有规则/机制的衔接

| 既有机制 | 与 collab 的关系 |
|----------|------------------|
| DATA_ARCHITECTURE 六表 | collab 在其上**新增扩展表**（entities/spaces/acl/versions/commits/skills/memory/requirements），复用 db/repository 后端抽象 |
| 数据管理员角色 | collab 引擎由「架构·数据管理员」统一执行，遵循「数据先行/统一口径/可回溯/可回放/唯一负责」五规则 |
| ISSUE_MANAGEMENT 双版本 | commit.scope=模块线、entity=agent 线，合并按 commit 顺序，冲突打回 rebase |
| 分形多小组（fractal） | 小组提交机制让多小组各自 commit 后统一向上整合 |
| 回转/打断协议 | 冲突即 `[回转]` 打回基于最新版 rebase；中断凭实体 version + 空间位置续跑 |

---

## 十一、落地清单

| 产物 | 位置 |
|------|------|
| 本设计文档 | `docs/COLLAB_ENGINE.md` |
| schema 扩展（8 张新表） | `local-agent/data/schema.py` |
| collab 运作引擎 | `local-agent/collab/engine.py` |
| collab 数据访问 | `local-agent/collab/store.py` |
| collab 测试 | `local-agent/tests/test_collab.sh` |
| 规则落地 | `AGENTS.md` / 本文档 |

> 一句话总结：**数据库是仓库，collab 是仓库的「管理制度 + 门禁 + 物流」**——
> loc:// 让东西有固定地址，spaces 让东西有归属层级，ACL 管谁能动哪个位置，
> versions+commits 让多人改同一件东西有序、不冲突、以小组为单位整合。
