#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 开发闭环引擎（dev_loop）测试 —— 参考 Goose 四维闭环「执行-验证-规划-监督」
# 验证：目标门控 / 执行-验证分离 / 确定性状态机(不让LLM自决) / 硬性熔断(上报Leader) /
#       进度北极星监督(哨兵停滞拦截) / 统一交付
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dev_loop.db"

echo "===== [dev_loop] 1. 目标门控（Planner：任务不明确拒绝进入循环） ====="
$PY - <<'EOF'
from dev_loop import DevLoopEngine, DevLoopError
# 目标总量<=0 → 拒绝进入循环（Goose：Planner 先明确目标，Coder 才允许开工）
try:
    DevLoopEngine(goal_total=0)
    raise AssertionError("goal_total<=0 应拒绝")
except DevLoopError as e:
    assert "目标总量必须" in str(e), e
print("  ✅ 目标不明确拒绝进入循环 通过")
# 已完成 → 拒绝进入
e = DevLoopEngine(goal_total=10.0); e.current = 10.0
ok, why = e.can_enter_loop()
assert ok is False and "已完成" in why, (ok, why)
print("  ✅ 已完成拒绝循环 通过")
# 明确且未完成 → 允许
e2 = DevLoopEngine(goal_total=10.0)
ok, why = e2.can_enter_loop()
assert ok is True, why
print("  ✅ 任务明确允许进入循环 通过")
EOF

echo "===== [dev_loop] 2. 执行-验证分离（Coder 不自己裁定合格） ====="
$PY - <<'EOF'
from dev_loop import DevLoopEngine, DevLoopError
from data import admin
admin.init()
eng = DevLoopEngine(goal_total=10.0)
s = eng.start_iteration("task-exec", "架构·开发", target="实现登录", note="Coder产出")
assert s["phase"] == "execute" and s["iteration"] == 1
# 未验证就交付 → 拒绝（必须客观验证 APPROVED 才能进下一阶段）
try:
    eng.deliver_to_manager("task-exec", "架构·开发")
    raise AssertionError("未验证应拒绝交付")
except DevLoopError as e:
    assert "尚未通过客观验证" in str(e), e
# 独立验证器（Reviewer）给出客观结论
eng.verify(approved=True, evidence="test 8/8 pass, eslint clean", by="objective_verifier",
           task_id="task-exec", agent_id="架构·开发")
d = eng.decide(task_id="task-exec", agent_id="架构·开发")
assert d["verdict"] in ("approved", "complete"), d
print(f"  ✅ 执行-验证分离 + 客观验证(evidence={eng.verdict['evidence']}) 通过")
EOF

echo "===== [dev_loop] 3. 确定性状态机（不让 LLM 决定下一步/是否结束） ====="
$PY - <<'EOF'
from dev_loop import run_single_round
# APPROVED → 放行进入下一阶段
d1 = run_single_round("t", "架构·开发", 10.0, 2.0, approved=True, evidence="pass")
assert d1["verdict"] == "approved" or d1["verdict"] == "complete", d1
# REJECTED → 强制回退 rework
d2 = run_single_round("t", "架构·开发", 10.0, 2.0, approved=False, evidence="fail")
assert d2["verdict"] == "rework", d2
print("  ✅ 确定性状态机：APPROVED放行 / REJECTED回退 通过")
EOF

echo "===== [dev_loop] 4. 硬性熔断（重做超过 max_attempts 上报 Leader，不无限重试） ====="
$PY - <<'EOF'
from dev_loop import DevLoopEngine
from data import admin
admin.init()
eng = DevLoopEngine(goal_total=10.0, max_attempts=3)
for i in range(1, 5):  # 第1-4次验证都 FAIL
    eng.start_iteration("task-fuse", "架构·开发", target="修复bug")
    eng.verify(approved=False, evidence=f"fail#{i}", task_id="task-fuse", agent_id="架构·开发")
    d = eng.decide(task_id="task-fuse", agent_id="架构·开发")
    if i <= 3:
        assert d["verdict"] == "rework", (i, d)
    else:
        assert d["verdict"] == "escalate", (i, d)  # 第4次超过 max_attempts=3 → 上报Leader
        assert d["reason"].find("上报 Leader") >= 0, d
assert eng.leader_escalated is True
# 熔断后禁止自行继续（等 Leader 决策）
ok, why = eng.can_enter_loop()
assert ok is False and "上报 Leader" in why, (ok, why)
print("  ✅ 硬性熔断：4次验证失败 → 上报 Leader，不再无限重试 通过")
EOF

echo "===== [dev_loop] 5. 最大迭代上限（资源耗尽防线） ====="
$PY - <<'EOF'
from dev_loop import DevLoopEngine, DevLoopError
eng = DevLoopEngine(goal_total=10.0, max_iterations=3)
for i in range(3):
    eng.start_iteration("t-iter", "架构·开发", target="x")
    eng.verify(approved=False, evidence=f"f{i}")
    eng.decide(task_id="t-iter", agent_id="架构·开发")
# 第4次 start 应因已达 max_iterations 被熔断
try:
    eng.start_iteration("t-iter", "架构·开发")
    raise AssertionError("超 max_iterations 应熔断")
except DevLoopError as e:
    assert "最大迭代上限" in str(e), e
print("  ✅ 最大迭代上限熔断 通过")
EOF

echo "===== [dev_loop] 6. 统一交付（完成/验证通过后一次性交给经理） ====="
$PY - <<'EOF'
from dev_loop import DevLoopEngine
from data import admin
admin.init()
eng = DevLoopEngine(goal_total=10.0)
eng.start_iteration("t-deliver", "架构·开发", target="完成模块")
eng.advance(10.0)  # 推进到目标
eng.verify(approved=True, evidence="all tests pass", task_id="t-deliver", agent_id="架构·开发")
d = eng.decide(task_id="t-deliver", agent_id="架构·开发")
assert d["verdict"] == "complete", d
r = eng.deliver_to_manager("t-deliver", "架构·开发", summary="模块完成")
assert r["delivered"] is True and r["remaining"] == 0.0, r
print("  ✅ 统一交付（完成→一次性交经理） 通过")
EOF

echo "===== [dev_loop] 7. 进度北极星监督（advance 不回退 + 哨兵可判停滞） ====="
$PY - <<'EOF'
from dev_loop import DevLoopEngine, DevLoopError
from sentinel import engine as sentinel
eng = DevLoopEngine(goal_total=10.0)
eng.advance(3.0); assert eng.current == 3.0
eng.advance(2.0); assert eng.current == 5.0
# 进度不可回退（横跳由哨兵判定）
try:
    eng.advance(-1.0)
    raise AssertionError("进度不可回退")
except DevLoopError as e:
    assert "不可回退" in str(e), e
# 哨兵可对该循环做停滞判定（接入 goal_meters）
from data import admin
admin.init()
# 连续无推进记录 → 哨兵判停滞
for _ in range(6):
    eng.start_iteration("t-stag-loop", "架构·开发")
a = sentinel.analyze(sentinel.store.meter_series(f"loop-{eng.loop_id}"),
                     goal_total=10.0, task_id="t-stag-loop", agent_id="架构·开发")
assert a["hit"] is True and a["reason"] == "stagnation", a
print("  ✅ 进度北极星监督（advance不回退 + 哨兵停滞拦截） 通过")
EOF

echo ""
echo "===== 全部 dev_loop 测试通过 ====="
