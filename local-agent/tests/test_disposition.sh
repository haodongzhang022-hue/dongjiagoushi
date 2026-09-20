#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 统一审查处置标签（Review Disposition）功能测试
# 验证 Issue #31 本轮需求——审查机制"统一全加规范处置标签 + 稳定触发 + 按标签自动化流程"：
#   ① 规范标签全集齐全（merge/proceed/fix_bug/research/human/consult/vote/blocked 八种）
#   ② 稳定触发：任何审查/决策点必然返回规范标签（含无输入兜底）
#   ③ 归一化映射：严重级/触发信号/既有action 统一映射到规范标签
#   ④ 非规范标签严格拒绝（require_label）
#   ⑤ 按标签自动化流程（route）路由正确
#   ⑥ 评审输出契约强制绑定 disposition 字段
#   ⑦ 留痕 + 俯瞰（record_disposition / disposition_overview）
set -e
cd "$(dirname "$0")/.."
PY=python3

export DB_PATH="$(mktemp -d)/test_disposition.db"

echo "===== [disposition] 1. 规范标签全集齐全（统一全加八种） ====="
$PY - <<'EOF'
from collab import disposition
labels = disposition.valid_labels()
# 用户要求覆盖的处置情况全部在列
need = {"merge","proceed","fix_bug","research","human","consult","vote","blocked"}
assert need <= set(labels), (need, labels)
assert len(labels) == 8, labels
# spec 机器可读规范：名称/action/route 与标签对齐
spec = disposition.spec()
assert spec["labels"] == labels
for lbl in labels:
    assert lbl in spec["names"] and lbl in spec["actions"] and lbl in spec["routes"]
# 每个标签都有规范名称与自动化流程 route
for lbl in labels:
    meta = disposition.DISPOSITION_LABELS[lbl]
    assert meta["name"] and meta["action"] and meta["route"] and meta["when"]
print("  ✅ 规范标签全集齐全", labels)
EOF

echo "===== [disposition] 2. 稳定触发：任何输入/无输入必然返回规范标签 ====="
$PY - <<'EOF'
from collab import disposition
# 无任何输入 → 兜底 proceed，恒有标签
r0 = disposition.dispose()
assert r0["disposition"] == "proceed"
assert r0["disposition"] in disposition.valid_labels()
# 八种显式标签都能 dispose 且返回该标签
for lbl in disposition.valid_labels():
    r = disposition.dispose(problem="测试", label=lbl)
    assert r["disposition"] == lbl
    assert r["flow"]["label"] == lbl
# 随机组合输入也必然返回规范标签（不抛错、恒有标签）
import itertools
for sigs in ([], ["hard"], ["dispute"], ["stall","hard"], ["scale_up"]):
    r = disposition.dispose(signals=sigs)
    assert r["disposition"] in disposition.valid_labels()
print("  ✅ 稳定触发：恒有规范标签")
EOF

echo "===== [disposition] 3. 归一化映射（严重级/信号/既有action → 规范标签） ====="
$PY - <<'EOF'
from collab import disposition
# 评审严重级
assert disposition.dispose(severity="🔴必修")["disposition"] == "fix_bug"
assert disposition.dispose(severity="red")["disposition"] == "fix_bug"
assert disposition.dispose(severity="🟢")["disposition"] == "merge"
assert disposition.dispose(severity="green")["disposition"] == "merge"
assert disposition.dispose(severity="🟡建议")["disposition"] == "proceed"
# 触发信号
assert disposition.dispose(signals=["hard"])["disposition"] == "consult"
assert disposition.dispose(signals=["high_risk"])["disposition"] == "consult"
assert disposition.dispose(signals=["dispute"])["disposition"] == "vote"
assert disposition.dispose(signals=["skill_gap"])["disposition"] == "research"
assert disposition.dispose(signals=["stall"])["disposition"] == "research"
assert disposition.dispose(signals=["defect"])["disposition"] == "fix_bug"
assert disposition.dispose(signals=["needs_human"])["disposition"] == "human"
assert disposition.dispose(requires_human=True)["disposition"] == "human"
# 既有 action 归一化
assert disposition.dispose(action="adopt")["disposition"] == "merge"
assert disposition.dispose(action="merge")["disposition"] == "merge"
assert disposition.dispose(action="escalate")["disposition"] == "human"
assert disposition.dispose(action="reroute")["disposition"] == "research"
assert disposition.dispose(action="consult")["disposition"] == "consult"
assert disposition.dispose(action="vote")["disposition"] == "vote"
# 场景语义提示
assert disposition.dispose(scenario_hint="这个方案适合合并")["disposition"] == "merge"
assert disposition.dispose(scenario_hint="存在必修缺陷需改bug")["disposition"] == "fix_bug"
assert disposition.dispose(scenario_hint="信息不足需要调研")["disposition"] == "research"
assert disposition.dispose(scenario_hint="需要移交人类判断")["disposition"] == "human"
assert disposition.dispose(scenario_hint="疑难问题适合专家会诊")["disposition"] == "consult"
assert disposition.dispose(scenario_hint="意见多重适合投票表决")["disposition"] == "vote"
print("  ✅ 归一化映射 通过")
EOF

