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


# ================= gid_registry（全局唯一编号注册表） =================

def registry_get(etype, biz_key):
    """查某业务 key 已登记的全局唯一 gid；未登记返回 None。"""
    row = db.query_one(
        "SELECT gid FROM gid_registry WHERE etype=? AND biz_key=?",
        (etype, biz_key),
    )
    return row["gid"] if row else None


def registry_set(etype, biz_key, gid):
    """登记某业务 key 的全局唯一 gid（幂等 upsert，同 key 同 gid）。"""
    db.execute(
        """
        INSERT INTO gid_registry (etype, biz_key, gid, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(etype, biz_key) DO UPDATE SET gid=excluded.gid
        """,
        (etype, biz_key, gid, db.now_iso()),
    )
    return gid


def registry_lookup_by_gid(gid):
    """按 gid 反查其 etype/biz_key（供精准定位某实体）。"""
    row = db.query_one(
        "SELECT etype, biz_key, gid FROM gid_registry WHERE gid=?", (gid,)
    )
    return dict(row) if row else None


# ================= task_pools（功能域任务池） =================

def upsert_pool(pool_id, domain, parent_pool="", capacity=0, load=0.0, status="active"):
    """登记/更新一个功能域任务池（按任务负载动态伸缩容量）。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO task_pools (pool_id, domain, parent_pool, capacity, load, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pool_id) DO UPDATE SET
            domain=excluded.domain, parent_pool=excluded.parent_pool,
            capacity=excluded.capacity, load=excluded.load, status=excluded.status
        """,
        (pool_id, domain, parent_pool, int(capacity), float(load), status, now),
    )
    return pool_id


def get_pool(pool_id):
    row = db.query_one("SELECT * FROM task_pools WHERE pool_id=?", (pool_id,))
    return dict(row) if row else None


def list_pools(domain=None, status=None):
    sql = "SELECT * FROM task_pools"
    params = []
    conds = []
    if domain:
        conds.append("domain=?")
        params.append(domain)
    if status:
        conds.append("status=?")
        params.append(status)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id"
    return [dict(r) for r in db.query(sql, params)]


def update_pool_capacity(pool_id, capacity):
    db.execute(
        "UPDATE task_pools SET capacity=?, load=? WHERE pool_id=?",
        (int(capacity), float(capacity), pool_id),
    )


def count_pools():
    row = db.query_one("SELECT COUNT(*) AS n FROM task_pools")
    return row["n"] if row else 0


# ================= task_split（任务拆分 / 加派） =================

def add_split(split_id, parent_task, branch_task, agent_id, reason="", submitter="",
              status="open"):
    """登记一次任务拆分/加派（开发中途发现任务过大申报，或初始拆分）。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO task_split (split_id, parent_task, branch_task, agent_id, reason,
                                submitter, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(split_id) DO UPDATE SET
            parent_task=excluded.parent_task, branch_task=excluded.branch_task,
            agent_id=excluded.agent_id, reason=excluded.reason,
            submitter=excluded.submitter, status=excluded.status
        """,
        (split_id, parent_task, branch_task, agent_id, reason, submitter, status, now),
    )
    return split_id


def split_of(parent_task, status="open"):
    """查某父任务的拆分分支记录（按时间升序）。"""
    sql = "SELECT * FROM task_split WHERE parent_task=?"
    params = [parent_task]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id"
    return [dict(r) for r in db.query(sql, params)]


def list_splits(status=None):
    sql = "SELECT * FROM task_split"
    params = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY id"
    return [dict(r) for r in db.query(sql, params)]


def set_split_status(split_id, status):
    db.execute("UPDATE task_split SET status=? WHERE split_id=?", (status, split_id))


# ================= task_prs（任务 PR/Issue 映射） =================

def add_task_pr(pr_id, task_id, agent_id, issue_id="", seq=1, kind="new", status="open"):
    """登记一个任务提交的 PR（每个任务可 1-3 个 PR，各按独立 Issue 处理）。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO task_prs (pr_id, task_id, agent_id, issue_id, seq, kind, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pr_id) DO UPDATE SET
            task_id=excluded.task_id, agent_id=excluded.agent_id,
            issue_id=excluded.issue_id, seq=excluded.seq, kind=excluded.kind,
            status=excluded.status
        """,
        (pr_id, task_id, agent_id, issue_id, int(seq), kind, status, now),
    )
    return pr_id


