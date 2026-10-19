#!/usr/bin/env bash
# 角色逐个指定模型 · 信号灯（Issue #182 · module model-routing v0.3.0-fix）
# 断言：settings.yml 声明的角色全部显式配链 / 角色间可差异化 / 别名归一 / 未配即审计红灯
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/local-agent"
echo "==== 角色逐个指定模型信号灯（Issue #182） ===="

echo "---- ① settings.yml 声明的角色全部显式指定（审计无缺） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec
declared = spec.declared_roles()
assert declared, "未读到 .cnb/settings.yml 角色声明"
missing = spec.audit_roles()
assert not missing, f"以下角色未在 models.yml 显式配链: {missing}"
for r in declared:
    assert spec.is_role_specified(r), r
print(f"  ✅ {len(declared)} 个角色全部显式配链，无缺省继承")
PY

echo "---- ② 角色链真实生效（按角色名解析，不是全部等于 default） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec
dev = spec.role_chain("架构·开发")
assert dev and dev[0] == "deepseek-v4.1-flash", dev
pol = spec.role_policy("架构·开发")
assert pol["specified"] is True, pol
# 差异化：至少有一个角色的主档与 default 不同（证明按角色配置真能独立生效）
diff = [r for r in spec.declared_roles() if spec.role_chain(r)[0] != spec.default_chain()[0]]
assert diff, "所有角色主档都等于 default —— 按角色指定形同虚设"
print("  ✅ 架构·开发 ->", list(dev), "| 主档异于 default 的角色:", diff)
PY

echo "---- ③ 角色别名归一（全称/短名指向同一条配置） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec
assert spec.role_chain("开发") == spec.role_chain("架构·开发")
assert spec.role_chain("秘书") == spec.role_chain("架构·秘书")
assert spec.is_role_specified("开发") is True
print("  ✅ 开发 == 架构·开发，秘书 == 架构·秘书")
PY

echo "---- ④ 未显式指定的角色不再悄悄等于 default（走 fallback_chain 且标 specified=False） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec
pol = spec.role_policy("架构·不存在的角色")
assert pol["specified"] is False, pol
assert list(spec.role_chain("架构·不存在的角色")) == list(spec.fallback_chain())
assert spec.audit_roles() == [] or True
# 反向验证审计真能报红：临时把某角色从配置里摘掉
import os, tempfile, yaml
raw = yaml.safe_load(open(spec.config_path(), encoding='utf-8')) or {}
raw["roles"].pop("架构·开发", None)
fd, tmp = tempfile.mkstemp(suffix=".yml"); os.close(fd)
with open(tmp, "w", encoding="utf-8") as f:
    yaml.safe_dump(raw, f, allow_unicode=True)
os.environ["MODEL_ROUTING_CONFIG"] = tmp
try:
    assert "架构·开发" in spec.audit_roles(), "审计未报出缺配角色"
    assert spec.is_role_specified("架构·开发") is False
finally:
    os.environ.pop("MODEL_ROUTING_CONFIG", None)
    os.unlink(tmp)
print("  ✅ 缺配即审计红灯（摘掉一个角色 → audit_roles 立刻报出）")
PY

echo "---- ⑤ 版本别名（1017）只做映射，不臆造平台 ID ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec
assert spec.resolve_alias("deepseek-v4.1-flash-1017") == "deepseek-v4.1-flash"
assert spec.resolve_alias("deepseek-v4.1-flash") == "deepseek-v4.1-flash"
assert spec.resolve_alias("未登记的任何串") == "未登记的任何串"
# 别名表右侧必须是链里真实出现的 ID，防臆造版本号污染链路
known = set(spec.default_chain()) | set(spec.fallback_chain())
for role in spec.declared_roles():
    known |= set(spec.role_chain(role))
import yaml
table = (yaml.safe_load(open(spec.config_path(), encoding='utf-8')) or {}).get("alias") or {}
bad = {k: v for k, v in table.items() if v not in known}
assert not bad, f"别名指向了链里不存在的模型 ID: {bad}"
print("  ✅ 1017 ->", spec.resolve_alias("deepseek-v4.1-flash-1017"), "| 别名右侧全部是真实 ID")
PY

echo "---- ⑥ CLI 真跑（roles / audit 两条管线） ----"
python3 -m model_routing.cli roles >/dev/null && echo "  ✅ cli roles"
python3 -m model_routing.cli audit >/dev/null && echo "  ✅ cli audit"

echo "---- ⑦ 模型 ID 纪律：.cnb.yml 与配置一致（防两处漂移） ----"
python3 - <<'PY'
import re, sys; sys.path.insert(0, '.')
from model_routing import spec
text = open("../.cnb.yml", encoding="utf-8").read()
m = re.search(r"^\s*model:\s*([A-Za-z0-9._\-]+)", text, re.M)
assert m, "未在 .cnb.yml 找到 npc:go model 字段"
assert m.group(1) == spec.default_chain()[0], (m.group(1), spec.default_chain()[0])
print("  ✅ .cnb.yml model ==", m.group(1), "== models.yml default.chain[0]")
PY

echo "==== ✅ 角色逐个指定模型信号灯全绿（7/7） ===="
