#!/usr/bin/env bash
# 模型路由信号灯（Issue #147 · module model-routing）
# 断言：主通道 deepseek-v4.1-flash → 不通时降级 glm-5.3-flash
set -e
cd "$(dirname "$0")/.."
echo "==== 模型路由信号灯（Issue #147） ===="

echo "---- ① 渠道顺序：主 → 备 ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import resolve_models, spec
order = resolve_models()
assert order[0] == "deepseek-v4.1-flash", f"主通道错误: {order}"
assert order[1] == "glm-5.3-flash", f"备用通道错误: {order}"
assert spec.PRIMARY == "deepseek-v4.1-flash"
assert spec.FALLBACK == "glm-5.3-flash"
print("  ✅", order)
PY

echo "---- ② 主通道通 → 用主通道 ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import route_call
res = route_call(lambda m, s, u, **k: f"ok:{m}", system_prompt="s", user_input="u")
assert res["ok"] and res["model"] == "deepseek-v4.1-flash", res
assert res["role"] == "primary", res
print("  ✅ 使用主通道", res["model"])
PY

echo "---- ③ 主渠道不通 → 自动降级备用 ----"
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

echo "---- ④ 两渠道全挂 → 显式失败（不静默） ----"
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

echo "---- ⑤ 留痕可读（监控俯瞰） ----"
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from model_routing import trace_overview
ov = trace_overview()
assert isinstance(ov, dict) and ov, ov
print("  ✅ 留痕统计:", ov)
PY

echo "==== ✅ 模型路由信号灯全绿（5/5） ===="
