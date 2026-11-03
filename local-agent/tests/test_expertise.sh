#!/usr/bin/env bash
# ============================================================
# 专家级架构能力测试（信号灯 · expertise 模块）
# 仓库：dongjiagoushi
#
# 作用：把「通用架构师 = 专家级」从说法变成**机器可核验的判据**。
#   区别于静态断言，本脚本对专家级能力的四个支柱做**真实执行**验证：
#
#   E1 规范自洽        —— 七维权重/必过/分档阈值唯一事实源自检
#   E2 行业岗位专家层  —— 真实加载 hanghangchuzhuangyuan 注册表并判定需求
#   E3 帕累托前沿      —— 支配关系/分层/不可信场景（候选不足）
#   E4 外部验证门禁    —— **真实跑子进程**：静态冒充/失败/超时/未来时间戳全被拦
#   E5 时效性闸门      —— 无日期/过期/AI 类快速过期 全判不可用
#   E6 七维评估        —— 自述"已验证"不被采信、缺维即准入不成立
#   E7 AI 能力前沿     —— 陈旧能力声明不得支撑"能做"
#
# 用法：bash tests/test_expertise.sh
# 本地/CI 通用；无第三方依赖（无 pyyaml 时走极简兜底）。
# ============================================================
set -u
cd "$(dirname "$0")/.."
# 解释器选择：显式 PYTHON 优先；否则若本脚本由 `python tests/xxx.sh` 之外的环境调用，
# 默认用「与本 shell 同环境的 python3」；Windows 上 bash 可能解析到 WSL 的 python3
# （另一套时钟/文件系统），会掩盖真实环境问题 —— 故允许 PYTHON 显式指定。
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "❌ 未找到 python3/python，无法运行 expertise 测试" >&2
  exit 2
fi
echo "  （解释器：$PY · $(command -v "$PY")）"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); FAILED_ITEMS+=("$1"); echo "  ❌ $1"; }

echo ""
echo "===== [expertise] E1. 规范自洽（唯一事实源） ====="
if "$PY" - <<'EOF'
import sys; sys.path.insert(0, '.')
from expertise.spec import validate_specs, DIMENSION_SPECS, DIMENSION_KEYS
ok, errs = validate_specs()
assert ok, errs
assert len(DIMENSION_SPECS) == 7, "七维定义必须是 7 条"
assert set(DIMENSION_KEYS) == {"height","depth","breadth","resource","path","pareto","external_validation"}
print("  spec ok:", len(DIMENSION_SPECS), "dims")
EOF
then ok "E1 七维规范自洽（权重和为1/七维全部必过/分档阈值有序）"; else bad "E1 规范自检失败"; fi

echo ""
echo "===== [expertise] E2. 行业岗位专家层（真实加载 hanghang） ====="
if EXPERT_LAYER_ROOT="${EXPERT_LAYER_ROOT:-}" "$PY" - <<'EOF'
import sys, os; sys.path.insert(0, '.')
from expertise import IndustryExpertLayer
layer = IndustryExpertLayer()
if not layer.available:
    # 专家层副本不存在属环境差异：必须**显式降级**，不得伪造命中
    res = layer.resolve("给律所做一个合同审查系统")
    assert res["status"] == "unverified", res
    print("  (skip) 专家层不可用，已显式降级为 unverified:", layer.error)
    raise SystemExit(0)
res = layer.resolve("给律所做一个合同审查系统")
assert res["status"] == "matched", res
assert res["industry"] == "法律咨询", res
roles = [r["role"] for r in res["roles"]]
assert "contract_advisor" in roles, roles
# 负例：无关需求不得硬凑命中
neg = layer.resolve("今天天气怎么样xyzq")
assert neg["status"] in ("no_match", "unverified"), neg
print("  matched:", res["industry"], roles[:3], "conf=", res.get("confidence"))
EOF
then ok "E2 专家层真实命中（法律咨询→contract_advisor）+ 无关需求不硬凑"; else bad "E2 专家层判定失败"; fi

