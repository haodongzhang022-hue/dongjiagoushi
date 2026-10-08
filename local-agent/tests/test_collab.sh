#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 协作运作机制（collab）功能测试
# 验证：实体解耦+loc寻址+移交 / 层级空间 / 权限空间(ACL) / 版本冲突检测 /
#      小组提交整合 / 一等实体(需求/skill/记忆)
set -e
cd "$(dirname "$0")/.."
PY=python3

export DB_PATH="$(mktemp -d)/test_collab.db"

echo "===== [collab] 1. 建表 + 实体解耦 + loc:// 寻址 + 灵活移交 ====="
$PY - <<'EOF'
from data import admin, schema
from collab import engine
admin.init()
for t in ["entities","spaces","acl","versions","commits","requirements","skills","memory"]:
    assert t in schema.list_tables(), f"缺表 {t}"
# 需求/任务/agent/skill/记忆 各自独立登记，靠 loc:// 地址寻址
req_loc = engine.register_entity("req", "g1", "login", {"title": "登录功能"}, owner="架构·产品")
task_loc = engine.register_entity("task", "g1", "t1", {"title": "实现登录"}, owner="agent_a")
sk_loc = engine.register_entity("skill", "g1", "arch-skill", {"name": "架构师"}, owner="agent_a")
assert engine.resolve(req_loc)["etype"] == "req"
assert engine.resolve(task_loc)["payload"]["title"] == "实现登录"
assert engine.resolve(sk_loc)["etype"] == "skill"
# 灵活移交：只改 owner
engine.handover(task_loc, "agent_b", principal="agent_a")
assert engine.resolve(task_loc)["owner"] == "agent_b"
print("  ✅ 实体解耦 + loc寻址 + 移交 通过")
EOF

echo "===== [collab] 2. 层级空间（父子树 + 共享空间） ====="
$PY - <<'EOF'
from data import admin
from collab import engine
admin.init()
engine.create_space("teamA", "", "团队A", "root")
engine.create_space("g1", "teamA", "小组一", "group")
engine.create_space("g1-sub", "g1", "子小组", "group")
tree = engine.space_tree("teamA")
assert tree["space_id"] == "teamA"
assert tree["children"][0]["space_id"] == "g1"
assert tree["children"][0]["children"][0]["space_id"] == "g1-sub"
print("  ✅ 层级空间父子树 通过")
EOF

echo "===== [collab] 3. 权限空间（ACL：谁可访问哪个任务/记忆位置） ====="
$PY - <<'EOF'
from data import admin
from collab import engine
admin.init()
loc = engine.register_entity("task", "g1", "t_sec", {"v":0}, owner="agent_a")
engine.grant("agent_a", "agent", "loc://task.g1/*", "rw")
engine.grant("agent_b", "agent", "loc://mem.shared/*", "r")
# 未授权 agent 读任务 → 拒绝
assert engine.check_access("agent_b", loc, "r") is False
# 授权 agent 读写 → 放行
assert engine.check_access("agent_a", loc, "w") is True
# 记忆：读授权/写未授权
assert engine.check_access("agent_b", "loc://mem.shared/ctx", "r") is True
assert engine.check_access("agent_b", "loc://mem.shared/ctx", "w") is False
# 写记忆强制校验
try:
    engine.write_memory("m1", "shared", "context", "c", "agent_b", principal="agent_b")
    raised = False
except PermissionError:
    raised = True
assert raised, "无写权限应拒绝"
engine.grant("agent_b", "agent", "loc://mem.shared/*", "rw")
engine.write_memory("m1", "shared", "context", "c", "agent_b", principal="agent_b")
assert engine.read_memory("m1", "shared", principal="agent_b")["content"] == "c"
print("  ✅ ACL 权限空间 通过")
EOF

echo "===== [collab] 4. 版本整合（并发修改冲突检测） ====="
$PY - <<'EOF'
from data import admin
from collab import engine
admin.init()
loc = engine.register_entity("task", "g1", "t_ver", {"v": 0}, owner="agent_a")
# agent_a 基于 baseline 0 写 v1
r1 = engine.update_entity_with_base(loc, {"v": 1}, 0, principal="agent_a")
assert r1["status"] == "ok" and r1["vno"] == 1
# agent_b 基于过期版本 0 写 → 冲突
r2 = engine.update_entity_with_base(loc, {"v": 99}, 0, principal="agent_a")
assert r2["status"] == "conflict", r2
cf = engine.conflicts()
assert any(v["status"] == "conflict" for v in cf["version_conflicts"])
print("  ✅ 版本冲突检测 通过")
EOF

