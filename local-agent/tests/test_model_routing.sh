#!/usr/bin/env bash
# 模型路由信号灯（Issue #147 · module model-routing v0.3.0-update）
# 断言：统一配置文件管理 + 多级降级链 + 角色名真实接进调用链（改配置即长期生效）
set -e
cd "$(dirname "$0")/.."
echo "==== 模型路由信号灯（Issue #147 · 统一配置 + 多级降级 + 真实接线） ===="

echo "---- ① 唯一配置文件存在且可解析（含三级链） ----"
python3 - <<'PY'
import os, sys; sys.path.insert(0, '.')
from model_routing import spec
assert os.path.exists(spec.config_path()), f"配置文件不存在: {spec.config_path()}"
assert spec.config_path().endswith("models.yml"), spec.config_path()
c = spec.default_chain()
assert c == ("deepseek-v4.1-flash", "codebuddy", "glm-5.3-flash"), c
print("  ✅ 唯一配置文件:", spec.config_path(), "chain =", list(c))
PY

echo "---- ② 不指定角色 → 走通用默认（default 三级链） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import resolve_models
assert resolve_models() == ["deepseek-v4.1-flash", "codebuddy", "glm-5.3-flash"], resolve_models()
assert resolve_models(role=None) == ["deepseek-v4.1-flash", "codebuddy", "glm-5.3-flash"]
print("  ✅ 不指定 → default:", resolve_models())
PY

echo "---- ③ 未列出的角色 → 继承 default（不指定就默认通用） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import spec, resolve_models
assert spec.role_policy("架构·开发没有列过")["chain"] == spec.default_policy()["chain"]
assert resolve_models(role="架构·未列出") == ["deepseek-v4.1-flash", "codebuddy", "glm-5.3-flash"]
print("  ✅ 未列出角色继承 default")
PY

echo "---- ④ 某角色单独指定 → 覆盖生效（改配置文件即生效，非单次） ----"
python3 - <<'PY'
import os, sys, tempfile; sys.path.insert(0, '.')
cfg = """
default:
  chain: [deepseek-v4.1-flash, codebuddy, glm-5.3-flash]
roles:
  "架构·评审":
    chain: [glm-5.3-flash, deepseek-v4.1-flash]
"""
fd, path = tempfile.mkstemp(suffix=".yml"); os.write(fd, cfg.encode()); os.close(fd)
os.environ["MODEL_ROUTING_CONFIG"] = path
from model_routing import spec
# 指定角色 → 整链覆盖；未指定 → 仍走 default
assert spec.role_chain("架构·评审") == ("glm-5.3-flash", "deepseek-v4.1-flash"), spec.role_chain("架构·评审")
assert spec.role_chain("架构·开发")[0] == "deepseek-v4.1-flash"
# ★ 非单次有效：改同一文件后再解析即时变化
open(path, "w").write("default:\n  chain: [codebuddy, glm-5.3-flash]\n")
assert spec.role_chain("架构·开发") == ("codebuddy", "glm-5.3-flash"), spec.role_chain("架构·开发")
os.remove(path); os.environ.pop("MODEL_ROUTING_CONFIG", None)
print("  ✅ 角色覆盖生效 + 改配置即时生效（非单次有效）")
PY

echo "---- ⑤ 主通道通 → 用主档 ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
res = route_call(lambda m, s, u, **k: f"ok:{m}", system_prompt="s", user_input="u")
assert res["ok"] and res["model"] == "deepseek-v4.1-flash", res
assert res["role"] == "primary", res
print("  ✅ 使用主通道", res["model"])
PY

echo "---- ⑥ 主渠道不通 → 自动降级二选（codebuddy） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
def caller(model, s, u, **k):
    if model == "deepseek-v4.1-flash":
        raise RuntimeError("connection error: channel unavailable")
    return f"ok:{model}"
res = route_call(caller, system_prompt="s", user_input="u")
assert res["ok"] and res["model"] == "codebuddy", res
assert res["role"] == "fallback", res
assert res["attempts"][0]["unavailable"] is True
print("  ✅ 降级到二选", res["model"])
PY

echo "---- ⑦ 主+二选均不通 → 降级三选（glm-5.3-flash） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
def caller(model, s, u, **k):
    if model in ("deepseek-v4.1-flash", "codebuddy"):
        raise RuntimeError("timeout: channel unavailable")
    return f"ok:{model}"
res = route_call(caller, system_prompt="s", user_input="u")
assert res["ok"] and res["model"] == "glm-5.3-flash", res
assert res["role"] == "fallback2", res
print("  ✅ 降级到三选", res["model"])
PY

echo "---- ⑧ 三级链全挂 → 显式失败（不静默） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
def caller(model, s, u, **k):
    raise RuntimeError("timeout: all channels down")
res = route_call(caller, system_prompt="s", user_input="u")
assert res["ok"] is False, res
assert res["reason"] == "all_channels_unavailable", res
assert len(res["attempts"]) == 3, res
print("  ✅ 全挂显式失败:", res["reason"])
PY

echo "---- ⑨ 留痕可读（监控俯瞰） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import trace_overview
ov = trace_overview()
assert isinstance(ov, dict) and ov, ov
print("  ✅ 留痕统计:", ov)
PY

echo "---- ⑩ 角色名真实接进调用链（run() → llm.call(role=...)） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
import llm
from roles.developer import DeveloperRole
class FakeBackend(llm.base.LLMBackend):
    name = "fake"
    def __init__(self): self.seen = []
    def available(self): return True
    def call(self, sp, ui, role=None, **kw):
        self.seen.append(role); return f"by:{role}"
r = DeveloperRole(); r.name = "架构·开发"
fb = FakeBackend()
out = r.run(fb, "hi")
assert fb.seen == ["架构·开发"], fb.seen
assert out == "by:架构·开发"
print("  ✅ 角色名已贯通 run()→llm.call(role=):", fb.seen)
PY

echo "---- ⑪ openai 后端按 role 解析渠道链（不硬编码，改配置即生效） ----"
python3 - <<'PY'
import os, sys, tempfile; sys.path.insert(0, '.')
fd, path = tempfile.mkstemp(suffix=".yml")
os.write(fd, ("default:\n  chain: [deepseek-v4.1-flash, codebuddy, glm-5.3-flash]\n"
              "roles:\n  \"架构·评审\":\n    chain: [glm-5.3-flash, deepseek-v4.1-flash]\n").encode())
os.close(fd)
os.environ["MODEL_ROUTING_CONFIG"] = path
import llm.openai_compat as oc
assert oc._resolve_backends("架构·开发")[0] == ["deepseek-v4.1-flash", "codebuddy", "glm-5.3-flash"]
assert oc._resolve_backends("架构·评审")[0] == ["glm-5.3-flash", "deepseek-v4.1-flash"]
os.remove(path); os.environ.pop("MODEL_ROUTING_CONFIG", None)
print("  ✅ 后端按 role 解析渠道链正确")
PY

echo "---- ⑫ .cnb.yml 的 npc:go model 与 models.yml default.chain[0] 一致（防配置错） ----"
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
assert m == spec.default_chain()[0], ".cnb.yml(%s) != models.yml default.chain[0](%s)" % (m, spec.default_chain()[0])
print("  ✅ .cnb.yml model == models.yml default.chain[0] ==", m)
PY

echo "==== ✅ 模型路由信号灯全绿（12/12） ===="
