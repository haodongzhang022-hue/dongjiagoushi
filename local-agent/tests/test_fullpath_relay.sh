#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 全路径出发（full-path firing）信号灯测试（Issue #142 机制加固）
# ============================================================
# 用户 #142 纠偏：「他说回转退回架构开发，实际他的唤醒没有成功做到。
# 他是假装触发了/想触发但没成功。应该带着路径出发。」
# 根因：评论只写 `[回转] 退回:架构·开发`（或只写 [触发:角色]），
# 没有完整 `@org/repo(架构·开发)` 路径 → 平台不推送，对端没被唤醒。
# 验证：
#   1. revert_to_developer 生成的回转文本必含 完整 @org/repo(架构·开发)
#      + [触发:架构·开发] + [回转] 退回:架构·开发（三要素，全路径出发）；
#   2. handoff_to_tester 转交文本必含完整 @org/repo(架构·测试) + [触发:架构·测试]；
#   3. BaseRole.awake() 对缺完整 @ 的 context 自动前置完整路径；
#   4. relay_card.check 校验缺完整 @ / [触发] 即 INVALID_RELAY（假触发被拦截）；
#   5. 测试回执 relay_receipt 含完整 @org/repo(架构·测试)（不写死）。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_fullpath_relay.db"

echo "===== [fullpath] 1. 回转文本三要素（完整@ + [触发] + [回转]退回）====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
assert hasattr(reviewer, "fullpath_relay"), "BaseRole 应具备 fullpath_relay()"
r = reviewer.revert_to_developer("必修任务", reason="🔴必修未清零",
                                 next_requirement="返工后交回复评")
text = r["relay_text"]
# 三要素：完整 @org/repo(架构·开发) + [触发:架构·开发] + [回转] 退回:架构·开发
assert "@dongdongxiaozu/dongjiagoushi(架构·开发)" in text, text
assert "[触发:架构·开发]" in text, text
assert "[回转] 退回:架构·开发" in text, text
assert r["relay_valid"] is True, r
print("  ✅ 回转文本三要素齐全 + relay_valid=True")
print("      " + text.replace(chr(10), ' / ')[:160])
EOF

echo "===== [fullpath] 2. 转交文本必含 完整@ + [触发:架构·测试] ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
r = reviewer.handoff_to_tester("通过任务", issue_ref="142",
                               review_summary="五维通过",
                               disposition_label="merge")
text = r["relay_text"]
assert "@dongdongxiaozu/dongjiagoushi(架构·测试)" in text, text
assert "[触发:架构·测试]" in text, text
assert r["relay_valid"] is True, r
print("  ✅ 转交文本含完整 @org/repo(架构·测试) + [触发:架构·测试]")
EOF

echo "===== [fullpath] 3. awake() 对缺完整@的 context 自动前置完整路径 ====="
$PY - <<'EOF'
import json
from data import admin
admin.init()
from roles import get_role

sec = get_role("架构·秘书")
# 老式 context：只有 [触发] 无完整 @ —— 应被自动补全路径
w = sec.awake("唤醒任务", "架构·产品",
              context="[触发:架构·产品] 请澄清需求细节", issue_ref="#142")
# 读出投递的 relay 消息（payload 可能是 JSON 字符串或 dict）
msgs = admin.replay(topic="depth.wake.架构·产品", limit=5)
found = False
for m in msgs:
    pl = m.get("payload") or {}
    if isinstance(pl, str):
        try:
            pl = json.loads(pl)
        except Exception:
            continue
    rt = pl.get("relay_text") or ""
    if "@dongdongxiaozu/dongjiagoushi(架构·产品)" in rt and "请澄清需求细节" in rt:
        found = True
assert found, "投递的 relay_text 应含完整 @org/repo(架构·产品) 路径"
print("  ✅ awake() 对缺完整@的 context 自动前置完整 @ 路径")
print("      relay_text=" + rt[:90])
EOF

echo "===== [fullpath] 4. relay_card 校验：只写 [回转]/[触发] 无完整@ → 拦截 ====="
$PY - <<'EOF'
from relay_card import check
# 老式写法：只有 [回转] 退回 + 角色名，无完整 @ → INVALID
ok, reasons = check("[回转] 退回:架构·开发 / 原因:x / 下一步要求:y", role="架构·开发")
assert ok is False, "缺完整 @ 的回转文本应判 INVALID_RELAY"
assert any("缺少完整" in r or "@org/repo" in r for r in reasons), reasons
# 只有 [触发:架构·开发] 无 @ → INVALID
ok2, reasons2 = check("[触发:架构·开发] 请返工", role="架构·开发")
assert ok2 is False, "缺完整 @ 的触发文本应判 INVALID_RELAY"
# 带完整 @ + [触发] → VALID
ok3, reasons3 = check("@dongdongxiaozu/dongjiagoushi(架构·开发) [触发:架构·开发] 返工",
                      role="架构·开发")
assert ok3 is True, reasons3
print("  ✅ relay_card：只写[回转]/[触发]无完整@ → 拦截；带完整@+[触发] → 放行")
EOF

echo "===== [fullpath] 5. 测试回执 relay_receipt 含完整 @org/repo(架构·测试) ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

tester = get_role("架构·测试")
reviewer = get_role("架构·评审")
task_key = "回执任务"
reviewer.handoff_to_tester(task_key, issue_ref="142", review_summary="通过",
                           disposition_label="proceed")
t = tester.take_over_and_develop(task_key, test_scope="E2E", goal_total=10,
                                 current=3, issue_ref="142")
assert t["accepted"] is True
assert "@dongdongxiaozu/dongjiagoushi(架构·测试)" in t["relay_receipt"], t["relay_receipt"]
assert "[触发:架构·测试]" in t["relay_receipt"]
print("  ✅ 测试回执含完整 @org/repo(架构·测试) + [触发:架构·测试]")
print("      " + t["relay_receipt"])
EOF

echo "===== [fullpath] ALL PASS ====="
