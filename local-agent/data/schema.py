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