echo ""
echo "===== [expertise] E3. 帕累托前沿 ====="
if "$PY" - <<'EOF'
import sys; sys.path.insert(0, '.')
from expertise import pareto
cands = [
    {"name": "A-自研", "objectives": {"性能": 9, "成本": 2, "工期": 2}},
    {"name": "B-开源", "objectives": {"性能": 6, "成本": 8, "工期": 8}},
    {"name": "C-外包", "objectives": {"性能": 5, "成本": 3, "工期": 9}},
    {"name": "D-劣化", "objectives": {"性能": 3, "成本": 2, "工期": 2}},
]
res = pareto.evaluate(cands)
assert res["trustworthy"] is True
assert set(res["frontier"]) == {"A-自研", "B-开源", "C-外包"}, res["frontier"]
assert "D-劣化" not in res["frontier"]
assert any(d["name"] == "D-劣化" for d in res["dominated"]), res["dominated"]
assert res["choice"] in res["frontier"]
# min 方向：成本越低越好时，不应被当作越大越好
minres = pareto.evaluate([
    {"name": "廉价", "objectives": {"成本": 1}, "direction": {"成本": "min"}},
    {"name": "昂贵", "objectives": {"成本": 9}, "direction": {"成本": "min"}},
])
assert minres["frontier"] == ["廉价"], minres["frontier"]
# 候选不足 → 判不可信
bad = pareto.evaluate([{"name": "唯一", "objectives": {"x": 1}}])
assert bad["trustworthy"] is False and bad["choice"] is None
print("  frontier:", res["frontier"], "| choice:", res["choice"])
EOF
then ok "E3 帕累托前沿正确（支配/分层/min方向/候选不足判不可信）"; else bad "E3 帕累托判定失败"; fi

echo ""
echo "===== [expertise] E4. 外部验证门禁（真实执行子进程） ====="
if PYBIN="$PY" "$PY" - <<'EOF'
import sys, os, shutil; sys.path.insert(0, '.')
from expertise import external_validation as ev

def _interp():
    env = os.environ.get("PYBIN", "")
    for cand in (env, "python3", "python"):
        if cand and shutil.which(cand):
            return cand
    return sys.executable

# 统一加引号：绝对路径可能带空格（Windows 本机）
def qipy(interp):
    return '"%s"' % interp if " " in interp or os.sep in interp or "/" in interp else interp

PY = qipy(_interp())

# 1) 真实功能性验证：真跑 python 打印
real = ev.run_check(PY + " -c \"print('functional-ok')\"")
assert real["status"] == "pass", (real["status"], real.get("reason"), real.get("output_summary"))
assert ev.is_functional(real["command"]) is True
claim = ev.verify_claim(real)
assert claim["verified"] is True, claim["problems"]

# 2) 静态冒充功能验证：grep 必须被判不可信
fake = ev.run_check("grep -q set tests/test_expertise.sh")
assert ev.is_functional(fake["command"]) is False
assert ev.verify_claim(fake)["verified"] is False, "静态检查不得冒充功能验证"

# 3) 失败命令
failrun = ev.run_check(PY + " -c \"raise SystemExit(3)\"")
assert failrun["status"] == "fail", failrun
assert ev.verify_claim(failrun)["verified"] is False

# 4) 超时
to = ev.run_check(PY + " -c \"import time; time.sleep(5)\"", timeout=1)
assert to["status"] == "timeout", to
assert ev.verify_claim(to)["verified"] is False

# 5) 未来时间戳（伪造证据）
from datetime import datetime, timedelta, timezone
forged = dict(real, executed_at=(datetime.now(timezone.utc) + timedelta(days=2)).isoformat())
assert ev.verify_claim(forged)["verified"] is False, "未来时间戳应判不可信"

# 6) 自述"已验证"但没有执行证据
self_declared = {"command": "pytest -q", "status": "pass", "verified": True}
assert ev.verify_claim(self_declared)["verified"] is False, "无 executed_at/exit_code 不得通过"

# 7) 门禁聚合
g = ev.gate([real])
assert g["passed"] is True, g
g2 = ev.gate([fake, failrun])
assert g2["passed"] is False
g3 = ev.gate([])
assert g3["passed"] is False and g3["verdict"] == "unknown", "没有证据必须判 unknown 不得当通过"
print("  real-pass:", real["status"], "| static rejected | timeout rejected | forged rejected")
EOF
then ok "E4 外部验证门禁（真实执行过才认；静态/失败/超时/伪造/自述全拦）"; else bad "E4 外部验证门禁失败"; fi

echo ""
echo "===== [expertise] E5. 时效性闸门 ====="
if "$PY" - <<'EOF'
import sys; sys.path.insert(0, '.')
from expertise import freshness
from datetime import date, timedelta

