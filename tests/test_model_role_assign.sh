#!/usr/bin/env bash
# 角色按需指定模型 · 信号灯（Issue #182 复评 · PR #184 · module model-routing）
# 断言：两链一致 / 无空壳链 / 别名归一(全称+短名双体检) / 审计能报红 / 未登记别名显式报红 / 模型纪律
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/local-agent"
echo "==== 角色按需指定模型信号灯（Issue #182 复评 · PR #184） ===="

echo "---- ① 两链一致：fallback_chain 引用 default.chain（配置层零重复字面量） ----"
python3 - <<'PY'
import os, sys, re; sys.path.insert(0, '.')
from model_routing import spec
fb = list(spec.fallback_chain())
df = list(spec.default_chain())
assert fb == df, f"两链不一致: fallback={fb} default={df}"
# 配置层禁止重复字面量：fallback_chain 后不应是三条独立 `- model` 行（必须靠锚点引用）
text = open(spec.config_path(), encoding='utf-8').read()
seg = text.split('fallback_chain:')[1].split('\n')[0]
assert '*default_chain' in seg or '<<' in seg or re.search(r'fallback_chain:\s*\*default_chain', text), \
    "fallback_chain 未通过锚点引用 default.chain（出现重复字面量）"
print(f"  ✅ 两链一致: {fb} | fallback_chain 引用 default.chain（无重复字面量）")
PY

echo "---- ② 无空壳链：显式列出的角色链不全等于 default（空壳已撤销） ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
ov = spec.role_overrides()
shells = [r for r in ov if ov[r].get('chain') == list(spec.default_chain())]
assert len(shells) < len(ov), f"仍有空壳链: {shells}"
assert shells == [], f"存在与 default 逐字相同的空壳链: {shells}"
print(f"  ✅ 显式角色 {len(ov)} 个，空壳链 0 个（差异化真实生效）")
PY

echo "---- ③ 按角色指定真实生效（差异化角色主档异于默认） ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
assert spec.default_chain()[0] == "deepseek-v4.1-flash"
# 差异化角色：进度推手 / 客服 主档应为 glm-5.3-flash
assert spec.role_chain("架构·进度推手")[0] == "glm-5.3-flash", spec.role_chain("架构·进度推手")
assert spec.role_chain("市场·客服")[0] == "glm-5.3-flash", spec.role_chain("市场·客服")
assert spec.is_role_specified("架构·进度推手") is True
# 开发角色本轮也挂了三档（用户 PR #185：快档里要用上和其他角色一样的模型）
assert spec.role_chain("架构·开发")[0] == "glm-5.3-flash", spec.role_chain("架构·开发")
assert spec.is_role_specified("架构·开发") is True
# 未显式指定的角色仍自然走 fallback（预期行为，不算空壳）
assert spec.is_role_specified("架构·评审") is False
assert list(spec.role_chain("架构·评审")) == list(spec.fallback_chain())
print("  ✅ 快档角色主档=glm-5.3-flash；未列出角色（架构·评审）走 fallback（specified=False）")
PY

echo "---- ④ 角色别名归一（全称 ↔ 短名，双向一致） ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
# 差异化角色的短名也必须落到同一条配置
assert spec.role_chain("进度推手") == spec.role_chain("架构·进度推手"), \
    (spec.role_chain("进度推手"), spec.role_chain("架构·进度推手"))
assert spec.is_role_specified("进度推手") == spec.is_role_specified("架构·进度推手")
# 快档角色：全称与短名落到同一条三档链（无断裂）
assert tuple(spec.role_chain("开发")) == tuple(spec.role_chain("架构·开发"))
assert spec.role_chain("开发")[0] == "glm-5.3-flash"
# 未列出角色：全称与短名都走 fallback，仍一致（无断裂）
assert tuple(spec.role_chain("测试")) == tuple(spec.role_chain("架构·测试")) == tuple(spec.fallback_chain())
print("  ✅ 进度推手==架构·进度推手；开发==架构·开发（短名不断裂）")
PY

