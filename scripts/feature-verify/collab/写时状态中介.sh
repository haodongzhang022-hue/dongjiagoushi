#!/usr/bin/env bash
# ============================================================
# [feature-verify] collab / 写时状态中介（差距 D 修复）
# ============================================================
# module:   collab（协作运作引擎 · 版本整合写路径）
# feature:  写时状态中介 —— 并发写同一实体时「读 latest + 写新版本」原子化，
#           主线 vno 不重复、冲突不丢、旧库经任意入口可写
# 五要素:
#   Given   一个已注册实体 + 旧库（旧唯一键 (entity_loc, vno)、冲突占正数 vno）
#   When    ① N 线程同基于 v0 并发提交；② 旧库只经 schema.init_schema()（dispatcher 同路径）后写入
#   Then    ① 恰好 1 成功 / N-1 冲突 / 0 异常，主线 vno 无重复（不是「撞键报错」）
#           ② 旧库唯一键升级为 (entity_loc, branch, vno)、主线可写、旧冲突仍留在队列
#           ③ 空库直接跑 `data-cli migrate` 不崩、不留「已标记但未建表」的半写
#           ④ transaction() 非 with 用法的 commit/rollback 后 tx_depth 归零
#           ⑤ 他人持写锁期间 init_schema()（webui 每请求 / gid 每操作的热路径）不阻塞
#   Evidence 本脚本内断言（真跑并发 + 真造旧库）+ 主线 vno / conflicts() 返回值
# 为什么是「功能级」：纯 grep 只能看到 `db.transaction()` 字样，抓不到
#   「并发下真的只有一个赢家、冲突提案真的不污染主线、旧库真的经入口被升级」。
#
# 用法：bash scripts/feature-verify.sh --feature "collab/写时状态中介"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] collab/写时状态中介 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF2'
import os, sqlite3, subprocess, sys, tempfile, threading, time

TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(TMP, "fv.db")
sys.path.insert(0, "local-agent")

from data import admin, db, schema, migrate
from collab import engine, store

FAIL = 0
def ok(m): print("  ✅ " + m)
def bad(m):
    global FAIL; FAIL += 1; print("  ❌ " + m)

admin.init()

# ---- Then-1: N 线程同基于 v0 并发提交 → 恰好 1 赢，主线 vno 无重复 ----
loc = engine.register_entity("task", "fv", "fv1", {"v": 0}, owner="agent_a")
engine.grant("agent_a", "agent", "loc://task.fv/*", "rw")
N = 16
bar = threading.Barrier(N)
res, errs = [], []
lock = threading.Lock()
def w(tag):
    try:
        bar.wait()
        r = engine.update_entity_with_base(loc, {"by": tag}, 0, principal="agent_a")
        with lock: res.append(r["status"])
    except Exception as e:
        with lock: errs.append(type(e).__name__ + ": " + str(e))
ts = [threading.Thread(target=w, args=(i,)) for i in range(N)]
[t.start() for t in ts]; [t.join() for t in ts]
mainline = sorted(v["vno"] for v in store.versions_of(loc) if v["status"] != "conflict")
if errs:
    bad("Then-1: 并发写出现异常 " + str(errs[:2]) + " → 写路径仍未原子化")
elif res.count("ok") == 1 and res.count("conflict") == N - 1 and mainline == [1]:
    ok("Then-1: %d 线程并发 → ok=1 conflict=%d err=0，主线 vno=%s 无重复" % (N, N - 1, mainline))
else:
    bad("Then-1: 结果异常 ok=%d conflict=%d 主线=%s" % (res.count("ok"), res.count("conflict"), mainline))

conf = engine.conflicts()["version_conflicts"]
if len(conf) == N - 1 and all(c["vno"] < 0 for c in conf):
    ok("Then-1b: %d 条冲突提案可被 conflicts() 取到，且占用负数编号空间（不污染主线）" % len(conf))
else:
    bad("Then-1b: 冲突提案丢失或编号污染主线（%d 条 / vno=%s）" % (len(conf), [c["vno"] for c in conf][:3]))

