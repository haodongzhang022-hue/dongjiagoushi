# -*- coding: utf-8 -*-
"""
上位机 · CLI 入口（cli.py）
============================
命令行方式演示/驱动「上位机对机器角色的定时器 + 状态机」管理。

用法：
  python -m local-agent.engine.cli demo            # 跑一个端到端演示（含超时自动打断）
  python -m local-agent.engine.cli state <card>    # 查看某机器角色状态卡
  python -m local-agent.engine.cli transitions     # 打印合法转移表
"""
import sys
import time

from .state_machine import TRANSITIONS, STATES
from .host import HostEngine


def _print_transitions():
    print("合法转移表（行=当前状态，列=允许去向）：")
    for cur in STATES:
        nxt = sorted(TRANSITIONS.get(cur, set()))
        print(f"  {cur:12s} -> {', '.join(nxt) if nxt else '-'}")


def _demo():
    host = HostEngine(tick_interval=0.01)
    # 三台机器角色上场
    host.start_role("架构·产品", "prod_1")
    host.start_role("架构·开发", "dev_1")
    host.start_role("架构·测试", "test_1")

    # 启动产品与开发（[触发] 接手）
    host.machine("prod_1").start(actor="上位机")
    host.machine("dev_1").start(actor="上位机")

    # 给开发设 0.02 秒超时，超时未完成自动打断（模拟开发卡死）
    host.timeout_watch("dev_1", timeout_sec=0.02, reason="开发任务 20ms 未完成")

    # 上位机统一巡检 50 次（驱动定时器作用到机器角色）
    for _ in range(50):
        host.tick()
        time.sleep(0.001)

    # 产品正常完成
    host.machine("prod_1").complete(actor="上位机", reason="需求规格已交付")

    print("\n=== 上位机 · 机器角色状态总表 ===")
    for r in host.overview():
        print(f"  [{r['role']}] {r['card_id']}: {r['status']}")
    print("\n状态统计:", dict(host.summary()))
    print("\n开发状态卡历史（留痕）：")
    for h in (host.machine("dev_1").peek() or {}).get("history", []):
        print("   ", h)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "demo"
    if cmd == "transitions":
        _print_transitions()
    elif cmd == "state":
        card = sys.argv[2] if len(sys.argv) > 2 else "dev_1"
        from .state_machine import StateMachine
        print(StateMachine(card).peek())
    else:
        _demo()


if __name__ == "__main__":
    main()
