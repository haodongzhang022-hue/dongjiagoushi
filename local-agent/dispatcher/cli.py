# -*- coding: utf-8 -*-
"""
调度中枢 · 命令行入口（cli）
==============================
用法：
  python -m local-agent.dispatcher.cli scan          # 单次扫描（事件源→规则→入队→派发）
  python -m local-agent.dispatcher.cli watch --interval 5 [--rounds N]
                                                    # 持续守护循环
  python -m local-agent.dispatcher.cli web --port 8080
                                                    # 起 Web 可视化面板
  python -m local-agent.dispatcher.cli overview      # 打印队列/驳回/统计摘要
  python -m local-agent.dispatcher.cli reject --task <gid> --agent <gid> --reason "🔴必修"
                                                    # 手工登记一条驳回，触发迭代回派
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import schema
from dispatcher.engine import Dispatcher


def _ensure_db():
    schema.init_schema()


def cmd_scan(args):
    _ensure_db()
    d = Dispatcher()
    report = d.scan_once()
    drained = d.drain()
    rejects = d.scan_rejections()
    print(json.dumps({
        "scanned": report["scanned"],
        "results": report["results"],
        "drained": drained,
        "rejection_reroutes": rejects,
        "stats": report["stats"],
    }, ensure_ascii=False, indent=2))


def cmd_watch(args):
    _ensure_db()
    d = Dispatcher()
    d.watch(interval=args.interval, iterations=args.rounds,
            on_scan=lambda r: print(json.dumps(r, ensure_ascii=False)))


def cmd_web(args):
    from dispatcher.webui import serve
    _ensure_db()
    serve(args.port)


def cmd_overview(args):
    _ensure_db()
    from dispatcher import queue as queue_mod
    from dispatcher import reject as reject_mod
    print(json.dumps({
        "queue_overview": queue_mod.overview(),
        "rejection_overview": reject_mod.overview(),
        "pending_rejections": [{
            "rejection_id": r["rejection_id"], "task_id": r["task_id"],
            "agent_id": r["agent_id"], "iteration": r["iteration"],
            "status": r["status"], "reason": r["reason"],
        } for r in reject_mod.pending()],
    }, ensure_ascii=False, indent=2))


def cmd_reject(args):
    _ensure_db()
    from dispatcher import reject as reject_mod
    rej = reject_mod.register(task_id=args.task, gid=args.gid or args.task,
                              agent_id=args.agent, reason=args.reason, level=args.level)
    # 触发迭代回派：按 gid 精准路由到负责 agent 改进重提
    d = Dispatcher()
    d.guard = d._guard
    result = d.scan_rejections()
    print(json.dumps({"registered": rej, "reroute_results": result},
                     ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="调度中枢（事件驱动自动化调度）")
    sub = parser.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="单次扫描事件源并派发")
    p_scan.set_defaults(fn=cmd_scan)

    p_watch = sub.add_parser("watch", help="持续守护循环")
    p_watch.add_argument("--interval", type=float, default=5.0)
    p_watch.add_argument("--rounds", type=int, default=None)
    p_watch.set_defaults(fn=cmd_watch)

    p_web = sub.add_parser("web", help="起 Web 可视化面板")
    p_web.add_argument("--port", type=int, default=8080)
    p_web.set_defaults(fn=cmd_web)

    p_ov = sub.add_parser("overview", help="打印队列/驳回/统计摘要")
    p_ov.set_defaults(fn=cmd_overview)

    p_rej = sub.add_parser("reject", help="登记一条驳回并触发迭代回派")
    p_rej.add_argument("--task", required=True, help="被驳回的任务 gid")
    p_rej.add_argument("--agent", required=True, help="负责 agent 的 gid")
    p_rej.add_argument("--reason", default="评审 🔴必修")
    p_rej.add_argument("--level", default="must")
    p_rej.add_argument("--gid", default=None, help="实体 gid（默认=task）")
    p_rej.set_defaults(fn=cmd_reject)

    args = parser.parse_args()
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
