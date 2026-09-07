#!/usr/bin/env bash
# ============================================================
# [feature-verify] entry-guard / 秘书入口护栏（强制入口不可绕过）
# ============================================================
# module:   entry-guard（三入口归一化 · 秘书强制入口护栏）
# feature: 秘书入口强制护栏——显式 @ 直接进角色也绕不过「架构·秘书」，
#          凡强制秘书的 profile，guard_entry() 必须拦截直入并判违规。
# 五要素:
#   Given   本地存在 local-agent 数据/逻辑层，内含 guard_entry()
#           （local-agent/scale/profile.py，Issue #105 秘书强制入口协议落地）。
#   When    真实 import 并调用 guard_entry(spec_profile, direct_role)，用
#           「经秘书路由」vs「显式 @ 角色跳过秘书」做正反用例断言。
#   Then    ① default profile + 显式 @架构·产品 → ok=False 且 mandatory=True，
#           ② message 明示"违反 rules 固定入口"，
#           ③ harness（内嵌定角色）为唯一允许跳过秘书的 profile，
#           ④ 其余全部内建 profile 一律强制秘书入口。
#   Evidence guard_entry() 返回 dict 的 ok / mandatory / entry / message
#           （机器可程序化断言的语义产物）+ 遍历 DEFAULT_PROFILES 全量核验
#           强制入口覆盖（可 grep "强制入口不可绕过" 等关键语义行）。
# 为什么是"功能级"：纯 grep/只看"函数存在/返回结构"抓不到——必须真实跑护栏引擎，
#   看它对"显式 @ 产品跳秘书"这类绕过是否真的拦截判违规（不因被 @ 就放行）。
#   跑不过 = 秘书强制入口功能没做完，脚本红。
#
# 环境守卫：本样例依赖 python3 + local-agent（CI/本地 python 环境跑），
#   纯 bash 无 python 环境优雅跳过（视为通过），对齐 tests/test_functional_links.sh
#   与 dispatch 样例先例。
# 用法：bash scripts/feature-verify/entry-guard/秘书入口护栏.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] entry-guard/秘书入口护栏 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, "local-agent")
import scale.profile as profile_mod
from scale.profile import guard_entry, is_secretary_mandatory
from scale.profile import SECRETARY_ROLE, SECRETARY_OPTIONAL_PROFILES

PASS = FAIL = 0
def ok(m):
    global PASS; PASS += 1; print("  ✅ " + m)
def bad(m):
    global FAIL; FAIL += 1; print("  ❌ " + m)

# ============================================================
# When + Then：真实跑护栏引擎，断言语义
# ============================================================

# ---------- 正向主用例：显式 @ 角色也绕不过秘书 ----------
# default（个人/内部需求默认入口）= 强制秘书。直接 @架构·产品跳秘书 → 必须被拦。
r1 = guard_entry(spec_profile="default", direct_role="架构·产品")
if r1["ok"] is False and r1["mandatory"] is True:
    ok("Then-1: default + 直接 @架构·产品 → 护栏拦截（ok=False, mandatory=True）")
else:
    bad("Then-1: 直接 @产品 竟被放行（ok=%s）→ 强制入口护栏失效" % r1["ok"])

# 拦截信息必须明示"跳过秘书违反 rules 固定入口"（可感知语义，非泛泛返回）
if "违反 rules 固定入口" in r1.get("message", ""):
    ok("Then-2: 拦截 message 明示『违反 rules 固定入口』")
else:
    bad("Then-2: 拦截 message 未点明『违反 rules 固定入口』→ 语义不清晰")

# 拦截后入口仍指向「架构·秘书」（回到秘书接收）
if r1.get("entry") == SECRETARY_ROLE:
    ok("Then-3: 拦截后 entry 回指「架构·秘书」")
else:
    bad("Then-3: 拦截后 entry=%s，未回指秘书" % r1.get("entry"))

# ---------- 正用对照：经秘书路由 → 合规放行 ----------
r2 = guard_entry(spec_profile="default", direct_role=None)
if r2["ok"] is True and r2["mandatory"] is True:
    ok("Then-4: default + 无 direct_role（走秘书）→ ok=True 合规放行")
else:
    bad("Then-4: 经秘书路由被误拦（ok=%s）→ 护栏误伤正常入口" % r2["ok"])

