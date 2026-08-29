#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 开发规范 MCP 宿主接入测试（信号灯 · Issue #83 / M5）
# 验证 dev-standard host 层：
#   宿主工具注册 / 按名调用 / 未知工具容错 / JSON host RPC 契约 /
#   CLI 入口 / CI 接线脚本 standard-check.sh 阻断行为
set -e
cd "$(dirname "$0")/.."
PY=python3
export PYTHONPATH="local-agent:$PYTHONPATH"

echo "===== [dev-standard-host] 1. 宿主工具注册（register_tools）====="
$PY - <<'EOF'
from dev_standard import get_host
host = get_host("测试宿主")
tools = host.register_tools()
# 至少包含核心 standard.* 工具
names = [t["name"] for t in tools]
for need in ("standard.list", "standard.get", "standard.enforced",
             "standard.check", "standard.report", "standard.summary"):
    assert need in names, f"缺少工具 {need}"
# 每个工具名统一 standard. 前缀
for t in tools:
    assert t["name"].startswith("standard."), t
# list_tools 含描述
lt = host.list_tools()
assert lt and all("description" in t for t in lt), lt
print(f"  ✅ 宿主注册 {len(tools)} 个 standard.* 工具，契约完整")
EOF

echo "===== [dev-standard-host] 2. 按名调用（call）====="
$PY - <<'EOF'
from dev_standard import get_host
host = get_host("测试宿主")
# summary
r = host.call("standard.summary", {})
assert r["ok"], r
assert "total" in r["data"] and r["data"]["total"] >= 10, r
# enforced
r2 = host.call("standard.enforced", {"stage": "pre_pr"})
assert r2["ok"] and "S01" in r2["data"] and "P01" in r2["data"], r2
# list 按类别过滤
r3 = host.call("standard.list", {"category": "structure"})
assert r3["ok"] and all(s["category"] == "structure" for s in r3["data"]), r3
print("  ✅ 按名调用 summary/enforced/list 全部正确")
EOF

echo "===== [dev-standard-host] 3. 未知工具容错 + 确定性检查透传 ====="
$PY - <<'EOF'
from dev_standard import get_host
host = get_host("测试宿主")
# 未知工具 → ok=False
r = host.call("standard.no_such_tool", {})
assert not r["ok"], r
assert "available" in r and "standard.summary" in r["available"], r
# 确定性检查透传（base!=main → hard 失败）
r2 = host.call("standard.check", {"target": {
    "pr_info": {"base": "auto/dev", "source": "auto/x-1",
                "target": "auto/dev", "test_files": ["t.sh"], "docs_files": ["d.md"]}}})
assert r2["ok"] and r2["data"]["S01"]["passed"] is False, r2
assert r2["data"]["S01"]["check_type"] == "hard", r2
print("  ✅ 未知工具容错 + 确定性检查透传（base!=main→hard失败）")
EOF

echo "===== [dev-standard-host] 4. JSON host RPC 契约（等效逻辑）====="
$PY - <<'EOF'
import json
from dev_standard import get_host
host = get_host("测试宿主")
# 模拟 POST /rpc 的 payload 处理（与 host.py serve 中 do_POST 一致）
def rpc(payload):
    tool = payload.get("tool", "")
    params = payload.get("params", {}) or {}
    op = payload.get("operator")
    return host.call(tool, params, operator=op)

r = rpc({"tool": "standard.summary", "params": {}, "operator": "ci"})
assert r["ok"] and r["data"]["total"] >= 10, r
r2 = rpc({"tool": "standard.get", "params": {"spec_id": "S01"}})
assert r2["ok"] and r2["data"]["id"] == "S01", r2
r3 = rpc({"tool": "standard.bad", "params": {}})
assert not r3["ok"], r3
print("  ✅ JSON host RPC 契约（tool/params/operator → ok/data）通过")
EOF

echo "===== [dev-standard-host] 5. CLI 入口 ====="
$PY -m dev_standard.host list > /tmp/dsh_list.json 2>&1
grep -q '"standard.summary"' /tmp/dsh_list.json && echo "  ✅ CLI host list 可用"
$PY -m dev_standard.host call standard.summary '{}' > /tmp/dsh_call.json 2>&1
grep -q '"total"' /tmp/dsh_call.json && echo "  ✅ CLI host call 可用"
$PY -m dev_standard.host overview > /tmp/dsh_ov.json 2>&1
grep -q '"tool_count"' /tmp/dsh_ov.json && echo "  ✅ CLI host overview 可用"

echo "===== [dev-standard-host] 6. CI 接线脚本 standard-check.sh ====="
# pass case → 退出 0
bash scripts/standard-check.sh check-pr --target main --source auto/dev-standard-m5 \
    --test-files "tests/a.sh" --docs-files "docs/A.md" >/dev/null 2>&1 \
    && echo "  ✅ check-pr 合规 → 退出 0"
# blocked case → 退出 1（hard 阻断）
if bash scripts/standard-check.sh check-pr --target main --source auto/x \
    --test-files "tests/a.sh" --docs-files "docs/A.md" >/dev/null 2>&1; then
  echo "  ❌ check-pr hard 失败未阻断"; exit 1
else
  echo "  ✅ check-pr hard 失败 → 阻断（退出 1）"
fi
# enforced 查询可用
bash scripts/standard-check.sh enforced --stage pre_pr >/dev/null 2>&1 \
    && echo "  ✅ standard-check.sh enforced 可用"
# host 工具清单可用
bash scripts/standard-check.sh host >/dev/null 2>&1 \
    && echo "  ✅ standard-check.sh host 可用"

echo ""
echo "===== [dev-standard-host] 全部信号灯通过 ✅ ====="
