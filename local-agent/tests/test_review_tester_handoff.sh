#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 评审→测试 任务转交闭环测试（信号灯）
# ============================================================
# 修复用户 Issue #55 痛点：
#   「评审交任务不会 @架构·测试，没有真交付任务而是描述」+
#   「架构·测试 要接手任务继续去开发」。
# 验证：
#   1. 评审通过（disposition=merge/proceed）→ 必须真实转交「架构·测试」，
#      用完整 @org/repo(架构·测试)+[触发:架构·测试] 唤醒，校验 awakened 回执；
#   2. 评审未通过（fix_bug）→ 不转交测试，走 [回转] 退回:架构·开发；
#   3. 架构·测试 收到转交 → 回执 [接单] + 开工 + 进度尺推进（真接手非描述）；
#   4. 测试回执后，评审复校验转交真实成立（awakened=True）。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_review_tester_handoff.db"

echo "===== [handoff] 1. 评审通过(merge/proceed) 必须真实转交测试，且可校验回执 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
assert hasattr(reviewer, "handoff_to_tester"), "评审应具备 handoff_to_tester()"
assert hasattr(reviewer, "passes_to_tester"), "评审应具备 passes_to_tester()"
# merge/proceed 放行；fix_bug 不放行
assert reviewer.passes_to_tester("merge") is True
assert reviewer.passes_to_tester("proceed") is True
assert reviewer.passes_to_tester("fix_bug") is False
assert reviewer.passes_to_tester("research") is False

task_key = "评审转交测试"
r = reviewer.handoff_to_tester(task_key, issue_ref="55",
                               review_summary="五维通过，无🔴必修",
                               disposition_label="merge")
# 未回执时：转交意图已投递，但 awakened=False（路由未真唤醒，须重触发/升级）
assert r["disposition"] == "merge"
assert r["handed_off"] is False, "测试尚未回执前转交未真实成立"
assert "架构·测试" in r["target_role"]
assert r["relay_card"]["target_agent"] == "架构·测试"
assert r["relay_card"]["level"] == 3
print("  ✅ 评审通过 -> 投递完整[触发:架构·测试]接力卡，未回执时 awakened=False")
print(f"      disposition={r['disposition']}, handle={r['handle']}")
EOF

echo "===== [handoff] 2. 评审未通过(fix_bug) 不转交测试，走回转开发 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
r = reviewer.handoff_to_tester("未通过任务", issue_ref="55",
                               review_summary="存在🔴必修",
                               disposition_label="fix_bug")
assert r["handed_off"] is False
assert "未放行转交测试" in r["reason"]
assert r["next_step"] == "[回转] 退回:架构·开发"
print("  ✅ 评审未通过(fix_bug) 不转交测试，next_step=[回转]退回开发")
EOF

echo "===== [handoff] 3. 架构·测试 接手评审转交 -> [接单]+开工+进度尺推进（真接手非描述） ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
tester = get_role("架构·测试")
assert hasattr(tester, "take_over_and_develop"), "测试应具备 take_over_and_develop()"

task_key = "评审转交测试2"
reviewer.handoff_to_tester(task_key, issue_ref="55", review_summary="评审通过",
                           disposition_label="proceed")
# 测试接手
t = tester.take_over_and_develop(task_key, test_scope="E2E", goal_total=10,
                                 current=3, issue_ref="55")
assert t["accepted"] is True
assert t["started"] == "working"
assert t["progress"]["distance"] == 7, f"distance 应为7，实际 {t['progress']['distance']}"
assert "[触发:架构·测试]" in t["relay_receipt"]
print("  ✅ 测试接手：ack_wake(回执) + start_work(开工) + track_progress(进度尺) 三闭环通过")
print(f"      distance={t['progress']['distance']}（goal 10 - current 3）")
EOF

echo "===== [handoff] 4. 测试回执后，评审复校验转交真实成立(awakened=True) ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
tester = get_role("架构·测试")
task_key = "评审转交测试3"
reviewer.handoff_to_tester(task_key, issue_ref="55", review_summary="评审通过",
                           disposition_label="merge")
# 测试回执接手
tester.take_over_and_develop(task_key, test_scope="联调", goal_total=5,
                             current=1, issue_ref="55")
# 评审复校验转交
r2 = reviewer.handoff_to_tester(task_key, issue_ref="55", review_summary="已转交",
                                disposition_label="merge")
assert r2["handed_off"] is True, "测试已回执，转交应真实成立"
assert r2["awakened"] is True
print("  ✅ 测试回执后，评审复校验转交真实成立（awakened=True）")
print(f"      handed_off={r2['handed_off']}, awakened={r2['awakened']}")
EOF

echo "===== [handoff] 5. 输出契约含转交/接手能力 ====="
$PY - <<'EOF'
from data import admin
admin.init()
from roles import get_role

reviewer = get_role("架构·评审")
tester = get_role("架构·测试")
rc = reviewer.output_contract()
tc = tester.output_contract()
assert any("转交测试" in c for c in rc["contract"]), "评审输出契约应含转交测试"
assert any("接手评审转交" in c or "take_over_and_develop" in c for c in tc["contract"]), "测试输出契约应含接手开发"
print("  ✅ 评审/测试输出契约已含「转交测试」与「接手继续开发」")
EOF

echo "===== [handoff] ALL PASS ====="
