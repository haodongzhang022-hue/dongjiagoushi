#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 评审有效性深度集成测试（Issue #100 决策⑤ · review-metrics 接入评审主流程 do_review）
# ============================================================
# 把 review-metrics 有效性度量从"就绪的独立能力"接到**评审主流程 do_review**：
# 每次评审走 do_review 时，自动对"本次处置"做一次确定性观测留痕（kind=review_disposition），
# 供评审有效性监控统计（多少次放行 merge / 打回 fix_bug / 评审不完整），不虚报自判有效。
# 验证：
#   1. do_review 达标放行 → 自动留痕 recorded=True + trace_id；
#   2. do_review 必修打回(fix_bug) → 自动留 fix_bug 处置观测；
#   3. do_review 缺轴不完整 → 仍自动留处置观测（不完整态）；
#   4. 留痕 meta 含 disposition/blocked/axes_complete，可被 trace_recent 消费；
#   5. 处置语义确定性映射（merge 放行 / fix_bug 打回 / 不完整各自独立）。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_review_effectiveness_integration.db"

echo "===== [eff-integ] 1. do_review 达标放行 → 自动有效性留痕 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
from review_metrics import engine

reviewer = get_role("架构·评审")
rep = reviewer.do_review(
    "达标任务", source="PR #x", spec_ref="Issue #1",
    standards_axis={"🔴": [], "note": "无必修"},
    spec_axis={"faithful": True, "note": "忠实实现"})
eff = rep["effectiveness"]
assert rep["disposition"] in ("merge", "proceed"), rep["disposition"]
assert eff["recorded"] is True, f"应留痕, got {eff}"
assert eff.get("trace_id", "").startswith("rvm-"), eff
assert eff["disposition"] in ("merge", "proceed"), eff
assert eff["axes_complete"] is True
print("  ✅ 达标放行 → disposition=", rep["disposition"], ", recorded=True, trace_id=", eff["trace_id"])
EOF

echo "===== [eff-integ] 2. do_review 必修打回 → 自动留 fix_bug 处置观测 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
rep = reviewer.do_review(
    "必修任务", source="PR #y", spec_ref="Issue #2",
    standards_axis={"🔴": ["内存泄漏"], "note": "有必修"},
    spec_axis={"faithful": True, "note": "实现存在必修"})
eff = rep["effectiveness"]
assert rep["blocked"] is True, rep
assert rep["disposition"] == "fix_bug", rep["disposition"]
assert eff["recorded"] is True, eff
assert eff["disposition"] == "fix_bug", eff
assert eff["blocked"] is True, eff
print("  ✅ 必修打回 → disposition=fix_bug, recorded=True, blocked=True")
EOF

echo "===== [eff-integ] 3. do_review 缺轴不完整 → 仍自动留处置观测 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
rep = reviewer.do_review(
    "缺轴任务", source="PR #z", spec_ref="Issue #3",
    standards_axis={"🔴": [], "note": "无必修"},
    spec_axis=None)  # 缺 Spec 轴
eff = rep["effectiveness"]
assert rep["axes_complete"] is False, rep
assert rep["disposition"] == "fix_bug", rep["disposition"]
assert eff["recorded"] is True, eff
assert eff["axes_complete"] is False, eff
print("  ✅ 缺轴不完整 → disposition=fix_bug(禁止放行), recorded=True, axes_complete=False")
EOF

echo "===== [eff-integ] 4. 留痕可被 trace_recent 消费（评审有效性监控数据源） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role
from review_metrics import engine

reviewer = get_role("架构·评审")
reviewer.do_review(
    "监控任务", source="PR #w",
    standards_axis={"🔴": [], "note": "ok"},
    spec_axis={"faithful": True, "note": "ok"})

recent = engine.trace_recent(limit=10)
review_disps = [t for t in recent if t["meta"].get("phase") == "review"]
assert review_disps, "应能读到评审处置观测"
last = review_disps[-1]
assert last["meta"]["disposition"] in ("merge", "proceed"), last["meta"]
assert last["meta"]["axes_complete"] is True
print("  ✅ trace_recent 读到评审处置观测", len(review_disps), "条，meta 含 disposition/blocked/axes_complete")
EOF

echo "===== [eff-integ] 5. 处置语义确定性映射（三种状态各自独立、不串扰） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
# 放行
p1 = reviewer.do_review("A", source="s1", standards_axis={"🔴":[],"note":"ok"},
                        spec_axis={"faithful":True,"note":"ok"})
# 打回
p2 = reviewer.do_review("B", source="s2", standards_axis={"🔴":["x"],"note":"必修"},
                        spec_axis={"faithful":True,"note":"ok"})
assert p1["effectiveness"]["disposition"] != p2["effectiveness"]["disposition"], "放行与打回处置不应相同"
assert p1["disposition"] in ("merge","proceed")
assert p2["disposition"] == "fix_bug"
assert p1["effectiveness"]["blocked"] is False
assert p2["effectiveness"]["blocked"] is True
print("  ✅ 放行/打回处置语义独立、确定性映射正确")
EOF

echo ""
echo "===== [eff-integ] ALL PASS ====="
