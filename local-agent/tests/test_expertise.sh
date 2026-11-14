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
# 统一导出：**所有**需要"再起一个子进程跑 Python"的用例都必须复用此解析结果，
# 禁止在用例内写死 `python`/`python3` —— 云 CI（python:3.11）只有 `python3`，
# 写死 `python` 会 exit 127，导致「外部验证」判不通过 → 用例误红。
# 教训（2026-11-03，CI cnb-cn4-1k6fsorel）：同一份测试在本地(有 python)绿、在容器红。
export PYBIN="$PY"

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
echo "===== [expertise] E2b. 专家层不可用时的降级（模拟 CI 容器无外部仓副本） ====="
if "$PY" - <<'EOF'
import os, sys; sys.path.insert(0, '.')
# 进程内模拟「本机没有 hanghangchuzhuangyuan 副本」：把探测候选全部指向不存在路径。
# 云 CI 容器里确实没有该仓副本，此分支必须**显式降级**而不是崩溃/伪造命中。
import expertise.experts as E
E._candidate_roots = lambda root=None: ["/nonexistent/no-such-expert-layer"]
from expertise import IndustryExpertLayer
layer = IndustryExpertLayer()
assert layer.available is False, "候选路径不存在时不得判可用"
res = layer.resolve("给律所做一个合同审查系统")
assert res["status"] == "unverified", res
assert "no-such" in (layer.error or "") or layer.error, layer.error
print("  degraded ->", res["status"], "| error:", (layer.error or "")[:40])
EOF
then ok "E2b 专家层缺失时显式降级 unverified（不崩溃、不伪造命中）"; else bad "E2b 降级分支失败"; fi

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
# 跨签名候选共存：缺维候选不得让标准化循环 KeyError（跨签名不比，都留前沿）
cross = pareto.evaluate([
    {"name": "A", "objectives": {"效果": 9}},
    {"name": "B", "objectives": {"效果": 6, "成本": 8}},
])
assert cross["trustworthy"] is True, cross
assert set(cross["frontier"]) == {"A", "B"}, cross["frontier"]
# scores 必须是 {name: score} 方向正确，且同分候选不互相覆盖
assert set(cross["scores"]) == {"A", "B"}, cross["scores"]
tie = pareto.evaluate([
    {"name": "A", "objectives": {"效果": 9, "成本": 3}},
    {"name": "B", "objectives": {"效果": 9, "成本": 3}},
])
assert set(tie["scores"]) == {"A", "B"}, tie["scores"]
assert all(isinstance(v, float) for v in tie["scores"].values()), tie["scores"]
print("  frontier:", res["frontier"], "| choice:", res["choice"])
EOF
then ok "E3 帕累托前沿正确（支配/分层/min方向/候选不足判不可信）"; else bad "E3 帕累托判定失败"; fi

echo ""
echo "===== [expertise] E4. 外部验证门禁（真实执行子进程） ====="
if PYBIN="$PY" "$PY" - <<'EOF'
import sys, os, shutil; sys.path.insert(0, '.')
from expertise import external_validation as ev

def _interp():
    for cand in (os.environ.get("PYBIN", ""), "python3", "python"):
        if cand and shutil.which(cand):
            return cand
    return sys.executable


def qipy(interp):
    """含空格/路径分隔符的解释器路径必须加引号，否则 shell 会按空格切词。"""
    quoted = " " in interp or os.sep in interp or "/" in interp
    return '"%s"' % interp if quoted else interp


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
import sys, os, shutil; sys.path.insert(0, '.')
from expertise import evaluate, run_check
from expertise.spec import DIMENSION_KEYS

# 解释器解析必须与 E4 一致：云 CI（python:3.11）里往往**没有** `python`，只有 `python3`。
# 此处若写死 `python`，run_check 会 exit 127 → 外部验证判不通过 → E6 误红（2026-11-03 实测过）。
# 曾因本行写死 `python` 导致 CI cnb-cn4-1k6fsorel 失败：本地 Windows 解析到 `python` 能过，
# 容器里没有该命令即红 —— 同一个测试在两种环境给出相反的绿/红，属基础设施级误判。
def _interp():
    for cand in (os.environ.get("PYBIN", ""), "python3", "python"):
        if cand and shutil.which(cand):
            return cand
    return sys.executable