# ---------- 正用对照：@架构·秘书 本身 → 合规 ----------
r3 = guard_entry(spec_profile="default", direct_role=SECRETARY_ROLE)
if r3["ok"] is True:
    ok("Then-5: default + @架构·秘书 → ok=True（秘书本体不构成绕过）")
else:
    bad("Then-5: @架构·秘书 被误判绕过（ok=%s）" % r3["ok"])

# ---------- 边界：harness（deepseek 内嵌定角色）为唯一允许跳过秘书者 ----------
# 规则："harness 模板因调用方是已定角色的 harness 宿主，允许跳过秘书直入产品"。
r4 = guard_entry(spec_profile="harness", direct_role="架构·产品")
if r4["ok"] is True and r4["mandatory"] is False:
    ok("Then-6: harness 内嵌允许跳过秘书（ok=True, mandatory=False）")
else:
    bad("Then-6: harness 不应强制秘书却 mandatory=%s" % r4["mandatory"])

# harness 必须是唯一豁免模板——其余内建 profile 一律强制秘书（防"悄悄多豁免"）
ALL_PROFILES = set(profile_mod.DEFAULT_PROFILES.keys())
OPTIONAL = set(SECRETARY_OPTIONAL_PROFILES)
non_harness_optional = OPTIONAL - {"harness"}
if not non_harness_optional and "harness" in OPTIONAL:
    ok("Then-7: 豁免模板仅 harness（其余 %d 个内建 profile 全强制秘书）"
       % (len(ALL_PROFILES - OPTIONAL)))
else:
    bad("Then-7: 存在非 harness 的豁免模板 %s → 强制入口被放宽"
        % (non_harness_optional or OPTIONAL))

# 全量核验：每个内建 profile，只要非 harness 就 is_secretary_mandatory=True
missing = [p for p in sorted(ALL_PROFILES)
           if p != "harness" and not is_secretary_mandatory(p)]
if not missing:
    ok("Then-8: 全部内建 profile（非 harness）is_secretary_mandatory 全覆盖")
else:
    bad("Then-8: 以下 profile 未强制秘书: %s" % missing)

# ---------- 负向自证（功能级 > 纯断言）----------
# 证明本脚本真的有能力"抓出绕过护栏导致功能没做完"，而不是只查函数结构。
# 演示：若配置被错误放宽（误把 default 也放进豁免），则"跳过秘书直入"会被放行，
# 此时需求缺秘书路由留痕 = 强制入口功能没做完——本脚本模拟该错误配置，
# 必须能抓到"放行直入"这个缺陷并判红（这就是 guard_entry 护栏要挡住的事故）。
# （monkeypatch 仅在本脚本进程内临时模拟，跑完恢复，不影响引擎真实状态。）
_was_optional = set(SECRETARY_OPTIONAL_PROFILES)
try:
    profile_mod.SECRETARY_OPTIONAL_PROFILES.add("default")  # 模拟错误放宽
    r_neg = guard_entry(spec_profile="default", direct_role="架构·产品")
finally:
    profile_mod.SECRETARY_OPTIONAL_PROFILES.clear()
    profile_mod.SECRETARY_OPTIONAL_PROFILES.update(_was_optional)

if r_neg["ok"] is True:
    # 证明：护栏一旦被绕开，direct_role 直接开工但秘书未留痕 → 功能缺失可被抓
    print("   ↳ [负向自证] 模拟错误放宽后 guard_entry 放行了直入（ok=True）——")
    print("     这正是要防的事故。若真实发生，需求缺秘书路由留痕，强制入口功能")
    print("     即未完成，本脚本判红拦截，合并门禁 blocked_on: feature_unverified。")
    ok("负向自证: 能识别『错误放宽 → 直入被放行』为缺陷（护栏必要性成立）")
else:
    bad("负向自证: 模拟错误放宽后仍被拦（ok=%s），护栏过强遮挡自证"
        % r_neg["ok"])

# 断言失败即退出码非 0
sys.exit(1 if FAIL else 0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 entry-guard/秘书入口护栏 未达成 → 强制入口功能没做完"
  exit 1
else
  echo "  🟢 entry-guard/秘书入口护栏 通过（直接 @ 秘书不可被绕过语义成立）"
  exit 0
fi
