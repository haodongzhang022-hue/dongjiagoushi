#!/usr/bin/env bash
# 角色按需指定模型 · 信号灯（Issue #182 复评 · PR #184 · module model-routing）
# 断言：两链一致 / 无空壳链 / 别名归一(全称+短名双体检) / 审计能报红 / 未登记别名显式报红 / 模型纪律
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/local-agent"
echo "==== 角色按需指定模型信号灯（Issue #182 复评 · PR #184/#185） ===="

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
# 未显式指定的角色自然走 fallback（预期行为，不算空壳）
assert spec.is_role_specified("架构·开发") is False
assert list(spec.role_chain("架构·开发")) == list(spec.fallback_chain())
print("  ✅ 差异化角色主档=glm-5.3-flash；非差异化角色走 fallback（specified=False）")
PY

echo "---- ④ 角色别名归一（全称 ↔ 短名，双向一致） ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
# 差异化角色的短名也必须落到同一条配置
assert spec.role_chain("进度推手") == spec.role_chain("架构·进度推手"), \
    (spec.role_chain("进度推手"), spec.role_chain("架构·进度推手"))
assert spec.is_role_specified("进度推手") == spec.is_role_specified("架构·进度推手")
# 非差异化角色：全称与短名都走 fallback，仍一致（无断裂）
assert tuple(spec.role_chain("开发")) == tuple(spec.role_chain("架构·开发")) == tuple(spec.fallback_chain())
print("  ✅ 进度推手==架构·进度推手；开发==架构·开发（短名不断裂）")
PY

echo "---- ⑤ 审计双体检（全称+短名）：当前无问题；摘掉短名别名立刻报红 ----"
python3 - <<'PY'
import os, sys, tempfile, yaml; sys.path.insert(0, '.')
from model_routing import spec
assert not spec.audit_roles(), f"当前配置审计应无问题: {spec.audit_roles()}"
# 反向：临时把「架构·进度推手」的短名从 role_aliases 摘掉 → 短名静默走 fallback，审计必须报红
raw = yaml.safe_load(open(spec.config_path(), encoding='utf-8')) or {}
ra = raw.get("role_aliases") or {}
ra["架构·进度推手"] = [n for n in (ra.get("架构·进度推手") or []) if n != "进度推手"]
fd, tmp = tempfile.mkstemp(suffix=".yml"); os.close(fd)
yaml.safe_dump(raw, open(tmp, "w", encoding="utf-8"), allow_unicode=True)
os.environ["MODEL_ROUTING_CONFIG"] = tmp
try:
    issues = spec.audit_roles()
    assert any(i["role"] == "架构·进度推手" and i["reason"] == "alias_broken" for i in issues), \
        f"摘掉短名别名后审计未报红: {issues}"
finally:
    os.environ.pop("MODEL_ROUTING_CONFIG", None); os.unlink(tmp)
print("  ✅ 当前审计全绿；摘掉短名别名 → 审计立即报 alias_broken（断点②不再复发）")
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
raw["alias"] = {"minimax-3.1-flash": "some-unverified-id"}
fd, tmp = tempfile.mkstemp(suffix=".yml"); os.close(fd)
yaml.safe_dump(raw, open(tmp, "w", encoding="utf-8"), allow_unicode=True)
os.environ["MODEL_ROUTING_CONFIG"] = tmp
try:
    issues = spec.audit_roles()
    assert any(i["reason"] == "alias_unused" for i in issues), f"登记未接线未报红: {issues}"
    # 真接线后（写进角色链）→ 不该再报
    raw["roles"] = dict(raw.get("roles") or {},
                        **{"架构·测试": {"chain": ["minimax-3.1-flash", "deepseek-v4.1-flash"]}})
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

echo "==== ✅ 角色按需指定模型信号灯全绿（8/8 · 含平台参数一致性 + 别名键体检） ===="