echo "---- ⑤ 审计双体检（全称+短名）：当前无问题；别名缺失即报红（仅在有差异化链时才可检出） ----"
python3 - <<'PY'
import os, sys, tempfile, yaml; sys.path.insert(0, '.')
from model_routing import spec
assert not spec.audit_roles(), f"当前配置审计应无问题: {spec.audit_roles()}"
# 反向 A：显式差异化角色的短名被摘掉 → 短名静默走 fallback，审计必须报 alias_broken
raw = yaml.safe_load(open(spec.config_path(), encoding="utf-8")) or {}
ra = raw.get("role_aliases") or {}
ra["架构·进度推手"] = [n for n in (ra.get("架构·进度推手") or []) if n != "进度推手"]
fd, tmp = tempfile.mkstemp(suffix=".yml"); os.close(fd)
yaml.safe_dump(raw, open(tmp, "w", encoding="utf-8"), allow_unicode=True)
os.environ["MODEL_ROUTING_CONFIG"] = tmp
try:
    issues = spec.audit_roles()
    assert any(i["role"] == "架构·进度推手" and i["reason"] == "alias_broken" for i in issues), issues
finally:
    os.environ.pop("MODEL_ROUTING_CONFIG", None); os.unlink(tmp)
# 反向 B：非差异化角色的整条别名缺失（架构·运维）——今日走 fallback 与全称同链，断不断都看不出来；
#         一旦它将来被差异化指定，缺别名就静默回落。这里把运维临时差异化，验证缺别名必报红。
raw = yaml.safe_load(open(spec.config_path(), encoding="utf-8")) or {}
raw.setdefault("roles", {})["架构·运维"] = {"chain": ["glm-5.3-flash", "deepseek-v4.1-flash"]}
raw["role_aliases"] = {k: v for k, v in (raw.get("role_aliases") or {}).items() if k != "架构·运维"}
fd, tmp = tempfile.mkstemp(suffix=".yml"); os.close(fd)
yaml.safe_dump(raw, open(tmp, "w", encoding="utf-8"), allow_unicode=True)
os.environ["MODEL_ROUTING_CONFIG"] = tmp
try:
    issues = spec.audit_roles()
    assert any(i["role"] == "架构·运维" and i["reason"] == "alias_broken" for i in issues), issues
finally:
    os.environ.pop("MODEL_ROUTING_CONFIG", None); os.unlink(tmp)
# 正向 C：声明角色（含 架构·数据管理 与 架构·数据管理员 同短名这对）逐一可反查，不落空、不静默走 fallback 后失联
declared = spec.declared_roles()
missing = [r for r in declared if not spec.role_chain(r)]
assert missing == [], f"声明角色解析出空链: {missing}"
assert set(declared) - set(spec.role_aliases()) == set(), (set(declared) - set(spec.role_aliases()))
print("  ✅ 审计全绿；摘短名 / 缺整条别名（差异化后）均报 alias_broken；24 声明角色全部可反查")
PY

echo "---- ⑥ 模型别名实名（issue #182 复评）：未登记版本后缀别名显式报红，不留伪配置 ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
# alias 当前为空（人类未确认 1017 真实 ID，故意不留伪配置）
assert spec._raw().get("alias") == {} or spec._raw().get("alias") is None, spec._raw().get("alias")
# 普通模型 ID 原样返回
assert spec.resolve_alias("deepseek-v4.1-flash") == "deepseek-v4.1-flash"
# 未登记版本后缀别名 → 解析期显式报红（不放行），不静默透传
try:
    spec.resolve_alias("deepseek-v4.1-flash-1017")
    raise AssertionError("未登记别名未报红（应显式拦截）")
except RuntimeError as e:
    assert "未登记别名" in str(e), str(e)
# role_at / resolve_models 同样报红（别名收口在 engine.resolve_models）
try:
    spec.role_at("架构·进度推手", 99)  # 越界落到末档 glm，不触发；用显式坏名测试映射