echo "===== [collab] 5. 小组提交整合 + 最小模块粒度 ====="
$PY - <<'EOF'
from data import admin
from collab import engine
admin.init()
locs = []
for i in range(3):
    loc = engine.register_entity("task", "g1", f"t{i}", {"v": 0}, owner="agent_a")
    engine.update_entity_with_base(loc, {"v": 1}, 0, principal="agent_a")
    locs.append(loc)
# 小组统一提交：scope=最小模块粒度
cid = engine.commit("loc://space.g1", "login-module", locs, [1,1,1], submitter="agent_a")
mr = engine.merge_commit(cid)
assert mr["status"] == "merged", mr
assert engine.commits(status="merged")[0]["commit_id"] == cid
print("  ✅ 小组提交整合 通过")
EOF

echo "===== [collab] 6. 一等实体（需求/skill/记忆）解耦共享 ====="
$PY - <<'EOF'
from data import admin
from collab import engine
admin.init()
engine.add_requirement("r1", "登录需求", "g1", {"scope": "认证"}, owner="架构·产品")
engine.register_skill("arch", "架构师方法论", "g1", "八步", playbook="SKILL.md", owner="架构·总师")
assert engine.store.get_req("r1")["status"] == "open"
assert engine.store.get_skill("arch")["name"] == "架构师方法论"
# 记忆按空间共享
engine.grant("agent_b", "agent", "loc://mem.shared/*", "rw")
engine.write_memory("ctx1", "shared", "decision", "选 sqlite+pg", "agent_a", principal="agent_b")
assert engine.read_memory("ctx1", "shared", principal="agent_b")["kind"] == "decision"
print("  ✅ 需求/skill/记忆 一等实体 通过")
EOF

echo "===== [collab] 7. 事务底座 · tx_depth 归零（非 with 用法不漏计数） ====="
$PY - <<'EOF'
from data import admin, db
from collab import engine
admin.init()
loc = engine.register_entity("task", "g1", "t_tx", {"v": 0}, owner="agent_a")
engine.grant("agent_a", "agent", "loc://task.g1/*", "rw")

# 非 with 用法：commit()/rollback() 必须把 tx_depth 收回到 0
# 否则 depth 永久留 1 → db.execute 不再自动提交、BEGIN IMMEDIATE 不再取锁，
# 事务静默失去原子性（「假原子性」）。
tx = db.transaction(); tx.commit()
assert getattr(db._thread_local, "tx_depth", 0) == 0, db._thread_local.tx_depth
tx = db.transaction(); tx.rollback()
assert getattr(db._thread_local, "tx_depth", 0) == 0, db._thread_local.tx_depth

# 泄漏过一次后，with 事务抛错必须能回滚（脏数据不落库）
try:
    with db.transaction():
        db.execute("INSERT INTO entities (etype,namespace,entity_id,loc,payload,"
                   "created_at,updated_at) VALUES ('t','n','dirty','loc://t.n/dirty',"
                   "'{}','x','x')")
        raise RuntimeError("boom")
except RuntimeError:
    pass
assert db.query("SELECT loc FROM entities WHERE loc='loc://t.n/dirty'") == [], "回滚失效"

# 嵌套事务仍只由最外层提交
with db.transaction():
    with db.transaction():
        db.execute("INSERT INTO entities (etype,namespace,entity_id,loc,payload,"
                   "created_at,updated_at) VALUES ('t','n','nested','loc://t.n/nested',"
                   "'{}','x','x')")
assert db.query("SELECT loc FROM entities WHERE loc='loc://t.n/nested'"), "嵌套提交失效"
assert getattr(db._thread_local, "tx_depth", 0) == 0
print("  ✅ 事务底座 tx_depth 归零 + 回滚/嵌套提交 通过")
EOF

echo "===== [collab] 全部通过 ✅ ====="
