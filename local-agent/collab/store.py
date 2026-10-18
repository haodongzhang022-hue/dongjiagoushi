# -*- coding: utf-8 -*-
"""
collab · 数据访问层（store）
============================
对 collab 引擎所需的全部新表（entities/spaces/acl/versions/commits/
requirements/skills/memory）提供统一 CRUD，屏蔽后端差异（sqlite/pg）。

设计：
  - 复用 data.db 连接与 data.repository 的 JSON 序列化约定；
  - 所有 payload/content 以 JSON 字符串存储，读取按需 json.loads；
  - 每个表一组语义化函数，供 collab/engine.py 调用。
"""
import json

from data import db


def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj


def _loads(s):
    if not s:
        return {}
    if isinstance(s, (dict, list)):
        return s
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        return {}


# ================= entities（实体注册表） =================

def upsert_entity(etype, namespace, entity_id, loc, payload=None, parent_loc="",
                  acl_key="", owner="", status="active", version=1):
    """登记/更新一个实体（loc:// 唯一地址）。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO entities (etype, namespace, entity_id, loc,
                              payload, parent_loc, acl_key, version, owner,
                              status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(loc) DO UPDATE SET
            etype=excluded.etype, namespace=excluded.namespace,
            entity_id=excluded.entity_id, parent_loc=excluded.parent_loc,
            acl_key=excluded.acl_key, payload=excluded.payload,
            version=excluded.version, owner=excluded.owner,
            status=excluded.status, updated_at=excluded.updated_at
        """,
        (etype, namespace, entity_id, loc, _dumps(payload or {}), parent_loc,
         acl_key, version, owner, status, now, now),
    )
    return loc


def get_entity(loc):
    row = db.query_one("SELECT * FROM entities WHERE loc=?", (loc,))
    if row:
        row["payload"] = _loads(row.get("payload"))
    return dict(row) if row else None


def update_entity_payload(loc, payload, version, owner=""):
    """更新实体内容 + 版本号（写新版本后同步主实体指针）。"""
    db.execute(
        "UPDATE entities SET payload=?, version=?, updated_at=? WHERE loc=?",
        (_dumps(payload), version, db.now_iso(), loc),
    )


def set_entity_owner(loc, owner):
    """灵活移交：只改 owner 即完成持有权交接。"""
    db.execute(
        "UPDATE entities SET owner=?, updated_at=? WHERE loc=?",
        (owner, db.now_iso(), loc),
    )


def list_entities(etype=None, namespace=None):
    sql = "SELECT * FROM entities"
    params = []
    conds = []
    if etype:
        conds.append("etype=?")
        params.append(etype)
    if namespace:
        conds.append("namespace=?")
        params.append(namespace)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id"
    rows = db.query(sql, params)
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.get("payload"))
        out.append(d)
    return out


# ================= spaces（层级空间） =================