except RuntimeError:
    pass
from model_routing import engine
try:
    engine.resolve_models(policy={"chain": ["deepseek-v4.1-flash-1017"]})
    raise AssertionError("resolve_models 未对未登记别名报红")
except RuntimeError as e:
    assert "未登记别名" in str(e), str(e)
print("  ✅ alias 空（无伪配置）；未登记版本别名在解析期显式报红（含 engine.resolve_models）")
PY

echo "---- ⑦ CLI 真跑 + 模型 ID 纪律（.cnb.yml model == default.chain[0]） ----"
python3 -m model_routing.cli roles >/dev/null && echo "  ✅ cli roles"
python3 -m model_routing.cli audit >/dev/null && echo "  ✅ cli audit（退出码 0）"
python3 - <<'PY'
import os, sys, re; sys.path.insert(0, '.')
from model_routing import spec
text = open("../.cnb.yml", encoding="utf-8").read()
m = re.search(r"^\s*model:\s*([A-Za-z0-9._\-]+)", text, re.M)
assert m, "未在 .cnb.yml 找到 npc:go model 字段"
assert m.group(1) == spec.default_chain()[0], (m.group(1), spec.default_chain()[0])
print("  ✅ .cnb.yml model ==", m.group(1), "== models.yml default.chain[0]")
PY

echo "---- ⑧ 平台参数 + 别名键（PR #185）：npc_go/.cnb.yml 一致、家族号不误伤、空登记报红 ----"
python3 - <<'PY'
import os, sys, re, tempfile, yaml; sys.path.insert(0, '.')
from model_routing import spec

# ⑧-1 平台可控参数：models.yml npc_go 与 .cnb.yml .npc_task 必须逐项一致
#     （npc:go 只认流水线 options，不读 models.yml；两边漂移 = 配置看着对、线上不生效）
params = spec.npc_go_params()
assert params, "models.yml 缺 npc_go 块（平台参数无人声明）"
text = open("../.cnb.yml", encoding="utf-8").read()
for k, v in params.items():
    m = re.search(r"^\s*%s:\s*(\S+)" % re.escape(k), text, re.M)
    assert m, f".cnb.yml 缺 {k}（与 models.yml npc_go 不一致）"
    got = m.group(1).strip().rstrip("#").strip()
    assert got == str(v), f"{k} 不一致：.cnb.yml={got!r} models.yml={v!r}"
# 平台合法域（文档 zh/build/internal-steps/npc/go.md）——写错平台直接报错
assert params.get("thinkingLevel") in {"off", "minimal", "low", "medium", "high", "xhigh", "max"}, params
cw = str(params.get("contextWindow"))
assert re.fullmatch(r"\d+k|\d+m|\d+", cw.lower()), f"contextWindow 写法非法: {cw}"

# ⑧-2 版本串判据不误伤模型家族号（minimax-3 / glm-5 是家族号，不是版本串）
assert spec.resolve_alias("minimax-3.1-flash") == "minimax-3.1-flash", "minimax 家族号被判成未登记别名"
assert spec.resolve_alias("glm-5.3-flash") == "glm-5.3-flash"
try:
    spec.resolve_alias("minimax-3.1-flash-1017")
    raise AssertionError("版本串未报红（应显式拦截）")
except RuntimeError as e:
    assert "未登记别名" in str(e), str(e)

