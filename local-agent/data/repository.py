# -*- coding: utf-8 -*-
"""
数据管理层 · 仓储层（repository）
================================
提供各数据表的统一 CRUD 接口，屏蔽后端差异（SQLite / PostgreSQL / MySQL）。
供上层（data.admin 数据管理员 / scale 引擎 / 看板生成）稳定调用。

设计：
  - 每个实体一组函数：agents / messages / tasks / progress / archives / stats；
  - 函数名语义化（upsert / enqueue / consume / add / count / recent...）；
  - 事务：批量写通过 db.transaction() 包裹，保证原子性；
  - 所有 payload/detail 以 JSON 字符串存储，读取时按需 json.loads。
"""
import json

from . import db


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj


# ================= agents（agent 档案） =================

def upsert_agent(agent_id, role, group_id="", status="in_progress", spec=None):
    """登记/更新一个 agent 档案（内容存档 · 信息互通定位）。"""
    now = db.now_iso()
    spec_str = _dumps(spec or {})
    db.execute(
        """
        INSERT INTO agents (agent_id, role, group_id, status, spec, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(agent_id) DO UPDATE SET
            role=excluded.role, group_id=excluded.group_id,
            status=excluded.status, spec=excluded.spec, updated_at=excluded.updated_at
        """,
        (agent_id, role, group_id, status, spec_str, now, now),
    )
    return agent_id


def get_agent(agent_id):
    return db.query_one("SELECT * FROM agents WHERE agent_id=?", (agent_id,))


def update_agent_status(agent_id, status):
    db.execute(
        "UPDATE agents SET status=?, updated_at=? WHERE agent_id=?",
        (status, db.now_iso(), agent_id),
    )


def count_agents():
    row = db.query_one("SELECT COUNT(*) AS n FROM agents")
    return row["n"] if row else 0


def active_agents(status="in_progress"):
    rows = db.query("SELECT * FROM agents WHERE status=?", (status,))
    return [dict(r) for r in rows]


def list_agents():
    return [dict(r) for r in db.query("SELECT * FROM agents ORDER BY id")]


# ================= messages（消息管线） =================