PYBIN = _interp()
real = run_check(PYBIN + " -c \"print('gate-ok')\"")
assert real["status"] == "pass", ("E6 前置：真实执行验证未通过", real["status"], real.get("output_summary"))
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
echo "===== [expertise] E9. 契约接线：三处建 Issue 出口必须过闸门（且不许自写读法）====="
if "$PY" - <<'EOF'
import sys, inspect; sys.path.insert(0, '.')
from expertise import issue_contract as ic

# ① 不合格标题被契约化（不丢信息：原文保留在 original 里）
g = ic.guard_create("开发登录模块", [])
assert g["action"] == "create", g
assert g["derived"] is True
assert ic.issue_key(g["title"]) == "CHORE:local-agent:task-" + ic._stable_digest("开发登录模块")
assert g["original"] == "开发登录模块"

# ② 幂等：同诉求再来一次 → reuse，绝不建第二个（这是「不重复」的结构性保证）
again = ic.guard_create("开发登录模块", [{"number": 42, "title": g["title"]}])
assert again["action"] == "reuse" and again["reuse_number"] == "42", again
# 已关闭的也 reuse（历史遗留可指回），不新开
closed = ic.guard_create("开发登录模块", [{"number": 7, "title": g["title"], "state": "closed"}])
assert closed["action"] == "reuse" and closed["reuse_number"] == "7", closed
# 存量脏标题（合不上契约）同名也要挡：这正是"同一天长出三条一样 Issue"的成因
dirty = ic.guard_create("开发登录模块", [{"number": 353, "title": "开发登录模块"}])
assert dirty["action"] == "reuse" and dirty["reuse_number"] == "353", dirty

# ③ derive=False 时直接拒绝（不自动造标题）
r = ic.guard_create("评审登录模块", [], derive=False)
assert r["action"] == "reject" and r["title"] == "", r

# ④ 合格标题原样放行，不被改写
ok_g = ic.guard_create("FEAT:expertise · pareto-frontier", [])
assert ok_g["action"] == "create" and ok_g["derived"] is False
assert ok_g["title"] == "FEAT:expertise · pareto-frontier"

# ⑤ 三处建 Issue 出口都必须真有闸门调用（函数写好了没人调 = 今天这个情况）
import inspect
sys.path.insert(0, 'local-agent')
import dispatch_engine
assert hasattr(dispatch_engine, "guard_issue_title"), "dispatch_engine 未挂契约闸门"
assert "guard_issue_title" in inspect.getsource(dispatch_engine._create_issue), \
    "_create_issue 绕过闸门 = 契约不生效"
from entries import cnb_live
assert "_gate_title" in inspect.getsource(cnb_live.send), "bridge 锚点 Issue 未过闸门"
from hybrid import batch as _batch
assert "guard_create" in inspect.getsource(_batch.CloudBatch._create_issue), \
    "hybrid.batch 建 Issue 绕过闸门（文案说三处，只断言两处 = 假信号灯）"

# ⑥ 三处都**不再自写存量读法**：非法 issues `--state all` / 自写正则解析 一律不许出现
#    （注意 `pulls list-pulls` 的 `--state all` 是合法值，故只核 issues 相关函数）
from entries import cnb_live as _live
targets = [("dispatch_engine", sys.modules["dispatch_engine"]),
           ("cnb_live._gate_title", _live._gate_title),
           ("cnb_live.send", _live.send),
           ("hybrid.batch", _batch.CloudBatch._create_issue)]
for mod, obj in targets:
    src = inspect.getsource(obj)
    assert '"--state", "all"' not in src and "'--state', 'all'" not in src, \
        f"{mod} 仍在给 issues 传非法 --state all（实测 400 → 存量恒空）"
    assert "issue_source" in src, \
        f"{mod} 未走 issue_source 唯一实现（存量读法不许各写一份）"
print("  契约化/幂等/拒绝/放行 + 三处真接线 + 单一存量读法 全部通过")
EOF
then ok "E9 契约接线（低信号契约化 · 同 key/同名复用 · 三处出口真接线 · 无非法 --state all）"; else bad "E9 契约接线失败"; fi

echo ""
echo "===== [expertise] E10. 闸门两端判定为真（存量读得到 · 不塌缩 · 不吞任务）====="
if "$PY" - <<'EOF'
import sys; sys.path.insert(0, '.')
from expertise import issue_contract as ic
from expertise import issue_source as src

REPO = "acme/demo"

