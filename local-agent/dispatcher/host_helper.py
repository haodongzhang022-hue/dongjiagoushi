# -*- coding: utf-8 -*-
"""
调度中枢 · 本地上位机辅助角色（host_helper）
============================================
用户拍板：**上位机那部分还没解决好，先预设功能，之后接入；或者当本地的上位机，
给他开发个功能去辅助完成这个角色**。

本模块把「本地电脑」视为本体系的上位机（host / 上位机主控），为其**预设一组辅助
功能**，辅助它完成「上位机角色」：本地终端作为云端团队的协作枢纽，把本地事件推入
dispatcher（经 webhook 或多源适配器），并接收/汇报云端派发的动作。

预设功能（都可独立演进、独立接入，先预设骨架后接真实上位机逻辑）：

  | 功能               | 说明                                                  |
  |--------------------|-------------------------------------------------------|
  | host_start()       | 启动上位机辅助：起多源 webhook 接收端 + 本地适配器     |
  | host_report()      | 本地上位机向云端上报事件（经 webhook 或本地 emit）      |
  | host_pull_actions()| 上位机拉取云端派发给本地 agent 的动作/任务              |
  | host_ack()         | 上位机确认/驳回一条派发（配合人工闸门 release）         |
  | host_overview()    | 上位机俯瞰本地队列/外部源认证/安全拦截                  |

接入方（真实上位机）只需在本地跑一个守护脚本，注入 `local_provider` 或调用
`emit`，即可把本地事件接入云端 dispatcher 同一链路。真实上位机接口未定时，
这里提供**可运行的预设实现 + 契约**，后续按真实上位机仓库/接口填实即可。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import db, schema
from . import security
from . import webhook
from . import sources as sources_mod


def host_start(webhook_port=8081, presets=True):
    """启动上位机辅助：预设多终端源 + 起多源 webhook 接收端。

    本地电脑作为上位机主控，接收各终端推送 + 主动扫描本地事件。
    """
    schema.init_schema()
    if presets:
        sources_mod.preset_host_sources()
    webhook.serve(webhook_port)


def host_report(event_type, entity, detail=None, source_name="local_pc", via="local"):
    """本地上位机向云端上报一条事件。

    via="local"  → 本地 emit（经本地适配器 poll 进 dispatcher）；
    via="webhook"→ 直接调用 webhook 处理逻辑（需带 key + IP）。
    返回处理结果 dict。
    """
    if isinstance(detail, str):
        try:
            detail = json.loads(detail) if detail else {}
        except Exception:
            detail = {}
    detail = detail or {}
    ev = {
        "event_type": event_type,
        "source": source_name,
        "entity": entity,
        "gid": detail.get("gid", "") if isinstance(detail, dict) else "",
        "detail": dict(detail) if isinstance(detail, dict) else {},
    }
    if via == "webhook":
        # 走 webhook 安全链路（模拟带 key 的请求；真实场景由 HTTP 调用）
        src = security.get_source(source_name)
        if not src:
            return {"ok": False, "error": "source not registered", "event": ev}
        from . import engine
        dispatcher = engine.Dispatcher()
        try:
            return {"ok": True, "result": dispatcher.process_event(ev)}
        except Exception as e:  # noqa
            return {"ok": False, "error": str(e)}
    # via="local"：经本地适配器 emit → 事件到达即触发脉冲式信号探测器（不轮询）
    adapter = sources_mod.get_adapter(source_name)
    if adapter is None:
        adapter = sources_mod.build_local_host(source_name)
    from . import probe as probe_mod
    report = adapter.emit(ev) or probe_mod.fire_signal(ev)
    return {"ok": True, "emit": True, "report": report}


def host_pull_actions(source_name="local_pc", limit=100):
    """上位机拉取云端派发给本地 agent 的动作/任务。

    读取 dispatch 表里目标 agent 归本上位机管的派发记录（演示用：按 source
    或 target_agent 前缀过滤；真实上位机按自己的 agent gid 过滤）。
    """
    rows = db.query(
        "SELECT * FROM dispatch WHERE status IN ('dispatched','released','queued') "
        "ORDER BY id DESC LIMIT ?", (limit,),
    )
    return [dict(r) for r in rows]


def host_ack(event_id, approve=True, note=""):
    """上位机确认/驳回一条派发。

    approve=True → 释放（走 dispatcher 派发）；approve=False → 标记 rejected。
    """
    from . import queue as queue_mod
    if approve:
        queue_mod.human_release(event_id)
        return {"event_id": event_id, "status": "released", "note": note or "上位机确认放行"}
    queue_mod.mark_rejected(event_id, note or "上位机驳回")
    return {"event_id": event_id, "status": "rejected", "note": note or "上位机驳回"}


def host_overview():
    """上位机俯瞰：外部源认证 / 安全拦截 / 队列 / 驳回 / 本地适配器。"""
    schema.init_schema()
    from . import queue as queue_mod
    from . import reject as reject_mod
    return {
        "external_sources": [
            {k: s[k] for k in ("src_id", "name", "kind", "enabled", "ip_whitelist")
             if k in s} for s in security.list_sources()
        ],
        "auth_overview": security.overview(),
        "auth_audit": security.audit(limit=50),
        "queue_overview": queue_mod.overview(),
        "rejection_overview": reject_mod.overview(),
        "adapters": list(sources_mod.list_adapters().keys()),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="本地上位机辅助角色")
    parser.add_argument("cmd", choices=["start", "report", "pull", "ack", "overview"],
                        nargs="?", default="overview")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--source", default="local_pc")
    parser.add_argument("--type", default="requirement")
    parser.add_argument("--entity", default="")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--reject", action="store_true", help="ack 时驳回")
    args = parser.parse_args()

    if args.cmd == "start":
        host_start(args.port)
    elif args.cmd == "report":
        detail = {"gid": ""} if not args.entity else {}
        print(json.dumps(host_report(args.type, args.entity or "host_event",
                                     detail), ensure_ascii=False, indent=2))
    elif args.cmd == "pull":
        print(json.dumps(host_pull_actions(args.source), ensure_ascii=False, indent=2))
    elif args.cmd == "ack":
        print(json.dumps(host_ack(args.event_id, approve=not args.reject),
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(host_overview(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