today = date(2026, 11, 3)
# AI 模型类：30 天上限
fresh = freshness.assess({"kind": "ai_model", "source": "official", "dated_at": "2026-10-20"}, now=today)
assert fresh["tier"] == "fresh" and fresh["usable"] is True, fresh
stale = freshness.assess({"kind": "ai_model", "source": "official", "dated_at": "2026-01-01"}, now=today)
assert stale["tier"] == "stale" and stale["usable"] is False, stale
# 无日期 = 不可信
undated = freshness.assess({"kind": "ai_model", "source": "x", "dated_at": None}, now=today)
assert undated["tier"] == "undated" and undated["usable"] is False, undated
# 有日期但无来源 = 不可用
nosrc = freshness.assess({"kind": "industry_practice", "dated_at": "2026-10-01"}, now=today)
assert nosrc["usable"] is False, "无来源不得作为决策依据"
# 行业做法类：1 年上限（同一条 200 天前对 AI 类是 stale，对行业类仍可用）
mid = freshness.assess({"kind": "industry_practice", "source": "report", "dated_at": "2026-04-15"}, now=today)
assert mid["tier"] in ("fresh", "ageing") and mid["usable"] is True, mid
# 门禁聚合
g = freshness.gate([{"kind": "ai_model", "source": "o", "dated_at": "2026-01-01"}], now=today)
assert g["passed"] is False
g2 = freshness.gate([], now=today)
assert g2["passed"] is False, "空事实集不得判通过"
print("  fresh/ageing/stale/undated 四档判定正确；空集不通过")
EOF
then ok "E5 时效性闸门（无日期/过期/无来源/空集 全部不通过）"; else bad "E5 时效性闸门失败"; fi

echo ""
echo "===== [expertise] E6. 七维评估（自述不被采信） ====="
if "$PY" - <<'EOF'
import sys; sys.path.insert(0, '.')
from expertise import evaluate, run_check
from expertise.spec import DIMENSION_KEYS

real = run_check("python -c \"print('gate-ok')\"")
facts = [{"kind": "ai_framework", "source": "repo:local", "dated_at": "2026-11-03"}]

def full_dims(strength=0.95):
    return {k: {"strength": strength, "note": "证据", "evidence": ["e"]} for k in DIMENSION_KEYS}

# 全维 + 真实验证 + 新鲜事实 → 专家级
good = evaluate({"dimensions": full_dims(), "claims": [real], "facts": facts,
                 "alternatives": [
                     {"name": "A", "objectives": {"效果": 9, "成本": 3}},
                     {"name": "B", "objectives": {"效果": 6, "成本": 8}},
                 ]})
assert good["admissible"] is True, good["highlights"]
assert good["tier"] == "expert", (good["tier"], good["score"])

# 自述"已验证"（无真实证据）→ 外部验证维度被压到弱，不得判 expert
self_talk = evaluate({"dimensions": dict(full_dims(), external_validation={"strength": 1.0, "note": "我已验证"}),
                      "claims": [], "facts": facts,
                      "alternatives": [
                          {"name": "A", "objectives": {"效果": 9, "成本": 3}},
                          {"name": "B", "objectives": {"效果": 6, "成本": 8}},
                      ]})
assert self_talk["tier"] != "expert", "自述验证不得判专家级"
assert self_talk["external_validation"]["passed"] is False

# 缺维度 → 准入不成立（inadmissible），无论其它维度多高
partial = dict(full_dims(), depth=None)
missing = evaluate({"dimensions": partial, "claims": [real], "facts": facts,
                    "alternatives": [
                        {"name": "A", "objectives": {"效果": 9}},
                        {"name": "B", "objectives": {"效果": 6}},
                    ]})
assert missing["admissible"] is False
assert missing["tier"] == "inadmissible"
assert "depth" in missing["missing_required"]

# 事实陈旧 → 准入不成立（证据不可信）
old_facts = [{"kind": "ai_model", "source": "s", "dated_at": "2025-01-01"}]
stale_ok = evaluate({"dimensions": full_dims(), "claims": [real], "facts": old_facts,
                     "alternatives": [
                         {"name": "A", "objectives": {"效果": 9}},
                         {"name": "B", "objectives": {"效果": 6}},
                     ]})
assert stale_ok["admissible"] is False, "陈旧事实不得支撑准入"
print("  expert:", good["tier"], good["score"], "| self-talk:", self_talk["tier"],
      "| missing-dim:", missing["tier"], "| stale:", stale_ok["tier"])