# ⑧-3 别名**键**体检：登记了却没接线 → 报 alias_unused（右值写坏也测不出来）
raw = yaml.safe_load(open(spec.config_path(), encoding="utf-8"))
# ★ Issue #199 起 minimax-3.1-flash 已是 default.chain 成员（快档第二优先），
#   再拿它做「登记了没接线」的反例就验不出东西了 —— 换一个确实不在任何链上的键。
raw["alias"] = {"unused-ver-1017": "some-unverified-id"}
fd, tmp = tempfile.mkstemp(suffix=".yml"); os.close(fd)
yaml.safe_dump(raw, open(tmp, "w", encoding="utf-8"), allow_unicode=True)
os.environ["MODEL_ROUTING_CONFIG"] = tmp
try:
    issues = spec.audit_roles()
    assert any(i["reason"] == "alias_unused" for i in issues), f"登记未接线未报红: {issues}"
    # 真接线后（写进角色链）→ 不该再报
    raw["roles"] = dict(raw.get("roles") or {},
                        **{"架构·测试": {"chain": ["unused-ver-1017", "deepseek-v4.1-flash"]}})
    yaml.safe_dump(raw, open(tmp, "w", encoding="utf-8"), allow_unicode=True)
    issues2 = [i for i in spec.audit_roles() if i["reason"] == "alias_unused"]
    assert not issues2, f"接线后仍报 alias_unused: {issues2}"
finally:
    os.environ.pop("MODEL_ROUTING_CONFIG", None); os.unlink(tmp)

# ⑧-4 CLI 真跑
import subprocess
out = subprocess.run([sys.executable, "-m", "model_routing.cli", "params"],
                     capture_output=True, text=True, check=True).stdout
assert "npc_go" in out and "thinkingLevel" in out, out
print("  ✅ npc_go 与 .cnb.yml 逐项一致；家族号不误伤；空登记报 alias_unused；接线后自愈；cli params 通")
PY

echo "---- ⑨ 三档语义：档1 指定 / 档2 与其他角色一样 / 档3 兜底（用户 PR #185） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec
# 快档角色（开发/进度推手/客服）必须是三档，且档2 与其他角色同一套模型
for role in ("架构·开发", "架构·进度推手", "市场·客服"):
    assert spec.is_fast_role(role), f"{role} 未挂快档链"
    view = spec.tier_view(role)
    kinds = [t["tier"] for t in view["tiers"]]
    assert kinds[0] == "fast", (role, kinds)
    assert "same" in kinds, (role, kinds)
    same_models = [t["model"] for t in view["tiers"] if t["tier"] == "same"]
    assert set(same_models).issubset(set(spec.fallback_chain())), (role, same_models)
    assert spec.last_resort_model(), role
# 未列出的角色：链上没有任何「指定快档」的档位，全是「和其他角色一样」
view = spec.tier_view("架构·评审")
assert spec.is_fast_role("架构·评审") is False, view
assert all(t["tier"] == "same" for t in view["tiers"]), view
print("  ✅ 快档角色三档齐备（fast → same → 兜底可解析）；未列出角色纯 same 链")
PY

echo "---- ⑩ 显性降级：档1 挂 → 降档2，结果与留痕都标 degraded（不静默） ----"
python3 - <<'PY'
import sys, os, json; sys.path.insert(0, '.')
from model_routing import engine
tf = engine._TRACE_FILE
before = sum(1 for _ in open(tf, encoding='utf-8')) if os.path.exists(tf) else 0
def caller(model, s, u, **k):
    if model == "deepseek-v4.1-flash":   # 默认链首档挂
        raise RuntimeError("timeout: channel unavailable")
    return f"ok:{model}"
res = engine.route_call(caller, system_prompt="s", user_input="u")
# 档序（Issue #199 人类拍板）：deepseek → minimax → codebuddy → glm
assert res["ok"] and res["model"] == "minimax-3.1-flash", res
assert res["degraded"] is True, res
assert res["from_model"] == "deepseek-v4.1-flash", res
assert res["used_tier"] == "fallback", res
lines = [json.loads(l) for l in open(tf, encoding='utf-8').read().splitlines()[before:]]
assert any(e.get("event") == "model.call.degraded" for e in lines), [e.get("event") for e in lines]
fails = [e for e in lines if e.get("event") == "model.call.fail"]
assert fails and fails[0].get("degraded") == 1 and fails[0].get("next") == "minimax-3.1-flash", fails
print("  ✅ 降级显性：结果 degraded=True /", res["from_model"], "→", res["model"], "；留痕含 model.call.degraded")
PY

