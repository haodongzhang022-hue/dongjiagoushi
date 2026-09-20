# -*- coding: utf-8 -*-
"""评审上下文增量复用 · CLI（MCP 管线：脚本/CI 可直接程序化调用）。"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from review_context import engine, spec


def cmd_build(args):
    stable = json.loads(args.stable) if args.stable else {}
    volatile = json.loads(args.volatile) if args.volatile else {}
    prev = None
    if args.prev and os.path.exists(args.prev):
        with open(args.prev, "r", encoding="utf-8") as f:
            prev = json.load(f)
    pack = engine.build(stable, volatile, prev=prev, task_key=args.task_key or "")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(pack, f, ensure_ascii=False, indent=2)
    print(json.dumps(pack, ensure_ascii=False, indent=2))


def cmd_demo(args):
    stable = {
        "goal": "把评审从每次复述整个大项目，改为只吃增量上下文",
        "boundary": "只优化评审/测试循环的上下文与构建复用，不改需求边界",
        "acceptance": "第二轮起评审不再复述全项目；同 diff 不重复触发构建",
        "contract": "build(stable_parts, volatile_parts, prev) -> pack",
        "decisions": "ADR-0011：评审增量上下文 + 评审段调度",
    }
    p1 = engine.build(stable, {"diff_summary": "首轮全量 diff ...",
                               "test_signals": "🟢"}, task_key="demo")
    p2 = engine.build(stable, {"diff_summary": "第二轮只是加了一行日志",
                               "test_signals": "🟢"}, prev=p1, task_key="demo")
    print("首轮 rebuilt=%s saved_ratio=%s" % (p1["rebuilt"], p1["saved_ratio"]))
    print("次轮 reused=%s saved_ratio=%s context_chars=%s(full=%s)" % (
        p2["reuse"]["reusable"], p2["saved_ratio"],
        p2["context_chars"], p2["full_chars"]))
    print("省下 token 估算 ~%d" % engine.estimate_saved_tokens(p2))


def main(argv=None):
    ap = argparse.ArgumentParser(description="评审上下文增量复用（review-context）")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="构建评审上下文包（增量复用）")
    b.add_argument("--stable", default=None, help="稳定骨架 JSON")
    b.add_argument("--volatile", default=None, help="变化片段 JSON")
    b.add_argument("--prev", default=None, help="上一轮 pack JSON 文件")
    b.add_argument("--out", default=None, help="输出 pack JSON 文件")
    b.add_argument("--task-key", default=None)
    b.set_defaults(fn=cmd_build)
    sub.add_parser("demo", help="演示：两轮评审的增量复用").set_defaults(fn=cmd_demo)
    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 0
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