EOF
then ok "E6 七维评估（自述验证/缺维/陈旧事实 均不能放行）"; else bad "E6 七维评估失败"; fi

echo ""
echo "===== [expertise] E7. AI 能力前沿 ====="
if "$PY" - <<'EOF'
import sys, os; sys.path.insert(0, '.')
from expertise import AIFrontier
from datetime import date
af = AIFrontier()
assert af.available, af.status()
st = af.status()
assert st["count"] >= 5
# 当前时点：主流能力应可行
now = date(2026, 11, 3)
cap = af.capability_at("代码生成与重构", now=now)
assert cap["found"] is True
assert cap["verdict"] in ("feasible", "risky"), cap
# 远期：同样的声明因陈旧而不得支撑「能做」
future = date(2027, 6, 1)
stale_cap = af.capability_at("代码生成与重构", now=future)
assert stale_cap["verdict"] == "unverified", stale_cap
# 未收录能力 → unknown，不得默认能做
unknown = af.capability_at("时间旅行", now=now)
assert unknown["found"] is False and unknown["verdict"] == "unknown"
print("  status:", st["count"], "caps | now:", cap["verdict"], "| future:", stale_cap["verdict"])
EOF
then ok "E7 AI 能力前沿（陈旧声明降级为 unverified，未收录判 unknown）"; else bad "E7 AI 能力前沿失败"; fi

echo ""
echo "===== [expertise] E8. Issue 唯一标题契约 ====="
if "$PY" - <<'EOF'
import sys; sys.path.insert(0, '.')
from expertise import issue_contract as ic

# 契约标题可生成可解析
t = ic.build_title("FEAT", "expertise", "pareto-frontier")
assert ic.issue_key(t) == "FEAT:expertise:pareto-frontier", ic.issue_key(t)
# 非法类型/未登记模块/非法唯一键 全部拒绝
for bad_args in [("WHATEVER", "expertise", "x-y"), ("FEAT", "no-such-module", "x-y"), ("FEAT", "expertise", "中文键")]:
    try:
        ic.build_title(*bad_args); raise AssertionError("未拒绝: %r" % (bad_args,))
    except ValueError:
        pass

# 幂等：同 key 绝不重复建
desired = [{"type": "FEAT", "module": "expertise", "key": "pareto-frontier"}]
p0 = ic.plan(desired, [])
assert len(p0["create"]) == 1
p1 = ic.plan(desired, [{"number": 1, "title": t}])
assert len(p1["create"]) == 0 and len(p1["reuse"]) == 1, p1
# 同批内重复也只建一次
p2 = ic.plan(desired * 3, [])
assert len(p2["create"]) == 1, p2

# 重复标题 → 收并计划（保留一个主号，其余关闭）
dup = ic.dedupe_plan([
    {"number": 229, "title": "云端开发请求：对齐登录模块PR产出"},
    {"number": 230, "title": "云端开发请求：对齐登录模块PR产出"},
    {"number": 1, "title": "FEAT:expertise · unique-one"},
])
assert len(dup["groups"]) == 1, dup["groups"]
g = dup["groups"][0]
assert g["keep"] == "229" and g["close"] == ["230"], g
assert "唯一标题契约" in g["comment"]

# 低信号标题在建之前就被拦（不让垃圾进仓库）
low = ic.plan([{"type": "TEST", "module": "expertise", "key": "p0"}], [])
assert len(low["create"]) == 0 and len(low["rejected"]) == 1, "低信号唯一键应被拦住"

# 正文契约：缺段必须报出来
okk, missing = ic.validate_body("## 目标\nfoo")
assert okk is False and "外部验证" in missing
body = ic.build_body(objective="o", in_scope=["a"], out_of_scope=["b"], acceptance=["c"],
                     verification=["python -m pytest -q"])
okk2, missing2 = ic.validate_body(body)
assert okk2 is True, missing2
print("  idempotent OK | dedupe keep=#229 close=['230'] | low-signal rejected | body OK")
EOF
then ok "E8 Issue 唯一标题契约（幂等派发/重复收并/低信号拦截/正文契约）"; else bad "E8 Issue 契约失败"; fi

echo ""
echo "──────────────────────────────────────────────"
echo "expertise 信号灯：通过 $PASS 组，失败 $FAIL 组"
if [ "$FAIL" -ne 0 ]; then
  printf '  失败项：%s\n' "${FAILED_ITEMS[@]}"
  exit 1
fi
echo "✅ 专家级架构能力全部通过"
