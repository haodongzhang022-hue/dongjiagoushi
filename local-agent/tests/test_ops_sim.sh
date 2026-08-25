#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 模拟测试：验证「防无效努力」升级后的 5 项能力确实可用，再谈 PR。
#   1. 全局唯一编号（agent/任务/PR/Issue 稳定寻址，二次触发同一实体）
#   2. 功能域任务池（按负载动态扩展 agent，非直接固定并发）
#   3. 进度尺小组长监督
#   4. 任务拆分 / 加派（小组长整合）
#   5. 每个角色任务 1-3 PR（各按独立 Issue；对已有 PR 修改不新增 Issue）
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_ops_sim.db"

echo "===== [ops·sim] 1. 全局唯一编号（二次触发同一实体） ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
assert "gid_registry" in schema.list_tables()
# 同一任务 key 二次登记 → 同一 gid
t1, new1 = admin.register_gid("task", "登录模块")
t2, new2 = admin.register_gid("task", "登录模块")
assert t1 == t2, "任务二次触发 gid 必须一致"
assert new1 is True and new2 is False
# 反查定位
info = admin.registry_lookup(t1)
assert info["etype"] == "task" and info["biz_key"] == "登录模块"
# 同一 agent key 二次登记 → 同一 agent（负责人不漂移）
a1, _ = admin.register_gid("agent", "task-001")
a2, _ = admin.register_gid("agent", "task-001")
assert a1 == a2, "agent 二次触发 gid 必须一致"
print("  ✅ 全局唯一编号 + 二次触发同一实体（任务/agent 不漂移）通过")
EOF

echo "===== [ops·sim] 2. 功能域任务池（按负载动态扩展 agent） ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import ops
# 投任务进登录域池子
r1 = ops.enqueue_task("登录域", "tk-001", "实现登录")
assert r1["pool_id"].startswith("pl-")
assert r1["agent_id"].startswith("ag-")
# 同一任务二次投递 → 同一 agent（全局唯一，不漂移）
r2 = ops.enqueue_task("登录域", "tk-001", "实现登录")
assert r1["agent_id"] == r2["agent_id"], "同一任务二次投递 agent 必须一致"
# 池子已建
pools = admin.list_pools(domain="登录域")
assert len(pools) >= 1
print("  ✅ 功能域任务池 + 任务驱动派 agent（二次投递同一 agent）通过 ->", r1["pool_id"])
EOF

echo "===== [ops·sim] 3. 进度尺小组长监督 ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
from sentinel import engine
# 建一个小组的成员并记录进度尺
admin.register_agent("ag-组员1", role="架构·开发", group_id="g-登录组")
admin.register_agent("ag-组员2", role="架构·开发", group_id="g-登录组")
engine.track("mt-a", task_id="t-login", agent_id="ag-组员1", target="登录", goal_total=10, current=6)
engine.track("mt-b", task_id="t-bill", agent_id="ag-组员2", target="结算", goal_total=8, current=2)
# 小组长监督视图
ov = engine.group_oversight("g-登录组")
assert ov["count"] == 2, ov
for m in ov["meters"]:
    assert "progress_ratio" in m and "distance" in m and "delta" in m
# 确认能看到每个成员的任务收敛
names = {m["agent_id"] for m in ov["meters"]}
assert names == {"ag-组员1", "ag-组员2"}
print("  ✅ 进度尺小组长监督（按小组归集，可看到本组成员收敛）通过")
EOF

echo "===== [ops·sim] 4. 任务拆分 / 加派（小组长整合） ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import ops
parent, _ = admin.register_gid("task", "支付模块")
# 初始拆分（任务一开始太大）
sp1 = ops.split_task(parent, reason="initial", branch_name="支付校验")
assert sp1["split_id"].startswith("sp-")
assert sp1["parent_task"] == parent
# 开发中发现过大申报加派
sp2 = ops.apply_more_agents(parent, reason="代码量超出预期", branch_name="支付对账")
assert "found_too_big" in sp2["reason"]
# 小组长整合
ops.team_lead_aggregate(sp1["split_id"])
splits = admin.splits_of(parent, status=None)
assert len(splits) >= 2
# 找已聚合的那条
agg = [s for s in splits if s["status"] == "aggregated"]
assert len(agg) >= 1
print("  ✅ 任务拆分/加派 + 小组长整合（初始拆分 + 开发中申报加派）通过")
EOF

echo "===== [ops·sim] 5. 每个角色任务 1-3 PR（各按独立 Issue；修改不新增） ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import ops
task, _ = admin.register_gid("task", "报表模块")
agent, _ = admin.register_gid("agent", "task-报表模块")
# 提交 1~3 个新 PR，各按独立 Issue
pr1 = ops.submit_pr(task, agent)
pr2 = ops.submit_pr(task, agent)
pr3 = ops.submit_pr(task, agent)
assert pr1["issue_id"] != pr2["issue_id"] != pr3["issue_id"], "各 PR 应独立 Issue"
assert pr1["seq"] == 1 and pr2["seq"] == 2 and pr3["seq"] == 3
# 第 4 个新 PR 应被拦（上限 3）
blocked = False
try:
    ops.submit_pr(task, agent)
except ValueError:
    blocked = True
assert blocked, "第 4 个新 PR 应被上限拦截"
# 对已有 PR 的修改再提交 → amend，复用原 Issue（不新增）
am = ops.amend_pr(task, agent, 1)
assert am["kind"] == "amend"
assert am["issue_id"] == pr1["issue_id"], "修改已有 PR 应复用原 Issue"
# 精准定位某 agent 的工作
aps = ops.agent_prs(agent)
assert len(aps) >= 4
print("  ✅ 任务 1-3 PR（各独立 Issue）+ 修改已有 PR 不新增 Issue + agent 精准定位 通过")
EOF

echo "===== [ops·sim] 6. 全局唯一 gid 精准二次触发（原需求点回归） ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import ops
# 模拟一次真实场景：某任务首次派发 → 哨兵打断 → 二次重派必须仍是同一 agent/任务
task_a = ops.register_task("结账任务")
agent_a = ops.register_agent_for("结账任务")
# 第一次触发后中断，二次触发（重派）
task_a2 = ops.register_task("结账任务")
agent_a2 = ops.register_agent_for("结账任务")
task_a, task_a2 = task_a["task_id"], task_a2["task_id"]
agent_a, agent_a2 = agent_a["agent_id"], agent_a2["agent_id"]
# 核心断言：二次触发的责任人和任务 都不得变更
assert task_a == task_a2, "二次触发任务 gid 漂移了！"
assert agent_a == agent_a2, "二次触发 agent（责任人）漂移了！"
print("  ✅ 二次触发仍是同一任务 + 同一责任人（gid 稳定寻址）通过")
EOF

echo "===== [ops·sim] ALL PASS ====="
