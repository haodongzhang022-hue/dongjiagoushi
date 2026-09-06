#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 经理分配引擎测试（信号灯）
# 验证「架构·经理」四层递进分发深度模型（docs/DISPATCH_DEPTH.md）：
#   L1 声明 → L2 分发 → L3 触发接单 → L4 工作执行（接单→开工→进度尺→交付）
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
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
    {"task_key": "结算模块", "title": "实现结算", "role": "架构·开发",
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

# 先分发+触发
assignments = [
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
]
l2 = dispatch_engine.dispatch_assign("", assignments)
l3 = dispatch_engine.dispatch_trigger(l2)
agent_id = l2[0]["agent_id"]
task_id = l2[0]["task_id"]

# agent 确认接单
result = dispatch_engine.accept_assignment("登录模块", agent_id, role="架构·开发",
                                           note="[接单] 登录模块已接手，目标明确")
assert result["status"] == "accepted"
assert result["task_id"] == task_id
# 任务状态已更新
tasks = admin.task_overview()
assert tasks["in_progress"] >= 1, f"任务应标记为 in_progress"
# 经理应能收到接单回执消息
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

# 进度尺推进
agent_id = l2[0]["agent_id"]
task_id = l2[0]["task_id"]
prog = dispatch_engine.track_progress(
    "登录模块", agent_id, target="实现登录功能", goal_total=10, current=3,
    note="完成需求分析")
assert prog["distance"] == 7, f"距离目标应为7，实际 {prog['distance']}"
assert prog["delta"] >= 0

# 再推进一次
prog2 = dispatch_engine.track_progress(
    "登录模块", agent_id, target="实现登录功能", goal_total=10, current=8,
    note="完成核心逻辑")
assert prog2["distance"] == 2, f"距离目标应为2，实际 {prog2['distance']}"

# 交付
deliver = dispatch_engine.deliver("登录模块", agent_id,
                                  output="登录功能已实现，通过自测",
                                  issue_ref="#40")
assert deliver["status"] == "delivered"
# 任务应标记 done
tasks = admin.task_overview()
assert tasks["done"] >= 1, f"任务应标记 done"
print("  ✅ L4 工作：开工 + 进度尺推进 + 向上交付 通过")
print(f"      distance: 7→2→0, delivered")
EOF

echo "===== [dispatch·engine] 6. 一站式四层分发（dispatch 入口） ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_dispatch6.db")  # 独立 DB，隔离前面已接单回执
from data import admin, schema
admin.init()
import dispatch_engine

assignments = [
    {"task_key": "登录模块", "title": "实现登录", "role": "架构·开发",
     "domain": "登录域", "depends_on": "", "priority": "P0", "detail": "实现账号密码登录"},
    {"task_key": "结算模块", "title": "实现结算", "role": "架构·开发",
     "domain": "结算域", "depends_on": "登录模块", "priority": "P1", "detail": "实现订单结算"},
]
result = dispatch_engine.dispatch("", assignments, enable_issue=False)
summary = result["summary"]
assert summary["total_tasks"] == 2
assert summary["declared_ok"] == 2
assert summary["dispatched_ok"] == 2
assert summary["triggered_ok"] == 2
assert len(result["L1_declare"]) == 2
assert len(result["L2_dispatch"]) == 2
assert len(result["L3_trigger"]) == 2
# ⚠️ Issue #100 防假装分配：没有任何对端回执 [接单]，不得谎报开工到 L4
assert summary["started_ok"] == 0, f"无接单回执不得开工，实际 {summary['started_ok']}"
assert summary["awake_count"] == 0, "无回执不得计入已唤醒"
assert summary["awaiting_receipt_count"] == 2, f"应暴露 2 个待真实唤醒任务"
assert summary["levels_reached"] < 4, "未获接单回执不得谎报到 L4"
assert len(result["L4_start"]) == 0, "无回执不应有 L4 开工"
assert len(result["awaiting_receipt"]) == 2, "应返回 2 个 awaiting_receipt 明细"
assert len(result["verification"]["awaiting_receipt"]) == 2
assert result["verification"]["verified_all_awake"] == False
print("  ✅ 一站式四层分发（防假装分配）：无回执→阻塞 L4、显式暴露 awaiting_receipt 通过")
print(f"      summary={summary}")

