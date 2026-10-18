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

热路径纪律：`migrate()` 被 `schema.init_schema()` 调用，而后者在 webui（每请求）/
gid（每操作）等热路径上高频执行。**待迁移项检查必须只读、不取写锁**：
只有确有 pending 时才开事务（sqlite 最外层 `BEGIN IMMEDIATE` 会取写锁，无 pending
也取锁会把只读语义的热路径串行化甚至打挂）。
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


class MigrationError(RuntimeError):
    """迁移无法安全进行（可读、可定位，替代底层 sqlite 的 no such column 冒泡）。"""


# 目标表列 → 老库缺列时的兜底表达式（NULL/默认值），避免「更旧的库」直接崩。
_COLUMN_DEFAULTS = {
    "payload": "'{}'",
    "author": "''",
    "branch": "'main'",
    "parent_vno": "0",
    "status": "'open'",
    "created_at": "NULL",
}
_REQUIRED_COLUMNS = ("entity_loc", "vno")


def last_result():
    """本进程最近一次迁移结果（供 admin.init 汇报，不重复执行迁移）。"""
    return dict(_LAST) if _LAST else None


def _applied(version):
    row = db.query_one("SELECT version FROM schema_migrations WHERE version=?", (version,))
    return row is not None


def _applied_versions():
    """已应用迁移版本集合（一次查询；表不存在返回空集，不吞其他异常）。

    供 `_run_migrations` 快路径用：比逐条 `_applied()` + `_table_exists()` 便宜，
    且 `migrate()` 只跑 sqlite 分支（远程后端在入口即 skip），故只捕 OperationalError。
    """
    import sqlite3
    try:
        return {r["version"] for r in db.query("SELECT version FROM schema_migrations")}
    except sqlite3.OperationalError:   # 表未建 = 尚未迁移
        return set()


def _mark(version):
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, db.now_iso()),
    )


def _table_exists(name):
    """表是否存在（走 schema 统一口径，避免各处重复探测）。"""
    from . import schema
    return schema.table_exists(name)


def _columns(table):
    """取某表现有列名集合（老库可能缺列，迁移要按实际列拼 SELECT）。"""
    return {r["name"] for r in db.query("PRAGMA table_info(%s)" % table)}


def pending():
    """待应用的迁移版本清单（**只读**，不取写锁）。

    供 `migrate --dry-run` / 诊断用；热路径的快路径判据在 `_run_migrations()` 里
    用 `_applied_versions()`（一次查询，比逐条探测便宜）。
    """
    if db.is_remote():
        return []
    if not _table_exists("schema_migrations"):
        # 标记表都没有：无法判断已应用哪些，按「都要跑」保守返回（首次迁移）。
        return [M1, M2]
    return [v for v in (M1, M2) if not _applied(v)]


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
    """versions 是否需要重建（唯一键缺 branch **或**缺 branch/status 列）。

    两条判据必须合并成一个——否则「唯一键已含 branch、但缺 status 列」的库
    （手工改库/第三方库形态）会被判「无需迁移」跳过，而 `init_schema()` 的
    `idx_versions_status` 建索引照样撞 `no such column` 崩在入口。
    """
    if not _table_exists("versions"):
        return False
    if ("entity_loc", "branch", "vno") not in _unique_cols("versions"):
        return True
    return bool({"branch", "status"} - _columns("versions"))


def ensure_versions_upgraded():
    """在建表 DDL 之前，先把结构过旧的 `versions` 表升到位（幂等，返回是否动了）。

    `init_schema()` 的索引 DDL（`idx_versions_branch` / `idx_versions_status`）
    引用 branch / status 列，**旧库没有该列时建索引直接抛 `no such column`**，
    在建表阶段就崩——迁移根本没机会跑。所以必须在 DDL 循环前先重建该表。
    """
    if db.is_remote() or not _table_exists("versions"):
        return False
    if not needs_m1():
        return False
    migrate_m1_unique_branch()
    return True