# --- ① 全量语义 = 分别拉 open + closed 再合并（`all` 是非法值，实测 400；
#        而"不带 --state"实测只返回 open，closed 的 218 条看不见）---
seen = []
def fake_ok(argv, timeout=180):
    seen.append(list(argv))
    st = argv[argv.index("--state") + 1] if "--state" in argv else "none"
    num = "42" if st == "open" else "41"
    return 0, ('status: 200\npage: 1\npageSize: 100\ntotal: 1\ntotalPages: 1\n'
               'data[1]:\n  - number: "%s"\n    state: %s\n    title: "开发登录模块"\n'
               % (num, st)), ""
snap = src.fetch_issues(REPO, runner=fake_ok)
assert snap["ok"] and sorted(i["number"] for i in snap["items"]) == ["41", "42"], snap
states_used = [a[a.index("--state") + 1] for a in seen if "--state" in a]
assert set(states_used) == {"open", "closed"}, f"全量必须两趟拉，实际 {states_used}"
assert "all" not in states_used, "不得再传 --state all（非法值实测 400）"

# --- ② 读失败不许冒充「仓库里没有 Issue」，且不许污染缓存 ---
src.reset_cache()
calls = {"n": 0}
def fake_400(argv, timeout=180):
    calls["n"] += 1
    return 3, "status: 400\nerrcode: 400\nerrmsg: bad request", ""
bad = src.existing(REPO, runner=fake_400)
assert bad["ok"] is False and bad["items"] == [] and "失败" in bad["error"], bad
before = calls["n"]
assert before >= 1, "根本没真调 CLI 就读失败，说明在读缓存"
# 缓存未被污染：下一次重探会真的再调（失败不写缓存）
again = src.existing(REPO, runner=fake_ok)
assert again["ok"] is True and again["items"], "一次 400 被永久缓存 → 幂等再也不恢复"
third = src.existing(REPO, runner=fake_400)
assert third["ok"] is True and third["items"], "成功读到非空后应命中缓存，不再受 400 影响"
# rc=0 但响应体是 errcode 也算失败（别拿错误响应当清单解析）
def fake_body_err(argv, timeout=180):
    return 0, "status: 500\nerrcode: 500\nerrmsg: internal error", ""
assert src.fetch_issues(REPO, runner=fake_body_err)["ok"] is False

# --- ③ 半途失败整体失败（不返回半份清单冒充全量）---
src.reset_cache()
def fake_second_page_fail(argv, timeout=180):
    if "--page" in argv and argv[argv.index("--page") + 1] == "2":
        return 3, "boom", ""
    return 0, ('totalPages: 3\ndata[1]:\n  - number: "1"\n    title: "x"\n'), ""
half = src.fetch_issues(REPO, runner=fake_second_page_fail)
assert half["ok"] is False and half["items"] == [], half
# closed 那趟失败也是整体失败（不许只交半份存量冒充全量）
def fake_closed_fail(argv, timeout=180):
    if "--state" in argv and argv[argv.index("--state") + 1] == "closed":
        return 3, "boom", ""
    return 0, ('totalPages: 1\ndata[1]:\n  - number: "1"\n    title: "x"\n'), ""
half2 = src.fetch_issues(REPO, runner=fake_closed_fail)
assert half2["ok"] is False and half2["items"] == [], half2

# --- ④ 新建回填 → 同批第 2 条起就能 reuse（否则同批去重不成立）---
src.reset_cache()
src.remember(REPO, "77", "开发登录模块")
after = src.existing(REPO, runner=lambda a, timeout=180: (0, 'totalPages: 1\ndata[0]:\n', ""))
assert any(i["number"] == "77" for i in after["items"]), "新建未回填 → 同批内重复建"
g = ic.guard_create("开发登录模块", after["items"])
assert g["action"] == "reuse" and g["reuse_number"] == "77", g

# --- ⑤ 唯一键不塌缩：不同诉求必须是不同 key（否则两件事被静默并成一件）---
pairs = [("API 接口改造", "登录模块 API"), ("开发登录模块 API", "CLI控制台发起二版"),
         ("fix 登录", "fix 支付"), ("PR 修复登录崩溃", "PR 修复支付超时"),
         # 这两条只能靠"覆盖率"判据挡（残片是合法词、不在关键字黑名单里）：
         # 光靠黑名单会漏，必须真算 ascii 覆盖了原文多少有效字符
         ("开发登录模块 v2beta", "结算模块 v2beta")]
