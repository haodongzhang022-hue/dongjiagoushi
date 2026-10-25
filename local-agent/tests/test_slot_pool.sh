#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 执行体槽位池（slot）· 近因优先 + 加长队列 + 领取后自愈 信号灯
# 治理病根：一个卡住的老任务长期占住并发额度，导致 @ 了角色却一直没反应。
# 对应用户原话（PR #247）：最新优先领取 / 加长队列 / 领取一个后把其他接上。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH=$(mktemp /tmp/slot-test-XXXX.db)
rm -f "$DB_PATH"

echo "===== [slot] 1. 近因优先：取最新入队，不是最早入队 ====="
$PY - <<'EOF'
import time
from slot import SlotPool
p = SlotPool(capacity=16, slots=4, clock=lambda: 0.0)
for i in range(1, 5):
    p.enqueue(f"task-{i}")
    p._tasks[f"task-{i}"].enqueued_at = float(i)     # 明确先后：4 最新
got = p.pick()
assert got.task_id == "task-4", got.task_id
p2 = SlotPool(capacity=16, slots=4, order="fifo")
for i in range(1, 5):
    p2.enqueue(f"task-{i}")
    p2._tasks[f"task-{i}"].enqueued_at = float(i)
assert p2.pick().task_id == "task-1", "fifo 对照应为最早"
print("  ✅ 近因优先取件（fifo 仅作对照）通过")
EOF

echo "===== [slot] 2. 卡住后不堵：卡住一件后仍能继续领，不会一直卡 ====="
$PY - <<'EOF'
from slot import SlotPool
p = SlotPool(capacity=16, slots=1, max_repairs=1)
for i in range(1, 5):
    p.enqueue(f"task-{i}")
    p._tasks[f"task-{i}"].enqueued_at = float(i)
r1 = p.reserve(); assert r1["task"].task_id == "task-4" and r1["slot"] == 0
p.mark_stuck("task-4")                              # 第一件就卡住
r2 = p.reserve(); assert r2["task"].task_id == "task-3", r2["task"].task_id
# 关键：卡住的 task-4 没有压住池头（近因优先下被跨过）
assert "task-4" in r2["repairs"], r2["repairs"]
p.release("task-3", ok=True)
r3 = p.reserve(); assert r3["task"] is not None, "槽位应已释放，能继续出活"
print("  ✅ 卡住不堵 + 跨过卡死任务 通过")
EOF

echo "===== [slot] 3. 领取后自愈接回 + 超限标 dead（不静默） ====="
$PY - <<'EOF'
from slot import SlotPool
p = SlotPool(capacity=16, slots=4, max_repairs=2)
p.enqueue("stuck-one")
p.mark_stuck("stuck-one")
assert p._tasks["stuck-one"].state == "stuck"
repaired = p.repair_rest()
assert "stuck-one" in repaired and p._tasks["stuck-one"].state == "queued"
assert p._tasks["stuck-one"].repairs == 1
# 自愈次数用完 → 仍卡 → 超 max_repairs 必须显式 dead，不静默重试
for _ in range(3):
    p.mark_stuck("stuck-one"); p.repair_rest()
t = p._tasks["stuck-one"]
assert t.state == "dead", t.state
assert "上报" in t.note and t.repairs >= 2
ov = p.overview()
assert ov["stats"]["dead"] == 1 and ov["needs_action"] >= 1
print("  ✅ 领取后自愈接回 + 超限显式 dead 通过")
EOF

echo "===== [slot] 4. 加长队列：满则拒绝并计数，不静默丢件 ====="
$PY - <<'EOF'
from slot import SlotPool
p = SlotPool(capacity=3, slots=2)
for i in range(3):
    assert p.enqueue(f"t{i}") is not None
assert p.enqueue("t3") is None, "队列满应拒绝"
st = p.stats()
assert st["rejected_full"] == 1, st
# 幂等：同 task_id 重复入队不重复占位
p2 = SlotPool(capacity=8, slots=2)
p2.enqueue("dup"); p2.enqueue("dup")
assert p2.stats()["queued"] == 1, p2.stats()
print("  ✅ 长队列容量 + 满则显式拒绝 + 幂等入队 通过")
EOF

echo "===== [slot] 5. 槽位满：显式 blocked，不假装领到 ====="
$PY - <<'EOF'
from slot import SlotPool
p = SlotPool(capacity=16, slots=1)
p.enqueue("a"); p.enqueue("b")
r1 = p.reserve(); assert r1["slot"] == 0 and not r1["blocked"]
r2 = p.reserve()                       # 唯一槽位被占
assert r2["blocked"] is True and r2["task"] is None and r2["slot"] is None
print("  ✅ 槽位满显式 blocked（不假装领到） 通过")
EOF

echo "===== [slot] 6. 超时判 stuck：占用挂着不会被静默遗忘 ====="
$PY - <<'EOF'
from slot import SlotPool
now = [0.0]
p = SlotPool(capacity=16, slots=1, stuck_after_seconds=10, clock=lambda: now[0])
p.enqueue("long")
p.reserve()
now[0] = 5.0
assert p.sweep_stuck() == [], "未超时不应判 stuck"
now[0] = 11.0
assert p.sweep_stuck() == ["long"]
assert p._tasks["long"].state == "stuck"
print("  ✅ 占用超时判 stuck 通过")
EOF

echo "===== [slot] 7. 配置同源：.cnb.yml 是单一事实源（CI/本地同读） ====="
$PY - <<'EOF'
import os
from slot.pool import load_npc_pool_config, pool_from_config, DEFAULTS
cfg = load_npc_pool_config()
assert cfg["source"] == ".cnb.yml:npc_task.slot_pool", cfg["source"]
assert cfg["queue_capacity"] == 512 and cfg["slots"] == 4, cfg
assert cfg["max_repairs"] >= 1 and cfg["stuck_after_seconds"] > 0
p = pool_from_config()
assert p.cfg["queue_capacity"] == 512
# 缺文件时退化为默认，不报错也不冒充读到
missing = load_npc_pool_config(repo_root="/tmp/definitely-not-a-repo")
assert missing["source"] == "defaults" and missing["queue_capacity"] == DEFAULTS["queue_capacity"]
print("  ✅ .cnb.yml slot_pool 配置同源 + 缺失时诚实退化 通过")
EOF

echo "===== [slot] 8. 端到端：10 件活 + 首件卡住，池子不空转 ====="
$PY - <<'EOF'
from slot import SlotPool
p = SlotPool(capacity=512, slots=2, max_repairs=3)
for i in range(1, 11):
    p.enqueue(f"job-{i}")
    p._tasks[f"job-{i}"].enqueued_at = float(i)
first = p.reserve()
assert first["task"].task_id == "job-10", "近因优先应取最新 job-10"
p.mark_stuck("job-10")
done = 0
for _ in range(12):
    r = p.reserve()
    if r["task"] is None:
        continue
    p.release(r["task"].task_id, ok=True)
    done += 1
st = p.stats()
assert done >= 9, f"应能交付大部分活，实际 {done}"
assert st["running"] == 0
assert st["dead"] <= 1                      # 自愈超限最多一个显式 dead
ov = p.overview()
assert ov["slots_free"] == 2 and ov["order_policy"].startswith("recency-first")
print(f"  ✅ 端到端通过（交付 {done} 件，dead={st['dead']}，stuck={st['stuck']}）")
EOF

echo ""
echo "🎉 [slot] 全部 8 组信号灯通过（近因优先 / 卡住不堵 / 领取后自愈 / 长队列 / 槽位满显式 / 超时判 stuck / 配置同源 / 端到端）"
