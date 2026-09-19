#!/usr/bin/env bash
# 模型路由信号灯（Issue #147 · module model-routing v0.2.0-update）
# 断言：统一配置文件管理 —— 不指定走 default；可按角色单独覆盖；主通道不通自动降级
set -e
cd "$(dirname "$0")/.."
echo "==== 模型路由信号灯（Issue #147 · 统一配置文件） ===="

echo "---- ① 唯一配置文件存在且可解析 ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
assert os.path.exists(spec.config_path()), f"配置文件不存在: {spec.config_path()}"
assert spec.config_path().endswith("models.yml"), spec.config_path()
d = spec.default_policy()
assert d["primary"] == "deepseek-v4.1-flash", d
assert d["fallback"] == "glm-5.3-flash", d
print("  ✅ 唯一配置文件:", spec.config_path(), d)
PY

echo "---- ② 不指定角色 → 走通用默认（default） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import resolve_models
assert resolve_models() == ["deepseek-v4.1-flash", "glm-5.3-flash"], resolve_models()
assert resolve_models(role=None) == ["deepseek-v4.1-flash", "glm-5.3-flash"]
print("  ✅ 不指定 → default:", resolve_models())
PY

echo "---- ③ 未列出的角色 → 继承 default（不指定就默认通用） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec, resolve_models
assert spec.role_policy("架构·开发没有列过") == spec.default_policy()
assert resolve_models(role="架构·未列出") == ["deepseek-v4.1-flash", "glm-5.3-flash"]
print("  ✅ 未列出角色继承 default")
PY

echo "---- ④ 某角色单独指定 → 覆盖生效（字段级覆盖，改配置文件即可） ----"
python3 - <<'PY'
import os, sys, tempfile; sys.path.insert(0, '.')
cfg = """
default:
  primary: deepseek-v4.1-flash
  fallback: glm-5.3-flash
roles:
  "架构·评审":
    primary: glm-5.3-flash
"""
fd, path = tempfile.mkstemp(suffix=".yml"); os.write(fd, cfg.encode()); os.close(fd)
os.environ["MODEL_ROUTING_CONFIG"] = path
import importlib
from model_routing import spec
importlib.reload(spec)
# 指定角色 → primary 被覆盖，fallback 继承 default
p = spec.role_policy("架构·评审")
assert p == {"primary": "glm-5.3-flash", "fallback": "glm-5.3-flash"}, p
# 未指定角色 → 仍走 default
assert spec.role_policy("架构·开发")["primary"] == "deepseek-v4.1-flash"
assert spec.role_overrides() == {"架构·评审": {"primary": "glm-5.3-flash"}}
os.remove(path); os.environ.pop("MODEL_ROUTING_CONFIG", None)
print("  ✅ 角色单独指定覆盖生效，其余继承 default")
PY

echo "---- ⑤ 主通道通 → 用主通道 ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
res = route_call(lambda m, s, u, **k: f"ok:{m}", system_prompt="s", user_input="u")
assert res["ok"] and res["model"] == "deepseek-v4.1-flash", res
assert res["role"] == "primary", res
print("  ✅ 使用主通道", res["model"])
PY

echo "---- ⑥ 主渠道不通 → 自动降级备用 ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
def caller(model, s, u, **k):
    if model == "deepseek-v4.1-flash":
        raise RuntimeError("connection error: channel unavailable")
    return f"ok:{model}"
res = route_call(caller, system_prompt="s", user_input="u")
assert res["ok"] and res["model"] == "glm-5.3-flash", res
assert res["role"] == "fallback", res
assert res["attempts"][0]["unavailable"] is True
print("  ✅ 降级到备用", res["model"])
PY

echo "---- ⑦ 两渠道全挂 → 显式失败（不静默） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
def caller(model, s, u, **k):
    raise RuntimeError("timeout: all channels down")
res = route_call(caller, system_prompt="s", user_input="u")
assert res["ok"] is False, res
assert res["reason"] == "all_channels_unavailable", res
assert len(res["attempts"]) == 2, res
print("  ✅ 全挂显式失败:", res["reason"])
PY

echo "---- ⑧ 留痕可读（监控俯瞰） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import trace_overview
ov = trace_overview()
assert isinstance(ov, dict) and ov, ov
print("  ✅ 留痕统计:", ov)
PY

echo "---- ⑨ .cnb.yml 的 npc:go model 与 models.yml default.primary 一致（防配置错） ----"
python3 - <<'PY'
import os, sys, re; sys.path.insert(0, '.')
from model_routing import spec
cnb = os.path.abspath(os.path.join(".", "..", ".cnb.yml"))
text = open(cnb, encoding="utf-8").read()
block_txt = text.split(".npc_task")[-1]
m = None
for line in block_txt.splitlines():
    st = line.strip()
    if st.startswith("#"):
        continue
    if re.match(r"^model:\s*\S", st):
        m = st.split(":", 1)[1].strip().split()[0]
        break
assert m, "未在 .npc_task 段找到 model: 字段"
assert m == spec.default_policy()["primary"], ".cnb.yml(%s) != models.yml default.primary(%s)" % (m, spec.default_policy()["primary"])
print("  ✅ .cnb.yml model == models.yml default.primary ==", m)
PY

echo "==== ✅ 模型路由信号灯全绿（9/9） ===="