for a, b in pairs:
    ka = ic.issue_key(ic.guard_create(a, [])["title"])
    kb = ic.issue_key(ic.guard_create(b, [])["title"])
    assert ka != kb, f"{a!r} 与 {b!r} 塌成同一个 key {ka!r} → 第二件事会被并进第一件"
# 同一诉求必须稳定（幂等的根）
assert ic.guard_create("API 接口改造", [])["title"] == ic.guard_create("API 接口改造", [])["title"]
# 内容全是 ascii 的照常可读，不被摘要化
assert ic.slugify_key("refactor login module") == "refactor-login-module"
# 有中文被丢弃时：可读残片 + 内容摘要后缀（可读性让位唯一性，绝不吞任务）
k1 = ic.slugify_key("update README 说明文档")
k2 = ic.slugify_key("update README 使用手册")
assert k1.startswith("update-readme-") and k2.startswith("update-readme-"), (k1, k2)
assert k1 != k2, "换一个字就是另一件事，不能共用一个键"
assert ic.issue_key(ic.build_title("CHORE", "local-agent", k1)), "带后缀的键仍须合法"

# --- ⑥ derive 后必须复核：占位词当唯一键不得放行 ---
for bad_title in ("p0", "tmp", "todo"):
    gg = ic.guard_create(bad_title, [])
    assert gg["action"] in ("create", "reject"), gg
    if gg["action"] == "create":
        low, why = ic.is_low_signal(gg["title"])
        assert low is False, f"{bad_title!r} 契约化后仍是低信号却被放行：{gg}"
# 空标题无法摘要 → 明确拒绝，不造垃圾
assert ic.guard_create("", [])["action"] == "reject"
assert ic.guard_create("   ", [])["action"] == "reject"

# --- ⑦ 三处出口的 action 分支真判（reject 不回落原标题 / reuse 不建新）---
import inspect
import dispatch_engine
d_src = inspect.getsource(dispatch_engine._create_issue)
assert 'action == "reject"' in d_src and 'action == "reuse"' in d_src, \
    "dispatch_engine 未按 action 分支处理（reject/reuse 会被当成 create）"
from entries import cnb_live
c_src = inspect.getsource(cnb_live.send)
assert '"reject"' in c_src, "cnb_live.send 未处理 reject（会静默回落原标题建垃圾）"
from hybrid import batch as _batch
b_src = inspect.getsource(_batch.CloudBatch._create_issue)
assert '"reject"' in b_src and '"reuse"' in b_src, \
    "hybrid.batch 未按 action 分支处理（空清单 + 回落原标题）"

# --- ⑧ 真行为（不是看源码字符串）：派发器同批去重 / 不吞任务 / 拒绝不建 ---
src.reset_cache()
created_titles = []
class _Res(object):
    def __init__(self, out, rc=0):
        self.stdout, self.stderr, self.returncode = out, "", rc

def _fake_run(cmd, **kw):
    if "create-issue" in cmd:
        n = 500 + len(created_titles)
        title = cmd[cmd.index("--title") + 1]
        created_titles.append(title)
        return _Res('data:\n  number: "%s"\n' % n)
    if "list-issues" in cmd:
        bucket = src._CREATED.get("acme/d", [])
        if not bucket:
            return _Res("totalPages: 1\ndata[0]:\n")
        lines = ["totalPages: 1", "data[%d]:" % len(bucket)]
        for it in bucket:
            lines += ['  - number: "%s"' % it["number"], "    title: %s" % it["title"]]
        return _Res("\n".join(lines))
    return _Res("")

dispatch_engine.subprocess.run = _fake_run     # 只替换本进程内的调用，不动真实 CLI
ids = [dispatch_engine._create_issue("acme/d", "开发登录模块", "b") for _ in range(3)]
assert len(ids) == 3 and ids[0] == ids[1] == ids[2], f"同批同名应只建一条，实际 {ids}"
assert len(created_titles) == 1, f"同批重复建了 {len(created_titles)} 条：{created_titles}"
# 不同诉求不许被并成一件（第二件事必须真的建出来）
other = [dispatch_engine._create_issue("acme/d", t, "b")
         for t in ("API 接口改造", "登录模块 API")]
assert len(set(other)) == 2, f"两件不同的事被并成一件：{other}"
assert len(created_titles) == 3, created_titles
# 拒绝路径不建、不回落原标题
assert dispatch_engine._create_issue("acme/d", "", "b") is None
assert len(created_titles) == 3, "空标题被建成垃圾 Issue"

