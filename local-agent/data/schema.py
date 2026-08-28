# -*- coding: utf-8 -*-
"""
数据管理层 · 数据表结构（schema）
================================
定义本仓库**数据库承载**所需的全部数据表。覆盖四大块（对应 2500 并发 agent
协作所需的信息互通与持久化）：

  | 表            | 承载内容                       | 用途 |
  |---------------|--------------------------------|------|
  | agents        | agent 档案（角色/小组/状态）    | 内容存档：每个并发 agent 的可寻址档案 |
  | messages      | agent 间消息管线（队列）        | 消息互通：发布/订阅/定向投递，可追踪可回放 |
  | tasks         | 任务分解与状态流转              | 任务存储：谁负责、依赖、进度 |
  | progress      | 进度事件流水                   | 进度统计：每个 agent/任务的状态变化 |
  | archives      | 协作产出内容存档               | 内容存档：里程碑/决策/交付物归档 |
  | stats         | 聚合指标快照                   | 进度统计：并发度/队列积压/活跃数等 |

表结构在 SQLite 与 PostgreSQL / MySQL 上保持一致（类型用通用类型，
SQLite 会宽松兼容），同一套 schema 在不同后端无缝切换。

SQL 方言说明：
  - 自增主键：SQLite `INTEGER PRIMARY KEY AUTOINCREMENT`、PG/MySQL `SERIAL/BIGINT AUTO_INCREMENT`
    为保持通用，主键用 `id INTEGER PRIMARY KEY`（SQLite 自增、PG 序列），
    脚本按后端选择合适 DDL（见 init_schema）。
  - TEXT 类型各库通用；布尔用 INTEGER(0/1) 兼容 SQLite，PG 映射 boolean。
"""
from . import db

