#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 经理分配引擎测试（信号灯）
# 验证「架构·经理」四层递进分发深度模型（docs/DISPATCH_DEPTH.md）：
#   L1 声明 → L2 分发 → L3 触发接单 → L4 工作执行（接单→开工→进度尺→交付）
# ⚠ 真实唤醒闸门：L4 必须以对端真实 [接单]/awake_ack 回执为唯一事实来源，
#   无人接单时禁止假装到 L4（防「假装分配」断链）。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dispatch_engine.db"

echo "===== [dispatch·engine] 1. L1 声明：任务/角色定义声明 ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "网关6", "title": "实现网关", "role": "架构·开发",
     "domain": "网关域", "depends_on": "", "priority": "P0", "detail": "网关"}, 
    {"task_key": "网关7", "title": "实现结算", "role": "架构·开发",
     "domain": "结算域", "depends_on": "登录模块", "priority": "P1", "detail": "实现订单结算"},
]
l1 = dispatch_engine.declare_assignments(assignments)
assert len(l1) == 2, f"应声明2个任务，实际 {len(l1)}"
for item in l1:
    assert item["level"] == 1
    assert item["status"] == "declared"
    assert item["task_id"].startswith("tk-"), item["task_id"]
# 同一 task_key 二次声明 → 同一 gid
l1_again = dispatch_engine.declare_assignments([assignments[0]])
assert l1_again[0]["task_id"] == l1[0]["task_id"], "二次声明任务 gid 必须一致"
print("  ✅ L1 声明：任务定义 + 全局唯一 gid + 二次触发稳定寻址 通过")
EOF

echo "===== [dispatch·engine] 2. L2 分发：拆分+分配+投池 ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
]
l2 = dispatch_engine.dispatch_assign("", assignments)
assert len(l2) == 1
item = l2[0]
assert item["level"] == 2
assert item["status"] == "dispatched"
assert item["task_id"].startswith("tk-"), item["task_id"]
assert item["agent_id"].startswith("ag-"), item["agent_id"]
# 验证任务已登记
tasks = admin.task_overview()
assert tasks["total"] >= 1
# 验证 agent gid 已登记
assert admin.registry_lookup(item["agent_id"]) is not None
print("  ✅ L2 分发：拆分任务 + 分配 agent + 投入任务池 通过")
print(f"      task_id={item['task_id']} agent_id={item['agent_id']}")
EOF

echo "===== [dispatch·engine] 3. L3 触发接单：投递接力卡 ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
]
l2 = dispatch_engine.dispatch_assign("", assignments)
l3 = dispatch_engine.dispatch_trigger(l2)
assert len(l3) == 1
item = l3[0]
assert item["level"] == 3
assert item["status"] == "triggered"
assert item["expect_receipt"] == "[接单] 回执待确认"
# 验证消息已投递到消息管线
pending = admin.pending(agent_id=item["agent_id"])
assert pending >= 1, f"应有至少1条待处理消息，实际 {pending}"
# 消费消息验证内容
msg = admin.consume(agent_id=item["agent_id"])
assert msg is not None
payload = msg["payload"]
assert "[触发:" in str(payload.get("trigger", "")), "接力卡应带 [触发:角色] 标记"
assert payload.get("depth_level", "") == "L3·触发接单"
print("  ✅ L3 触发：接力卡投递 + [触发:角色] + 等待接单回执 通过")
EOF

echo "===== [dispatch·engine] 4. L3.5 接单回执：agent 确认 [接单] ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
]
l2 = dispatch_engine.dispatch_assign("", assignments)
l3 = dispatch_engine.dispatch_trigger(l2)
agent_id = l2[0]["agent_id"]
task_id = l2[0]["task_id"]

result = dispatch_engine.accept_assignment("登录模块", agent_id, role="架构·开发",
                                           note="[接单] 登录模块已接手，目标明确")
assert result["status"] == "accepted"
assert result["task_id"] == task_id
tasks = admin.task_overview()
assert tasks["in_progress"] >= 1, f"任务应标记为 in_progress"
pending_mgr = admin.pending(agent_id="架构·经理")
assert pending_mgr >= 1, "经理应收到接单回执"
print("  ✅ L3.5 接单回执：[接单] 确认 + 任务标记 in_progress + 经理收到回执 通过")
EOF