def prs_for_task(task_id, status=None):
    """某任务的全部 PR（按提交顺序）。"""
    sql = "SELECT * FROM task_prs WHERE task_id=?"
    params = [task_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY seq, id"
    return [dict(r) for r in db.query(sql, params)]


def pr_count_for_task(task_id, status=None):
    """某任务已提交的 PR 数（用于 1-3 上限校验）。"""
    return len(prs_for_task(task_id, status))


def prs_for_agent(agent_id, status=None):
    """某 agent 提交的全部 PR（精准定位某 agent 的工作）。"""
    sql = "SELECT * FROM task_prs WHERE agent_id=?"
    params = [agent_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id"
    return [dict(r) for r in db.query(sql, params)]
# ================= labels（标签管理 · Issue #51） =================

def apply_label(entity, label_key, operator="", value="", action="apply",
                source="direct", note=""):
    """打标/去标/刷值（幂等 UPSERT：同一实体同一标签同一动作覆盖更新）。"""
    label_id = f"lb-{abs(hash(entity + label_key + action)) % 1000000}"
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO labels (label_id, entity, label_key, value, operator,
                            action, source, note, ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity, label_key, action) DO UPDATE SET
            value=excluded.value, operator=excluded.operator,
            source=excluded.source, note=excluded.note, ts=excluded.ts
        """,
        (label_id, entity, label_key, value, operator, action, source, note, now),
    )
    return label_id


def get_labels(entity):
    """某实体的全部标签（按分类可俯瞰）。"""
    rows = db.query(
        "SELECT * FROM labels WHERE entity=? ORDER BY id", (entity,)
    )
    return [dict(r) for r in rows]


def remove_label(entity, label_key, operator=""):
    """去标：写一条 action=remove 覆盖（保留留痕而非物理删除）。"""
    return apply_label(entity, label_key, operator=operator, action="remove",
                       source="direct", note="移除标签")


def list_labels(label_key=None, entity=None):
    """按标签 key / 实体过滤查询标签记录。"""
    sql = "SELECT * FROM labels WHERE 1=1"
    params = []
    if label_key:
        sql += " AND label_key=?"
        params.append(label_key)
    if entity:
        sql += " AND entity=?"
        params.append(entity)
    sql += " ORDER BY id DESC"
    return [dict(r) for r in db.query(sql, params)]


# ================= label_requests（标签提议 · 全员可提·管理员审批） =================

def propose_label(entity, label_key, proposer, reason="", value=""):
    """全员提议：为某实体提议加标签，进入审批队列。"""
    request_id = f"lq-{abs(hash(entity + label_key + proposer)) % 1000000}"
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO label_requests (request_id, entity, label_key, value,
                                    proposer, reason, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (request_id, entity, label_key, value, proposer, reason, now, now),
    )
    return request_id


def list_label_requests(status="pending"):
    """查看标签提议队列（默认 pending，管理员审批）。"""
    sql = "SELECT * FROM label_requests WHERE 1=1"
    params = []
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY id"
    return [dict(r) for r in db.query(sql, params)]


def review_label_request(request_id, reviewer, decision="approved", note=""):
    """管理员审批标签提议（approved→自动落标 / rejected→拒绝）。"""
    now = db.now_iso()
    db.execute(
        """
        UPDATE label_requests SET status=?, reviewed_by=?, note=?, updated_at=?
        WHERE request_id=?
        """,
        (decision, reviewer, note, now, request_id),
    )
    req = db.query_one(
        "SELECT * FROM label_requests WHERE request_id=?", (request_id,)
    )
    if req is None:
        return {"ok": False, "reason": "提议不存在"}
    if decision == "approved":
        apply_label(req["entity"], req["label_key"], operator=reviewer,
                    value=req["value"], source="proposal",
                    note=req["reason"] or "管理员审批通过")
    return {"ok": True, "request_id": request_id, "status": decision,
            "entity": req["entity"], "label_key": req["label_key"]}


# ================= MCP 管线：程序化进度/状态查询（不靠 AI 对话） =================

def query_progress(task_id, agent_id=""):
    """统一查询任务/agent 的进度：合并 goal_meters + progress 表，程序化暴露。

    返回 { task_id, goal_total, current, distance, percent, event_count, latest_ts }，
    供任何角色通过 MCP 接口直接获取，不依赖 AI 对话告知。
    """
    meters = db.query(
        "SELECT * FROM goal_meters WHERE task_id=? ORDER BY id DESC LIMIT 1",
        (task_id,),
    )
    meter = dict(meters[0]) if meters else None
    progress_rows = db.query(
        "SELECT COUNT(*) AS n, MAX(ts) AS latest FROM progress WHERE task_id=?",
        (task_id,),
    )
    pinfo = dict(progress_rows[0]) if progress_rows else {}
    goal_total = (meter or {}).get("goal_total") or 0
    current = (meter or {}).get("current") or 0
    percent = round(current / goal_total * 100) if goal_total else None
    return {
        "task_id": task_id,
        "agent_id": (meter or {}).get("agent_id", agent_id),
        "goal_total": goal_total,
        "current": current,
        "distance": max(0, goal_total - current),
        "percent": percent,
        "event_count": pinfo.get("n") or 0,
        "latest_ts": pinfo.get("latest") or (meter or {}).get("ts") or "",
    }


def query_status(entity):
    """统一查询实体状态标签（最近一条 status 类标签 + 全部标签）。"""
    labels = get_labels(entity)
    status_keys = [l for l in labels if l["label_key"] in
                   ("open", "in_progress", "review", "done", "merged",
                    "blocked", "stale", "verified", "invalid")]
    latest = status_keys[-1]["label_key"] if status_keys else ""
    return {
        "entity": entity,
        "status": latest,
        "labels": labels,
    }
