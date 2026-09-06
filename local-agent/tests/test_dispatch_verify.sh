#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 真实唤醒回执校验测试（信号灯 · Issue #100 防假装分配）
# ============================================================
# 用户痛点（Issue #100）：秘书/经理/产品"列个表"调 dispatch() 就当完成，
# 实际没人接单、没唤醒 agent、没校验后续。本测试给这条断链上红灯：
#   1. dispatch() 无对端回执 → 不得谎报开工到 L4，须暴露 awaiting_receipt
#   2. dispatch_verify() 能核验真实唤醒状态（无回执=未唤醒，绝不放行）
#   3. 对端真实回执 [接单] 后 → 核验成立，才可放行 L4
#   4. 秘书/经理/产品（任意角色）都能调用 dispatch_verify 核验，不"列了就算"
set -e
cd "$(dirname "$0")/.."
PY=python3

echo "===== [verify] 1. 无对端回执的 dispatch() 不得假装到 L4 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_verify1.db")
from data import admin
admin.init()
import dispatch_engine

# 秘书/经理/产品"列个表"就调一站式 dispatch，从未有人接单
assign = [
    {"task_key": "假装任务A", "title": "A", "role": "架构·产品",
     "domain": "域", "priority": "P1", "detail": "A"},
    {"task_key": "假装任务B", "title": "B", "role": "架构·开发",
     "domain": "域", "priority": "P2", "detail": "B"},
]
res = dispatch_engine.dispatch("dongdongxiaozu/dongjiagoushi", assign,
                               enable_issue=False)
s = res["summary"]
# 核心断言：列清单 ≠ 派发完成，未回执不得谎报开工到 L4
assert s["started_ok"] == 0, f"无回执不得开工，实际 {s['started_ok']}"
assert s["awake_count"] == 0, "无回执不得计入已唤醒"
assert s["awaiting_receipt_count"] == 2, f"应暴露2个待真实唤醒，实际 {s['awaiting_receipt_count']}"
assert s["levels_reached"] < 4, f"未回执不得谎报 L4，实际 {s['levels_reached']}"
assert res["verification"]["verified_all_awake"] == False
assert len(res["awaiting_receipt"]) == 2
print("  ✅ 无回执 dispatch()：started_ok=0、awaiting=2、levels<4 —— 不再假装完成")
print(f"      summary={s}")
EOF

echo "===== [verify] 2. dispatch_verify 能区分真实唤醒与仅投接力卡 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_verify2.db")
from data import admin
admin.init()
import dispatch_engine

assign = [{"task_key": "唤醒任务", "title": "唤醒", "role": "架构·产品",
           "domain": "域", "priority": "P1", "detail": "唤醒"}]
l2 = dispatch_engine.dispatch_assign("", assign)
l3 = dispatch_engine.dispatch_trigger(l2)
agent_id = l2[0]["agent_id"]; task_id = l2[0]["task_id"]

# ① 触发后、回执前 → 未真实唤醒
v_before = dispatch_engine.dispatch_verify(l2)
assert v_before["verified_all_awake"] == False, "未回执应判定未唤醒"
assert v_before["awake_count"] == 0
assert v_before["awaiting_receipt_count"] == 1

# ② 对端真实回执 [接单] 后 → 真实唤醒成立
dispatch_engine.accept_assignment("唤醒任务", agent_id, role="架构·产品",
                                  note="[接单] 已回执")
v_after = dispatch_engine.dispatch_verify(l2)
assert v_after["verified_all_awake"] == True, "回执后应判定真实唤醒"
assert v_after["awake_count"] == 1
assert v_after["awaiting_receipt_count"] == 0
print("  ✅ dispatch_verify：仅投接力卡=未唤醒；对端回执 [接单] 后=真实唤醒成立")
EOF

echo "===== [verify] 3. 任意角色（秘书/经理/产品）都可调用 dispatch_verify ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_verify3.db")
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import admin; admin.init()
from roles.secretary import SecretaryRole
from roles.manager import ManagerRole
from roles.product import ProductRole

for role in (SecretaryRole(), ManagerRole(), ProductRole()):
    assert hasattr(role, "dispatch_verify"), f"{role.name} 应具备 dispatch_verify()"
    assert hasattr(role, "dispatch"), f"{role.name} 应具备 dispatch()"
    print(f"  ✅ {role.name}：dispatch() + dispatch_verify() 真实唤醒核验 可用")
print("  ✅ 秘书/经理/产品全员可核验真实唤醒 —— 不再'列个表就自认完成'")
EOF

echo "===== [verify] 4. 校验机制接入：有回执才放行 L4，混合任务不假装全成 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_verify4.db")
from data import admin; admin.init()
import dispatch_engine

# 任务C 预置真实回执
pre = dispatch_engine.dispatch_assign("", [{"task_key":"C","title":"C",
    "role":"架构·产品","domain":"域","detail":"C"}])
dispatch_engine.accept_assignment("C", pre[0]["agent_id"], role="架构·产品")

assign = [
    {"task_key":"C","title":"C","role":"架构·产品","domain":"域","detail":"C"},
    {"task_key":"D","title":"D","role":"架构·开发","domain":"域","detail":"D"},
]
res = dispatch_engine.dispatch("", assign, enable_issue=False)
s = res["summary"]
assert s["started_ok"] == 1, "只有已回执的 C 应开工"
assert s["awaiting_receipt_count"] == 1, "D 未回执应暴露待唤醒"
assert s["awaiting_receipt_tasks"] == ["D"]
assert [x["task_key"] for x in res["L4_start"]] == ["C"]
print("  ✅ 混合：C(已回执)开工、D(未回执)阻塞暴露 awaiting_receipt —— 不假装全成")
EOF

echo "===== [verify] ALL PASS ====="
