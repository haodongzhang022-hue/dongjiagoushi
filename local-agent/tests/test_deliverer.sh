#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 架构·交付 角色测试（全流程呈现 + 收尾交付）
# ============================================================
# 验证：
#   1. 角色已注册（get_role("架构·交付") 可用）
#   2. 输出契约含「全流程呈现 + 收尾交付 + 人类确认后触发」
#   3. progress_report 生成完成度快照 + 进度尺
#   4. signal_echo 回显信号灯 + 遗留问题
#   5. remaining_issues 列遗留问题（🟡不阻塞 + 优先级）
#   6. closeout 收尾闭环（提交PR/处理冲突/关闭Issue/合并确认）
#   7. 人类未确认（CP3）不执行收尾合并
#   8. can_start_closeout 判定🟢+人类确认才可收尾
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_deliverer.db"

echo "===== [deliverer] 1. 角色已注册，可加载 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
assert d is not None, "架构·交付 角色应可加载"
assert d.name == "架构·交付"
print("  ✅ 架构·交付 角色已注册并可用")
EOF

echo "===== [deliverer] 2. 输出契约含呈现+收尾+人类确认后触发 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
c = d.output_contract()
contract_str = " ".join(c["contract"])
assert "progress_report" in contract_str or "全流程呈现" in contract_str
assert "closeout" in contract_str or "收尾交付" in contract_str
assert "人类确认" in contract_str or "CP3" in contract_str
print("  ✅ 输出契约含「全流程呈现 + 收尾交付 + 人类确认后触发」")
for item in c["contract"]:
    print(f"      - {item}")
EOF

echo "===== [deliverer] 3. progress_report 生成完成度快照 + 进度尺 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
r = d.progress_report("呈现测试任务", agent_id="deliverer-1",
                      stages=[
                          {"name": "产品", "status": "✅", "pct": 100},
                          {"name": "架构", "status": "✅", "pct": 100},
                          {"name": "开发", "status": "✅", "pct": 100},
                          {"name": "评审", "status": "✅", "pct": 100},
                          {"name": "测试", "status": "🟢", "pct": 100},
                          {"name": "交付", "status": "⏳", "pct": 0},
                      ],
                      goal_total=100, current=85)
assert r["completion_pct"] == 0.85
assert len(r["stages"]) == 6
assert r["progress_meter"]["distance"] == 15
print("  ✅ progress_report：完成度85%，6阶段快照，进度尺 distance=15")
print(f"      stages: {[s['name'] + s['status'] for s in r['stages']]}")
EOF

echo "===== [deliverer] 4. signal_echo 回显信号灯 + 遗留问题 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
r = d.signal_echo(signal="🟢", blockers=[],
                  warnings=["stats.py 可顺手清理未用导入", "workload_4d project 重复聚合"])
assert r["can_merge"] is True
assert r["summary"] == "🟢 通过，可进入收尾"
assert len(r["warnings"]) == 2
print("  ✅ signal_echo：🟢通过可合并，遗留警告2项")
print(f"      summary={r['summary']}")

# 🔴阻塞
r2 = d.signal_echo(signal="🔴", blockers=["SQL注入面未修复"], warnings=[])
assert r2["can_merge"] is False
assert "🔴" in r2["summary"]
print("  ✅ signal_echo：🔴阻塞不可合并，summary含回转提示")
EOF

echo "===== [deliverer] 5. remaining_issues 列遗留问题（🟡不阻塞+优先级） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
r = d.remaining_issues(["stats.py 未用导入", "project 重复聚合"], priorities=["p5", "p3"])
assert r["total"] == 2
assert all(not item["blocking"] for item in r["items"])
assert r["items"][0]["priority"] == "p5"
assert r["items"][1]["priority"] == "p3"
print("  ✅ remaining_issues：2项🟡遗留，p5/p3，均不阻塞合并")
for item in r["items"]:
    print(f"      #{item['id']} [{item['priority']}] {item['issue']} (blocking={item['blocking']})")
EOF

echo "===== [deliverer] 6. closeout 收尾闭环（提交PR/处理冲突/关闭Issue/合并确认） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
# 人类确认 + 有PR + 无冲突 → 可合并
r = d.closeout("收尾测试任务", agent_id="deliverer-2",
               pr_url="https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/pulls/56",
               issue_ref="55", merged=True, conflicts=[], goal_total=10, current=7)
assert r["prechecks"]["pr_submitted"] is True
assert r["prechecks"]["issue_referenced"] is True
assert r["conflict_resolved"] is True
assert r["can_close_issue"] is True
assert r["action"] == "已合并，关闭 Issue 归档"
print("  ✅ closeout：PR已提交+无冲突+已合并 → 关闭Issue归档")
print(f"      action={r['action']}, can_close={r['can_close_issue']}")

# 有冲突 → 不能关闭
r2 = d.closeout("收尾冲突任务", pr_url="https://pr/xx", issue_ref="55",
                merged=False, conflicts=["conflict in stats.py"], goal_total=10, current=3)
assert r2["conflict_resolved"] is False
assert r2["can_close_issue"] is False
print("  ✅ closeout：有冲突 → 需rebase解决，不能关闭Issue")
print(f"      action={r2['action']}")
EOF

echo "===== [deliverer] 7. 人类未确认（CP3未达成）不执行收尾合并 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

d = get_role("架构·交付")
r = d.closeout("未确认任务", pr_url="https://pr/xx", issue_ref="55",
               merged=False, conflicts=[], goal_total=10, current=2)
assert r["can_close_issue"] is False
assert "待人类确认" in r["action"] or "待" in r["action"]
print("  ✅ 人类未确认（CP3未达成）：不执行收尾合并，等待人类确认")
print(f"      action={r['action']}")
EOF

echo "===== [deliverer] 8. can_start_closeout 判定🟢+人类确认才可收尾 ====="
$PY - <<'EOF'
from roles.deliverer import can_start_closeout

assert can_start_closeout("🟢", True) is True, "🟢+人类确认 → 可收尾"
assert can_start_closeout("🟢", False) is False, "🟢但人类未确认 → 不可收尾"
assert can_start_closeout("🔴", True) is False, "🔴即使人类确认 → 不可收尾"
assert can_start_closeout("🟡", True) is False, "🟡有条件 → 不可收尾"
print("  ✅ can_start_closeout：仅当 🟢通过 + 人类确认 才可进入收尾")
EOF

echo "===== [deliverer] ALL PASS ====="