def migrate_m1_unique_branch():
    """versions 唯一键补 branch 维度（幂等）。

    建表语句引用 `schema.VERSIONS_TABLE_DDL` 常量，不再靠 DDL 字符串匹配：
    以前 `"CREATE TABLE IF NOT EXISTS versions " in ddl` 一旦 DDL 改格式
    （换行/多空格）就静默失配，`ALTER` 已换名后建表落空 → `no such table: versions`。
    """
    if not needs_m1():
        return {"migration": M1, "status": "skip"}
    from . import schema
    cols = _columns("versions")
    missing = [c for c in _REQUIRED_COLUMNS if c not in cols]
    if missing:
        # 可读错误，不让底层 `no such column` 冒到 Web 面板 / gid 入口
        raise MigrationError(
            "versions 表缺少必需列 %s，无法自动迁移（结构非本仓库所建？）；"
            "请人工核对后重跑 data-cli migrate。" % ", ".join(missing))
    # 目标列 → 源表达式：老库缺列时用默认值兜底（更旧的库没有 branch 也能升上来）
    targets = [c for c in ("id", "entity_loc", "vno", "payload", "author", "branch",
                           "parent_vno", "status", "created_at") if c in cols or c in _COLUMN_DEFAULTS]
    exprs = []
    for c in targets:
        if c in cols:
            exprs.append("COALESCE(branch, 'main')" if c == "branch" else c)
        else:
            exprs.append("%s AS %s" % (_COLUMN_DEFAULTS[c], c))
    # 整段包一个事务：中途失败不留 versions_old_mig 残表
    with db.transaction():
        db.execute("DROP TABLE IF EXISTS versions_old_mig")
        db.execute("ALTER TABLE versions RENAME TO versions_old_mig")
        db.execute(schema.VERSIONS_TABLE_DDL)
        db.execute(
            "INSERT INTO versions (%s) SELECT %s FROM versions_old_mig"
            % (", ".join(targets), ", ".join(exprs))
        )
        db.execute("DROP TABLE versions_old_mig")
        # 换表会连索引一起丢，重建（DROP 之后名字才空出来，顺序不能反）
        for ddl in schema.VERSIONS_INDEX_DDL:
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
    # 快路径优先：迁移已全部应用（健康库的常态）→ 直接返回，
    # **不开写事务、不跑任何 DDL、不建表探测**（只一次索引查询）。
    # `init_schema()` 是读热路径的必经点（gid / sentinel / dispatcher / webui…）：
    # 无条件开 `BEGIN IMMEDIATE` 会让一次纯读也抢写锁，并发长写事务下被阻塞到
    # `busy_timeout` 抛 `database is locked`；同理 `CREATE TABLE IF NOT EXISTS`
    # 在表已存在时也会取写锁（实测），必须一并跳过。读路径本不该受写锁影响。
    # 判据用标记而非建表探测：`_mark` 与迁移步骤同事务，标记在即表在。
    applied = _applied_versions()
    if M1 in applied and M2 in applied:
        return {"backend": db.backend(),
                "results": [{"migration": M1, "status": "already"},
                            {"migration": M2, "status": "already"}]}
    # 慢路径：缺表先建——空库直接跑 `data-cli migrate` 不再崩，
    # 也不会留下「已记 M1 applied 但 versions 不存在」的半写标记。
    if not _table_exists("versions"):
        from . import schema
        schema.init_schema()   # 内层 migrate() 由重入守卫挡掉
    if not _table_exists("schema_migrations"):
        db.execute(SCHEMA_MIGRATIONS_DDL)   # 仅首次建标记表（唯一一次额外写）

    results = []
    # 确有 pending 才开事务；迁移步骤与 `_mark` 必须同事务，否则中途失败会留下
    # 「已标记但未生效」。
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


def migrate(dry_run=False):
    """执行全部迁移（幂等，可重复调用）。

    `dry_run=True` 只报告待迁移项，不落任何写（对应 ADR-0013 的 `migrate --dry-run`）。
    """
    if db.is_remote():
        return {"backend": db.backend(), "status": "skipped-remote"}
    if dry_run:
        return {"backend": db.backend(), "dry_run": True, "pending": pending()}
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