def enqueue_message(topic, payload, from_agent="system", to_agent=""):
    """向消息管线投递一条消息（返回消息行）。"""
    msg_id = f"m{db.now_iso()}_{abs(hash(topic)) % 100000}"
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO messages (msg_id, topic, from_agent, to_agent, payload, status, ts)
        VALUES (?, ?, ?, ?, ?, 'queued', ?)
        """,
        (msg_id, topic, from_agent, to_agent, _dumps(payload), now),
    )
    return {
        "msg_id": msg_id,
        "topic": topic,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "payload": payload,
        "status": "queued",
        "ts": now,
    }


def consume_next(to_agent=None, topic=None):
    """取最早一条未消费消息并标记 consumed（消息管线 FIFO）。"""
    sql = "SELECT * FROM messages WHERE status='queued'"
    params = []
    if to_agent:
        sql += " AND to_agent=?"
        params.append(to_agent)
    if topic:
        sql += " AND topic=?"
        params.append(topic)
    sql += " ORDER BY id LIMIT 1"
    row = db.query_one(sql, params)
    if row is None:
        return None
    db.execute(
        "UPDATE messages SET status='consumed', consumed_at=? WHERE id=?",
        (db.now_iso(), row["id"]),
    )
    row["payload"] = json.loads(row["payload"]) if row.get("payload") else {}
    return dict(row)


def pending_count(to_agent=None, topic=None):
    sql = "SELECT COUNT(*) AS n FROM messages WHERE status='queued'"
    params = []
    if to_agent:
        sql += " AND to_agent=?"
        params.append(to_agent)
    if topic:
        sql += " AND topic=?"
        params.append(topic)
    row = db.query_one(sql, params)
    return row["n"] if row else 0


def replay_topic(topic, limit=100):
    """回放某 topic 的消息（可追踪历史，供审计/复盘）。"""
    rows = db.query(
        "SELECT * FROM messages WHERE topic=? ORDER BY id DESC LIMIT ?",
        (topic, limit),
    )
    return [dict(r) for r in rows]


def fan_out(topics, payload, from_agent="system"):
    """向一组 topic 广播消息，返回投递数。"""
    n = 0
    for t in topics:
        enqueue_message(t, payload, from_agent)
        n += 1
    return n


# ================= tasks（任务存储） =================

def upsert_task(task_id, title="", assignee="", depends_on="", status="todo", detail=""):
    """登记/更新一个任务（任务存储与状态流转）。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO tasks (task_id, title, assignee, depends_on, status, detail, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            title=excluded.title, assignee=excluded.assignee,
            depends_on=excluded.depends_on, status=excluded.status,
            detail=excluded.detail, updated_at=excluded.updated_at
        """,
        (task_id, title, assignee, depends_on, status, _dumps(detail), now, now),
    )
    return task_id


def update_task_status(task_id, status):
    db.execute(
        "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
        (status, db.now_iso(), task_id),
    )


def get_task(task_id):
    row = db.query_one("SELECT * FROM tasks WHERE task_id=?", (task_id,))
    if row and row.get("detail"):
        try:
            row["detail"] = json.loads(row["detail"])
        except Exception:  # noqa: BLE001
            pass
    return dict(row) if row else None


def list_tasks(status=None):
    sql = "SELECT * FROM tasks"
    params = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY id"
    rows = db.query(sql, params)
    return [dict(r) for r in rows]


def count_tasks(status=None):
    sql = "SELECT COUNT(*) AS n FROM tasks"
    params = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    row = db.query_one(sql, params)
    return row["n"] if row else 0


# ================= progress（进度事件流水） =================

def record_progress(agent_id, event, detail="", task_id=""):
    """记录一条进度事件（进度统计的原始流水）。"""
    db.execute(
        "INSERT INTO progress (agent_id, task_id, event, detail, ts) VALUES (?, ?, ?, ?, ?)",
        (agent_id, task_id, event, _dumps(detail), db.now_iso()),
    )


def progress_count(agent_id=None):
    sql = "SELECT COUNT(*) AS n FROM progress"
    params = []
    if agent_id:
        sql += " WHERE agent_id=?"
        params.append(agent_id)
    row = db.query_one(sql, params)
    return row["n"] if row else 0


def recent_progress(limit=50):
    rows = db.query(
        "SELECT * FROM progress ORDER BY id DESC LIMIT ?", (limit,)
    )
    return [dict(r) for r in rows]


# ================= archives（内容存档） =================

def add_archive(archive_id, kind="artifact", title="", content="", source=""):
    """写入一条内容存档（协作产出归档，供 AI/人类回溯）。"""
    db.execute(
        """
        INSERT OR REPLACE INTO archives
            (archive_id, kind, title, content, source, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (archive_id, kind, title, _dumps(content), source, db.now_iso()),
    )
    return archive_id


def get_archive(archive_id):
    row = db.query_one("SELECT * FROM archives WHERE archive_id=?", (archive_id,))
    if row:
        row["content"] = json.loads(row["content"]) if row.get("content") else ""
    return dict(row) if row else None


def list_archives(kind=None, limit=50):
    sql = "SELECT * FROM archives"
    params = []
    if kind:
        sql += " WHERE kind=?"
        params.append(kind)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.query(sql, params)]


def count_archives():
    row = db.query_one("SELECT COUNT(*) AS n FROM archives")
    return row["n"] if row else 0


# ================= stats（聚合指标快照） =================

def record_stat(metric, value, unit=""):
    """记录一个聚合指标快照（进度统计/看板）。"""
    db.execute(
        "INSERT INTO stats (metric, value, unit, ts) VALUES (?, ?, ?, ?)",
        (metric, float(value), unit, db.now_iso()),
    )


def latest_stats():
    """返回每个指标的最新值（metric → value/unit）。"""
    rows = db.query(
        """
        SELECT s.metric, s.value, s.unit FROM stats s
        JOIN (SELECT metric, MAX(id) AS mid FROM stats GROUP BY metric) m
        ON s.id = m.mid
        """
    )
    return {r["metric"]: {"value": r["value"], "unit": r["unit"]} for r in rows}


def stat_history(metric, limit=100):
    rows = db.query(
        "SELECT * FROM stats WHERE metric=? ORDER BY id DESC LIMIT ?",
        (metric, limit),
    )
    return [dict(r) for r in rows]
