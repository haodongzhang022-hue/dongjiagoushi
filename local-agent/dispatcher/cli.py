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
  python -m local-agent.dispatcher.cli ext list            # 列出外部源（key/IP 白名单）
  python -m local-agent.dispatcher.cli ext add <name> --ip 127.0.0.1
                                                    # 登记外部源（生成独立 key）
  python -m local-agent.dispatcher.cli ext rotate <name>  # 轮换秘钥
  python -m local-agent.dispatcher.cli ext audit          # 外部源认证审计（安全拦截）
  python -m local-agent.dispatcher.cli webhook --port 8081
                                                    # 起多源 Webhook 接收端
  python -m local-agent.dispatcher.cli host overview     # 本地上位机辅助俯瞰
  python -m local-agent.dispatcher.cli host report --type requirement --entity "本地需求"
                                                    # 本地电脑向云端上报事件
  python -m local-agent.dispatcher.cli host ack --event-id <ev>  # 上位机确认派发
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


def cmd_ext(args):
    """外部源管理：list / add / rotate / audit。

    多终端（本地电脑/手机/虚拟机/沙盒/上位机）各自独立 key + IP 白名单。
    安全：秘钥 key + IP 白名单；audit 展示认证审计（拦截情况）。
    """
    _ensure_db()
    from dispatcher import security as sec
    if args.ext_cmd == "list":
        out = []
        for s in sec.list_sources():
            out.append({"name": s["name"], "kind": s["kind"],
                        "enabled": bool(s["enabled"]),
                        "ip_whitelist": s["ip_whitelist"],
                        "api_key": s["api_key"]})
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.ext_cmd == "add":
        src = sec.register_source(args.name, ip_whitelist=args.ip or [],
                                  kind=args.kind)
        print(json.dumps(src, ensure_ascii=False, indent=2))
        print("⚠️ 请保存 key：它只会显示这一次（安全）")
    elif args.ext_cmd == "rotate":
        new_key = sec.gen_key()
        sec.update_source(args.name, key=new_key)
        print(json.dumps({"name": args.name, "api_key": new_key},
                         ensure_ascii=False, indent=2))
        print("⚠️ 请保存新 key（旧 key 已失效）")
    elif args.ext_cmd == "audit":
        print(json.dumps({"overview": sec.overview(),
                           "audit": sec.audit(limit=args.limit)},
                          ensure_ascii=False, indent=2))


def cmd_webhook(args):
    """起多源 Webhook 接收端（本地电脑/手机/虚拟机/沙盒/上位机统一入口）。"""
    from dispatcher.webhook import serve
    _ensure_db()
    serve(args.port, register_defaults=not args.no_preset)


def cmd_probe(args):
    """脉冲式信号探测器：fire / reg / overview。"""
    _ensure_db()
    from dispatcher import probe as probe_mod
    probe_cmd = getattr(args, "probe_cmd", "overview")
    if probe_cmd == "fire":
        ev = {
            "event_type": args.type,
            "source": args.source,
            "entity": args.entity,
            "gid": args.gid,
            "detail": _parse_detail(args.detail),
        }
        report = probe_mod.fire_signal(ev, register_miss=True)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    elif probe_cmd == "reg":
        if args.action_type == "script":
            action = {"type": "script", "script": args.action_key}
        elif args.action_type == "dispatch":
            action = {"type": "dispatch", "target_role": args.action_key or "架构·开发"}
        else:
            action = {"type": args.action_type}
        pid = probe_mod.register_probe(
            args.name, event_type=args.type or "", source=args.source or "",
            action=action, enabled=not args.disabled,
        )
        print(json.dumps({"probe_id": pid, "name": args.name}, ensure_ascii=False))
    else:
        print(json.dumps({
            "probes": probe_mod.list_probes(),
            "overview": probe_mod.firing_overview(limit=args.limit),
        }, ensure_ascii=False, indent=2, default=str))


def cmd_host(args):
    """本地上位机辅助角色。"""
    _ensure_db()
    from dispatcher import host_helper as hh
    if args.host_cmd == "start":
        hh.host_start(args.port, presets=True)
    elif args.host_cmd == "overview":
        print(json.dumps(hh.host_overview(), ensure_ascii=False, indent=2))
    elif args.host_cmd == "report":
        detail = _parse_detail(args.detail)
        print(json.dumps(hh.host_report(args.type, args.entity, detail),
                         ensure_ascii=False, indent=2))
    elif args.host_cmd == "pull":
        print(json.dumps(hh.host_pull_actions(args.source), ensure_ascii=False,
                         indent=2))
    elif args.host_cmd == "ack":
        print(json.dumps(hh.host_ack(args.event_id, approve=not args.reject),
                         ensure_ascii=False, indent=2))