# --- ⑨ bridge：同诉求复用锚点，不新建第二条 ---
from entries import cnb_live as _live
src.reset_cache()
live_calls = []
def _fake_cnb(args, timeout=60):
    live_calls.append(list(args))
    if "list-issues" in args:
        bucket = src._CREATED.get("acme/d", [])
        if not bucket:
            return {"ok": True, "raw": "totalPages: 1\ndata[0]:\n"}
        lines = ["totalPages: 1", "data[%d]:" % len(bucket)]
        for it in bucket:
            lines += ['  - number: "%s"' % it["number"], "    title: %s" % it["title"]]
        return {"ok": True, "raw": "\n".join(lines)}
    if "create-issue" in args:
        return {"ok": True, "raw": 'data:\n  number: "900"\n'}
    return {"ok": True, "raw": ""}
_real_run_cnb = _live._run_cnb
_live._run_cnb = _fake_cnb
try:
    h = {"req": "开发登录模块", "entry": "local"}
    r1 = _live.send(h, repo="acme/d")
    r2 = _live.send(h, repo="acme/d")
    assert r1["cloud_ref"]["issue_id"] == "900", r1
    assert r2["cloud_ref"]["issue_id"] == "900", r2
    assert sum(1 for c in live_calls if "create-issue" in c) == 1, \
        "同诉求第二次又新建了锚点 Issue（幂等没生效）"
finally:
    _live._run_cnb = _real_run_cnb

print("  存量读取/失败不缓存/同批回填/唯一键不塌缩/derive复核/action分支/真行为去重 全部通过")
EOF
then ok "E10 闸门两端判定为真（读得到存量 · 失败不缓存 · 不塌缩不吞任务 · 按 action 分支）"; else bad "E10 闸门行为判定失败"; fi

echo "===== [expertise] E11. 卡片修复的行为验证（长标题不塌缩 · 批量不吞活 · 文档不自相矛盾）====="
if "$PY" - <<'EOF'
import sys, json, os; sys.path.insert(0, '.')
from expertise import issue_contract as ic
from expertise import issue_source as src

# --- ① 英文长标题超 48 字符仍不许塌缩（残片截断后必须带摘要后缀）---
# 原实现：`_ascii_coverage>=0.999` 就 `return ascii_part`，而 ascii_part 已被截到
# 48 字符 → 第 48 字符之后不参与唯一性 → 两条不同诉求压出同一个键 → 第二条被 reuse
# 并进第一条的 Issue（比重复更糟）。E10 第⑤组用例全在 48 字符内，覆盖不到这一层。
LONG_A = "Update the cloud pipeline stage one description with more detail AAAA"
LONG_B = "Update the cloud pipeline stage one description with more detail BBBB"
assert len(ic._SLUG_RE.sub("-", LONG_A.lower()).strip("-")) > 48, "用例没超过 48 字符，测不到截断"
kA, kB = ic.slugify_key(LONG_A), ic.slugify_key(LONG_B)
assert kA != kB, f"超长英文标题仍塌缩：{kA!r} == {kB!r}"
keyA = ic.issue_key(ic.guard_create(LONG_A, [])["title"])
keyB = ic.issue_key(ic.guard_create(LONG_B, [])["title"])
assert keyA != keyB, "闸门层面仍把两件事并成一件"
# 截断后仍要可读（残片当线索），不能直接退化成纯摘要
assert kA.startswith("update-the-cloud-pipeline-stage-one"), kA
# 同一诉求稳定（幂等的根没被破坏）
assert ic.guard_create(LONG_A, [])["title"] == ic.guard_create(LONG_A, [])["title"]
# 短纯 ascii 照旧可读（不能被顺手改成摘要）
assert ic.slugify_key("refactor login module") == "refactor-login-module"

# --- ② hybrid.batch：不同批次不得互相 reuse 吞活 ---
from hybrid import batch as B
t_batch1 = [{"title": "登录模块改造", "description": "第一批 A"},
            {"title": "结算模块改造", "description": "第一批 B"}]
t_batch2 = [{"title": "登录模块改造", "description": "第二批 A 不同"},
            {"title": "结算模块改造", "description": "第二批 B 不同"}]
def _title(tasks):
    return "[批量] %s 等 %d 个任务（CloudBatch · %s）" % (
        tasks[0]["title"][:20], len(tasks), B._batch_fingerprint(tasks))