echo "===== [disposition] 4. 非规范标签严格拒绝（防加错/漏加） ====="
$PY - <<'EOF'
from collab import disposition
# 显式非规范标签 → 报错
try:
    disposition.dispose(label="bad_label")
    raise AssertionError("非规范显式标签不应放行")
except ValueError:
    pass
try:
    disposition.require_label("whatever")
    raise AssertionError("非规范标签 require_label 不应通过")
except ValueError:
    pass
# 规范标签通过
disposition.require_label("merge")
print("  ✅ 非规范标签严格拒绝 通过")
EOF

echo "===== [disposition] 5. 按标签自动化流程（route） ====="
$PY - <<'EOF'
from collab import disposition
# 每种标签路由到确定的自动化流程
r = disposition.route("merge")
assert r["merge"] is True and r["handoff"] == "经理/评审"
assert any("合并确认" in s for s in r["steps"])
r = disposition.route("fix_bug")
assert r["revert"] is True and r["revert_to"] == "开发"
assert any("回转" in s for s in r["steps"])
r = disposition.route("human")
assert r["human_gate"] is True and r["handoff"] == "人类(用户)"
r = disposition.route("consult")
assert r["consult"] is True and r["handoff"] == "同岗编队(cohort)"
r = disposition.route("vote")
assert r["vote"] is True and r["handoff"] == "同岗编队(cohort)"
r = disposition.route("research")
assert r["explore"] is True and r["handoff"] == "调研专员/架构·总师助理"
r = disposition.route("proceed")
assert r["proceed"] is True and r["handoff"] == "开发/小组长"
print("  ✅ 按标签自动化流程 通过")
EOF

echo "===== [disposition] 6. 评审输出契约强制绑定 disposition 字段 ====="
$PY - <<'EOF'
import sys; sys.path.insert(0, '.')
from roles import get_role
rev = get_role("架构·评审")
assert rev is not None
contract = rev.output_contract()["contract"]
# 输出契约必须含统一处置标签（强制必填）
assert any("disposition" in c for c in contract), contract
# 评审 dispose 强制给标签：🔴→fix_bug，无信号→proceed
assert rev.dispose(severity="🔴必修")["disposition"] == "fix_bug"
assert rev.dispose()["disposition"] == "proceed"
# 评审 SYSTEM_PROMPT 声明"缺标签即评审未完成"
assert "缺标签即评审未完成" in rev.SYSTEM_PROMPT
print("  ✅ 评审输出契约强制绑定 disposition 通过")
EOF

echo "===== [disposition] 7. 留痕 + 俯瞰（record_disposition / disposition_overview） ====="
$PY - <<'EOF'
from data import admin
from collab import disposition
admin.init()
# 留痕：审查处置写入 archives（kind=disposition）
disposition.record_disposition(problem="多端方案评审", label="merge",
                               task_id="tk-d1", reviewer="架构·评审")
disposition.record_disposition(problem="登录安全缺陷", label="fix_bug",
                               task_id="tk-d2", reviewer="架构·评审")
disposition.record_disposition(problem="疑难取舍", label="consult",
                               task_id="tk-d3", reviewer="架构·评审")
# 俯瞰：统计各标签出现次数
ov = disposition.disposition_overview()
assert ov["total"] == 3, ov
assert ov["by_label"]["merge"] == 1
assert ov["by_label"]["fix_bug"] == 1
assert ov["by_label"]["consult"] == 1
assert ov["by_label"]["proceed"] == 0
print("  ✅ 留痕 + 俯瞰 通过", ov["by_label"])
EOF

echo "===== [disposition] 统一审查处置标签机制 全部通过 ✅ ====="
