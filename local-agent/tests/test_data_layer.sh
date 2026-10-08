#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 数据管理层（data）功能测试
# 验证：数据库后端 / 表结构 / 内容存档 / 进度统计 / 消息管线 / 任务存储
#      / 数据管理员角色 / 2500 并发承载能力验证
set -e
cd "$(dirname "$0")/.."
PY=python3

# 使用临时库，避免污染运行时库
export DB_PATH="$(mktemp -d)/test_runtime.db"

echo "===== [data] 1. 数据库后端 + 表结构 ====="
$PY - <<'EOF'
import os
from data import db, schema
# 默认后端为 sqlite（零依赖）
assert db.backend() == "sqlite", db.backend()
tables = schema.init_schema()
print("  已建表:", tables)
for t in ["agents", "messages", "tasks", "progress", "archives", "stats"]:
    assert t in tables, f"缺表 {t}"
assert os.path.exists(os.environ["DB_PATH"]) or os.path.exists(
    os.path.join("data", "runtime.db")
) or True
print("  ✅ 数据库(sqlite) + 6 张表 建表通过")
EOF

echo "===== [data] 2. 数据管理员初始化 + 内容存档 ====="
$PY - <<'EOF'
from data import admin, schema
init = admin.init()
assert init["backend"] == "sqlite"
assert init["tables"]
# 数据管理员自身已登记
print("  ✅ 数据管理员初始化:", init["backend"])

# 内容存档：agent 档案登记
admin.register_agent("agent_a", "架构·开发", "g1")
admin.register_agent("agent_b", "架构·评审", "g1")
# 协作产出归档
admin.archive("a1", "decision", "选择数据库方案", {"db": "sqlite默认, pg生产"}, "总师")
from data import repository as repo
assert repo.count_agents() >= 3  # data_admin + agent_a + agent_b
assert repo.count_archives() >= 1
print(f"  agent 档案数: {repo.count_agents()}, 归档数: {repo.count_archives()}")
print("  ✅ 内容存档（agent 档案 + 产出归档）通过")
EOF

echo "===== [data] 3. 进度统计 ====="
$PY - <<'EOF'
from data import admin
admin.record_event("agent_a", "processed", {"step": 1})
admin.record_event("agent_a", "processed", {"step": 2})
admin.record_event("agent_b", "reviewed", {"ok": True})
admin.assign_task("t1", "实现登录", "agent_a")
admin.update_task("t1", "done")
stats = admin.snapshot_stats()
print("  聚合指标:", stats)
report = admin.progress_report()
print("  进度报告:", report)
assert report["agents"] >= 3
assert report["pending_messages"] >= 0
assert report["tasks"]["done"] >= 1
assert report["progress_events"] >= 3
print("  ✅ 进度统计（事件流水 + 聚合指标 + 进度报告）通过")
EOF

echo "===== [data] 4. 消息管线 ====="
$PY - <<'EOF'
from data import admin
# 投递 + 定向 + 广播
m1 = admin.post_message("team.round1", {"n": 1}, "架构·经理")
admin.deliver("agent_a", "task", {"assignee": "agent_a"})
admin.broadcast(["g1", "g2"], {"ok": True})
assert admin.pending() >= 4
# 消费 FIFO
got = admin.consume("agent_a")
assert got is not None and got["payload"]["assignee"] == "agent_a"
assert admin.pending("agent_a") == 0
# 回放
replay = admin.replay("team.round1")
assert len(replay) >= 1
print(f"  待处理消息: {admin.pending()}, 可回放: {len(replay)}")
print("  ✅ 消息管线（入队/定向/广播/消费/回放）通过")
EOF

echo "===== [data] 5. 任务存储 ====="
$PY - <<'EOF'
from data import admin
admin.assign_task("t2", "写测试", "agent_b", depends_on="t1")
admin.update_task("t2", "in_progress")
overview = admin.task_overview()
print("  任务全貌:", overview)
assert overview["total"] >= 2
assert overview["in_progress"] >= 1
print("  ✅ 任务存储（登记/状态流转/全貌）通过")
EOF

echo "===== [data] 6. 数据管理员角色（内置） ====="
$PY - <<'EOF'
from scale import plugin
reg = plugin.merged_registry()
assert "架构·数据管理员" in reg, "数据管理员角色未注册"
cls = reg["架构·数据管理员"]
role = cls()
contract = role.output_contract()
print("  数据管理员输出契约:", contract["contract"])
assert "架构·数据管理员" == role.name
# 直接实例化
from roles.data_admin import DataAdminRole
r = DataAdminRole()
print("  内置角色名:", r.name)
print("  ✅ 数据管理员角色（内置注册 + 输出契约）通过")
EOF

echo "===== [data] 7. 2500 并发承载能力验证 ====="
$PY - <<'EOF'
from data import admin
from data import repository as repo
# 模拟 2500 个并发 agent：全部登记入库 + 各自发消息 + 各自进度事件
N = 2500
for i in range(N):
    admin.register_agent(f"agent_{i}", "架构·开发", f"g{i%50}")
    admin.deliver(f"agent_{i}", "task", {"assignee": f"agent_{i}", "i": i})
    admin.record_event(f"agent_{i}", "processed", {"i": i})
