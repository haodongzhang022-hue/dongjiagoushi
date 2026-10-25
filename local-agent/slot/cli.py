# -*- coding: utf-8 -*-
"""
执行体槽位池 · 命令行（slot.cli）
==================================
用法：
  python -m slot.cli overview                 # 按 .cnb.yml 配置打印池子全貌
  python -m slot.cli config                   # 只打印生效配置（核验 CI/本地同源）
  python -m slot.cli demo                     # 跑一遍近因优先 + 领取后自愈
  python -m slot.cli simulate --tasks 6 --slots 2 --stuck-first
                                              # 模拟：FIFO vs 近因优先 的卡住影响对比
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slot.pool import SlotPool, DEFAULTS, pool_from_config, load_npc_pool_config


def cmd_overview(args):
    pool = pool_from_config(**({"capacity": args.capacity} if args.capacity else {}))
    print(json.dumps(pool.overview(), ensure_ascii=False, indent=2))


def cmd_config(args):
    print(json.dumps(load_npc_pool_config(), ensure_ascii=False, indent=2))


def cmd_demo(args):
    pool = SlotPool(capacity=8, slots=1, stuck_after_seconds=60, max_repairs=2)
    for i in range(1, 5):
        pool.enqueue(f"task-{i}")
    first = pool.reserve()
    print("① 近因优先领取：", first["task"].task_id, "（应是 task-4，最新入队）")
    pool.mark_stuck(first["task"].task_id)
    second = pool.reserve()
    print("② 卡住后不堵：", second["task"].task_id, "（应是 task-3，跨过卡住的 task-4）")
    print("③ 领取后自愈接回：", second["repairs"], "（task-4 被重新接回）")
    print(json.dumps(pool.overview(), ensure_ascii=False, indent=2))


def cmd_simulate(args):
    """同一组任务，FIFO 与近因优先各自的实际结果对比（诚实口径）。

    两列都报：
      picked       实际被取走的序列（含自愈接回后重取的）
      first_ok_at  第一件成功交付的取件序号（1 = 第一下就出活，不被卡住压住）
      ok           累计成功交付件数
    """
    n = args.tasks
    ids = [f"task-{i}" for i in range(1, n + 1)]

    def run(order):
        p = SlotPool(capacity=n + 4, slots=(args.slots or 1),
                     stuck_after_seconds=60, max_repairs=1, order=order)
        for tid in ids:
            p.enqueue(tid)
        picked, first_ok_at, ok = [], None, 0
        for i in range(n):
            r = p.reserve()
            if r["task"] is None:
                break
            tid = r["task"].task_id
            is_first = not picked
            picked.append(tid)
            if args.stuck_first and is_first:
                p.mark_stuck(tid)              # 第一件就卡住
                continue
            p.release(tid, ok=True)
            ok += 1
            if first_ok_at is None:
                first_ok_at = i + 1
        return {"picked": picked, "first_ok_at": first_ok_at, "ok": ok,
                "stats": p.stats()}

    fifo = run("fifo")
    rec = run("recency")
    print(json.dumps({
        "tasks": n,
        "stuck_first": bool(args.stuck_first),
        "fifo": fifo,
        "recency": rec,
        "why": "近因优先的价值是『第一下不被卡住的老任务压住』；卡住的活由 repair_rest 接回，"
               "接回次数由 max_repairs 兜底，超限标 dead 显式暴露（不静默）。",
    }, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="slot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("overview")
    o.add_argument("--capacity", type=int)
    o.set_defaults(func=cmd_overview)
    sub.add_parser("config").set_defaults(func=cmd_config)
    sub.add_parser("demo").set_defaults(func=cmd_demo)
    s = sub.add_parser("simulate")
    s.add_argument("--tasks", type=int, default=6)
    s.add_argument("--slots", type=int, default=1)
    s.add_argument("--stuck-first", action="store_true")
    s.set_defaults(func=cmd_simulate)
    args = ap.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
