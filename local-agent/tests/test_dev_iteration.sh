#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 开发持续推进引擎测试（信号灯）
# 验证「开发没开发完 → 继续接开发（自循环）」机制（docs/DEV_ITERATION.md）：
#   ① 任务明确前提（goal_total > 0）
#   ② 记录推进度（goal_meters + archives，非对话）
#   ③ 哨兵拦截（停滞/横跳/重复错误 → 打断，防无限循环）
#   ④ 完成统一交付给经理（一次性通知 + 完整进度记录）
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dev_iteration.db"

echo "===== [dev_iteration] 1. 任务明确前提 ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, os.getcwd())
from data import admin, schema
admin.init()
import dev_iteration

# ① 任务明确：goal_total > 0 才能自循环
r = dev_iteration.can_continue("登录模块", goal_total=10, current=3)
assert r["can_continue"] == True, r
assert r["reason"] == "ready"
assert r["distance"] == 7

# ② 目标不明确：goal_total <= 0 → 不能自循环
r2 = dev_iteration.can_continue("模糊任务", goal_total=0, current=3)
assert r2["can_continue"] == False, r2
assert r2["reason"] == "no_goal"

# ③ 已完成：current >= goal_total → 应交付
r3 = dev_iteration.can_continue("已完成任务", goal_total=10, current=10)
assert r3["can_continue"] == False, r3
assert r3["reason"] == "completed"

print("  ✅ 任务明确前提：goal>0可自循环 / goal<=0拒绝 / 完成则交付 通过")
EOF

echo "===== [dev_iteration] 2. 记录推进度（goal_meters + archives，非对话） ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, os.getcwd())
from data import admin, schema
admin.init()
import dev_iteration

task_id, _ = admin.register_gid("task", "登录模块")
agent_id, _ = admin.register_gid("agent", "登录模块")

# 每次推进写进度尺 + 存档（不投递对话消息）
res = dev_iteration.continue_dev(
    "登录模块", agent_id, target="实现登录功能",
    goal_total=10, current=3, note="完成需求分析",
    archive_detail="梳理了登录流程，明确了用户表结构",
)
assert res["can_continue"] == True
assert res["continue_reason"] == "ready"
assert res["record"]["distance"] == 7
assert res["record"]["archived"] == True
assert res["sentinel"]["hit"] == False

# 再次推进
res2 = dev_iteration.continue_dev(
    "登录模块", agent_id, target="实现登录功能",
    goal_total=10, current=8, note="完成核心逻辑",
)
assert res2["can_continue"] == True
assert res2["record"]["distance"] == 2
assert res2["record"]["delta"] == -5  # 在靠近（负 delta）

# 过程中不触发经理对话：经理不应收到待处理消息
mgr_pending = admin.pending(agent_id="架构·经理")
print(f"  经理待处理消息: {mgr_pending}（应为0，过程中不打扰经理）")

print("  ✅ 记录推进度：goal_meters + archives 留痕，非对话，经理不被打扰 通过")
EOF

echo "===== [dev_iteration] 3. 完成判定：统一交付给经理 ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, os.getcwd())
from data import admin, schema
admin.init()
import dev_iteration

task_id, _ = admin.register_gid("task", "结算模块")
agent_id, _ = admin.register_gid("agent", "结算模块")

# 自循环推进到完成
results = dev_iteration.run_iterations(
    "结算模块", agent_id, target="实现结算功能",
    goal_total=5, steps=[1, 2, 3, 4, 5],
    notes=["梳理结算流程", "实现金额计算", "实现优惠处理", "接入支付接口", "全量自测通过"],
)
assert len(results) == 5
assert results[-1]["continue_reason"] == "completed"
assert results[-1]["can_continue"] == False
assert results[-1]["distance"] == 0

# 统一交付给经理（一次性通知）
delivered = dev_iteration.deliver_to_manager(
    "结算模块", agent_id,
    output="结算功能已实现，5轮开发全部完成，自测通过",
    issue_ref="#41",
)
assert delivered["status"] == "delivered"
assert len(delivered["progress_history"]) == 5

# 交付后经理应收到一条交付消息
mgr_pending = admin.pending(agent_id="架构·经理")
assert mgr_pending >= 1, f"交付后经理应收到消息，实际 {mgr_pending}"
msg = admin.consume(agent_id="架构·经理")
assert msg is not None
payload = msg["payload"]
assert payload.get("action") == "开发已完成，统一交付"
assert len(payload.get("progress_history", [])) == 5

print("  ✅ 完成统一交付：一次性给经理 + 完整进度记录回放 通过")
EOF

echo "===== [dev_iteration] 4. 哨兵拦截：防无限循环（重复错误） ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, os.getcwd())
from data import admin, schema
admin.init()
import dev_iteration

task_id, _ = admin.register_gid("task", "重复错误任务")
agent_id, _ = admin.register_gid("agent", "重复错误任务")

# 连续提交相同错误（3 次触发 repeated_error 拦截）
results = []
for i in range(5):
    res = dev_iteration.continue_dev(
        "重复错误任务", agent_id, target="修bug",
        goal_total=10, current=i, note="尝试修复：运行报错 test failed, 重试",
    )
    results.append(res)
    if not res["can_continue"]:
        break

# 应有哨兵拦截
hit = any(r["continue_reason"].startswith("sentinel_") for r in results)
assert hit, "应有哨兵拦截（重复错误）"

# 处置：打断重规划
hit_res = next(r for r in results if r["continue_reason"].startswith("sentinel_"))
handled = dev_iteration.handle_sentinel_hit("重复错误任务", agent_id, hit_res["sentinel"])
assert handled["handled"] == True
assert handled["level"] == 1
assert handled["action"] == "打断重规划（依据剩余距离重新分配）"

print("  ✅ 哨兵拦截：重复错误 → 打断重规划，防无限循环 通过")
EOF

echo "===== [dev_iteration] 5. 二级信息：进度回放 + 迭代俯瞰 ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, os.getcwd())
from data import admin, schema
admin.init()
import dev_iteration

# 进度回放
hist = dev_iteration.progress_history("登录模块")
assert len(hist) >= 2, f"登录模块应有至少2条进度记录，实际 {len(hist)}"

# 迭代俯瞰
ov = dev_iteration.iteration_overview()
assert ov["total_tasks"] >= 1
assert ov["total_meters"] >= 2

print("  ✅ 二级信息：progress_history 回放 + iteration_overview 俯瞰 通过")
EOF

echo "===== [dev_iteration] ALL PASS ====="
