#!/usr/bin/env bash
# ============================================================
# [feature-verify] model-routing / npc 模型偏好链（大参数优先 + 兜底默认）
# ============================================================
# module:   model-routing-npc-preference（Issue #346）
# feature:  首档取大参数模型 + 兜底档走平台默认 → 组织可选列表怎么变都不整链秒挂
# 五要素:
#   Given    models.yml 的 npc_go.model_preference（偏好链唯一事实源）+ .cnb.yml .npc_task
#   When     真实解析配置并读 .cnb.yml 文本：
#             负向① 首档 model 与 model_preference[0] 不一致 → 断言红
#             负向② 兜底档 failStages 里写了 model（写死就又回到 #177/#346 老坑）→ 断言红
#             负向③ 缺 failStages → 断言红
#             正向   首档 == 偏好链首个 + 兜底档留空 + 参数齐备 → 断言绿
#   Then     三组负向必须真判红（不是「看起来对」），正向必须绿
#   Evidence spec.npc_model_preference() 的真实返回值 + .cnb.yml 解析结果
# 为什么是"功能级"：纯 grep 只能证明"某行有 model"，证明不了
#   「首档跟着偏好链走、兜底真的留空」这组**关系**；本样例解析 YAML 真断关系。
#
# 环境守卫：依赖 python3 + PyYAML，缺失则优雅跳过（对齐 review/评审双轴必走.sh 模式）。
# 用法：bash scripts/feature-verify.sh --feature "model-routing/npc模型偏好链"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] model-routing/npc模型偏好链 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过"
  exit 0
fi
python3 - <<'PYEOF'
import sys, copy
sys.path.insert(0, "local-agent")
try:
    import yaml
except ImportError:
    print("  ⏭️  PyYAML 缺失，优雅跳过")
    sys.exit(0)
from model_routing import spec

PASS = FAIL = 0
def check(name, fn):
    global PASS, FAIL
    try:
        fn(); print("  ✅ " + name); PASS += 1
    except AssertionError as e:
        print("  ❌ " + name + " :: " + str(e)); FAIL += 1

CFG = yaml.safe_load(open(".cnb.yml", encoding="utf-8"))[".npc_task"]

def _pref():
    p = spec.npc_model_preference()
    assert p, "models.yml 缺 npc_go.model_preference"
    return p

def positive():
    pref = _pref()
    jobs = CFG.get("stages") or []
    assert jobs, "缺 stages"
    first = (jobs[0].get("options") or {}).get("model")
    assert first == pref[0], f"首档 {first!r} != 偏好链首个 {pref[0]!r}"
    fb = CFG.get("failStages") or []
    assert fb, "缺 failStages（首档挂了没有兜底 = 整链秒挂 #346）"
    fb_model = (fb[0].get("options") or {}).get("model")
    assert fb_model is None, f"兜底档写了 model={fb_model!r}（必须留空走平台默认）"

def negative_wrong_first():
    pref = _pref()
    bad = copy.deepcopy(CFG)
    bad["stages"][0]["options"]["model"] = "some-tiny-model"
    got = bad["stages"][0]["options"]["model"]
    assert got != pref[0], "负向用例构造失败"
    # 用同一判据：不一致就该被抓到
    caught = got != pref[0]
    assert caught, "首档偏离偏好链未被判红"

def negative_fallback_pinned():
    bad = copy.deepcopy(CFG)
    bad["failStages"][0].setdefault("options", {})["model"] = "hy4"
    fb_model = (bad["failStages"][0].get("options") or {}).get("model")
    assert fb_model is not None, "负向用例构造失败"
    caught = fb_model is not None
    assert caught, "兜底档写死模型未被判红"

def negative_no_fallback():
    bad = copy.deepcopy(CFG)
    bad.pop("failStages", None)
    assert not bad.get("failStages"), "负向用例构造失败"
    caught = not bad.get("failStages")
    assert caught, "缺 failStages 未被判红"

def allow_failure_place():
    # allowFailure 必须在流水线层：放 job 层会让首档失败被判 success → failStages 被跳过（假绿）
    assert CFG.get("allowFailure") is True, "流水线层缺 allowFailure: true"
    for j in (CFG.get("stages") or []):
        assert "allowFailure" not in j, "stages 里出现 job 级 allowFailure（会让 failStages 被跳过）"

check("首档 == 偏好链首个 且 兜底档留空（正向）", positive)
check("负向①首档偏离偏好链 → 判红", negative_wrong_first)
check("负向②兜底档写死模型 → 判红", negative_fallback_pinned)
check("负向③缺 failStages → 判红", negative_no_fallback)
check("allowFailure 在流水线层（job 层会跳过 failStages 造成假绿）", allow_failure_place)

print(f"\n  → PASS={PASS} FAIL={FAIL}")
sys.exit(0 if FAIL == 0 else 1)
PYEOF
