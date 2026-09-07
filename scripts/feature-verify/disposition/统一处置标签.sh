#!/usr/bin/env bash
# ============================================================
# [feature-verify] review-disposition / 统一处置标签
# ============================================================
# module:   review-disposition（统一审查处置标签引擎）
# feature:  任何审查/决策点恒输出规范处置标签；缺=评审未完成；非规范报错（Issue #100）
# 五要素:
#   Given   若干真实 dispose() 调用场景（兜底无信号 / 🔴必修 / 🟢优化 / hard 疑难 /
#           需人类担责 / 显式乱写标签）
#   When    真实调 local-agent/collab/disposition.py 的 dispose() / require_label()
#   Then   ① 无信号/无 action 兜底 → 恒返回规范标签 proceed（稳定触发、必有标签）
#           ② severity 🔴/red → fix_bug；🟢/green → merge（评审分级强信号）
#           ③ signal hard/high_risk → consult（专家会诊）
#           ④ requires_human=True → 恒 human（最高优先，不被 🔴/green 覆盖）
#           ⑤ 显式 label=乱写标签 → require_label()/dispose() 抛 ValueError 拒绝
#          —— 任一不满足即判红：缺规范处置标签/乱标签被放行 = 评审未完成仍放行（假完成）
#   Evidence dispose() 返回的 disposition / require_label() 的 ValueError（可程序化断言的语义产物）
# 为什么是"功能级"：纯 grep/通畅测试抓不到——必须真实跑 dispose() 分类器，看它是否
#   "任何输入恒返回规范标签、缺=评审未完成、非规范必报错"。跑不过=统一处置标签语义没做完，
#   "评审没带规范标签仍放行"的假完成抓不出来。
#
# 环境守卫：依赖 python3 + local-agent/collab/disposition.py；无 python 环境优雅跳过
#   （对齐 scripts/feature-verify/dispatch/真实唤醒校验闸门.sh 模式），CI python 环境全量跑。
# 用法：bash scripts/feature-verify.sh --feature "disposition/统一处置标签"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] disposition/统一处置标签 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="${REPO_ROOT}/local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, "local-agent")
from collab.disposition import dispose, require_label, valid_labels

PASS = FAIL = 0
def ok(m): print("  ✅ " + m)
def bad(m): print("  ❌ " + m)

# ---- 判据基座：全部规范标签集合（防"漏加/自造"） ----
_NORM = set(valid_labels())
def is_norm(lbl): return lbl in _NORM

# ============================================================
# Then-1: 兜底必有标签 —— dispose(无信号/无action) 恒返回规范标签 proceed
# ============================================================
r = dispose(problem="任意审查结论")["disposition"]
if r == "proceed" and is_norm(r):
    ok("Then-1: 无信号/无 action 兜底 → 恒返回规范标签 proceed（必有标签·稳定触发）")
else:
    bad("Then-1: 兜底未返回 proceed（实际=%s）→ '恒有规范标签'语义失效" % r)
    FAIL += 1

# ============================================================
# Then-2: 评审严重级强信号映射 —— 🔴/red→fix_bug；🟢/green→merge；🟡→proceed
# ============================================================
for sev, expect in (("🔴必修", "fix_bug"), ("red", "fix_bug"),
                    ("🟢优化", "merge"), ("green", "merge"),
                    ("🟡建议", "proceed"), ("yellow", "proceed")):
    got = dispose(severity=sev)["disposition"]
    if got == expect:
        ok("Then-2: severity=%s → %s" % (sev, got))
    else:
        bad("Then-2: severity=%s 期望 %s 实得 %s" % (sev, expect, got))
        FAIL += 1

# ============================================================
# Then-3: 触发信号映射 —— hard/high_risk→consult（专家会诊）
# ============================================================
for sig in ("hard", "high_risk"):
    got = dispose(signals=[sig])["disposition"]
    if got == "consult":
        ok("Then-3: signal=%s → consult" % sig)
    else:
        bad("Then-3: signal=%s 期望 consult 实得 %s" % (sig, got))
        FAIL += 1

# ============================================================
# Then-4: 需人类担责 → 恒 human（最高优先，不被 🔴/green 覆盖）
# ============================================================
for sev in ("green", "🔴必修"):
    got = dispose(severity=sev, requires_human=True)["disposition"]
    if got == "human":
        ok("Then-4: severity=%s + requires_human=True → human（恒最高优先）" % sev)
    else:
        bad("Then-4: requires_human=True 应恒 human，severity=%s 实得 %s" % (sev, got))
        FAIL += 1

# ============================================================
# Then-5: 非规范标签拦截 —— 显式乱写 label → dispose()/require_label() 抛 ValueError
#         能抓出"评审没带规范标签仍放行"的假完成
# ============================================================
for fn in ("require_label", "dispose"):
    caught = False
    try:
        if fn == "require_label":
            require_label("乱写的标签")
        else:
            dispose(label="乱写的标签")
    except ValueError:
        caught = True
    if caught:
        ok("Then-5: %s('乱写的标签') 抛 ValueError 拒绝（非规范必拦，防假完成）" % fn)
    else:
        bad("Then-5: %s('乱写的标签') 未拦截 → 乱标签被放行（假完成抓不住）" % fn)
        FAIL += 1

# 显式合法标签仍可正常解析（不误伤规范标签）
if dispose(label="merge")["disposition"] == "merge":
    ok("Then-5b: 显式规范标签 merge 仍正常放行（不误伤）")
else:
    bad("Then-5b: 规范标签被误伤拦截")
    FAIL += 1

sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 disposition/统一处置标签 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 disposition/统一处置标签 通过（统一处置标签语义成立）"
  exit 0
fi
