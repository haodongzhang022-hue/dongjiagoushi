#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 上位机 · 工程能力引擎（engine）功能测试
# 验证：状态机合法转移强制校验 / 定时器（心跳·超时·定时任务）/ 上位机整合
# 对应 docs/HOST_ENGINE.md；纳入 local-agent 测试信号灯。
set -e
cd "$(dirname "$0")/.."
PY=python3

echo "===== [engine] 1. 状态机 · 合法转移表 ====="
$PY - <<'EOF'
from engine.state_machine import STATES, TRANSITIONS, is_valid_transition
# 状态集完整（含接力协议所需状态）
for s in ["pending","in_progress","done","reverted","retry","interrupted","blocked","paused"]:
    assert s in STATES, f"缺状态 {s}"
# 关键合法转移
assert is_valid_transition("in_progress","done")      # [触发]->[通过]
assert is_valid_transition("done","reverted")         # [回转]
assert is_valid_transition("reverted","retry")        # 返工重跑
assert is_valid_transition("in_progress","interrupted")  # [打断]
assert is_valid_transition("interrupted","in_progress")  # [续跑]
assert is_valid_transition("in_progress","paused")    # CP 闸门暂停
print(f"  STATES={len(STATES)} 个，关键转移断言通过")
print("  ✅ 状态集 + 合法转移表通过")
EOF

echo "===== [engine] 2. 状态机 · 非法转移强制拦截 ====="
$PY - <<'EOF'
from engine.state_machine import StateMachine
from scale import store
store.clear_all()
sm = StateMachine("bad_1")
# pending -> done 非法，必须报错
try:
    sm.complete()
    raise AssertionError("非法转移未被拦截")
except ValueError as e:
    assert "非法转移" in str(e)
# pending -> interrupted 也非法（必须先 start）
try:
    StateMachine("bad_2").interrupt()
    raise AssertionError("非法转移未被拦截")
except ValueError:
    pass
print("  ✅ 非法转移被强制拦截")
EOF

echo "===== [engine] 3. 状态机 · 完整接力链路（回转/打断/续跑/阻塞）===="
$PY - <<'EOF'
from engine.state_machine import StateMachine
from scale import store
store.clear_all()
sm = StateMachine("task_1")
sm.start(actor="产品")                 # pending->in_progress
sm.complete(actor="产品")              # ->done
sm.revert(reason="评审 🔴必修", actor="评审")  # done->reverted
assert sm.status == "reverted"
sm.retry(actor="产品")                 # reverted->retry
sm.start(actor="产品")                 # retry->in_progress
sm.interrupt(checkpoint="已做到第2步，卡在依赖", actor="打断")  # in_progress->interrupted
assert sm.status == "interrupted"
sm.resume(actor="产品")                # interrupted->in_progress 续跑
sm.complete(actor="产品")              # ->done
# 留痕可观测
hist = sm.peek()["history"]
assert len(hist) >= 6, "每次转移都应留痕"
print(f"  留痕条数={len(hist)}，最后一条={hist[-1]['msg']}")
print("  ✅ 完整接力链路（回转/打断/续跑）通过")
EOF

echo "===== [engine] 4. 定时器 · 定时任务 + 一次性触发 ====="
$PY - <<'EOF'
import time
from engine.timer import TimerEngine
t = TimerEngine()
calls = {"n": 0}
t.schedule("job_a", interval=0.005, fn=lambda: calls.__setitem__("n", calls["n"]+1))
# 只执行一次的定时触发
once = {"n": 0}
t.schedule("job_b", interval=0.001, fn=lambda: once.__setitem__("n", once["n"]+1), repeat=False)
# 跑 60 次 tick（放宽以抵御调度抖动）
for _ in range(60):
    t.tick(); time.sleep(0.0005)
assert calls["n"] >= 3, f"周期任务应多次执行, got {calls['n']}"
assert once["n"] == 1, f"一次性任务应只执行1次, got {once['n']}"
assert "job_b" not in t._jobs, "一次性任务执行后应移除"
print(f"  周期任务执行 {calls['n']} 次 | 一次性任务 {once['n']} 次")
print("  ✅ 定时任务（周期 + 一次性）通过")
EOF

echo "===== [engine] 5. 定时器 · 超时自动打断/阻塞 ====="
$PY - <<'EOF'
import time
from engine.timer import TimerEngine
from engine.state_machine import StateMachine
from scale import store
store.clear_all()

# 场景A：in_progress 超时 -> 自动打断（interrupt）
smA = StateMachine("dev_A"); smA.start()
tA = TimerEngine()
tA.watch("dev_A", timeout_sec=0.02, reason="开发卡死")
for _ in range(30):
    tA.tick(); time.sleep(0.001)
assert store.get("dev_A")["status"] == "interrupted", "超时应自动打断"
assert "续跑" in store.get("dev_A")["checkpoint"]

# 场景B：超时 -> 直接阻塞（block，on_timeout="block"）
smB = StateMachine("dev_B"); smB.start()
tB = TimerEngine()
tB.watch("dev_B", timeout_sec=0.02, on_timeout="block", reason="严重卡死")
for _ in range(30):
    tB.tick(); time.sleep(0.001)
assert store.get("dev_B")["status"] == "blocked", "超时应自动阻塞"
print("  ✅ 超时自动打断 / 自动阻塞 通过")
EOF

echo "===== [engine] 6. 上位机 HostEngine · 整合巡检 ====="
$PY - <<'EOF'
import time
from engine.host import HostEngine
from scale import store
store.clear_all()
host = HostEngine(tick_interval=0.005)
host.start_role("架构·产品", "prod_1")
host.start_role("架构·开发", "dev_1")
host.schedule("heartbeat", 0.01, lambda: None)
host.timeout_watch("dev_1", 0.02, reason="开发卡死")
host.machine("prod_1").start(actor="上位机")
host.machine("dev_1").start(actor="上位机")
for _ in range(60):
    host.tick(); time.sleep(0.001)
host.machine("prod_1").complete(actor="上位机")
ov = host.overview()
assert host.machine("prod_1").status == "done"
assert host.machine("dev_1").status == "interrupted"
assert len(ov) == 2
assert host.summary()["done"] == 1 and host.summary()["interrupted"] == 1
print("  状态总表:")
for r in ov:
    print(f"    [{r['role']}] {r['card_id']}: {r['status']}")
print("  ✅ 上位机整合巡检（定时器+状态机统一管理）通过")
EOF

echo "===== [engine] 7. CLI 入口 ====="
$PY -m engine.cli transitions >/dev/null && echo "  ✅ engine.cli transitions 可运行"
$PY -m engine.cli demo >/dev/null && echo "  ✅ engine.cli demo 可运行"

echo ""
echo "✅ [engine] 全部测试通过"