# ---- Then-2: 旧库只经 schema.init_schema()（dispatcher 同路径）→ 约束升级 + 可写 + 冲突不丢 ----
p2 = os.path.join(TMP, "legacy.db")
os.environ["DB_PATH"] = p2
import importlib
importlib.reload(db)
from collab import engine as engine2  # noqa: E402
admin.init()
loc2 = engine2.register_entity("task", "h", "h", {"v": 0}, owner="agent_a")
engine2.grant("agent_a", "agent", "loc://task.h/*", "rw")
c = sqlite3.connect(p2)
c.executescript("""
DROP TABLE IF EXISTS schema_migrations;
DROP TABLE versions;
CREATE TABLE versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_loc TEXT NOT NULL, vno INTEGER NOT NULL, payload TEXT DEFAULT '{}',
    author TEXT DEFAULT '', branch TEXT DEFAULT 'main', parent_vno INTEGER DEFAULT 0,
    status TEXT DEFAULT 'open', created_at TEXT,
    UNIQUE(entity_loc, vno)
);
INSERT INTO versions (entity_loc, vno, payload, status) VALUES
 ('loc://task.h/h', 1, '{"v":1}', 'open'),
 ('loc://task.h/h', 2, '{"c":1}', 'conflict');
""")
c.commit(); c.close()
schema.init_schema()          # dispatcher 等 9 处入口走的就是这一条
cols_ok = ("entity_loc", "branch", "vno") in migrate._unique_cols("versions")
r = engine2.update_entity_with_base(loc2, {"v": 2}, 1, principal="agent_a")
kept = len(engine2.conflicts()["version_conflicts"])
if cols_ok and r["status"] == "ok" and kept == 1:
    ok("Then-2: 旧库经 init_schema() 唯一键升级 + 主线可写 + 旧冲突仍在队列")
else:
    bad("Then-2: 旧库未修复（约束升级=%s 写=%s 冲突保留=%d）" % (cols_ok, r.get("status"), kept))

# ---- Then-3: 空库直接 migrate 不崩、不留半写 ----
p3 = os.path.join(TMP, "empty.db")
env = dict(os.environ, DB_PATH=p3, PYTHONPATH="local-agent")
pr = subprocess.run([sys.executable, "-m", "data.cli", "migrate"],
                    capture_output=True, text=True, env=env, cwd="local-agent")
cc = sqlite3.connect(p3)
tables = {x[0] for x in cc.execute("SELECT name FROM sqlite_master WHERE type='table'")}
marked = {x[0] for x in cc.execute("SELECT version FROM schema_migrations")} if "schema_migrations" in tables else set()
cc.close()
if pr.returncode == 0 and "versions" in tables and marked <= {"2026-10-08-01_versions_unique_branch", "2026-10-08-02_conflict_vno_to_negative"}:
    ok("Then-3: 空库 data-cli migrate 不崩、表已建、标记与实际一致（无半写）")
else:
    bad("Then-3: 空库 migrate 异常 rc=%d tables=%s 标记=%s" % (pr.returncode, sorted(tables)[:4], sorted(marked)))

# ---- Then-4: 事务底座不自相矛盾（非 with 用法的 commit/rollback 必须归零）----
db2 = importlib.reload(db)
importlib.reload(schema)
tx = db2.transaction(); tx.commit()
d1 = getattr(db2._thread_local, "tx_depth", 0)
tx2 = db2.transaction(); tx2.rollback()
d2 = getattr(db2._thread_local, "tx_depth", 0)
if d1 == 0 and d2 == 0:
    ok("Then-4: transaction().commit()/rollback() 后 tx_depth 归零（无泄漏）")
else:
    bad("Then-4: tx_depth 泄漏 commit后=%d rollback后=%d" % (d1, d2))

# ---- Then-5: 热路径可用性——他人持写锁时 init_schema() 不得阻塞/抛锁错 ----
# 🔴5 就是从这个缝里漏出去的：迁移下沉后 init_schema() 无条件 BEGIN IMMEDIATE，
# webui 每请求 / gid 每操作都被写锁串行化。这里锁死「只读检查不取写锁」。
p4 = os.path.join(TMP, "hot.db")
os.environ["DB_PATH"] = p4
db3 = importlib.reload(db)
importlib.reload(schema)
schema.init_schema()

def _hold(sec, ev):
    cc = sqlite3.connect(p4, timeout=30); cc.isolation_level = None
    cc.execute("BEGIN IMMEDIATE")
    cc.execute("INSERT INTO stats (metric,value,ts) VALUES ('x',1,'t')")
    ev.set(); time.sleep(sec); cc.commit(); cc.close()