def upsert_space(space_id, parent_id="", name="", kind="group", owner=""):
    """登记一个空间（父子树节点）。"""
    loc = f"loc://space.{space_id}"
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO spaces (space_id, parent_id, name, kind, loc, owner, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(space_id) DO UPDATE SET
            parent_id=excluded.parent_id, name=excluded.name,
            kind=excluded.kind, owner=excluded.owner
        """,
        (space_id, parent_id, name, kind, loc, owner, now),
    )
    return loc


def get_space(space_id):
    row = db.query_one("SELECT * FROM spaces WHERE space_id=?", (space_id,))
    return dict(row) if row else None


def list_spaces():
    return [dict(r) for r in db.query("SELECT * FROM spaces ORDER BY id")]


def children_of(space_id):
    rows = db.query("SELECT * FROM spaces WHERE parent_id=? ORDER BY id", (space_id,))
    return [dict(r) for r in rows]


# ================= acl（权限空间） =================

def grant(principal, ptype, loc_pattern, access, by=""):
    """授予/覆盖一条访问规则。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO acl (principal, ptype, loc_pattern, access, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(principal, loc_pattern) DO UPDATE SET
            ptype=excluded.ptype, access=excluded.access, created_at=excluded.created_at
        """,
        (principal, ptype, loc_pattern, access, now),
    )
    # 留痕
    db.execute(
        "INSERT INTO progress (agent_id, task_id, event, detail, ts) VALUES (?, '', ?, ?, ?)",
        ("data_admin", "acl_grant",
         _dumps({"principal": principal, "loc": loc_pattern, "access": access, "by": by}),
         now),
    )
    return loc_pattern


def revoke(principal, loc_pattern):
    db.execute("DELETE FROM acl WHERE principal=? AND loc_pattern=?", (principal, loc_pattern))
    return True


def acl_rules():
    return [dict(r) for r in db.query("SELECT * FROM acl ORDER BY id")]


def rules_for(principal):
    """返回某主体的全部规则（含 public）。"""
    rows = db.query(
        "SELECT * FROM acl WHERE principal=? OR ptype='public' ORDER BY id",
        (principal,),
    )
    return [dict(r) for r in rows]


# ================= versions（版本） =================

def add_version(entity_loc, vno, payload, author="", branch="main", parent_vno=0,
                status="open"):
    """新增一个版本快照。"""
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO versions (entity_loc, vno, payload, author, branch, parent_vno,
                              status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entity_loc, vno, _dumps(payload), author, branch, parent_vno, status, now),
    )
    return {"entity_loc": entity_loc, "vno": vno, "status": status}


def latest_version(entity_loc, branch="main"):
    """取某实体某分支的当前**主线有效**版本号（不含 conflict 提案）。

    conflict 版本只是待处理的越权提案，不推进主线，因此不参与取最大。
    """
    row = db.query_one(
        "SELECT MAX(vno) AS v FROM versions "
        "WHERE entity_loc=? AND branch=? AND status!='conflict' AND vno>0",
        (entity_loc, branch),
    )
    return row["v"] if row and row["v"] else 0


def add_conflict_version(entity_loc, payload, author="", branch="main", parent_vno=0):
    """记录一个冲突提案（占用独立负数编号空间，不污染主线 vno）。"""
    row = db.query_one(
        "SELECT MIN(vno) AS v FROM versions WHERE entity_loc=? AND branch=? AND vno<0",
        (entity_loc, branch),
    )
    vno = (row["v"] - 1) if row and row["v"] else -1
    return add_version(entity_loc, vno, payload, author=author, branch=branch,
                       parent_vno=parent_vno, status="conflict")


def get_version(entity_loc, vno, branch="main"):
    """取某分支下的指定版本（约束含 branch 后，vno 单值不再唯一）。"""
    row = db.query_one(
        "SELECT * FROM versions WHERE entity_loc=? AND vno=? AND branch=?",
        (entity_loc, vno, branch))
    if row:
        row["payload"] = _loads(row.get("payload"))
    return dict(row) if row else None


def set_version_status(entity_loc, vno, status, branch="main"):
    """改某分支下指定版本的状态（不带 branch 会误改其他分支的同号版本）。"""
    db.execute(
        "UPDATE versions SET status=? WHERE entity_loc=? AND vno=? AND branch=?",
        (status, entity_loc, vno, branch))


def conflict_versions(entity_loc=None):
    """按 status 直查全部冲突提案（不受 vno 排序窗口影响）。"""
    sql = "SELECT * FROM versions WHERE status='conflict'"
    params = ()
    if entity_loc:
        sql += " AND entity_loc=?"
        params = (entity_loc,)
    sql += " ORDER BY entity_loc, vno DESC"
    out = []
    for r in db.query(sql, params):
        d = dict(r)
        d["payload"] = _loads(d.get("payload"))
        out.append(d)
    return out


def versions_of(entity_loc, limit=50):
    rows = db.query(
        "SELECT * FROM versions WHERE entity_loc=? ORDER BY vno DESC LIMIT ?",
        (entity_loc, limit),
    )
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.get("payload"))
        out.append(d)
    return out


# ================= commits（小组提交） =================

def add_commit(commit_id, group_loc, scope, entity_locs, base_versions, submitter,
               status="open"):
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO commits (commit_id, group_loc, scope, entity_locs, base_versions,
                             status, submitter, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (commit_id, group_loc, scope, _dumps(entity_locs), _dumps(base_versions),
         status, submitter, now),
    )
    return commit_id


def get_commit(commit_id):
    row = db.query_one("SELECT * FROM commits WHERE commit_id=?", (commit_id,))
    if row:
        row["entity_locs"] = _loads(row.get("entity_locs"))
        row["base_versions"] = _loads(row.get("base_versions"))
    return dict(row) if row else None


def set_commit_status(commit_id, status):
    db.execute("UPDATE commits SET status=? WHERE commit_id=?", (status, commit_id))


def commits(status=None, group_loc=None):
    sql = "SELECT * FROM commits"
    params = []
    conds = []
    if status:
        conds.append("status=?")
        params.append(status)
    if group_loc:
        conds.append("group_loc=?")
        params.append(group_loc)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id"
    rows = db.query(sql, params)
    out = []
    for r in rows:
        d = dict(r)
        d["entity_locs"] = _loads(d.get("entity_locs"))
        d["base_versions"] = _loads(d.get("base_versions"))
        out.append(d)
    return out


# ================= requirements（需求） =================

def upsert_req(req_id, title="", space="", detail=None, status="open",
               parent_req="", owner=""):
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO requirements (req_id, title, space, detail, status, parent_req,
                                  owner, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(req_id) DO UPDATE SET
            title=excluded.title, space=excluded.space, detail=excluded.detail,
            status=excluded.status, parent_req=excluded.parent_req,
            owner=excluded.owner
        """,
        (req_id, title, space, _dumps(detail or {}), status, parent_req, owner, now),
    )
    return req_id


def get_req(req_id):
    row = db.query_one("SELECT * FROM requirements WHERE req_id=?", (req_id,))
    if row:
        row["detail"] = _loads(row.get("detail"))
    return dict(row) if row else None


# ================= skills =================

def upsert_skill(skill_id, name="", space="", desc="", playbook="", owner="", version=1):
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO skills (skill_id, name, space, desc, playbook, version, owner, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(skill_id) DO UPDATE SET
            name=excluded.name, space=excluded.space, desc=excluded.desc,
            playbook=excluded.playbook, version=excluded.version, owner=excluded.owner
        """,
        (skill_id, name, space, desc, playbook, version, owner, now),
    )
    return skill_id


def get_skill(skill_id):
    row = db.query_one("SELECT * FROM skills WHERE skill_id=?", (skill_id,))
    return dict(row) if row else None


# ================= memory（记忆） =================

def upsert_memory(mem_id, space="", kind="context", content="", owner="", version=1):
    now = db.now_iso()
    db.execute(
        """
        INSERT INTO memory (mem_id, space, kind, content, owner, version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(mem_id) DO UPDATE SET
            space=excluded.space, kind=excluded.kind, content=excluded.content,
            owner=excluded.owner, version=excluded.version
        """,
        (mem_id, space, kind, content, owner, version, now),
    )
    return mem_id


def get_memory(mem_id):
    row = db.query_one("SELECT * FROM memory WHERE mem_id=?", (mem_id,))
    return dict(row) if row else None


def list_memory(space=None, kind=None):
    sql = "SELECT * FROM memory"
    params = []
    conds = []
    if space:
        conds.append("space=?")
        params.append(space)
    if kind:
        conds.append("kind=?")
        params.append(kind)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id"
    return [dict(r) for r in db.query(sql, params)]
