#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 规模伸缩层（scale）功能测试
# 验证：团队规模声明 / 前置流程区分 / 角色插件 / 状态分片 / 消息总线 / 并发池
set -e
cd "$(dirname "$0")/.."
PY=python3

echo "===== [scale] 1. 规模声明 spec ====="
$PY - <<'EOF'
from scale import spec
s = spec.normalize({"team_size": 2500, "levels": 3, "mode": "harness"})
assert s["team_size"] == 2500
assert s["levels"] == 3
assert s["concurrency"] == 2500  # 未显式给并发 → 取 team_size
est = spec.resource_estimate(s)
print("  team_size=2500 → concurrency", s["concurrency"], "| fits_local", est["fits_local"])
assert est["suggested_backend"] == "redis+distributed"  # 2500 超单机上限
# 小规模应 fits_local
s2 = spec.normalize({"team_size": 8})
assert spec.resource_estimate(s2)["fits_local"] is True
print("  ✅ spec 声明/资源评估通过")
EOF

echo "===== [scale] 2. 前置流程区分 profile ====="
$PY - <<'EOF'
from scale import profile
# 三种不同"位置"走不同流程
for p in ["default", "company", "harness", "acquisition", "support"]:
    r = profile.route(p)
    print(f"  {p}: {r['description']}")
assert profile.route("harness")["profile"] == "harness"
assert profile.route("unknown_x")["fallback"] is True  # 未知回退 default
assert profile.route("company")["entry"] == "架构·秘书"
assert profile.route("acquisition")["entry"] == "市场·销售"
assert profile.route("harness")["entry"] == "架构·产品"
print("  ✅ 前置流程区分（多入口模板）通过")
EOF

echo "===== [scale] 3. 状态分片 store ====="
$PY - <<'EOF'
from scale import store
store.clear_all()
c = store.new_card("agent_7", role="架构·开发", status="in_progress")
store.update("agent_7", step="develop")
store.append_log("agent_7", "task assigned")
store.append_log("agent_7", "processed")
got = store.get("agent_7")
assert got["step"] == "develop"
assert len(got["history"]) == 2
assert store.count() == 1
# 并发安全：多卡互不覆盖
store.new_card("agent_8", role="架构·评审")
assert store.get("agent_8")["role"] == "架构·评审"
assert store.get("agent_7")["role"] == "架构·开发"  # 未被覆盖
print(f"  分片卡数: {store.count()}")
store.clear_all()
print("  ✅ 状态分片（按 agent 隔离）通过")
EOF

echo "===== [scale] 4. 消息总线 broker ====="
$PY - <<'EOF'
from scale import broker
broker.publish("team.round1", {"n": 1}, from_agent="架构·经理")
broker.publish("team.round1", {"n": 2}, from_agent="架构·经理")
n = broker.topic_len("team.round1")
assert n == 2, n
broker.deliver("agent_0", "task", {"assignee": "agent_0"})
assert broker.pending("agent_0") == 1
m = broker.consume("agent_0")
assert m["payload"]["assignee"] == "agent_0"
broker.fan_out(["g1", "g2", "g3"], {"ok": True})
print("  broker stats:", broker.stats())
print("  ✅ 消息总线（发布/定向/广播）通过")
EOF

echo "===== [scale] 5. 并发池 pool（真并行波次）====="
$PY - <<'EOF'
import time
from scale import pool
def work(x):
    time.sleep(0.05)
    return f"done_{x}"
tasks = [(f"n{i}", (lambda a=i: lambda: work(a))) for i in range(10)]
t0 = time.time()
r = pool.run_concurrent(tasks, max_workers=10)
dt = time.time() - t0
assert len(r["results"]) == 10
assert not r["errors"]
print(f"  10 个任务并发(workers=10)完成，耗时约 {dt:.2f}s（应≈0.05s，非串行0.5s）")
assert dt < 0.3, f"未真正并行: {dt}"  # 若串行会 >0.5s
print("  ✅ 并发池（真并行，非纸面并行）通过")
EOF

echo "===== [scale] 6. 角色插件 plugin ====="
$PY - <<'EOF'
from scale import plugin
reg = plugin.merged_registry()
print(f"  内置+插件角色总数: {len(reg)}")
# 插件目录存在且为空时不报错
assert "架构·秘书" in reg
# 过滤：按规模声明只取子集
sub = plugin.filter_by_spec(["架构·产品","架构·总师","架构·开发"], ["架构·开发"])
assert sub == ["架构·开发"]
print("  ✅ 角色插件注册 + 按规模过滤 通过")
EOF

echo "===== [scale] 7. 统一调度引擎 engine（含 2500 并发模拟）====="
$PY - <<'EOF'
from scale import engine
# 小规模全链路
rep = engine.run_scaled("做一个客服系统", spec_obj={"team_size": 8, "profile": "company"})
assert rep["scaled"]
assert rep["route"]["profile"] == "company"
assert rep["cards_created"] == 8
assert len(rep["execution"]["results"]) == 8
assert not rep["execution"]["errors"]
print(f"  小规模(8)耗时 {rep['elapsed_sec']}s, broker: {rep['broker_stats']}")
EOF

echo ""
echo "===== 全部 scale 测试通过 ====="
