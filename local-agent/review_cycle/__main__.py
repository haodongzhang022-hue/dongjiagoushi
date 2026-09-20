# -*- coding: utf-8 -*-
"""评审段调度器 CLI 入口：`python3 -m review_cycle <run|overview|stats|demo>`。

Issue #150 返工 S9：文档里的 CLI 必须**真的能跑通**——此前只有库接口、没有
`__main__`，`python -m review_cycle run` 直接失败。本入口补齐，并把 CLI 收口到
一处（与 `run.py --review-cycle` 同引擎，不重复实现）。

从仓库根运行（PYTHONPATH 指向 local-agent，与其它 local-agent 模块一致）：
  PYTHONPATH=local-agent python3 -m review_cycle demo
  PYTHONPATH=local-agent python3 -m review_cycle stats
  PYTHONPATH=local-agent python3 -m review_cycle overview
  PYTHONPATH=local-agent python3 -m review_cycle gate
  PYTHONPATH=local-agent python3 -m review_cycle run --task-key T \
      --stable '{"goal":"..."}' --volatile '{"diff_summary":"..."}'
"""
import argparse
import json
import sys

from . import Scheduler, spec


def _dump(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="review_cycle",
        description="评审段调度器（攒批 + 复用 + 减 CPU 损耗 · Issue #150）")
    sub = ap.add_subparsers(dest="cmd")

    d = sub.add_parser("demo", help="演示：两轮评审段的增量复用 + 攒批")
    d.add_argument("--real", action="store_true", help="真实执行测试（默认演练）")
    sub.add_parser("stats", help="省下的成本报表")
    sub.add_parser("overview", help="全局俯瞰（每任务轮次表 + 报表）")
    sub.add_parser("gate", help="阶段链门控大盘（放行/三类驳回统计）")

    r = sub.add_parser("run", help="跑一轮/多轮评审段")
    r.add_argument("--task-key", required=True, help="任务标识（稳定不漂移）")
    r.add_argument("--stable", default=None, help="稳定骨架 JSON")
    r.add_argument("--volatile", default=None, help="本轮变化 JSON")
    r.add_argument("--rounds", type=int, default=1, help="连续跑几轮")
    r.add_argument("--real", action="store_true", help="真实执行测试（默认演练）")

    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 0

    sch = Scheduler(dry_run=not getattr(args, "real", False))
    if args.cmd == "stats":
        _dump(sch.stats())
        return 0
    if args.cmd == "overview":
        _dump(sch.overview())
        return 0
    if args.cmd == "gate":
        from review_cycle.gate import StageGate, gate_stats
        _dump({"chain": StageGate().overview(), "gates": gate_stats()})
        return 0
    if args.cmd == "demo":
        out = sch.run("demo", {"goal": "评审不再逐轮复述整个项目",
                               "boundary": "只优化上下文/构建复用，不改需求边界",
                               "acceptance": "同 diff 指纹不重复触发构建"},
                      {"diff_summary": "首轮变更 ..."},
                      round_volatiles=[{"diff_summary": "首轮变更 ..."},
                                       {"diff_summary": "首轮变更 ..."}],
                      max_rounds=2)
        _dump({"state": out["state"],
               "rounds": out["rounds"],
               "stats": out["stats"]})
        return 0
    # run
    stable = json.loads(args.stable) if args.stable else {}
    volatile = json.loads(args.volatile) if args.volatile else {}
    out = sch.run(args.task_key, stable, volatile, max_rounds=args.rounds)
    _dump({"task_key": out["task_key"], "state": out["state"],
           "rounds": out["rounds"], "stats": out["stats"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