echo "===== [dispatch·engine] 5. L4 开工 + 进度尺推进 + 交付 ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
]
l2 = dispatch_engine.dispatch_assign("", assignments)
l4 = dispatch_engine.dispatch_start(l2)
assert len(l4) == 1
assert l4[0]["level"] == 4
assert l4[0]["status"] == "working"

agent_id = l2[0]["agent_id"]
task_id = l2[0]["task_id"]
prog = dispatch_engine.track_progress(
    "登录模块", agent_id, target="实现登录功能", goal_total=10, current=3,
    note="完成需求分析")
assert prog["distance"] == 7, f"距离目标应为7，实际 {prog['distance']}"
assert prog["delta"] >= 0

prog2 = dispatch_engine.track_progress(
    "登录模块", agent_id, target="实现登录功能", goal_total=10, current=8,
    note="完成核心逻辑")
assert prog2["distance"] == 2, f"距离目标应为2，实际 {prog2['distance']}"

deliver = dispatch_engine.deliver("登录模块", agent_id,
                                  output="登录功能已实现，通过自测",
                                  issue_ref="#40")
assert deliver["status"] == "delivered"
tasks = admin.task_overview()
assert tasks["done"] >= 1, f"任务应标记 done"
print("  ✅ L4 工作：开工 + 进度尺推进 + 向上交付 通过")
print(f"      distance: 7→2→0, delivered")
EOF

echo "===== [dispatch·engine] 6. 一站式分发（真实唤醒闸门：无回执禁止假装L4） ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "网关6", "title": "实现网关", "role": "架构·开发",
     "domain": "网关域", "depends_on": "", "priority": "P0", "detail": "网关"}, 
    {"task_key": "网关7", "title": "实现结算", "role": "架构·开发",
     "domain": "结算域", "depends_on": "登录模块", "priority": "P1", "detail": "实现订单结算"},
]

# 6a 无对端真实回执 → 诚实停在 L3 待回执，绝不假装到 L4（防断链核心）
result = dispatch_engine.dispatch("", assignments, enable_issue=False)
summary = result["summary"]
assert summary["total_tasks"] == 2
assert summary["declared_ok"] == 2
assert summary["dispatched_ok"] == 2
assert summary["triggered_ok"] == 2
assert summary["started_ok"] == 0, "无回执不得假开工"
assert summary["verified_ok"] == 0, "无回执不得算已验证"
assert summary["awaiting_receipt"] == 2, "两任务都应待接单"
assert summary["levels_reached"] == 3, f"无回执应诚实停在 L3，实际 {summary['levels_reached']}"
assert len(result["awaiting_receipt"]) == 2
assert len(result["L4_start"]) == 0
print("  ✅ 6a 无回执：诚实停在 L3 待回执，不再假装到 L4")
print(f"      summary={summary}")

# 6b 对端真实接单回执后 → 才放行到 L4（真实唤醒成立）
for a in assignments:
    l2 = dispatch_engine.dispatch_assign("", [a])
    agent_id = l2[0]["agent_id"]
    dispatch_engine.accept_assignment(a["task_key"], agent_id,
                                      role="架构·开发", note="[接单] 真实接手")
result2 = dispatch_engine.dispatch("", assignments, enable_issue=False)
s2 = result2["summary"]
assert s2["verified_ok"] == 2, "两任务都应已验证接单"
assert s2["awaiting_receipt"] == 0
assert s2["started_ok"] == 2, "有真实回执才放行开工"
assert s2["levels_reached"] == 4, f"真实回执后才到 L4，实际 {s2['levels_reached']}"
print("  ✅ 6b 真实回执后：才放行到 L4 开工")
print(f"      summary={s2}")
EOF

echo "===== [dispatch·engine] 7. 经理角色可调用 dispatch 方法（含真实唤醒闸门） ====="
$PY - <<'EOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DB_PATH"] = "/tmp/test_mgr_dispatch.db"
from roles.manager import ManagerRole