ta, tb = _title(t_batch1), _title(t_batch2)
assert ta != tb, "两批不同任务仍同标题 → 过闸门必被判 reuse"
assert ic.issue_key(ic.guard_create(ta, [])["title"]) != \
       ic.issue_key(ic.guard_create(tb, [])["title"]), "两批不同任务仍塌成一个 key"
# 真跑 flush：走真实路径（假云端），验证队列不被静默清空
import urllib.request
created = []
class _Resp(object):
    def __init__(self, d): self._d, self.status = d, 200
    def read(self): return json.dumps(self._d).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
def _fake_urlopen(req, timeout=20):
    body = json.loads(req.data.decode())
    created.append(body)
    return _Resp({"number": str(700 + len(created)), "title": body["title"],
                  "state": "open"})
urllib.request.urlopen = _fake_urlopen
os.environ.setdefault("cnbcooldong", "x")
src.reset_cache()
q = "/tmp/expertise_e11_queue.json"
if os.path.exists(q):
    os.remove(q)
b = B.CloudBatch(repo="acme/b", min_tasks=1, queue_file=q)
b.enqueue("登录模块改造", "第一批 A")
b.enqueue("结算模块改造", "第一批 B")
r1 = b.flush()
assert r1.get("submitted") == 2 and len(created) == 1, r1
b.enqueue("登录模块改造", "第二批 A 不同")
b.enqueue("结算模块改造", "第二批 B 不同")
r2 = b.flush()
assert len(created) == 2, "第二批新任务被静默吞掉（队列清了、body 从未发出）"
assert r2.get("submitted") == 2 and r2.get("queue_cleared") == 2, r2
assert b._load()["tasks"] == [], "提交成功后队列应清空"
# 同一批再 flush = 真重复：命中的是同一批内容 → 不新建、队列清、如实标 duplicate
b.enqueue("登录模块改造", "第二批 A 不同")
b.enqueue("结算模块改造", "第二批 B 不同")
r3 = b.flush()
assert len(created) == 2, "同批重复 flush 又新建了 Issue"
assert r3.get("duplicate") is True and r3.get("submitted") == 0, r3
# 命中标题与本批不一致时（脏存量同名/键塌缩）→ 保留队列 + 显式报错，绝不静默吞活
class _FakeBatch(B.CloudBatch):
    matched = ""
    def _create_issue(self, title, body):
        gate = {"matched_title": self.matched} if self.matched is not None else {}
        return {"number": "1234", "reused": True, "title": title,
                "gate": gate, "url": "x"}
fb = _FakeBatch(repo="acme/b", min_tasks=1, queue_file=q)
# ① 命中标题与本批不一致（脏存量同名/键塌缩）→ 保留队列 + 显式报错
fb.matched = "CHORE:local-agent · 别的东西"
fb.enqueue("测试流任务", "内容")
kept = fb.flush()
assert kept.get("error") and kept.get("queue_cleared") == 0, kept
assert len(fb._load()["tasks"]) == 1, "内容不一致却清了队列 → 活被吞了"
# ② 拿不到命中标题（gate 没给 matched_title）同样不许当核对通过
fb.matched = None
kept2 = fb.flush()
assert kept2.get("error") and kept2.get("queue_cleared") == 0, kept2
assert len(fb._load()["tasks"]) == 1, "未知命中标题被当核对通过 → 活被吞了"

# --- ③ issue_source 文档不许再自相矛盾（「全量=不带 --state」是错的）---
_flat = " ".join((src.__doc__ or "").split()).replace("`", "")
assert "分别拉 open + closed 再合并" in _flat, \
    "全量语义必须写明 open+closed 两趟（不带 --state 只返回 open）"
assert "全量语义 = 不带" not in _flat, \
    "文档又写回「全量=不带 --state」→ 后来者照改会丢 218 条 closed 存量"

print("  超长标题不塌缩/批量不吞活/同批真重复/内容不符不静默/文档不自相矛盾 全部通过")
EOF
then ok "E11 本轮三条卡点的行为验证（长标题不塌缩 · 批量不吞活 · 文档自洽）"; else bad "E11 本轮卡点行为验证失败"; fi

echo ""
echo "──────────────────────────────────────────────"
echo "expertise 信号灯：通过 $PASS 组，失败 $FAIL 组"
if [ "$FAIL" -ne 0 ]; then
  printf '  失败项：%s\n' "${FAILED_ITEMS[@]}"
  exit 1
fi
echo "✅ 专家级架构能力全部通过"
