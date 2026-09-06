#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 秘书层动态扩展机制（Secretary Scale · Issue #100 决策①）功能测试
# 验证"识别/注册/路由三层 + 权限边界护栏"，秘书只交接不执行、可增可减：
#   ① 识别层：确定性判据（复用率 + 边界评分），不靠感觉；需终端执行→拦下不设
#   ② 注册层：动态挂载/卸载秘书服务 + 生命周期（registered/active/draining）
#   ③ 路由层：请求命中秘书域→交接给 handoff_to；未命中→回终端开发线（不吞活）
#   ④ 权限护栏：交接类放行 / 终端执行类拦截 / 未知职责宁拦不放
#   ⑤ 能力挂载：秘书/经理角色可用（BaseRole 透传）
#   ⑥ 留痕：识别/注册/路由动作可回溯
set -e
cd "$(dirname "$0")/.."
PY=python3

echo "===== [secretary-scale] 1. 识别层确定性判据（复用+边界，不靠感觉） ====="
$PY - <<'EOF'
from scale import secretary_scale as ss
# 高复用 + 边界清晰 + 不需执行 → 建议增设秘书
r1 = ss.identify_secretary("mcp", reuse_count=5,
    boundary_factor_scores={"clear_interface":0.9,"single_owner":0.9,"self_contained":0.8})
assert r1["warrant"] is True, r1
assert r1["score"] >= 0.6, r1
# 低复用 → 不建议（不浪费：复用不足不值得独立秘书）
r2 = ss.identify_secretary("mcp", reuse_count=1,
    boundary_factor_scores={"clear_interface":0.9,"single_owner":0.9,"self_contained":0.8})
assert r2["warrant"] is False, r2
# 需终端执行 → 拦下不设（秘书只交接不执行）
r3 = ss.identify_secretary("biz-dev", reuse_count=9, requires_execution=True)
assert r3["warrant"] is False and "需终端执行" in r3["reasons"][0], r3
# 确定性：同输入两次同结果
assert ss.identify_secretary("mcp",5,{"clear_interface":0.9,"single_owner":0.9,"self_contained":0.8}) == r1
print("  ✅ 识别层：复用+边界+不执行 三判据确定性成立")
EOF

echo "===== [secretary-scale] 2. 注册层动态挂载/卸载 + 生命周期 ====="
$PY - <<'EOF'
from scale import secretary_scale as ss
# 卸载干净（幂等：重复卸载返回 False）
while ss.unregister_secretary("port"): pass
# 注册 + 生命周期流转
svc = ss.register_secretary("port", desc="端口管理秘书", handoff_to="架构·开发", reuse=3)
assert svc["status"] == "registered" and svc["handoff_to"] == "架构·开发"
assert ss.activate_secretary("port")["status"] == "active"
assert ss.drain_secretary("port")["status"] == "draining"
assert ss.activate_secretary("port")["status"] == "active"
# 可减（卸载）
assert ss.unregister_secretary("port") is True
assert ss.get_secretary("port") is None
# 无 handoff_to 拒绝注册（秘书不许吞活）
try:
    ss.register_secretary("x", handoff_to=""); raise SystemExit("should reject no handoff")
except ValueError as e:
    assert "handoff_to" in str(e)
# 重名拒绝（不漂移）
ss.register_secretary("dup", handoff_to="架构·开发")
try:
    ss.register_secretary("dup", handoff_to="架构·开发"); raise SystemExit("should reject dup")
except ValueError:
    pass
ss.unregister_secretary("dup")
print("  ✅ 注册层：可挂载/可卸载 + 生命周期 + 拒无归属/拒重名")
EOF

echo "===== [secretary-scale] 3. 路由层：命中交接 / 未命中回终端开发线 ====="
$PY - <<'EOF'
from scale import secretary_scale as ss
while ss.unregister_secretary("svc"): pass
ss.register_secretary("svc", desc="服务秘书", handoff_to="架构·开发", reuse=2)
ss.activate_secretary("svc")
# 命中 → 交接给 handoff_to，并累计复用
r1 = ss.route_request({"domain":"svc","payload":"启动服务"})
assert r1["matched"] and r1["to"]=="架构·开发" and r1["handoff"], r1
assert ss.get_secretary("svc")["reuse"] >= 3   # 命中累计复用
# 未命中 → 回终端开发线（秘书不吞活、不改形）
r2 = ss.route_request({"domain":"unknown"})
assert r2["matched"] is False and r2["to"]=="终端开发线(默认)", r2
ss.unregister_secretary("svc")
print("  ✅ 路由层：命中交接给下游 / 未命中回终端开发线")
EOF

echo "===== [secretary-scale] 4. 权限护栏：秘书只交接不执行 ====="
$PY - <<'EOF'
from scale import secretary_scale as ss
# 交接/路由/分诊 → 放行
for d in ("handoff","route","relay","intake","triage"):
    assert ss.guard(d)["allowed"] is True, d
