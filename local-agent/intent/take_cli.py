# -*- coding: utf-8 -*-
"""承接侧 CLI（intent.take 的命令行入口）。

用法：
    python -m intent new --title "活" --kind code --runtime local --accept "信号灯全绿" --md
    python -m intent judge --kind code --runtime cloud
    python -m intent handoff --card ib-xxx --entry "bash local-agent/tests/test_x.sh"
    python -m intent collect --card ib-xxx --test-output "14 通过 / 0 失败" \
        --changed-file a.py --evidence '{"分支":"auto/x"}'
    python -m intent show --card ib-xxx
    python -m intent tally
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from intent import take  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="intent", description="云端承接侧：承接卡 / 交接单 / 回传核对")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="建承接卡")
    n.add_argument("--title", required=True)
    n.add_argument("--origin", default="issue")
    n.add_argument("--kind", default="unknown")
    n.add_argument("--runtime", default="local")
    n.add_argument("--accept", action="append", default=[], help="验收标准，可多次")
    n.add_argument("--done", action="append", default=[], help="做（边界内），可多次")
    n.add_argument("--not", dest="nots", action="append", default=[], help="不做（边界外），可多次")
    n.add_argument("--deliverable", default=None)
    n.add_argument("--md", action="store_true", help="输出 Markdown 承接卡")

    j = sub.add_parser("judge", help="只看承接判定")
    j.add_argument("--kind", default="unknown")
    j.add_argument("--runtime", default="local")

    h = sub.add_parser("handoff", help="出交接单（交本地 runtime）")
    h.add_argument("--card", required=True)
    h.add_argument("--entry", default=None)

    c = sub.add_parser("collect", help="收本地回传并按验收核对")
    c.add_argument("--card", required=True)
    c.add_argument("--test-output", default="")
    c.add_argument("--changed-file", action="append", default=[])
    c.add_argument("--evidence", default="{}")
    c.add_argument("--reopen", action="store_true",
                   help="已交付的卡确需重跑重判时显式放行（原回执进 receipt_history）")

    s = sub.add_parser("show", help="看承接卡")
    s.add_argument("--card", required=True)

    sub.add_parser("tally", help="三态批扫")

    a = p.parse_args(argv)
    if a.cmd == "new":
        card = take.make_card(title=a.title, origin=a.origin, kind=a.kind,
                              runtime=a.runtime, acceptance=a.accept,
                              scope_done=a.done, scope_not=a.nots,
                              deliverable=a.deliverable)
        print(take.render_md(card) if a.md
              else json.dumps(card, ensure_ascii=False, indent=2))
        return 0 if card["decision"]["accept"] else 3
    if a.cmd == "judge":
        print(json.dumps(take.judge(kind=a.kind, runtime=a.runtime),
                         ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "handoff":
        card = take.load_card(a.card)
        if not card:
            print("承接卡不存在: " + a.card)
            return 2
        r = take.handoff(card, entry_cmd=a.entry)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1
    if a.cmd == "collect":
        card = take.load_card(a.card)
        if not card:
            print("承接卡不存在: " + a.card)
            return 2
        try:
            ev = json.loads(a.evidence or "{}")
        except Exception:  # noqa: BLE001
            ev = {"note": a.evidence}
        r = take.collect(card, {"test_output": a.test_output,
                                "changed_files": a.changed_file,
                                "evidence": ev}, reopen=a.reopen)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("passed") else 4
    if a.cmd == "show":
        card = take.load_card(a.card)
        if not card:
            print("承接卡不存在: " + a.card)
            return 2
        print(take.render_md(card))
        return 0
    if a.cmd == "tally":
        print(json.dumps(take.tally(), ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
