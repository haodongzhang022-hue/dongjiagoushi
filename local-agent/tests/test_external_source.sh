#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 外部事件源接入（external-source）· 功能测试
# 验证用户最新拍板的落地：
#   1. 多终端源预设（本地电脑/手机/虚拟机/沙盒/上位机，不只一个源）
#   2. 秘钥 key + IP 白名单 安全认证（deny-by-default）
#   3. Webhook 接收端（POST /webhook/<source>，webhook 更合理）
#   4. 认证审计（成功/拦截留痕，面板可俯瞰）
#   5. 本地上位机辅助角色预设（host_helper）
# 对应 docs/EXTERNAL_SOURCE.md；纳入 local-agent 测试信号灯。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH=$(mktemp /tmp/external-source-test-XXXX.db)
rm -f "$DB_PATH"

echo "===== [external-source] 1. 外部源登记 + 多终端独立授权 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import security

# 多终端源预设
from dispatcher import sources
srcs = sources.preset_host_sources()
assert set(srcs) >= {"local_pc", "phone", "vm", "sandbox", "host_upper"}, \
    f"应预设多终端源，实际 {set(srcs)}"

# 每个外部源独立 key + IP 白名单（互不共享）
all_sources = security.list_sources()
keys = {s["name"]: s["api_key"] for s in all_sources if s["name"] in srcs}
assert len(set(keys.values())) == len(keys), "每个源应独立 key，不共享"

# deny-by-default：未登记源拒绝
ok, reason, _ = security.authenticate("unknown_src", "x", "127.0.0.1")
assert ok is False and reason == "外部源未登记"
print("  ✅ 多终端独立 key + 白名单 + deny-by-default 通过")
EOF

echo "===== [external-source] 2. 秘钥 + IP 白名单 认证 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import security

s = security.register_source("auth_pc", ip_whitelist=["127.0.0.1", "10.0.0.0/8"], kind="webhook")
key = s["api_key"]

# 正确 key + 白名单 IP → 通过
ok, reason, src = security.authenticate("auth_pc", key, "127.0.0.1")
assert ok and src["name"] == "auth_pc"
# CIDR 段内 IP → 通过
ok, reason, _ = security.authenticate("auth_pc", key, "10.1.2.3")
assert ok, "CIDR 段内应通过"
# 错误 key → 拒绝
ok, reason, _ = security.authenticate("auth_pc", "wrong", "127.0.0.1")
assert ok is False and "秘钥" in reason
# 非白名单 IP → 拒绝
ok, reason, _ = security.authenticate("auth_pc", key, "8.8.8.8")
assert ok is False and "白名单" in reason
# 停用源 → 拒绝
security.update_source("auth_pc", enabled=False)
ok, reason, _ = security.authenticate("auth_pc", key, "127.0.0.1")
assert ok is False and "停用" in reason
security.update_source("auth_pc", enabled=True)

# 认证审计留痕（成功 + 拦截）
audit = security.audit()
assert any(a["result"] == "allow" for a in audit)
assert any(a["result"] == "deny" for a in audit)
# 秘钥不落明文
assert all("sk-" not in (a.get("api_key_masked") or "") for a in audit)
print("  ✅ 秘钥 + IP 白名单认证 + 审计打码通过")
EOF

echo "===== [external-source] 3. Webhook 接收端（POST /webhook/<source>）===="
$PY - <<'EOF'
import json, threading, urllib.request, urllib.error
from data import schema
schema.init_schema()
from dispatcher import security
from dispatcher.webhook import _WebhookHandler
from http.server import HTTPServer

s = security.register_source("wh_pc", ip_whitelist=["127.0.0.1"], kind="webhook")
key = s["api_key"]

server = HTTPServer(("127.0.0.1", 0), _WebhookHandler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()

def post(body, headers=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/webhook/wh_pc",
        data=json.dumps(body).encode(), headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# 无 key → 401
st, b = post({"event_type": "requirement", "entity": "E1"})
assert st == 401, f"无 key 应 401，实际 {st}"
# 错误 key → 401
st, b = post({"event_type": "requirement", "entity": "E1"}, {"X-API-Key": "bad"})
assert st == 401
# 正确 key → 200 注入
st, b = post({"event_type": "requirement", "entity": "E1"}, {"X-API-Key": key})
assert st == 200 and b["ok"] and b["accepted"] == 1
# 批量事件
st, b = post({"events": [
    {"event_type": "requirement", "entity": "E2"},
    {"event_type": "issue.open", "entity": "E3"},
]}, {"X-API-Key": key})
assert st == 200 and b["accepted"] == 2
server.shutdown()
print("  ✅ Webhook 接收端：认证 + 单事件 + 批量注入通过")
EOF

echo "===== [external-source] 4. 本地上位机辅助角色预设 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import host_helper, sources

# 本地电脑上报事件（云端-本地协同主源）
r = host_helper.host_report("requirement", "本地新需求", {"gid": "tk-host1"}, "local_pc", via="local")
assert r["ok"] is True, f"本地上报应成功，实际 {r}"
# 上位机俯瞰：外部源/认证/队列
ov = host_helper.host_overview()
assert "local_pc" in [s["name"] for s in ov["external_sources"]]
assert "auth_overview" in ov
# 上位机拉取派发动作
acts = host_helper.host_pull_actions()
assert isinstance(acts, list)
print("  ✅ 本地上位机辅助角色（上报/俯瞰/拉取）通过")
EOF

echo "===== [external-source] 5. CLI 命令（ext / webhook / host）===="
export DB_PATH=$(mktemp /tmp/external-source-cli-XXXX.db)
rm -f "$DB_PATH"
$PY -m dispatcher.cli ext add cli_src --ip 127.0.0.1 | grep -q "cli_src"
$PY -m dispatcher.cli ext list | grep -q "cli_src"
$PY -m dispatcher.cli ext audit | grep -q "overview"
$PY -m dispatcher.cli host overview | grep -q "external_sources"
echo "  ✅ CLI 命令（ext add/list/audit, host overview）通过"

echo ""
echo "🎉 [external-source] 全部测试通过（多源/安全/Webhook/上位机辅助）"
