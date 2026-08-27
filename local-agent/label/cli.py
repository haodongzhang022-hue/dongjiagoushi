# -*- coding: utf-8 -*-
"""
标签管理 · CLI（MCP 管线 · 程序化操作入口 · Issue #51）
=========================================================
让任何 agent/脚本/CI 通过命令行程序化打标、查进度、查状态、提议、审批，
形成"MCP 管线效果"——不靠 AI 对话告知，走程序化接口。

用法：
  # 查询（全员）
  python -m label.cli progress --task tk-xxx
  python -m label.cli status --entity issue-12
  python -m label.cli labels --entity issue-12
  # 打标（一线白名单角色）
  python -m label.cli apply --entity issue-12 --label in_progress --operator 架构·开发
  python -m label.cli remove --entity issue-12 --label need_fix --operator 架构·评审
  # 提议（全员）
  python -m label.cli propose --entity issue-12 --label p0_critical --operator 市场·销售 --reason 阻塞上线
  # 审批（标签管理员）
  python -m label.cli review --request lq-xxx --operator 架构·数据管理员 --decision approved
  # 事件驱动自动打标
  python -m label.cli auto --event progress.advance --entity issue-12 --goal-total 10 --current 4
  python -m label.cli refresh --entity issue-12 --goal-total 5 --current 5
"""
import argparse
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


def _ability(operator):
    from label import LabelAbility
    return LabelAbility(owner=operator or "系统")


def main(argv=None):
    p = argparse.ArgumentParser(prog="label.cli", description="标签管理 MCP 管线")
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp, with_operator=True):
        if with_operator:
            sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("progress", help="程序化查进度")
    sp.add_argument("--task", required=True)
    add_common(sp)

    sp = sub.add_parser("status", help="程序化查状态标签")
    sp.add_argument("--entity", required=True)
    add_common(sp)

    sp = sub.add_parser("labels", help="查实体全部标签")
    sp.add_argument("--entity", required=True)
    add_common(sp)

    sp = sub.add_parser("apply", help="一线直接打标")
    sp.add_argument("--entity", required=True)
    sp.add_argument("--label", required=True)
    sp.add_argument("--value", default="")
    sp.add_argument("--note", default="")
    add_common(sp)

    sp = sub.add_parser("remove", help="一线去标")
    sp.add_argument("--entity", required=True)
    sp.add_argument("--label", required=True)
    add_common(sp)

    sp = sub.add_parser("propose", help="全员提议加/改标签")
    sp.add_argument("--entity", required=True)
    sp.add_argument("--label", required=True)
    sp.add_argument("--reason", default="")
    add_common(sp)

    sp = sub.add_parser("review", help="标签管理员审批提议")
    sp.add_argument("--request", required=True)
    sp.add_argument("--decision", default="approved", choices=["approved", "rejected"])
    sp.add_argument("--note", default="")
    add_common(sp)

    sp = sub.add_parser("pending", help="查看待审批提议")
    add_common(sp)

    sp = sub.add_parser("auto", help="事件驱动自动打标")
    sp.add_argument("--event", required=True)
    sp.add_argument("--entity", required=True)
    sp.add_argument("--goal-total", type=float, default=None)
    sp.add_argument("--current", type=float, default=None)
    sp.add_argument("--note", default="")
    add_common(sp)

    sp = sub.add_parser("refresh", help="刷进度百分比标签")
    sp.add_argument("--entity", required=True)
    sp.add_argument("--goal-total", type=float, required=True)
    sp.add_argument("--current", type=float, required=True)
    add_common(sp)

    args = p.parse_args(argv)
    if not args.cmd:
        p.print_help()
        return

    ab = _ability(args.operator)

    if args.cmd == "progress":
        print(ab.query_progress(args.task))
    elif args.cmd == "status":
        st = ab.query_status(args.entity)
        print(f"entity={st['entity']} status={st['status']}")
        for l in st["labels"]:
            print(f"  - {l['label_key']} = {l['value']!r} [{l['source']}] by {l['operator']}")
    elif args.cmd == "labels":
        for l in ab.query_labels(args.entity):
            print(f"  - {l['label_key']} = {l['value']!r} [{l['source']}] by {l['operator']}")
    elif args.cmd == "apply":
        print(ab.apply_label(args.entity, args.label, value=args.value, note=args.note))
    elif args.cmd == "remove":
        print(ab.remove_label(args.entity, args.label))
    elif args.cmd == "propose":
        print(ab.propose_label(args.entity, args.label, reason=args.reason))
    elif args.cmd == "review":
        print(ab.review_request(args.request, decision=args.decision, note=args.note))
    elif args.cmd == "pending":
        for r in ab.pending_requests():
            print(f"  {r['request_id']} {r['entity']} {r['label_key']} by {r['proposer']}: {r['reason']} [{r['status']}]")
    elif args.cmd == "auto":
        print(ab.auto_trigger(args.event, args.entity, goal_total=args.goal_total,
                              current=args.current, note=args.note))
    elif args.cmd == "refresh":
        from label.auto import AutoLabelEngine
        print(AutoLabelEngine(owner=args.operator).trigger(
            "issue.update", args.entity, goal_total=args.goal_total,
            current=args.current, note="CLI refresh"))


if __name__ == "__main__":
    main()
