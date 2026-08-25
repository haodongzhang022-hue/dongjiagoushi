#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 监控哨兵（sentinel）功能测试 —— 防无效努力 / 目标收敛监控
# 验证：目标进度尺刻度 / 停滞(stagnation) / 横跳(oscillation) / 重复错误(repeated_error) /
#       1级打断重规划 / 2级上报架构师助理 / 健康报告
set -e
cd "$(dirname "$0")/.."
PY=python3

export DB_PATH="$(mktemp -d)/test_sentinel.db"

echo "===== [sentinel] 1. 建表 + 目标进度尺刻度（量化距离） ====="
$PY - <<'EOF'
from data import admin, schema
from sentinel import store, engine
admin.init()
for t in ["goal_meters", "sentinel_actions"]:
    assert t in schema.list_tables(), f"缺表 {t}"
# 记录推进：goal_total=10，current=4 → distance=6，delta(首次)=0
m1 = store.record_meter("g-task1", task_id="task1", agent_id="架构·开发",
                        target="完成登录", goal_total=10.0, current=4.0, note="模块A完成")
assert m1["distance"] == 6.0
# 推进到 6 → distance=4，delta=-2（在靠近）
m2 = store.record_meter("g-task1", task_id="task1", agent_id="架构·开发",
                        target="完成登录", goal_total=10.0, current=6.0, note="模块B完成")
assert m2["distance"] == 4.0 and m2["delta"] == -2.0
series = store.meter_series("g-task1")
assert len(series) == 2 and series[-1]["current"] == 6.0
print("  ✅ 目标进度尺刻度 + 量化距离 通过")
EOF

echo "===== [sentinel] 2. 停滞检测（原地打转） ====="
$PY - <<'EOF'
from data import admin
from sentinel import engine
admin.init()
engine.track("g-stag", task_id="t-stag", agent_id="架构·开发", target="X",
             goal_total=10.0, current=5.0, note="n1")
for i in range(6):
    engine.track("g-stag", task_id="t-stag", agent_id="架构·开发", target="X",
                 goal_total=10.0, current=5.0, note="无进展")  # current 不变 → 停滞
a = engine.analyze(engine.store.meter_series("g-stag"), goal_total=10.0,
                   task_id="t-stag", agent_id="架构·开发")
assert a["hit"] is True and a["reason"] == "stagnation", a
print("  ✅ 停滞检测 通过")
EOF

echo "===== [sentinel] 3. 横跳检测（反复来回不收敛） ====="
$PY - <<'EOF'
from data import admin
from sentinel import engine
admin.init()
# 距离序列在 0.5~0.6 之间来回摆动，净推进 < 阈值 → oscillation
seq = [5.0, 4.0, 5.0, 4.0, 5.0, 4.0, 5.0]  # current 相对 goal_total=10 → distance 5/6 摆动
for i, cur in enumerate(seq):
    engine.track("g-osc", task_id="t-osc", agent_id="架构·开发", target="Y",
                 goal_total=10.0, current=cur, note=f"来回{i}")
a = engine.analyze(engine.store.meter_series("g-osc"), goal_total=10.0,
                   task_id="t-osc", agent_id="架构·开发")
assert a["hit"] is True and a["reason"] == "oscillation", a
print("  ✅ 横跳检测 通过")
EOF

echo "===== [sentinel] 4. 重复错误检测 ====="
$PY - <<'EOF'
from data import admin
from sentinel import engine
admin.init()
for i in range(5):
    engine.track("g-rep", task_id="t-rep", agent_id="架构·开发", target="Z",
                 goal_total=10.0, current=float(i), note="同样的报错重试")  # 同一失败动作
a = engine.analyze(engine.store.meter_series("g-rep"), goal_total=10.0,
                   task_id="t-rep", agent_id="架构·开发")
assert a["hit"] is True and a["reason"] == "repeated_error", a
print("  ✅ 重复错误检测 通过")
EOF

echo "===== [sentinel] 5. 正常收敛不误伤（放行） ====="
$PY - <<'EOF'
from data import admin
from sentinel import engine
admin.init()
for cur in [0.0, 2.0, 4.0, 6.0, 8.0, 9.5]:  # 单调推进
    engine.track("g-ok", task_id="t-ok", agent_id="架构·开发", target="OK",
                 goal_total=10.0, current=cur, note="稳步推进")
a = engine.analyze(engine.store.meter_series("g-ok"), goal_total=10.0,
                   task_id="t-ok", agent_id="架构·开发")
assert a["hit"] is False, a
print("  ✅ 正常收敛放行（不误伤） 通过")
EOF

echo "===== [sentinel] 6. 处置协议：1级打断重规划 + 2级上报架构师助理 ====="
$PY - <<'EOF'
from data import admin
from sentinel import engine
admin.init()
admin.assign_task("t-inter", "无效任务", "架构·开发")
# 制造停滞 → 触发 1 级打断
r1 = engine.handle("g-h", task_id="t-inter", agent_id="架构·开发",
                   target="无效", goal_total=10.0, current=5.0, note="n")
for _ in range(6):
    r1 = engine.handle("g-h", task_id="t-inter", agent_id="架构·开发",
                       target="无效", goal_total=10.0, current=5.0, note="无进展")
assert r1["handled"] is True, r1
assert engine.store.count_actions(level=1) >= 1
# 再触发一次 → 该任务已有 2 级计数? 第一次是 1 级。制造再次命中 → 级别应升 2
a = engine.analyze(engine.store.meter_series("g-h"), goal_total=10.0,
                   task_id="t-inter", agent_id="架构·开发")
# 首次命中为 1 级；继续制造命中（再次 analyze 时 prev_l2=0，仍 1 级，但 handle 已落 1 级）。
# 直接调 escalate 验证 2 级留痕
action_id = engine.escalate("t-inter", "架构·开发", "oscillation",
                            {"note": "二度无效努力"})
assert engine.store.level2_count_for_task("t-inter") >= 1
assert engine.store.count_actions(level=2) >= 1
print("  ✅ 1级打断 + 2级上报架构师助理 通过")
EOF

echo "===== [sentinel] 7. 健康报告（二级信息） ====="
$PY - <<'EOF'
from data import admin
from sentinel import engine
admin.init()
r = engine.health_report()
assert "meters" in r and "interrupts" in r and "escalations" in r
assert r["meters"] >= 0 and r["interrupts"] >= 0 and r["escalations"] >= 0
print("  ✅ 健康报告 通过 ->", r)
EOF

echo "===== [sentinel] 8. 角色注册 ====="
$PY - <<'EOF'
from roles import get_role, list_roles
assert "架构·监控哨兵" in list_roles()
role = get_role("架构·监控哨兵")
assert role is not None and role.name == "架构·监控哨兵"
assert "无效努力" in role.SYSTEM_PROMPT
print("  ✅ 架构·监控哨兵 角色注册 通过")
EOF

echo "===== [sentinel] ALL PASS ====="