# --- 追加：给任务补真实接单回执后再核验，放行开工到 L4 ---
l2 = result["L2_dispatch"]
for a in l2:
    dispatch_engine.accept_assignment(a["task_key"], a["agent_id"],
                                       role=a["role"], note="[接单] 已回执")
verify = dispatch_engine.dispatch_verify(l2)
assert verify["verified_all_awake"] == True, "补回执后应全部真唤醒"
assert verify["awake_count"] == 2
l4 = dispatch_engine.dispatch_start(l2)
assert len(l4) == 2 and all(x["status"] == "working" for x in l4)
print("  ✅ 一站式后续：补真实接单回执 → dispatch_verify 全部真唤醒 → 放行 L4 通过")
EOF

echo "===== [dispatch·engine] 7. 经理角色可调用 dispatch 方法 ====="
$PY - <<'EOF'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DB_PATH"] = "/tmp/test_mgr_dispatch.db"
from roles.manager import ManagerRole

manager = ManagerRole()
assert manager.name == "架构·经理"
# SYSTEM_PROMPT 包含四层深度模型
prompt = manager.system_prompt()
assert "四层递进深度模型" in prompt or "分发四层" in prompt, "SYSTEM_PROMPT 应包含四层深度模型说明"
assert "L4" in prompt, "SYSTEM_PROMPT 应包含 L4 工作层"
assert "dispatch" in prompt, "SYSTEM_PROMPT 应包含 dispatch 引擎"
# dispatch 方法存在且可调用
assert hasattr(manager, "dispatch"), "ManagerRole 应具备 dispatch() 方法"
assignments = [
    {"task_key": "测试任务", "title": "测试", "role": "架构·开发",
     "domain": "测试域", "priority": "P0", "detail": "测试"},
]
result = manager.dispatch("", assignments, enable_issue=False)
# ⚠️ Issue #100：经理一站式 dispatch 无回执时不得谎报 L4（防假装分配）
assert result["summary"]["levels_reached"] < 4, "无接单回执经理不得谎报到 L4"
assert result["summary"]["awaiting_receipt_count"] == 1, "应暴露 1 个待真实唤醒任务"
assert hasattr(manager, "dispatch_verify"), "经理应具备 dispatch_verify() 真实唤醒核验方法"
# dispatch_depth 别名也存在
assert hasattr(manager, "dispatch_depth")
print("  ✅ 经理角色：SYSTEM_PROMPT 含四层深度模型 + dispatch() 无回执不谎报 L4 + 可核验唤醒 通过")
EOF

echo "===== [dispatch·engine] 8. 差异化补强：深度俯瞰 + L4 action 路由 + 防跳层 ====="
$PY - <<'EOF'
import os, tempfile
from data import admin
admin.init()
import dispatch_engine as de

# 8a 深度俯瞰：能按深度分组，区分「只声明/只分发」与「已工作」
de.declare_assignments([{"task_key": "补强A", "title": "A", "role": "架构·开发", "domain": "d1"}])
de.dispatch_assign("", [{"task_key": "补强B", "title": "B", "role": "架构·开发", "domain": "d2"}])
ov = de.dispatch_depth_overview()
assert ov["total_tasks"] >= 2, ov
assert ov["by_depth"]["L2_分发"] >= 1, ov["by_depth"]
print(f"  ✅ 深度俯瞰 by_depth={ov['by_depth']} 可区分深度")

# 8b L4 action 路由执行 script（接单后真的在干活）
sc = os.path.join(tempfile.gettempdir(), "engine_extra_test.sh")
open(sc, "w").write("#!/bin/bash\necho ENGINE_EXTRA_RAN\n")
os.chmod(sc, 0o755)
a = de.dispatch_assign("", [{"task_key": "补强路由", "title": "路由", "role": "架构·开发", "domain": "rt"}])[0]
started = de.dispatch_start([{**a, "action": {"type": "script", "path": sc}}])
ar = started[0]["action_result"]
assert ar["status"] == "ok" and "ENGINE_EXTRA_RAN" in ar["note"], ar
print(f"  ✅ L4 action 路由执行脚本：{ar['status']}")

# 8c 防跳层校验函数：未达前置深度显式报错
try:
    de._require_level("补强任务", 2, 1)
    raise SystemExit("FAIL: 未达深度不应放行")
except ValueError:
    pass
print("  ✅ 防跳层：未达前置深度显式报错")
EOF

echo "===== [dispatch·engine] ALL PASS ====="