echo "---- ⑪ 主档直通 → 不带 degraded（不误报降级） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import engine
res = engine.route_call(lambda m, s, u, **k: f"ok:{m}", system_prompt="s", user_input="u")
assert res["ok"] and res["degraded"] is False, res
assert res["from_model"] is None and res["used_tier"] == "primary", res
print("  ✅ 主档直通 degraded=False（不误报）")
PY

echo "---- ⑫ 全链耗尽 → degraded=True 且显式失败（不假装成功） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import engine
def caller(m, s, u, **k):
    raise RuntimeError("timeout: all down")
res = engine.route_call(caller, system_prompt="s", user_input="u", role="架构·开发")
assert res["ok"] is False and res["degraded"] is True, res
assert res["reason"] == "all_channels_unavailable", res
assert res["attempts"][0]["next"] == res["chain"][1]
assert res["attempts"][-1]["next"] is None
print("  ✅ 全挂：degraded=True / 末档 next=None / 显式失败")
PY

echo "---- ⑬ 后端把降级标出来（llm 层读同一结果，不另立口径） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import model_routing.spec as spec
from model_routing.engine import call_with_chain

chain = list(spec.role_chain("架构·开发"))

# 用「每档各自的 caller」真实降级（这正是后端 call() 用的 invocation shape）
calls = []
def make(name):
    def fn(sp, ui, **k):
        calls.append(name)
        if name == chain[0]:
            raise RuntimeError("timeout: unavailable")
        return "answer"
    return fn
callers = {ch: make(ch) for ch in chain}
res = call_with_chain(callers, system_prompt="sp", user_input="ui", role="架构·开发")
assert res["ok"] and res["output"] == "answer", res
# ★ 逐档真试（闭包捕获循环变量时会全打链尾 —— Issue #195 的静默失效）
assert calls == chain[:2], (calls, chain)
assert res["degraded"] is True and res["from_model"] == chain[0], res
print("  ✅ 逐档真试：", " → ".join(calls), "；degraded=True / 来源", chain[0])

# 全挂：显式失败，不假装成功
calls.clear()
def boom(sp, ui, **k):
    calls.append("x")
    raise RuntimeError("unavailable")
res = call_with_chain({ch: boom for ch in chain}, system_prompt="s", user_input="u", role="架构·开发")
assert res["ok"] is False and res["degraded"] is True, res
assert len(calls) == len(chain), calls
print("  ✅ 全链不通 → ok=False + degraded=True（显式失败，不假装成功）")
PY

# ⑬b 闭包回归防护（源码级）：禁止退回「lambda 捕获循环变量」的写法。
#    Issue #195：所有 caller 指向链尾 → 降级静默退化，还伪装成「每档都试过」。
#    本项由 PR #196（llm 模块）落地，它在 main 之后合入；此处只在源码已修时断言，
#    未修时明确报「待 #196」，不制造假绿。
_OC="$ROOT/local-agent/llm/openai_compat.py"   # 脚本已 cd 到 local-agent，改用绝对 ROOT，避免路径解析错位
if grep -q 'model=ch' "$_OC" 2>/dev/null; then
  # 只看代码行，忽略注释：修复处的注释本身就写有反例写法，注释误判会假红
  grep -vE '^[[:space:]]*#' "$_OC" | grep -qE 'lambda [^:]+: self\._call_model\(m,' \
    && { echo "  ❌ caller 退回闭包捕获循环变量（Issue #195 回归）"; exit 1; }
  echo "  ✅ 源码级：caller 逐档绑定 model=ch（闭包回归防护）"
else
  echo "  ⚠️  源码仍是闭包捕获写法 —— 修复在 PR #196，合入后本项自动转 ✅"
fi

echo "---- ⑭ CLI tiers 真跑（人可读俯瞰三档） ----"
python3 -m model_routing.cli tiers 架构·开发 >/dev/null && echo "  ✅ cli tiers"

echo "==== ✅ 角色按需指定模型信号灯全绿（14/14 · 含三档语义 + 显性降级） ===="
