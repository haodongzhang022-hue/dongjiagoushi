#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 评审双轴必走测试（信号灯）
# ============================================================
# 修复 Issue #98 遗留（评审机制不全）：双轴评审不再只是"就绪可调能力方法"，
# 而是**评审必走闸门**——评审主流程统一入口 do_review() 强制先产出双轴。
# 验证：
#   1. do_review 存在（评审主流程统一入口）；
#   2. 双轴完整达标 → review_complete=True + disposition=merge/proceed（放行）；
#   3. 双轴完整有必修 → blocked=True + fix_bug（打回）；
#   4. 缺任一轴 → axes_complete=False + review_complete=False + fix_bug（禁止放行）；
#   5. 两轴独立产出、互不污染（Standards 必修不因 Spec 达标而被放行）。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dual_axis_review.db"

echo "===== [dual-axis] 1. 评审主流程 do_review 存在 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
assert hasattr(r, "do_review"), "评审应具备主流程入口 do_review()"
assert hasattr(r, "dual_axis_review"), "评审应具备 dual_axis_review()"
# 输出契约含 do_review 主流程
contract = " ".join(r.output_contract()["contract"])
assert "do_review" in contract, "输出契约应含 do_review"
print("  ✅ do_review 主流程入口存在 + 输出契约绑定")
EOF

echo "===== [dual-axis] 2. 双轴完整达标 → 放行（merge/proceed）====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
rep = r.do_review("达标任务", source="PR #1", spec_ref="Issue #1",
                  standards_axis={"🔴": [], "note": "无必修"},
                  spec_axis={"faithful": True, "pass": True},
                  issue_ref="1", auto_route=False)
assert rep["axes_complete"] is True
assert rep["review_complete"] is True
assert rep["blocked"] is False
assert rep["disposition"] in ("merge", "proceed"), rep["disposition"]
print("  ✅ 双轴完整达标 → axes_complete=True, review_complete=True, disposition=放行")
EOF

echo "===== [dual-axis] 3. 双轴完整有必修 → fix_bug（打回）====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
rep = r.do_review("必修任务", source="PR #2", spec_ref="Issue #2",
                  standards_axis={"🔴": ["内存泄漏"], "note": "有必修"},
                  spec_axis={"faithful": True, "pass": True},
                  issue_ref="2", auto_route=False)
assert rep["axes_complete"] is True
assert rep["blocked"] is True
assert rep["disposition"] == "fix_bug", rep["disposition"]
print("  ✅ 双轴完整有必修 → blocked=True, disposition=fix_bug（打回）")
EOF

echo "===== [dual-axis] 4. 缺 Spec 轴 → 评审不完整禁止放行 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
rep = r.do_review("缺轴任务", source="PR #3", spec_ref="Issue #3",
                  standards_axis={"🔴": [], "note": "无必修"},
                  spec_axis={},   # 缺 Spec 轴
                  issue_ref="3", auto_route=False)
assert rep["axes_complete"] is False, "缺轴应不完整"
assert rep["review_complete"] is False, "缺轴评审不完整"
assert rep["disposition"] == "fix_bug", "缺轴禁止放行应 fix_bug"
print("  ✅ 缺 Spec 轴 → axes_complete=False, review_complete=False, fix_bug（禁止放行）")
EOF

echo "===== [dual-axis] 5. 缺 Standards 轴 → 评审不完整禁止放行 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
rep = r.do_review("缺轴任务2", source="PR #4", spec_ref="Issue #4",
                  standards_axis={},  # 缺 Standards 轴
                  spec_axis={"faithful": True, "pass": True},
                  issue_ref="4", auto_route=False)
assert rep["axes_complete"] is False
assert rep["review_complete"] is False
assert rep["disposition"] == "fix_bug"
print("  ✅ 缺 Standards 轴 → axes_complete=False, fix_bug（禁止放行）")
EOF

echo "===== [dual-axis] 6. 双轴互不污染（Standards 必修不因 Spec 达标放行）====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
# Standards 有必修，Spec 忠实 → 仍应 blocked（Standards 轴带偏不得放行）
rep = r.do_review("污染校验", source="PR #5", spec_ref="Issue #5",
                  standards_axis={"🔴": ["代码异味严重"], "note": "Standards 必修"},
                  spec_axis={"faithful": True, "pass": True},  # Spec 达标
                  issue_ref="5", auto_route=False)
assert rep["blocked"] is True, "Standards 必修不得因 Spec 达标而被放行"
assert rep["disposition"] == "fix_bug"
print("  ✅ Standards 有必修 + Spec 达标 → 仍 fix_bug（两轴独立不互相污染）")
EOF

echo "===== [dual-axis] 7. auto_route=True 达标 → 真实路由转交/打回 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
r = get_role("架构·评审")
# 达标 → 路由 handoff_to_tester
rep = r.do_review("路由任务", source="PR #6", spec_ref="Issue #6",
                  standards_axis={"🔴": [], "note": "无必修"},
                  spec_axis={"faithful": True, "pass": True},
                  issue_ref="6", auto_route=True)
assert rep["disposition"] in ("merge", "proceed")
assert rep["route_type"] == "handoff_to_tester"
# 有必修 → 路由 revert_to_developer
rep2 = r.do_review("路由任务2", source="PR #7", spec_ref="Issue #7",
                   standards_axis={"🔴": ["严重"], "note": "必修"},
                   spec_axis={"faithful": True},
                   issue_ref="7", auto_route=True)
assert rep2["disposition"] == "fix_bug"
assert rep2["route_type"] == "revert_to_developer"
print("  ✅ 达标→handoff_to_tester，必修→revert_to_developer（主流程真实路由）")
EOF

echo "===== [dual-axis] ALL PASS ====="