manager = ManagerRole()
assert manager.name == "架构·经理"
prompt = manager.system_prompt()
assert "四层递进深度模型" in prompt or "分发四层" in prompt, "SYSTEM_PROMPT 应包含四层深度模型说明"
assert "L4" in prompt, "SYSTEM_PROMPT 应包含 L4 工作层"
assert "dispatch" in prompt, "SYSTEM_PROMPT 应包含 dispatch 引擎"
assert hasattr(manager, "dispatch"), "ManagerRole 应具备 dispatch() 方法"
assignments = [
    {"task_key": "测试任务", "title": "测试", "role": "架构·开发",
     "domain": "测试域", "priority": "P0", "detail": "测试"},
]
# 无对端回执 → 经理不得自认为派活到 L4（防「假装分配」）
result = manager.dispatch("", assignments, enable_issue=False)
assert result["summary"]["levels_reached"] == 3, "无回执经理不得假装到L4"
assert result["summary"]["awaiting_receipt"] == 1
assert hasattr(manager, "dispatch_depth")
print("  ✅ 经理角色：SYSTEM_PROMPT 含四层深度 + dispatch() 方法可用 + 无回执不假装L4 通过")
EOF

echo "===== [dispatch·engine] 8. 差异化补强：深度俯瞰 + L4 action 路由 + 防跳层 ====="
$PY - <<'EOF'
import os, tempfile
from data import admin
admin.init()
import dispatch_engine as de

de.declare_assignments([{"task_key": "补强A", "title": "A", "role": "架构·开发", "domain": "d1"}])
de.dispatch_assign("", [{"task_key": "补强B", "title": "B", "role": "架构·开发", "domain": "d2"}])
ov = de.dispatch_depth_overview()
assert ov["total_tasks"] >= 2, ov
assert ov["by_depth"]["L2_分发"] >= 1, ov["by_depth"]
print(f"  ✅ 深度俯瞰 by_depth={ov['by_depth']} 可区分深度")

sc = os.path.join(tempfile.gettempdir(), "engine_extra_test.sh")
open(sc, "w").write("#!/bin/bash\necho ENGINE_EXTRA_RAN\n")
os.chmod(sc, 0o755)
a = de.dispatch_assign("", [{"task_key": "补强路由", "title": "路由", "role": "架构·开发", "domain": "rt"}])[0]
started = de.dispatch_start([{**a, "action": {"type": "script", "path": sc}}])
ar = started[0]["action_result"]
assert ar["status"] == "ok" and "ENGINE_EXTRA_RAN" in ar["note"], ar
print(f"  ✅ L4 action 路由执行脚本：{ar['status']}")

try:
    de._require_level("补强任务", 2, 1)
    raise SystemExit("FAIL: 未达深度不应放行")
except ValueError:
    pass
print("  ✅ 防跳层：未达前置深度显式报错")
EOF

echo "===== [dispatch·engine] 9. 真实唤醒闸门红灯：无回执禁止报 L4 ====="
$PY - <<'EOF'
from data import admin, schema
admin.init()
import dispatch_engine

# 红灯信号灯：列清单调 dispatch() 但没人回执，若还报 L4 即「假装分配」→ 必须红灯
assignments = [
    {"task_key": "假装检测", "title": "假装检测任务", "role": "架构·开发",
     "domain": "防伪域", "priority": "P0", "detail": "测试是否假装分配"},
]
r = dispatch_engine.dispatch("", assignments, enable_issue=False)
s = r["summary"]
assert s["started_ok"] == 0, f"红灯应拦下假开工，实际 started_ok={s['started_ok']}"
assert s["levels_reached"] < 4, f"红灯应拦下假装到L4，实际 {s['levels_reached']}"
assert s["awaiting_receipt"] == 1, "待回执应如实暴露"
ok, receipts = dispatch_engine.has_receipt(r["L2_dispatch"][0]["task_id"])
assert ok is False and receipts == []
print("  ✅ 红灯：无人接单时 dispatch() 诚实停在 L3，不报 L4、不假开工")

# 单点工具：真实接单后 has_receipt 返回 True
a = r["L2_dispatch"][0]
dispatch_engine.accept_assignment("假装检测", a["agent_id"], role="架构·开发", note="[接单]")
ok2, rec2 = dispatch_engine.has_receipt(a["task_id"])
assert ok2 is True and len(rec2) >= 1
print("  ✅ has_receipt 能识别真实 [接单] 回执")
EOF

echo "===== [dispatch·engine] ALL PASS ====="