def _parse_detail(detail):
    """把 detail 参数解析为 dict（支持 JSON 串 / 逗号分隔 k=v / 空）。"""
    if isinstance(detail, dict):
        return detail
    detail = (detail or "").strip()
    if not detail or detail == "{}":
        return {}
    try:
        return json.loads(detail)
    except Exception:
        out = {}
        for kv in detail.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                out[k.strip()] = v.strip()
        return out


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

    # 外部源管理（多终端：本地电脑/手机/虚拟机/沙盒/上位机）
    p_ext = sub.add_parser("ext", help="外部源管理（key/IP 白名单）")
    ext_sub = p_ext.add_subparsers(dest="ext_cmd")
    e_list = ext_sub.add_parser("list", help="列出外部源")
    e_list.set_defaults(fn=cmd_ext)
    e_add = ext_sub.add_parser("add", help="登记外部源（生成独立 key）")
    e_add.add_argument("name", help="外部源名（local_pc/phone/vm/sandbox/host_upper）")
    e_add.add_argument("--ip", action="append", default=[], help="允许来源 IP/CIDR")
    e_add.add_argument("--kind", default="webhook")
    e_add.set_defaults(fn=cmd_ext)
    e_rot = ext_sub.add_parser("rotate", help="轮换秘钥")
    e_rot.add_argument("name")
    e_rot.set_defaults(fn=cmd_ext)
    e_audit = ext_sub.add_parser("audit", help="外部源认证审计（安全拦截）")
    e_audit.add_argument("--limit", type=int, default=50)
    e_audit.set_defaults(fn=cmd_ext)

    # 多源 Webhook 接收端
    p_wh = sub.add_parser("webhook", help="起多源 Webhook 接收端")
    p_wh.add_argument("--port", type=int, default=8081)
    p_wh.add_argument("--no-preset", action="store_true", help="不预设默认源")
    p_wh.set_defaults(fn=cmd_webhook)

    # 本地上位机辅助角色
    p_host = sub.add_parser("host", help="本地上位机辅助")
    host_sub = p_host.add_subparsers(dest="host_cmd")
    h_start = host_sub.add_parser("start", help="启动上位机辅助（webhook+多源）")
    h_start.add_argument("--port", type=int, default=8081)
    h_start.set_defaults(fn=cmd_host)
    h_ov = host_sub.add_parser("overview", help="上位机俯瞰")
    h_ov.set_defaults(fn=cmd_host)
    h_report = host_sub.add_parser("report", help="本地电脑向云端上报事件")
    h_report.add_argument("--type", default="requirement")
    h_report.add_argument("--entity", default="host_event")
    h_report.add_argument("--detail", default="{}")
    h_report.set_defaults(fn=cmd_host)
    h_pull = host_sub.add_parser("pull", help="上位机拉取派发给本地的动作")
    h_pull.add_argument("--source", default="local_pc")
    h_pull.set_defaults(fn=cmd_host)
    h_ack = host_sub.add_parser("ack", help="上位机确认/驳回派发")
    h_ack.add_argument("--event-id", required=True)
    h_ack.add_argument("--reject", action="store_true")
    h_ack.set_defaults(fn=cmd_host)

    # 脉冲式信号探测器：signal fire / reg / overview
    p_probe = sub.add_parser("signal", help="脉冲式信号探测器（有条件就触发，路由到脚本，不轮询）")
    probe_sub = p_probe.add_subparsers(dest="probe_cmd")
    p_fire = probe_sub.add_parser("fire", help="投递一个信号，命中探测器即触发一次")
    p_fire.add_argument("--type", default="requirement")
    p_fire.add_argument("--source", default="repo")
    p_fire.add_argument("--entity", default="")
    p_fire.add_argument("--gid", default="")
    p_fire.add_argument("--detail", default="{}")
    p_fire.set_defaults(fn=cmd_probe)
    p_reg = probe_sub.add_parser("reg", help="注册一个探测器（触发条件+路由动作）")
    p_reg.add_argument("name", help="探测器名")
    p_reg.add_argument("--type", default="", help="命中的事件类型（空=任意）")
    p_reg.add_argument("--source", default="", help="命中的事件源（空=任意）")
    p_reg.add_argument("--action-type", default="dispatch", choices=["dispatch", "script", "emit", "handler"])
    p_reg.add_argument("--action-key", default="", help="路由动作的键（script 路径 / target_role）")
    p_reg.add_argument("--disabled", action="store_true")
    p_reg.set_defaults(fn=cmd_probe)
    p_ov2 = probe_sub.add_parser("overview", help="探测器 + 触发留痕俯视图")
    p_ov2.add_argument("--limit", type=int, default=50)
    p_ov2.set_defaults(fn=cmd_probe)
    p_ov2.set_defaults(probe_cmd="overview")

    args = parser.parse_args()
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 1
    args.fn(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
