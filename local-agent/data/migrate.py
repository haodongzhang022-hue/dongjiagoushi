# -*- coding: utf-8 -*-
"""
数据管理层 · 轻量迁移（migrate）
================================
补齐 `schema.py` 只有 `CREATE TABLE IF NOT EXISTS`、**不升级既有库**的缺口。

本迁移针对「差距 D 修复」引入的两处不兼容（旧库上线即坏）：

  M-1 约束迁移：`versions` 唯一键 `(entity_loc, vno)` → `(entity_loc, branch, vno)`。
      sqlite 不支持 ALTER 约束，只能「建新表 → 拷数据 → 换名」。
  M-2 数据迁移：旧代码把冲突提案写成**正数 vno**，修复后 `latest_version`
      会排除它们（`vno>0 AND status!='conflict'`），但行仍占着正数编号，
      主线写 vno 时撞唯一键 → 老库永久坏。迁移把旧冲突行搬到负数编号空间。

设计：**幂等 + 可重放**——重复执行不产生副作用；用 `schema_migrations` 记录已应用版本。
"""
import threading

from . import db

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT
)
"""

M1 = "2026-10-08-01_versions_unique_branch"
M2 = "2026-10-08-02_conflict_vno_to_negative"

# 重入守卫：`migrate()` 缺表时会调 `schema.init_schema()`，而后者末尾又会调回
# `migrate()`（迁移已下沉到 init_schema）。靠本标记挡掉内层重入，避免无限递归。
_state = threading.local()
_LAST = {}


def last_result():
    """本进程最近一次迁移结果（供 admin.init 汇报，不重复执行迁移）。"""
    return dict(_LAST) if _LAST else None


def _applied(version):
    row = db.query_one("SELECT version FROM schema_migrations WHERE version=?", (version,))
    return row is not None


def _mark(version):
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, db.now_iso()),
    )


def _table_exists(name):
    """表是否存在（走 schema 统一口径，避免各处重复探测）。"""
    from . import schema
    return schema.table_exists(name)


def _unique_cols(table):
    """按 PRAGMA 取该表的全部唯一索引列组合（sqlite）。

    不靠 DDL 字符串匹配：把约束写成 `UNIQUE(entity_loc,\n branch, vno)` 之类的
    换行/多空格写法，字符串匹配会误判成「需迁移」，对已正确的库做无谓重建。
    """
    out = []
    for ix in db.query("PRAGMA index_list(%s)" % table):
        if not ix["unique"]:
            continue
        cols = tuple(r["name"] for r in db.query("PRAGMA index_info(%s)" % ix["name"]))
        out.append(cols)
    return out


def needs_m1():
    """唯一键是否还缺 branch 维度（缺则需迁移；无 versions 表则无需迁移）。"""
    if not _table_exists("versions"):
        return False
    return ("entity_loc", "branch", "vno") not in _unique_cols("versions")


def migrate_m1_unique_branch():
    """versions 唯一键补 branch 维度（幂等）。"""
    if not needs_m1():
        return {"migration": M1, "status": "skip"}
    from . import schema
    # 整段包一个事务：中途失败不留 versions_old_mig 残表
    with db.transaction():
        db.execute("ALTER TABLE versions RENAME TO versions_old_mig")
        for ddl in schema.SCHEMA_DDL:
            if "CREATE TABLE IF NOT EXISTS versions " in ddl:
                db.execute(ddl)
                break
        db.execute(
            """
            INSERT INTO versions (id, entity_loc, vno, payload, author, branch,
                                  parent_vno, status, created_at)
            SELECT id, entity_loc, vno, payload, author, COALESCE(branch, 'main'),
                   parent_vno, status, created_at
            FROM versions_old_mig
            """
        )
        db.execute("DROP TABLE versions_old_mig")
        # 换表会连索引一起丢，重建（DROP 之后名字才空出来，顺序不能反）
        for ddl in schema.SCHEMA_DDL:
            if " ON versions(" in ddl:
                db.execute(ddl)
    return {"migration": M1, "status": "applied"}


def migrate_m2_conflict_to_negative():
    """把旧库中占用正数 vno 的冲突行搬到负数编号空间（幂等）。"""
    moved = 0
    rows = db.query(
        "SELECT id, entity_loc, branch, vno FROM versions "
        "WHERE status='conflict' AND vno>0 ORDER BY entity_loc, branch, vno"
    )
    for r in rows:
        loc, br = r["entity_loc"], r["branch"] or "main"
        row = db.query_one(
            "SELECT MIN(vno) AS v FROM versions "
            "WHERE entity_loc=? AND branch=? AND vno<0",
            (loc, br),
        )
        new_vno = (row["v"] - 1) if row and row["v"] is not None else -1
        db.execute("UPDATE versions SET vno=? WHERE id=?", (new_vno, r["id"]))
        moved += 1
    return {"migration": M2, "status": "applied" if moved else "skip", "moved": moved}


def _run_migrations():
    """实际迁移流程（调用方已持重入守卫）。"""
    # 缺表先建：空库直接跑 `data-cli migrate` 不再崩，也不会留下
    # 「已记 M1 applied 但 versions 不存在」的半写标记。
    if not _table_exists("versions"):
        from . import schema
        schema.init_schema()   # 内层 migrate() 由重入守卫挡掉
    db.execute(SCHEMA_MIGRATIONS_DDL)
    results = []
    # 迁移步骤与 `_mark` 必须在同一事务：否则中途失败会留下「已标记但未生效」。
    with db.transaction():
        if not _applied(M1):
            results.append(migrate_m1_unique_branch())
            _mark(M1)
        else:
            results.append({"migration": M1, "status": "already"})
        if not _applied(M2):
            results.append(migrate_m2_conflict_to_negative())
            _mark(M2)
        else:
            results.append({"migration": M2, "status": "already"})
    return {"backend": db.backend(), "results": results}


def migrate():
    """执行全部迁移（幂等，可重复调用）。"""
    if db.is_remote():
        return {"backend": db.backend(), "status": "skipped-remote"}
    if getattr(_state, "active", False):
        return {"backend": db.backend(), "status": "reentrant-skip"}
    _state.active = True
    try:
        result = _run_migrations()
    finally:
        _state.active = False
    _LAST.clear()
    _LAST.update(result)
    return result
