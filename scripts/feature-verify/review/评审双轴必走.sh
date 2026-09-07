#!/usr/bin/env bash
# ============================================================
# [feature-verify] review / 评审双轴必走（缺轴禁放行）
# ============================================================
# module:   review-dualaxis（评审双轴必走）
# feature:  双轴评审缺任一轴即 axes_complete=False → 评审不完整禁止放行
# 五要素:
#   Given    ReviewerRole.dual_axis_review() 已实现（Standards∥Spec 双轴强制）
#   When     真实构造三组用例调用 dual_axis_review()：
#             负向① 只给 spec_axis、standards_axis 空 → 断 axes_complete=False + blocked=True
#             负向② 只给 standards_axis、spec_axis 空 → 断 axes_complete=False + blocked=True
#             正向   两轴都给非空产出 → 断 axes_complete=True；叠加 Standards🔴必修 → 仍 blocked=True
#   Then     漏单轴必须判 axes_complete=False（机器可核验"只评一轴≠评完"）,
#            note 明确缺哪个轴（Standards / Spec）、禁止放行措辞在;
#            双轴齐全且无必修才 axes_complete=True, 但必改(🔴)仍 blocked=True 不因轴全放行
#   Evidence dual_axis_review() 返回的 axes_complete / blocked / note（可程序化断言的语义产物）
# 为什么是"功能级"：纯 grep 抓不到——必须真实跑 dual_axis_review()，看它对
#   单轴/缺轴输入是否诚实返回 axes_complete=False + blocked=True，不把"只评一轴"当"评完放行"。
#   评审假走单轴混评漏双轴时样例直接判红。
#
# 环境守卫：本样例依赖 python3 + local-agent 角色库，无 python 优雅跳过（视为通过），
#   对齐 scripts/feature-verify/dispatch/真实唤醒校验闸门.sh 模式。
# 用法：bash scripts/feature-verify.sh --feature "review/评审双轴必走"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] review/评审双轴必走 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, "local-agent")
from roles.reviewer import ReviewerRole

PASS = FAIL = 0
def ok(m): print("  ✅ " + m)
def bad(m): print("  ❌ " + m)

r = ReviewerRole()

# ============================================================
# 负向①：只给 spec_axis（有产出）、standards_axis 空
#   → 漏 Standards 轴 → axes_complete=False + blocked=True
# ============================================================
res1 = r.dual_axis_review(
    source="fv-review-spec-only",
    standards_axis={},
    spec_axis={"blocking": [], "faithful": True, "note": "spec 忠实实现"},
)
# Then-1a: axes_complete 必须 False（缺 Standards 轴）
if res1.get("axes_complete") is False:
    ok("Then-1a: 只给 spec 轴（standards 空）→ axes_complete=False（缺 Standards 轴）")
else:
    bad("Then-1a: 只给 spec 轴却 axes_complete=%r → 漏轴仍被判完整，闸门失效" % res1.get("axes_complete"))
    FAIL += 1
# Then-1b: blocked 必须 True（不得放行）
if res1.get("blocked") is True:
    ok("Then-1b: 漏 Standards 轴 → blocked=True（禁止放行）")
else:
    bad("Then-1b: 漏 Standards 轴却 blocked=%r → 假放行" % res1.get("blocked"))
    FAIL += 1
# Then-1c: note 须明确「缺 Standards 轴」+「禁止放行」
note1 = res1.get("note", "")
if "Standards" in note1 and "禁止放行" in note1:
    ok("Then-1c: note 明确指 Standards 轴缺失且禁止放行")
else:
    bad("Then-1c: note 未明确缺 Standards 轴 / 禁止放行 → 提示不诚实, note=%r" % note1)
    FAIL += 1

# ============================================================
# 负向②：只给 standards_axis、spec_axis 空
#   → 漏 Spec 轴 → axes_complete=False + blocked=True
# ============================================================
res2 = r.dual_axis_review(
    source="fv-review-standards-only",
    standards_axis={"blocking": [], "note": "standards 合规"},
    spec_axis={},
)
# Then-2a: axes_complete 必须 False（缺 Spec 轴）
if res2.get("axes_complete") is False:
    ok("Then-2a: 只给 standards 轴（spec 空）→ axes_complete=False（缺 Spec 轴）")
else:
    bad("Then-2a: 只给 standards 轴却 axes_complete=%r → 漏轴仍被判完整" % res2.get("axes_complete"))
    FAIL += 1
# Then-2b: blocked 必须 True
if res2.get("blocked") is True:
    ok("Then-2b: 漏 Spec 轴 → blocked=True（禁止放行）")
else:
    bad("Then-2b: 漏 Spec 轴却 blocked=%r → 假放行" % res2.get("blocked"))
    FAIL += 1
# Then-2c: note 须明确「缺 Spec 轴」
note2 = res2.get("note", "")
if "Spec" in note2 and "禁止放行" in note2:
    ok("Then-2c: note 明确指 Spec 轴缺失且禁止放行")
else:
    bad("Then-2c: note 未明确缺 Spec 轴 / 禁止放行, note=%r" % note2)
    FAIL += 1

# ============================================================
# 正向：两轴都给非空产出 → axes_complete=True
# ============================================================
res3 = r.dual_axis_review(
    source="fv-review-both-axes",
    standards_axis={"blocking": [], "note": "standards 合规无必修"},
    spec_axis={"blocking": [], "faithful": True, "note": "spec 忠实实现"},
)
# Then-3a: 两轴都给 → axes_complete=True
if res3.get("axes_complete") is True:
    ok("Then-3a: 双轴齐全 → axes_complete=True")
else:
    bad("Then-3a: 双轴齐全却 axes_complete=%r → 误判轴缺" % res3.get("axes_complete"))
    FAIL += 1
# Then-3b: 双轴齐全且无必修 → blocked=False（可放行）
if res3.get("blocked") is False:
    ok("Then-3b: 双轴齐全无必修 → blocked=False（达标可放行）")
else:
    bad("Then-3b: 双轴齐全无必修却 blocked=%r → 过度拦截" % res3.get("blocked"))
    FAIL += 1

# ============================================================
# 正向叠加必改：双轴齐全但 Standards 有 🔴 必修 → 仍 blocked=True
# ============================================================
res4 = r.dual_axis_review(
    source="fv-review-both-with-red",
    standards_axis={"blocking": ["🔴 变量命名违反命名规范"], "note": "standards 有必修"},
    spec_axis={"blocking": [], "faithful": True, "note": "spec 忠实实现"},
)
# Then-4a: 双轴齐全 → axes_complete=True（轴完整不代表可放行）
if res4.get("axes_complete") is True:
    ok("Then-4a: 双轴齐全（含必修）→ axes_complete=True（轴完整判定成立）")
else:
    bad("Then-4a: 双轴齐全（含必修）却 axes_complete=%r → 误判轴缺" % res4.get("axes_complete"))
    FAIL += 1
# Then-4b: Standards🔴必修 → blocked=True（必改优先打回，不因轴全就放行）
if res4.get("blocked") is True:
    ok("Then-4b: Standards🔴必修 → blocked=True（必改优先，不因轴全放行）")
else:
    bad("Then-4b: Standards🔴必修却 blocked=%r → 必改项被放行，评审失效" % res4.get("blocked"))
    FAIL += 1

sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 review/评审双轴必走 未达成 → 功能没做完（漏单轴未判不完整/禁放行）"
  exit 1
else
  echo "  🟢 review/评审双轴必走 通过（双轴必走语义机器可核验成立）"
  exit 0
fi