# 通用 DDL（SQLite 方言，PG/MySQL 在 init_schema 内做最小改写）
SCHEMA_DDL = [
    # ---- 1. agent 档案（内容存档 / 信息互通定位）----
    """
    CREATE TABLE IF NOT EXISTS agents (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id      TEXT NOT NULL,
        role          TEXT NOT NULL,
        group_id      TEXT DEFAULT '',
        status        TEXT DEFAULT 'in_progress',
        spec          TEXT DEFAULT '{}',          -- 规模/分工声明快照
        created_at    TEXT,
        updated_at    TEXT,
        UNIQUE(agent_id)
    )
    """,
    # ---- 2. 消息管线（消息互通，可追踪可回放）----
    """
    CREATE TABLE IF NOT EXISTS messages (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        msg_id        TEXT,
        topic         TEXT,
        from_agent    TEXT,
        to_agent      TEXT DEFAULT '',
        payload       TEXT DEFAULT '{}',          -- JSON 载荷
        status        TEXT DEFAULT 'queued',      -- queued/consumed
        ts            TEXT,
        consumed_at   TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_msg_topic ON messages(topic)",
    "CREATE INDEX IF NOT EXISTS idx_msg_to ON messages(to_agent)",
    "CREATE INDEX IF NOT EXISTS idx_msg_status ON messages(status)",
    # ---- 3. 任务存储（任务分解与状态流转）----
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id       TEXT NOT NULL,
        title         TEXT DEFAULT '',
        assignee      TEXT DEFAULT '',
        depends_on    TEXT DEFAULT '',
        status        TEXT DEFAULT 'todo',        -- todo/in_progress/done/blocked
        detail        TEXT DEFAULT '',
        created_at    TEXT,
        updated_at    TEXT,
        UNIQUE(task_id)
    )
    """,
    # ---- 4. 进度事件流水（进度统计）----
    """
    CREATE TABLE IF NOT EXISTS progress (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id      TEXT,
        task_id       TEXT DEFAULT '',
        event         TEXT,                        -- created/updated/processed/done
        detail        TEXT DEFAULT '',
        ts            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_progress_agent ON progress(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_progress_task ON progress(task_id)",
    # ---- 5. 内容存档（协作产出归档）----
    """
    CREATE TABLE IF NOT EXISTS archives (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        archive_id    TEXT,
        kind          TEXT DEFAULT 'artifact',     -- artifact/decision/milestone/log
        title         TEXT DEFAULT '',
        content       TEXT DEFAULT '',
        source        TEXT DEFAULT '',
        created_at    TEXT,
        UNIQUE(archive_id)
    )
    """,
    # ---- 6. 聚合指标快照（进度统计 / 看板）----
    """
    CREATE TABLE IF NOT EXISTS stats (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        metric        TEXT,                        -- concurrent_agents/pending_messages/total_tasks...
        value         REAL DEFAULT 0,
        unit          TEXT DEFAULT '',
        ts            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_stats_metric ON stats(metric)",
    # ---- 7. 实体注册表（协作运作机制 · ① 实体解耦 + loc:// 位置寻址）----
    """
    CREATE TABLE IF NOT EXISTS entities (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        etype         TEXT NOT NULL,            -- req|task|agent|skill|mem|space|archive
        namespace     TEXT DEFAULT '',          -- 归属空间
        entity_id     TEXT NOT NULL,            -- 对象 id（空间内唯一）
        loc           TEXT NOT NULL,            -- loc:// 规范地址（唯一索引）
        parent_loc    TEXT DEFAULT '',          -- 父实体地址（层级归属）
        acl_key       TEXT DEFAULT '',          -- 权限键（''=公开）
        payload       TEXT DEFAULT '{}',        -- 实体内容（JSON）
        version       INTEGER DEFAULT 1,        -- 当前版本号
        owner         TEXT DEFAULT '',          -- 当前持有者（可移交）
        status        TEXT DEFAULT 'active',    -- active/archived/merged
        created_at    TEXT,
        updated_at    TEXT,
        UNIQUE(loc)
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_loc ON entities(loc)",
    "CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(etype)",
    # ---- 8. 层级空间（协作运作机制 · ② 父子树 / 共享空间）----
    """
    CREATE TABLE IF NOT EXISTS spaces (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        space_id      TEXT NOT NULL,            -- 空间 id
        parent_id     TEXT DEFAULT '',          -- 父空间 id（''=根）
        name          TEXT DEFAULT '',
        kind          TEXT DEFAULT 'group',     -- root/group/team/area
        loc           TEXT NOT NULL,
        owner         TEXT DEFAULT '',
        created_at    TEXT,
        UNIQUE(space_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_spaces_parent ON spaces(parent_id)",
    # ---- 9. 权限空间（协作运作机制 · ③ ACL 访问控制）----
    """
    CREATE TABLE IF NOT EXISTS acl (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        principal    TEXT NOT NULL,             -- agent_id 或 group/space 名
        ptype        TEXT DEFAULT 'agent',      -- agent|group|role|public
        loc_pattern  TEXT NOT NULL,             -- 位置匹配模式 loc://task.g1/*
        access       TEXT DEFAULT 'r',          -- r|w|rw|none
        created_at   TEXT,
        UNIQUE(principal, loc_pattern)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_acl_principal ON acl(principal)",
    "CREATE INDEX IF NOT EXISTS idx_acl_pattern ON acl(loc_pattern)",
    # ---- 10. 版本实体（协作运作机制 · ④ 版本整合，冲突检测）----
    """
    CREATE TABLE IF NOT EXISTS versions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        entity_loc    TEXT NOT NULL,
        vno           INTEGER NOT NULL,         -- 1..n
        payload       TEXT DEFAULT '{}',
        author        TEXT DEFAULT '',
        branch        TEXT DEFAULT 'main',
        parent_vno    INTEGER DEFAULT 0,        -- 基于哪一版（冲突检测关键）
        status        TEXT DEFAULT 'open',      -- open/merged/conflict/discarded
        created_at    TEXT,
        UNIQUE(entity_loc, vno)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_versions_loc ON versions(entity_loc)",
    "CREATE INDEX IF NOT EXISTS idx_versions_branch ON versions(branch)",
    # ---- 11. 小组整合提交（协作运作机制 · ⑤ 小组提交）----
    """
    CREATE TABLE IF NOT EXISTS commits (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        commit_id     TEXT NOT NULL,            -- commit-<uuid>
        group_loc     TEXT DEFAULT '',          -- 提交的小组/空间
        scope         TEXT DEFAULT '',          -- 最小模块粒度
        entity_locs   TEXT DEFAULT '[]',        -- 实体地址清单
        base_versions TEXT DEFAULT '[]',        -- 各实体父版本
        status        TEXT DEFAULT 'open',      -- open/merged/conflict
        submitter     TEXT DEFAULT '',
        created_at    TEXT,
        UNIQUE(commit_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_commits_group ON commits(group_loc)",
    "CREATE INDEX IF NOT EXISTS idx_commits_status ON commits(status)",
    # ---- 12. 需求（协作运作机制 · 一等实体，与任务/agent 解耦）----
    """
    CREATE TABLE IF NOT EXISTS requirements (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        req_id       TEXT NOT NULL,
        title        TEXT DEFAULT '',
        space        TEXT DEFAULT '',
        detail       TEXT DEFAULT '{}',
        status       TEXT DEFAULT 'open',       -- open/refined/assigned/closed
        parent_req   TEXT DEFAULT '',           -- 需求父子拆分
        owner        TEXT DEFAULT '',
        created_at   TEXT,
        UNIQUE(req_id)
    )
    """,
    # ---- 13. skill（协作运作机制 · 一等实体，与 agent 解耦可共享）----
    """
    CREATE TABLE IF NOT EXISTS skills (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id     TEXT NOT NULL,
        name         TEXT DEFAULT '',
        space        TEXT DEFAULT '',
        desc         TEXT DEFAULT '',
        playbook     TEXT DEFAULT '',
        version      INTEGER DEFAULT 1,
        owner        TEXT DEFAULT '',
        created_at   TEXT,
        UNIQUE(skill_id)
    )
    """,
    # ---- 14. 记忆（协作运作机制 · 一等实体，按空间共享受 ACL 管控）----
    """
    CREATE TABLE IF NOT EXISTS memory (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        mem_id       TEXT NOT NULL,
        space        TEXT DEFAULT '',
        kind         TEXT DEFAULT 'context',    -- context/decision/log/learned
        content      TEXT DEFAULT '',
        owner        TEXT DEFAULT '',
        version      INTEGER DEFAULT 1,
        created_at   TEXT,
        UNIQUE(mem_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_space ON memory(space)",
    # ---- 15. 目标进度尺（防无效努力 · 量化距离到目标的刻度，供监控哨兵判定收敛/停滞）----
    """
    CREATE TABLE IF NOT EXISTS goal_meters (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        meter_id      TEXT NOT NULL,            -- 目标刻度 id（如 g-<task_id>）
        task_id       TEXT DEFAULT '',          -- 关联任务
        agent_id      TEXT DEFAULT '',          -- 正在推进该目标的角色
        target        TEXT DEFAULT '',          -- 目标描述（验收标准 / 北极星）
        goal_total    REAL DEFAULT 0,           -- 目标总量（0..goal_total，距离=goal_total-current）
        current       REAL DEFAULT 0,           -- 当前已达量（向目标收敛的进度刻度）
        distance      REAL DEFAULT 0,           -- 距目标距离 = goal_total - current（越小越近）
        delta         REAL DEFAULT 0,           -- 本次相对上次的进展（正=推进，0=停滞，负=回退/横跳）
        note          TEXT DEFAULT '',          -- 说明（做了什么）
        ts            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_goal_task ON goal_meters(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_goal_agent ON goal_meters(agent_id)",
    # ---- 16. 监控哨兵动作（防无效努力 · 打断/重规划/上报/调整 留痕）----
    """
    CREATE TABLE IF NOT EXISTS sentinel_actions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        action_id     TEXT NOT NULL,            -- 动作 id（interrupt-<uuid> / escalate-<uuid>）
        task_id       TEXT DEFAULT '',
        agent_id      TEXT DEFAULT '',          -- 被打断的角色
        level         INTEGER DEFAULT 1,        -- 触发级别：1=打断+重规划 / 2=上报架构师助理讨论局部调整
        reason        TEXT DEFAULT '',          -- 触发原因（stagnation/oscillation/repeated_error）
        detail        TEXT DEFAULT '{}',        -- 检测详情（距离序列 / 判定参数）
        action        TEXT DEFAULT '',          -- 处置动作描述
        ts            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sentinel_task ON sentinel_actions(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_sentinel_level ON sentinel_actions(level)",
    # ---- 17. 全局唯一编号注册表（gid · 全局唯一、稳定寻址、二次触发同一实体）----
    """
    CREATE TABLE IF NOT EXISTS gid_registry (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        etype         TEXT NOT NULL,            -- agent|task|pr|issue|group|pool|meter
        biz_key       TEXT NOT NULL,            -- 业务 key（稳定名/标题/功能域），同一 key 取同一 gid
        gid           TEXT NOT NULL,            -- 全局唯一 ID（ag-/tk-/pr-/...前缀）
        created_at    TEXT,
        UNIQUE(etype, biz_key),
        UNIQUE(gid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_gid_type_key ON gid_registry(etype, biz_key)",
    "CREATE INDEX IF NOT EXISTS idx_gid_gid ON gid_registry(gid)",
    # ---- 18. 功能域任务池（pool · 按任务负载动态扩展 agent，非直接固定并发）----
    """
    CREATE TABLE IF NOT EXISTS task_pools (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        pool_id       TEXT NOT NULL,            -- 功能域任务池唯一 id（pl-前缀）
        domain        TEXT NOT NULL,            -- 功能域（登录/结算/报表/...）
        parent_pool   TEXT DEFAULT '',          -- 父池（拆分子池时指向父）
        capacity      INTEGER DEFAULT 0,        -- 当前扩容后的并发容量（随任务负载伸缩）
        load          REAL DEFAULT 0,           -- 当前负载（积压任务数 / 权重）
        status        TEXT DEFAULT 'active',    -- active/draining/closed
        created_at    TEXT,
        UNIQUE(pool_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pool_domain ON task_pools(domain)",
    # ---- 19. 任务拆分 / 加派（小组长整合 · 大任务拆分与开发中途申报加派）----
    """
    CREATE TABLE IF NOT EXISTS task_split (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        split_id      TEXT NOT NULL,            -- 拆分/加派记录 id（sp-前缀）
        parent_task   TEXT NOT NULL,            -- 被拆分的父任务 gid
        branch_task   TEXT NOT NULL,            -- 拆分出的分支任务 gid
        agent_id      TEXT NOT NULL,            -- 负责该分支的 agent gid
        reason        TEXT DEFAULT '',          -- 拆分/加派原因（任务过大/开发中发现过大/申报）
        submitter     TEXT DEFAULT '',          -- 申报方（开发 agent / 小组长）
        status        TEXT DEFAULT 'open',      -- open/aggregated（是否已汇总回小组长）
        created_at    TEXT,
        UNIQUE(split_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_split_parent ON task_split(parent_task)",
    # ---- 20. 任务 PR/Issue 映射（每个角色任务 1-3 PR，各按独立 Issue 处理）----
    """
    CREATE TABLE IF NOT EXISTS task_prs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        pr_id         TEXT NOT NULL,            -- PR 全局唯一 id（pr-前缀）
        task_id       TEXT NOT NULL,            -- 归属任务 gid
        agent_id      TEXT NOT NULL,            -- 提交该 PR 的 agent gid
        issue_id      TEXT DEFAULT '',          -- 对应独立 Issue id（is-前缀）
        seq           INTEGER DEFAULT 1,        -- 第几个 PR（1/2/3）
        kind          TEXT DEFAULT 'new',       -- new=独立新PR / amend=对既有PR修改再提交
        status        TEXT DEFAULT 'open',      -- open/merged/closed
        created_at    TEXT,
        UNIQUE(pr_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_taskprs_task ON task_prs(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_taskprs_agent ON task_prs(agent_id)",
    # ---- 21. 事件路由日志（dispatcher · 事件→路由→派发→守卫拦截 全链路留痕）----
    """
    CREATE TABLE IF NOT EXISTS dispatch (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id      TEXT NOT NULL,            -- 事件唯一 id（ev-前缀，同事件去重键）
        event_type    TEXT DEFAULT '',          -- issue.open/issue.update/rejection/comment/...
        source        TEXT DEFAULT '',          -- 事件源（本仓库/外部适配器名）
        entity        TEXT DEFAULT '',          -- 关联实体 key（issue 标题/任务 gid/驳回 key）
        gid           TEXT DEFAULT '',          -- 全局唯一寻址（task/issue/agent gid）
        matched_rule  TEXT DEFAULT '',          -- 命中的触发规则名
        target_role   TEXT DEFAULT '',          -- 路由目标角色
        target_agent  TEXT DEFAULT '',          -- 派发的目标 agent gid
        status        TEXT DEFAULT 'queued',    -- queued/released/hold/rejected/skipped/dispatched
        gate          TEXT DEFAULT 'auto',      -- auto=自动放行 / hold=人工审核闸门
        dedup_key     TEXT DEFAULT '',          -- 去重键（同 key 只派一次）
        note          TEXT DEFAULT '',          -- 说明（守卫拦截原因/派发说明）
        created_at    TEXT,
        updated_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dispatch_event ON dispatch(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_dispatch_status ON dispatch(status)",
    "CREATE INDEX IF NOT EXISTS idx_dispatch_gid ON dispatch(gid)",
    # ---- 22. 驳回迭代表（rejections · 驳回非终点，进入再次迭代闭环）----
    """
    CREATE TABLE IF NOT EXISTS rejections (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        rejection_id  TEXT NOT NULL,            -- 驳回记录 id（rj-前缀）
        task_id       TEXT NOT NULL,            -- 被驳回的任务 gid
        gid           TEXT NOT NULL,            -- 唯一确定的负责实体 gid（精准路由目标）
        agent_id      TEXT NOT NULL,            -- 负责该任务的 agent gid（按 gid 精准回派）
        reason        TEXT DEFAULT '',          -- 驳回原因（评审 🔴必修 / 测试 🔴阻塞 / 哨兵上报）
        level         TEXT DEFAULT 'must',      -- must/block/other
        iteration     INTEGER DEFAULT 1,        -- 迭代次数（驳回非终点，+1 再回环）
        status        TEXT DEFAULT 'pending',   -- pending/reassigned/reworked/approved/blocked
        assigned_to   TEXT DEFAULT '',          -- 派发的目标 agent gid（改进重提）
        monitor       INTEGER DEFAULT 1,        -- 是否纳入监控（哨兵联动）
        created_at    TEXT,
        updated_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rejection_task ON rejections(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_rejection_gid ON rejections(gid)",
    "CREATE INDEX IF NOT EXISTS idx_rejection_status ON rejections(status)",
    # ---- 23. 外部事件源登记表（security · 秘钥 + IP 白名单，多终端独立授权）----
    """
    CREATE TABLE IF NOT EXISTS external_sources (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        src_id        TEXT NOT NULL,            -- 外部源 id（ext-前缀，全局唯一）
        name          TEXT NOT NULL,            -- 外部源名（local_pc/phone/vm/sandbox/host_upper）
        api_key       TEXT DEFAULT '',          -- 该源独立秘钥（安全：key 认证）
        ip_whitelist  TEXT DEFAULT '',          -- 允许的来源 IP/CIDR（逗号分隔；空=deny-all）
        kind          TEXT DEFAULT 'webhook',   -- webhook/poll/host
        meta          TEXT DEFAULT '{}',        -- 扩展元信息（备注/对接地址）
        enabled       INTEGER DEFAULT 1,        -- 1=启用 / 0=停用
        created_at    TEXT,
        updated_at    TEXT,
        UNIQUE(name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_extsrc_name ON external_sources(name)",
    # ---- 24. 外部源认证审计表（security · 每次认证成功/失败留痕，供面板俯瞰）----
    """
    CREATE TABLE IF NOT EXISTS external_auth (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        auth_id       TEXT NOT NULL,            -- 认证记录 id（au-前缀）
        source_name   TEXT DEFAULT '',          -- 外部源名
        client_ip     TEXT DEFAULT '',          -- 来源 IP
        result        TEXT DEFAULT '',          -- allow=通过 / deny=拦截
        reason        TEXT DEFAULT '',          -- 拦截原因（未登记/停用/秘钥不匹配/IP不在白名单）
        api_key_masked TEXT DEFAULT '',         -- 秘钥打码留痕（不落明文，安全红线）
        created_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_extauth_src ON external_auth(source_name)",
    "CREATE INDEX IF NOT EXISTS idx_extauth_result ON external_auth(result)",
    # ---- 25. 脉冲式信号探测器（probe · 有条件就触发，路由到脚本，不轮询）----
    """
    CREATE TABLE IF NOT EXISTS probe (
        probe_id      TEXT PRIMARY KEY,         -- 探测器 id（prb-前缀 / 稳定寻址，二次注册取回同一）
        name          TEXT DEFAULT '',          -- 探测器名（业务标识）
        event_type    TEXT DEFAULT '',          -- 命中的事件类型（空=任意）
        source        TEXT DEFAULT '',          -- 命中的事件源（空=任意）
        action        TEXT DEFAULT '',          -- 处理器路由配置 JSON（script/handler/dispatch/emit）
        enabled       INTEGER DEFAULT 1,        -- 1=启用 / 0=停用
        priority      INTEGER DEFAULT 0,        -- 匹配优先级（值大先匹配）
        created_at    TEXT,
        updated_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_probe_enabled ON probe(enabled)",
    # ---- 26. 信号触发留痕（probe_firings · 每次触发显式记录，不静默失败）----
    """
    CREATE TABLE IF NOT EXISTS probe_firings (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        firing_id     TEXT NOT NULL,            -- 触发记录 id（pf-前缀）
        probe_id      TEXT DEFAULT '',          -- 命中的探测器 id
        probe_name    TEXT DEFAULT '',          -- 命中的探测器名
        event_id      TEXT DEFAULT '',          -- 触发它的信号/事件 id
        event_type    TEXT DEFAULT '',          -- 信号事件类型
        source        TEXT DEFAULT '',          -- 信号来源
        entity        TEXT DEFAULT '',          -- 关联实体 key
        gid           TEXT DEFAULT '',          -- 关联实体 gid
        matched       INTEGER DEFAULT 1,        -- 是否命中
        ok            INTEGER DEFAULT 1,        -- 触发执行是否成功（0=失败，显式上报不吞）
        note          TEXT DEFAULT '',          -- 触发结果/失败原因
        created_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_probe_firing_probe ON probe_firings(probe_id)",
    "CREATE INDEX IF NOT EXISTS idx_probe_firing_ok ON probe_firings(ok)",
    # ---- 27. 遗漏信号留痕（probe_misses · 无探测器命中的信号显式暴露，不静默吞掉）----
    """
    CREATE TABLE IF NOT EXISTS probe_misses (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        miss_id       TEXT NOT NULL,            -- 遗漏记录 id（pm-前缀）
        event_id      TEXT DEFAULT '',          -- 未被处理的信号 id
        event_type    TEXT DEFAULT '',          -- 信号事件类型
        source        TEXT DEFAULT '',          -- 信号来源
        entity        TEXT DEFAULT '',          -- 关联实体 key
        gid           TEXT DEFAULT '',          -- 关联实体 gid
        note          TEXT DEFAULT '',          -- 说明（遗漏未处理，需安排）
        created_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_probe_miss_type ON probe_misses(event_type)",
    # ---- 28. 缓存命中监控留痕（cache_stats · 全链路缓存优化 Issue #41）----
    # 记录每个 agent × 层的缓存命中/未命中/命中率/节省 token，供「架构·数据管理员」
    # 统一统计与人类俯瞰，量化缓存效果、判定是否有浪费（命中率高=无浪费）。
    """
    CREATE TABLE IF NOT EXISTS cache_stats (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        agent         TEXT NOT NULL,            -- 角色/agent（如 架构·开发）
        layer         TEXT DEFAULT '',          -- llm / shell / orchestrator / node
        cache_hits    INTEGER DEFAULT 0,        -- 命中缓存次数
        cache_misses  INTEGER DEFAULT 0,        -- 未命中次数
        cache_hit_rate REAL DEFAULT 0,          -- 命中率 %
        prefix_chars  INTEGER DEFAULT 0,        -- 复用前缀字符数
        saved_tokens  INTEGER DEFAULT 0,        -- 因命中缓存节省的 token 估算
        req_key       TEXT DEFAULT '',          -- 关联需求/任务 key
        gid           TEXT DEFAULT '',          -- 关联实体 gid
        created_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_cache_stats_agent ON cache_stats(agent)",
    "CREATE INDEX IF NOT EXISTS idx_cache_stats_layer ON cache_stats(layer)",
    # ---- 29. 标签管理（labels · 标签记录，实体打标/查询/审批全链路留痕）----
    """
    CREATE TABLE IF NOT EXISTS labels (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        label_id      TEXT NOT NULL,            -- 标签记录 id（lb-前缀）
        entity        TEXT NOT NULL,            -- 关联实体 key（issue-12 / task gid / pr-x）
        label_key     TEXT NOT NULL,            -- 规范标签 key（in_progress / done / p0..p9...）
        value         TEXT DEFAULT '',          -- 标签值（进度百分比 progress_pct 等）
        operator      TEXT DEFAULT '',          -- 操作者（一线直接打标 / 审批通过落标）
        action        TEXT DEFAULT 'apply',     -- apply=打标 / remove=去标 / refresh=刷值
        source        TEXT DEFAULT 'direct',    -- direct=一线直接 / proposal=提议审批 / auto=事件自动
        note          TEXT DEFAULT '',          -- 说明
        ts            TEXT,
        UNIQUE(entity, label_key, action)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_labels_entity ON labels(entity)",
    "CREATE INDEX IF NOT EXISTS idx_labels_key ON labels(label_key)",
    # ---- 30. 标签提议（label_requests · 全员可提议，标签管理员审批）----
    """
    CREATE TABLE IF NOT EXISTS label_requests (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id    TEXT NOT NULL,            -- 提议 id（lq-前缀）
        entity        TEXT NOT NULL,            -- 目标实体（issue-12 / task gid）
        label_key     TEXT NOT NULL,            -- 提议的规范标签
        value         TEXT DEFAULT '',          -- 提议值
        proposer      TEXT DEFAULT '',          -- 提议方（任何 agent/角色）
        reason        TEXT DEFAULT '',          -- 提议理由
        status        TEXT DEFAULT 'pending',   -- pending/approved/rejected
        reviewed_by   TEXT DEFAULT '',          -- 审批方（数据管理员/标签管理员）
        note          TEXT DEFAULT '',          -- 审批说明
        created_at    TEXT,
        updated_at    TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_lblreq_status ON label_requests(status)",
    "CREATE INDEX IF NOT EXISTS idx_lblreq_entity ON label_requests(entity)",
    # ---- 31. token 消耗记录（token_usage · BI 大屏 token 分析 M2）----
    # 按消息唯一去重（msg_id UNIQUE），method 标记估算(estimate)/真实(real)，
    # 支持按 agent/岗位/对话/项目 四维聚合 + 时间趋势（AC-2）。
    """
    CREATE TABLE IF NOT EXISTS token_usage (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        msg_id        TEXT NOT NULL UNIQUE,     -- 关联消息唯一 id（防重复计算）
        agent_id      TEXT DEFAULT '',          -- 归属 agent
        role          TEXT DEFAULT '',          -- 归属岗位（秘书/产品/开发...）
        topic         TEXT DEFAULT '',          -- 对话/会话标识
        project       TEXT DEFAULT '',          -- 关联项目（issue/task gid）
        token_count   INTEGER DEFAULT 0,        -- token 数
        method        TEXT DEFAULT 'estimate',  -- estimate=估算 / real=真实回传
        ts            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_token_agent ON token_usage(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_token_role ON token_usage(role)",
    "CREATE INDEX IF NOT EXISTS idx_token_project ON token_usage(project)",
    "CREATE INDEX IF NOT EXISTS idx_token_ts ON token_usage(ts)",
    # ---- 32. 代码变化统计（code_changes · BI 大屏代码变化统计 M3）----
    # 按 commit 归集 +/- 行（AC-4），可归集到项目/agent 呈现贡献分布。
    """
    CREATE TABLE IF NOT EXISTS code_changes (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        commit_id     TEXT NOT NULL UNIQUE,     -- 关联 commit id
        agent_id      TEXT DEFAULT '',          -- 归属 agent
        project       TEXT DEFAULT '',          -- 关联项目
        added         INTEGER DEFAULT 0,        -- 新增行数
        deleted       INTEGER DEFAULT 0,        -- 删除行数
        ts            TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_code_agent ON code_changes(agent_id)",
    "CREATE INDEX IF NOT EXISTS idx_code_project ON code_changes(project)",

    # ---- 33. 测试指纹缓存（test_cache · 测试智能优化层 T3 指纹缓存复用）----
    # 记录每个测试脚本在特定源码指纹下最后一次执行结果，命中即跳过重复执行（CPU 归零）。
    # 指纹 = 覆盖源码文件的 git blob hash 摘要（保守可靠，源码一变指纹即变缓存失效）。
    """
    CREATE TABLE IF NOT EXISTS test_cache (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        cache_id      TEXT NOT NULL,            -- 缓存记录 id（tc-前缀）
        script        TEXT NOT NULL,            -- 测试脚本路径
        fingerprint   TEXT NOT NULL,            -- 覆盖源码指纹（blob hash 摘要）
        result        TEXT DEFAULT '{}',        -- 上次执行结果 JSON（exit_code/duration/output）
        status        TEXT DEFAULT 'pass',      -- pass/fail/skip（fail 缓存用于失败重试去重）
        ts            TEXT,                     -- 上次缓存时间
        UNIQUE(script, fingerprint)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_testcache_script ON test_cache(script)",
    "CREATE INDEX IF NOT EXISTS idx_testcache_fp ON test_cache(fingerprint)",
]


def init_schema():
    """初始化全部数据表（幂等，可重复调用）。"""
    for ddl in SCHEMA_DDL:
        db.execute(ddl)
    return list_tables()


def list_tables():
    """列出当前库中已建的表。"""
    if db.is_remote():
        rows = db.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public'"
        )
        return [r["table_name"] for r in rows]
    rows = db.query(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [r["name"] for r in rows]


def table_exists(name):
    return name in list_tables()