def _timed(fn, sec=2.0):
    ev = threading.Event()
    th = threading.Thread(target=_hold, args=(sec, ev)); th.start(); ev.wait()
    t = time.time()
    try:
        fn(); r, err = "OK", None
    except Exception as e:
        r, err = type(e).__name__ + ": " + str(e), e
    dt = time.time() - t
    th.join()
    return r, err, dt

r5, err5, dt5 = _timed(schema.init_schema)
if err5 is None and dt5 < 0.5:
    ok("Then-5: 他人持写锁 2s 时 init_schema() 不阻塞（%.3fs，热路径不被写锁串行化）" % dt5)
else:
    bad("Then-5: init_schema() 被写锁阻塞/打挂：%s %.2fs" % (r5, dt5))

r5b, err5b, dt5b = _timed(lambda: __import__("data.migrate", fromlist=["migrate"]).migrate())
if err5b is None and dt5b < 0.5:
    ok("Then-5b: migrate()（无 pending 时）同样只读不取锁（%.3fs）" % dt5b)
else:
    bad("Then-5b: migrate() 无 pending 仍取写锁：%s %.2fs" % (r5b, dt5b))

# ---- Then-2b: 更旧的库（连 branch/status 列都没有）→ 建表前必须先升表 ----
# 复评 🟡2：唯一键缺 branch 或 缺列，任一成立都要重建；否则 idx_versions_* 撞 no such column。
p5 = os.path.join(TMP, "older.db")
os.environ["DB_PATH"] = p5
db4 = importlib.reload(db)
importlib.reload(schema)
c5 = sqlite3.connect(p5)
c5.executescript("""
CREATE TABLE versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_loc TEXT NOT NULL, vno INTEGER NOT NULL, payload TEXT DEFAULT '{}',
    author TEXT DEFAULT '', parent_vno INTEGER DEFAULT 0, created_at TEXT,
    UNIQUE(entity_loc, vno)
);
INSERT INTO versions (entity_loc, vno, payload) VALUES ('loc://task.h/h', 1, '{}');
""")
c5.commit(); c5.close()
try:
    schema.init_schema()
    cols = migrate._columns("versions")
    if ("entity_loc", "branch", "vno") in migrate._unique_cols("versions") and not ({"branch", "status"} - cols):
        ok("Then-2b: 更旧的库（缺 branch/status 列）经 init_schema 先升表再建索引，不崩")
    else:
        bad("Then-2b: 缺列未补齐（cols=%s）" % sorted(cols))
except Exception as e:
    bad("Then-2b: 缺列库建表崩（%s: %s）" % (type(e).__name__, str(e)[:80]))

# ---- Then-6: 远程后端写路径显式收口（fail-loud，不留假象）----
# 复评 🔴：db.execute 在远程每次另开事务，无法复用当前事务连接 → 必须显式拒绝，不静默半工作。
os.environ["DB_BACKEND"] = "postgresql"
os.environ["DB_URL"] = "sqlite:///" + os.path.join(TMP, "sqla.db")
db5 = importlib.reload(db)
try:
    with db5.transaction():
        db5.execute("CREATE TABLE IF NOT EXISTS t_fv (a int)")
    bad("Then-6: 远程事务内 db.execute 未 fail-loud（静默失去原子性）")
except RuntimeError as e:
    if "事务内" in str(e) and getattr(db5._thread_local, "tx_depth", 0) == 0:
        ok("Then-6: 远程事务内 db.execute() fail-loud（拒绝静默半工作）+ tx_depth 归零")
    else:
        bad("Then-6: 抛错但语义/计数不对：%s depth=%s" % (str(e)[:50], getattr(db5._thread_local, "tx_depth", 0)))
except Exception as e:
    bad("Then-6: 抛了非 RuntimeError：%s: %s" % (type(e).__name__, str(e)[:60]))
os.environ.pop("DB_BACKEND", None); os.environ.pop("DB_URL", None)

print()
sys.exit(1 if FAIL else 0)
PYEOF2
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "  🔴 collab/写时状态中介 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 collab/写时状态中介 通过（写路径原子化语义成立）"
  exit 0
fi
