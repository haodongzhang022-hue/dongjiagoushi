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