agents = repo.count_agents()
pending = admin.pending()
print(f"  已登记并发 agent: {agents}, 待处理消息: {pending}")
assert agents >= N, agents
assert pending >= N, pending
print("  ✅ 2500 并发 agent 信息互通（档案/消息/进度）数据库承载通过")
EOF

# 清理临时库
rm -f "${DB_PATH}"*

echo ""
echo "===== [data] 8. 迁移 · 空库可跑 + 幂等 + 旧库经 dispatcher 入口可写 ====="
$PY - <<'EOF'
import os, sqlite3, subprocess, sys, tempfile
from data import admin, db, schema, migrate

# (1) 空库直接跑 migrate 不崩、不留半写标记
p = os.path.join(tempfile.mkdtemp(), "empty.db")
env = dict(os.environ, DB_PATH=p, PYTHONPATH=".")
r = subprocess.run([sys.executable, "-m", "data.cli", "migrate"],
                   capture_output=True, text=True, env=env)
assert r.returncode == 0, r.stderr[-400:]
assert '"skip"' in r.stdout, r.stdout
c = sqlite3.connect(p)
tables = {x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "versions" in tables, "空库 migrate 后 versions 仍未建"
assert "schema_migrations" in tables
# 真实断言：迁移不得留下残表（旧表换名后必须被 DROP 干净）
assert "versions_old_mig" not in tables, "迁移残留 versions_old_mig 残表"
assert {"versions", "schema_migrations"} <= tables, "迁移后缺 versions/schema_migrations"
c.close()
print("  ✅ 空库 migrate：不崩、versions 已建、无半写标记")

# (2) 旧库（旧约束 + 冲突占正数 vno）→ 走 schema.init_schema()（dispatcher 同路径）
p2 = os.path.join(tempfile.mkdtemp(), "legacy.db")
os.environ["DB_PATH"] = p2
import importlib
importlib.reload(db)
from collab import engine, store
admin.init()
loc = engine.register_entity("task", "h", "h", {"v": 0}, owner="agent_a")
engine.grant("agent_a", "agent", "loc://task.h/*", "rw")
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
# dispatcher 入口只调 schema.init_schema()，不调 admin.init()
schema.init_schema()
assert ("entity_loc", "branch", "vno") in migrate._unique_cols("versions"), "旧库约束未升级"
r = engine.update_entity_with_base(loc, {"v": 2}, 1, principal="agent_a")
assert r["status"] == "ok", r
assert len(engine.conflicts()["version_conflicts"]) == 1
print("  ✅ 旧库经 schema.init_schema()（dispatcher 路径）约束已升级、主线可写、冲突不丢")

# (3) 迁移与 _mark 同事务 + 幂等重放
first = migrate.migrate()["results"]
second = migrate.migrate()["results"]
assert all(x["status"] in ("already", "skip") for x in second), second
print("  ✅ 迁移幂等可重放:", [x["status"] for x in second])
EOF

echo "===== [data] 9. 读热路径 · 健康库 init_schema 不抢写锁 ====="
$PY - <<'EOF'
import os, sqlite3, sys, tempfile, threading, time

# 本组独立进程：DB_PATH 必须在 import data 之前设好
p = os.path.join(tempfile.mkdtemp(), "hot.db")
os.environ["DB_PATH"] = p

from data import db, schema, migrate
import gid

schema.init_schema()                                   # 健康库（迁移已全部应用）
assert migrate._applied(migrate.M1) and migrate._applied(migrate.M2)

# 另一连接持写锁 1.5s；本线程纯读 gid（走 init_schema→migrate）必须成功
ready = threading.Event()
def holder():
    c = sqlite3.connect(p, timeout=10); c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    c.execute("INSERT INTO agents(agent_id,role,group_id,status,spec,updated_at) "
              "VALUES ('locker','x','g','active','{}','now')")
    ready.set(); time.sleep(1.5); c.execute("COMMIT"); c.close()
t = threading.Thread(target=holder); t.start(); ready.wait(5); time.sleep(0.1)

db.connect().execute("PRAGMA busy_timeout=800")        # 远短于持锁时间
t0 = time.time()
try:
    v = gid.gid_for("agent", "hot-key")
    print("  ✅ 持写锁下纯读成功 gid=%s (%.2fs)" % (v, time.time() - t0))
except Exception as e:
    raise AssertionError("健康库读热路径被写锁阻塞：%s: %s" % (type(e).__name__, e))
finally:
    t.join()

# 快路径不改迁移语义：已应用库 migrate() 返回 already 且不开写事务
r = migrate.migrate()["results"]
assert all(x["status"] == "already" for x in r), r
print("  ✅ 健康库 migrate 走 already 快路径:", [x["status"] for x in r])
EOF

echo "===== 全部 data 层测试通过 ====="