# 终端执行 → 拦截（越权接终端任务即拦）
for d in ("implement","develop","fix_bug","execute","write_code","deliver_result"):
    assert ss.guard(d)["allowed"] is False, d
# 未知职责 → 宁拦不放（防越权成长）
assert ss.guard("anything_else")["allowed"] is False
print("  ✅ 权限护栏：交接放行 / 终端拦截 / 未知宁拦不放")
EOF

echo "===== [secretary-scale] 5. 能力挂载（秘书/经理角色透传） ====="
$PY - <<'EOF'
from roles.secretary import SecretaryRole
from roles.manager import ManagerRole
for R in (SecretaryRole, ManagerRole):
    r = R()
    assert r.secretary_scale_ability is not None
    assert "secretary_scale_ability" in r.capability()
    sug = r.secretary_scale_suggest("mcp", reuse_count=4,
        scores={"clear_interface":0.9,"single_owner":0.8,"self_contained":0.8})
    assert sug["warrant"] is True
    r.register_secretary_service("mcp", desc="MCP秘书", handoff_to="架构·开发")
    rt = r.secretary_route({"domain":"mcp"})
    assert rt["matched"] and rt["to"]=="架构·开发"
    assert r.secretary_guard("handoff")["allowed"] is True
    assert r.secretary_guard("implement")["allowed"] is False
    r.unregister_secretary_service("mcp")
    print(f"  ✅ {r.name} 秘书层动态扩展能力透传 OK")
EOF

echo "===== [secretary-scale] 6. 留痕可回溯 ====="
$PY - <<'EOF'
from scale import secretary_scale as ss
# 清理干净
while ss.unregister_secretary("trace-svc"): pass
# 核心动作各自留痕：identify/register/activate/route/guard/unregister
ss.identify_secretary("trace-svc", reuse_count=5,
    boundary_factor_scores={"clear_interface":0.9,"single_owner":0.9,"self_contained":0.8})
ss.register_secretary("trace-svc", desc="留痕测试", handoff_to="架构·开发")
ss.activate_secretary("trace-svc")
ss.route_request({"domain":"trace-svc"})
ss.guard("implement")
ss.unregister_secretary("trace-svc")
# 断言各核心动作均已落留痕
actions = [l["action"] for l in ss.recent_logs()]
for expected in ("identify","register","activate","route","guard","unregister"):
    assert expected in actions, f"missing trace: {expected}"
print("  ✅ 核心动作各自留痕（identify/register/activate/route/guard/unregister）可回溯")
EOF

echo "===== [secretary-scale] 7. 路由返回无自引用（可 JSON 序列化） ====="
$PY - <<'EOF'
import json
from scale import secretary_scale as ss
while ss.unregister_secretary("json-svc"): pass
ss.register_secretary("json-svc", desc="JSON测试", handoff_to="架构·开发")
ss.activate_secretary("json-svc")
r = ss.route_request({"domain":"json-svc","payload":{"nested":True}})
assert r["matched"] and r["handoff"]
# 不应包含 original 自引用环，可 JSON 序列化
json.dumps(r)   # 若仍含自引用 → RecursionError
assert "original" not in r["request"], f"should not embed original ref: {r}"
# 未命中分支的 request 同样可 JSON 序列化
r2 = ss.route_request({"domain":"nope"})
json.dumps(r2)
ss.unregister_secretary("json-svc")
print("  ✅ 路由命中/未命中返回均无自引用、可 JSON 序列化")
EOF

echo "===== [secretary-scale] 8. 护栏接入路由强制点（确定性拦截） ====="
$PY - <<'EOF'
from scale import secretary_scale as ss
while ss.unregister_secretary("guard-svc"): pass
ss.register_secretary("guard-svc", desc="护栏测试", handoff_to="架构·开发")
ss.activate_secretary("guard-svc")
# 终端执行类职责在路由入口被拦截，不路由到秘书
r1 = ss.route_request({"domain":"guard-svc"}, duty="implement")
assert r1["matched"] is False, r1
assert r1.get("blocked") is True, r1
assert "秘书只交接不执行" in r1.get("guard_reason",""), r1
# 交接类职责可正常路由
r2 = ss.route_request({"domain":"guard-svc"}, duty="handoff")
assert r2["matched"] is True and r2["to"]=="架构·开发", r2
# 未声明 duty 的请求也兼容（不强制）
r3 = ss.route_request({"domain":"guard-svc"})
assert r3["matched"] is True and r3["to"]=="架构·开发", r3
ss.unregister_secretary("guard-svc")
print("  ✅ 护栏在路由入口接入强制点：终端执行 duty 确定性拦截")
EOF

echo ""
echo "===== [secretary-scale] ALL PASS ====="
