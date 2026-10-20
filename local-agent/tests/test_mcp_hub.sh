#!/usr/bin/env bash
# ============================================================
# MCP 汇聚注册表 · 信号灯（module mcp-hub v0.1.0）
# ============================================================
# 判据都是「改错了会真红」，不是「跑通了就算」：
#   - 端点登记表必须与真实模块对得上（防止登记的路径/工具是编的）
#   - 四个 MCP 面必须都在表里（防止新加端点又成孤儿）
#   - 三前端能力集合必须一致（http / sse / jsonrpc 缺一即红）
#   - 未登记工具必须拒、写操作无 operator 必须拒（防假绿）
#   - launch 必须复用已在跑的服务，不重复起（防端口打架）
#   - 服务进程崩了/没起时 status 必须如实红灯
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT/local-agent" || exit 1

PASS=0; FAIL=0; FAILED_NAMES=()
ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); FAILED_NAMES+=("$1"); echo "  ❌ $1  ${2:-}"; }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1" "${3:-}"; fi; }

PORT=39092
PY=${PYTHON:-python3}

echo "==== [mcp-hub] 信号灯 ===="

# 1) 端点登记表 vs 真实文件（登记了却找不到文件 = 假登记）
echo "--- 1. 端点登记与真实模块对齐 ---"
MISSING=""
for path in $(cd "$REPO_ROOT/local-agent" && $PY -c "
from mcp_hub import specs
import os
for e in specs.ENDPOINTS:
    m = e['module']
    print(os.path.join('..', m) if m.startswith('dsh-adapter') else m)
" 2>/dev/null); do
  [ -e "$REPO_ROOT/local-agent/$path" ] || MISSING="$MISSING $path"
done
if [ -z "$MISSING" ]; then ok "5 个端点登记的模块文件都真实存在"; else bad "端点模块文件缺失" "$MISSING"; fi

# 2) 四个 MCP 面全部在表里（防新端点成孤儿）
echo "--- 2. 既有 MCP 面全覆盖 ---"
check "dsh 桥已登记" "$PY -c 'from mcp_hub import endpoint_by_id; assert endpoint_by_id(\"dsh-adapter\")'"
check "dev-standard 已登记" "$PY -c 'from mcp_hub import endpoint_by_id; assert endpoint_by_id(\"dev-standard\")'"
check "roster 已登记" "$PY -c 'from mcp_hub import endpoint_by_id; assert endpoint_by_id(\"roster\")'"
check "label 已登记" "$PY -c 'from mcp_hub import endpoint_by_id; assert endpoint_by_id(\"label\")'"
check "relay_card 已登记" "$PY -c 'from mcp_hub import endpoint_by_id; assert endpoint_by_id(\"relay-card\")'"
check "工具清单非空且含 standard./relay./label." "$PY -c '
from mcp_hub import tool_names
n = tool_names()
assert any(t.startswith(\"standard.\") for t in n) and any(t.startswith(\"relay.\") for t in n) and any(t.startswith(\"label.\") for t in n)'"

# 3) 端口只做建议（不出现两处硬编码冲突）
echo "--- 3. 端口建议唯一 ---"
check "端口只在 specs 出现一次且不冲突" "$PY -c '
from mcp_hub import port_owners
o = port_owners()
assert all(len(v) == 1 for v in o.values()), o'"

# 4) 转发真调（不是假的 ok:true）
echo "--- 4. 工具转发是真调 ---"
check "relay.check 判别出合法卡" "$PY -c '
from mcp_hub import call
r = call(\"relay.check\", {\"text\": \"@dongdongxiaozu/dongjiagoushi(架构·开发) [触发:架构·开发]\"})
assert r[\"ok\"] and r[\"data\"][\"valid\"] is True, r'"
check "relay.check 判得出非法卡（缺 @）" "$PY -c '
from mcp_hub import call
r = call(\"relay.check\", {\"text\": \"[触发:架构·开发] 没写 @\"})
assert r[\"data\"][\"valid\"] is False, r'"
check "standard.summary 返回真实规范数" "$PY -c '
from mcp_hub import call
r = call(\"standard.summary\", {})
assert r[\"ok\"] and r[\"data\"][\"total\"] > 0, r'"

# 5) 未接线/未登记/裸写操作 一律拒（防假绿）
echo "--- 5. 拒判不假装成功 ---"
check "未登记工具 → unknown_tool" "$PY -c '
from mcp_hub import call
r = call(\"nope.tool\", {})
assert r[\"ok\"] is False and r[\"reason\"] == \"unknown_tool\", r'"
check "rosrter 走 HTTP → http_only（不代调）" "$PY -c '
from mcp_hub import call
r = call(\"roster.intake\", {})
assert r[\"ok\"] is False and r[\"reason\"] == \"http_only\", r'"
check "label 写操作无 operator → operator_required" "$PY -c '
from mcp_hub import call
r = call(\"label.apply\", {\"entity\": \"issue-1\", \"label\": \"p2\"})
assert r[\"ok\"] is False and r[\"reason\"] == \"operator_required\", r'"
check "dsh 工具 → external_host（不在 hub 代调）" "$PY -c '
from mcp_hub import call
r = call(\"dsh.compat\", {})
assert r[\"ok\"] is False and r[\"reason\"] == \"external_host\", r'"

# 6) 三前端能力集合一致
echo "--- 6. 三前端一处语义 ---"
$PY -m mcp_hub.cli launch --port $PORT >/tmp/mcp_hub_launch.json 2>&1
LAUNCH_OK=$($PY -c "import json;print(json.load(open('/tmp/mcp_hub_launch.json')).get('ok'))" 2>/dev/null)
if [ "$LAUNCH_OK" = "True" ]; then ok "launch 拉起服务并回探活"; else bad "launch 起不来" "$(cat /tmp/mcp_hub_launch.json)"; fi

check "health 无副作用可 GET" "curl -s --max-time 3 http://127.0.0.1:$PORT/health | grep -q tool_count"
check "http /message tools/list 可用" "curl -s --max-time 3 -X POST http://127.0.0.1:$PORT/message -H 'Content-Type: application/json' -d '{\"tool\":\"tools/list\"}' | grep -q '\"tools\"'"
check "http /message 真调工具" "curl -s --max-time 3 -X POST http://127.0.0.1:$PORT/message -H 'Content-Type: application/json' -d '{\"tool\":\"relay.gen\",\"params\":{\"to\":\"架构·评审\"}}' | grep -q '触发:架构·评审'"
check "sse GET 推 endpoint 事件" "curl -s --max-time 1 http://127.0.0.1:$PORT/sse | grep -q 'event: endpoint'"
check "sse POST /message 同一语义" "curl -s --max-time 3 -X POST 'http://127.0.0.1:$PORT/message?session=t' -H 'Content-Type: application/json' -d '{\"tool\":\"relay.check\",\"params\":{\"text\":\"@dongdongxiaozu/dongjiagoushi(架构·评审) [触发:架构·评审]\"}}' | grep -q '\"valid\": true'"
check "jsonrpc initialize 回规范帧" "curl -s --max-time 3 -X POST http://127.0.0.1:$PORT/jsonrpc -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{}}' | grep -q protocolVersion"
check "jsonrpc tools/call 返回 content[]" "curl -s --max-time 3 -X POST http://127.0.0.1:$PORT/jsonrpc -H 'Content-Type: application/json' -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"standard.summary\",\"arguments\":{}}}' | grep -q '\"content\"'"
TOOL_HTTP=$(curl -s --max-time 3 -X POST http://127.0.0.1:$PORT/message -H 'Content-Type: application/json' -d '{"tool":"tools/list"}' | $PY -c "import sys,json;print(len(json.load(sys.stdin)['data']['tools']))" 2>/dev/null)
TOOL_RPC=$(curl -s --max-time 3 -X POST http://127.0.0.1:$PORT/jsonrpc -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}' | $PY -c "import sys,json;print(len(json.load(sys.stdin)['result']['tools']))" 2>/dev/null)
if [ -n "$TOOL_HTTP" ] && [ "$TOOL_HTTP" = "$TOOL_RPC" ]; then ok "两前端工具数一致（$TOOL_HTTP）"; else bad "前端能力集合分叉" "http=$TOOL_HTTP jsonrpc=$TOOL_RPC"; fi

# 7) 复用不重复起
echo "--- 7. 已在跑则复用 ---"
check "二次 launch 复用（reused=true）" "$PY -m mcp_hub.cli launch --port $PORT | grep -q '\"reused\": true'"

# 8) 探活如实：没起就红灯
echo "--- 8. 探活不假装 ---"
# status 是「探活不假装」的关键：没起必须 alive=False，不能空壳成功
if $PY -c '
from mcp_hub import status
import sys
sys.exit(0 if status(39093)["alive"] is False else 1)'; then
  ok "未起端口 status=false"
else
  bad "未起端口却报 alive=True" "探活假绿"
fi

# 收尾：杀掉本测试起的服务
PID=$(cat mcp_hub/_runtime/serve.pid 2>/dev/null || true)
[ -n "${PID:-}" ] && kill "$PID" 2>/dev/null
sleep 0.3
check "停服后 status 如实为 false" "$PY -c '
from mcp_hub import status
import sys
sys.exit(0 if status('$PORT')[\"alive\"] is False else 1)'"

echo ""
echo "==== [mcp-hub] $PASS 通过 / $FAIL 失败 ===="
if [ "$FAIL" -ne 0 ]; then
  printf '  失败项: %s\n' "${FAILED_NAMES[*]}"
  exit 1
fi
exit 0
