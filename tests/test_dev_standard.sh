#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 开发规范体系测试（信号灯 · Issue #83）
# 验证 dev-standard 模块的确定性检查 + 全员能力 + CLI 可用性：
#   规范注册表完整性 / 确定性 hard/soft 判定 / 各 check_* 逻辑 /
#   BaseRole 挂载 / CLI 可用
set -e
cd "$(dirname "$0")/.."
PY=python3
export PYTHONPATH="local-agent:$PYTHONPATH"

echo "===== [dev-standard] 1. 规范注册表完整性 ====="
$PY - <<'EOF'
from dev_standard import specs
s = specs.summary()
assert s["total"] >= 10, s  # 至少 10 条规范
assert "L1" in s["by_level"] and s["by_level"]["L1"] >= 8, s
# 每条规范结构完整
for sid, spec in specs.STANDARD_SPECS.items():
    for field in ("id","title","level","category","check_type","description","enforce_at","verify"):
        assert field in spec, (sid, field)
    assert spec["level"] in specs.VALID_LEVELS, spec
    assert spec["category"] in specs.VALID_CATEGORIES, spec
    assert spec["check_type"] in ("hard","soft"), spec
# 按级别/类别/时机索引一致
assert specs.SPECS_BY_LEVEL["L1"], "L1 必做规范不能为空"
assert specs.SPECS_BY_CATEGORY["structure"], "结构类规范不能为空"
assert specs.SPECS_BY_ENFORCE_AT["pre_pr"], "pre_pr 强制规范不能为空"
print(f"  ✅ 注册表 {s['total']} 条规范，L1={s['by_level']['L1']}，结构完整")
EOF

echo "===== [dev-standard] 2. 确定性检查器：hard/soft 判定 ====="
$PY - <<'EOF'
from dev_standard.checker import StandardChecker
ck = StandardChecker()
# S01 base main：合规
r = ck.check_pr({"pr_info": {"base": "main", "source": "auto/x-1",
                             "test_files": ["t.sh"], "docs_files": ["d.md"],
                             "has_test": True, "has_docs": True}})
assert r["S01"]["passed"] is True, r["S01"]
assert r["S05"]["passed"] is True, r["S05"]
# S01 base 非 main：hard 失败
r2 = ck.check_pr({"pr_info": {"base": "auto/dev", "source": "auto/x-1",
                              "test_files": ["t.sh"], "docs_files": ["d.md"]}})
assert r2["S01"]["passed"] is False, r2["S01"]
assert r2["S01"]["check_type"] == "hard", r2["S01"]
# report 判定 blocked
report = ck.report(r2, format="json")
assert report["overall"] == "blocked", report
assert "S01" in report["hard_fail_items"], report
print("  ✅ 确定性 hard 判定：base!=main → blocked")
EOF

echo "===== [dev-standard] 3. 代码规范检查：裸except / 敏感信息 / 死代码 ====="
$PY - <<'EOF'
from dev_standard.checker import StandardChecker
import tempfile, os
ck = StandardChecker()
# 裸 except → C01 hard 失败
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write("try:\n    x()\nexcept:\n    pass\n")
    path = f.name
try:
    r = ck.check_code(path)
    assert r["C01"]["passed"] is False, r["C01"]
    assert r["C01"]["check_type"] == "hard"
finally:
    os.unlink(path)
# 敏感信息 → C02 hard 失败
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write("token = 'sk-abcdefghijklmnopqrstuvwxyz123456'\n")
    path = f.name
try:
    r = ck.check_code(path)
    assert r["C02"]["passed"] is False, r["C02"]
finally:
    os.unlink(path)
# 干净代码 → 通过
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write("import os\n\ndef f():\n    return os.getcwd()\n")
    path = f.name
try:
    r = ck.check_code(path)
    assert r["C01"]["passed"] is True, r["C01"]
    assert r["C02"]["passed"] is True, r["C02"]
finally:
    os.unlink(path)
print("  ✅ 代码规范：裸except/敏感信息/死代码 确定性判定")
EOF

echo "===== [dev-standard] 4. StandardAbility 能力（BaseRole 挂载）====="
$PY - <<'EOF'
import sys
sys.path.insert(0, "local-agent")
from roles.base import BaseRole
# 一个空角色（模拟开发角色）
class Dev(BaseRole):
    name = "架构·开发"
dev = Dev()
# StandardAbility 已挂载
assert dev.standard_ability is not None, "BaseRole 未挂载 StandardAbility"
# 能力接口可用
specs = dev.list_standards(level="L1")
assert len(specs) >= 8, len(specs)
enforced = dev.get_enforced_specs("pre_pr")
assert len(enforced) >= 5, enforced
r = dev.check_pr({"pr_info": {"base": "main", "source": "auto/x-1",
                              "test_files": ["t.sh"], "docs_files": ["d.md"],
                              "has_test": True, "has_docs": True}})
assert r["S01"]["passed"] is True, r["S01"]
# capability 声明含 standard_ability
cap = dev.capability()
assert "standard_ability" in cap, list(cap.keys())
print("  ✅ StandardAbility 挂载 BaseRole，能力接口全部可用")
EOF

echo "===== [dev-standard] 5. CLI 可用性（MCP 管线）====="
$PY -m dev_standard.cli list --level L1 > /tmp/ds_list.json 2>&1
grep -q "S01" /tmp/ds_list.json && echo "  ✅ CLI list 可用"
$PY -m dev_standard.cli enforced --stage pre_pr > /tmp/ds_enforced.txt 2>&1
grep -q "S01" /tmp/ds_enforced.txt && echo "  ✅ CLI enforced 可用"
$PY -m dev_standard.cli check-pr --target main --source auto/x-1 \
    --test-files tests/a.sh --docs-files docs/A.md > /tmp/ds_check.json 2>&1
grep -q '"overall": "compliant"' /tmp/ds_check.json && echo "  ✅ CLI check-pr 合规判定"
$PY -m dev_standard.cli summary > /tmp/ds_summary.json 2>&1
grep -q "total" /tmp/ds_summary.json && echo "  ✅ CLI summary 可用"

echo ""
echo "===== [dev-standard] 全部信号灯通过 ✅ ====="
