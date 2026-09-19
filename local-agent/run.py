#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 Agent · 入口（替代云端 @ 触发）
====================================
用法：
  # 一键编排完整团队流水线（产品→架构→分工→协同→测试→交付）
  python local-agent/run.py --pipeline full --req "我要做一个XX系统"

  # 触发单个角色（对应云端 @角色）
  python local-agent/run.py --role 架构·总师 --req "对XX做架构设计"

  # 列出团队角色
  python local-agent/run.py --list-roles

  # 从接力卡续跑（对应云端 [打断] 续跑）
  python local-agent/run.py --resume

  # 指定模型后端（默认自动：OPENAI_API_KEY → cli_fallback 占位）
  python local-agent/run.py --pipeline full --req "XX" --backend cli_fallback

  # 清空接力卡
  python local-agent/run.py --clear
"""
import argparse
import json
import os
import sys

# 允许直接以脚本运行（python run.py）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orchestrator
import relay
from roles import list_roles

# 规模伸缩层（架构升级核心）
from scale import engine, spec, profile, prescale, plugin


def _serve_http(dash_mod, port=8080):
    """把跨端聚合控制页挂到常驻 HTTP 服务（FastAPI /docs 式，零重依赖 http.server）。

    GET  /           全端大盘人可读 HTML 聚合页
    GET  /entry/{e}  某端面板 HTML
    GET  /api        全端快照 JSON（FastAPI 风格聚合）
    GET  /api/entry/{e}  某端面板 JSON
    POST /api/control   一键控制（body: JSON action/handle_id/...）
    这即上轮（PR #113）点名的候选：把 html_page 挂可常驻服务供浏览器直接开。
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import json as _json
    import urllib.parse

    class _H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # 静默访问日志
            pass

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _api(self, obj):
            data = _json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, "application/json", data)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            # /api 前缀 → JSON
            if path == "/api" or path == "/api/":
                return self._api(dash_mod.snapshot())
            if path.startswith("/api/entry/"):
                e = path.split("/")[-1]
                return self._api(dash_mod.panel(e))
            if path.startswith("/api/handles"):
                return self._api(dash_mod._handles_view())
            if path == "/api/health":
                return self._api(dash_mod.snapshot().get("health"))
            # 其余 → HTML 聚合页
            if path.startswith("/entry/"):
                e = path.split("/")[-1]
                body = dash_mod.html_page(e).encode("utf-8")
            else:
                body = dash_mod.html_page().encode("utf-8")
            return self._send(200, "text/html", body)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path != "/api/control" and not path.endswith("/control"):
                return self._send(404, "text/plain", b"not found")
            try:
                ln = int(self.headers.get("Content-Length") or 0)
                payload = _json.loads(self.rfile.read(ln) or b"{}")
            except Exception as e:  # noqa: BLE001
                return self._api({"ok": False, "error": f"body 解析失败: {e}"})
            action = payload.get("action") or "overview"
            out = dash_mod.control(
                action,
                handle_id=payload.get("handle_id"),
                collect_state=payload.get("collect_state"),
                pr_ids=payload.get("pr_ids"),
                req=payload.get("req"),
                entry=payload.get("entry") or "local",
            )
            return self._api(out)

    srv = HTTPServer(("127.0.0.1", int(port)), _H)
    print("   控制台: GET  http://127.0.0.1:%s   (HTML 聚合页)" % port)
    print("   API:    GET  http://127.0.0.1:%s/api   (JSON 快照)" % port)
    print("   API:    POST http://127.0.0.1:%s/api/control  (一键控制)" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[serve] 已停止")
        srv.server_close()


def main():
    parser = argparse.ArgumentParser(
        description="本地 Agent 团队入口（替代云端 @ 触发）"
    )
    parser.add_argument("--pipeline", help="运行团队流水线，如 full")
    parser.add_argument("--role", help="触发单个角色，如 架构·总师")
    parser.add_argument("--req", help="用户需求/请求")
    parser.add_argument("--backend", default=None, help="模型后端：openai_compat / cli_fallback")
    parser.add_argument("--list-roles", action="store_true", help="列出团队角色（含插件）")
    parser.add_argument("--resume", action="store_true", help="从接力卡续跑")
    parser.add_argument("--clear", action="store_true", help="清空接力卡")
    # ---- 架构升级新增入口 ----
    parser.add_argument("--scale", action="store_true", help="运行规模化流水线（scale 引擎）")
    parser.add_argument("--spec", default=None,
                        help='团队规模声明 JSON，如 \'{"team_size": 2500, "levels": 3, "mode": "harness"}\'')
    parser.add_argument("--profile", default=None, help="前置流程模板：default/company/harness/acquisition/support")
    parser.add_argument("--list-profiles", action="store_true", help="列出前置流程模板")
    parser.add_argument("--concurrency", type=int, default=None, help="覆盖并发度（压测）")
    # ---- 规模预设 + 强制入口（测试关键发现修复）----
    parser.add_argument("--prescale", action="store_true", help="对需求做规模预设（澄清阶段基准锚点）")
    parser.add_argument("--complexity", default=None, help="显式指定复杂度带：simple/medium/complex")
    # ---- 融合路由接线（打通"规模→拓扑→执行"断点）----
    parser.add_argument("--no-fusion", action="store_true", help="回退老行为：不走融合路由，硬编码 team.yaml dag")
    parser.add_argument("--topo", default=None, help="显式指定拓扑：linear/dag/event/hybrid/scatter/agile/prefix（绕过规模评估）")
    parser.add_argument("--subtasks", type=int, default=None, help="显式子任务数（融合路由规模信号）")

    parser.add_argument("--guard-entry", action="store_true", help="校验强制入口（是否必须经架构·秘书）")
    parser.add_argument("--direct-role", default=None, help="显式 @ 的角色（用于校验是否跳过秘书）")
    parser.add_argument("--prescale-records", action="store_true", help="列出规模预设留痕记录")
    parser.add_argument("--platform-overview", action="store_true", help="三入口归一化俯瞰 (Issue #105)")
    parser.add_argument("--entry", default=None, help="入口归一化: web/cnb/local (收敛到秘书主入口并落位适配器)")
    # ---- 本地⇄云端桥接闭环（Issue #105 最常用链路 · entries.bridge）----
    parser.add_argument("--bridge", default=None,
                        help="本地⇄云端桥接闭环 action: request/collect/align/localtest/overview")
    parser.add_argument("--handle", default=None, help="--bridge 操作对应的桥接句柄 handle_id")
    parser.add_argument("--collect-state", default=None, help="--bridge collect 云端完成信号 merged/done/need_fix")
    parser.add_argument("--bridge-pr-ids", default=None, help="--bridge collect 云端PR列表(逗号分隔)")
    parser.add_argument("--bridge-live", action="store_true",
                        help="--bridge request 走真实 cnb.cool 传输通道（默认真实，用户：模拟数据不可信）")
    parser.add_argument("--bridge-via", default=None,
                        help="--bridge request 指定真实宿主传输: cnb-live/local-harness/web-bridge(或别名)，v0.6.0 三宿主注册表；--bridge via-overview 看三宿主可达矩阵")
    # ---- 真实 cnb.cool 传输通道（Issue #105 · entries.cnb_live · v0.5.0）----
    parser.add_argument("--live", default=None,
                        help="真实 cnb.cool 通道 action: probe/transport (发送信号探测真实配合)")
    parser.add_argument("--serve", default=None,
                        help="把跨端聚合控制页挂到常驻 HTTP 服务 (FastAPI 风格)，--serve 8080")
    # ---- 跨端聚合控制页（Issue #105 · entries.dashboard · v0.5.0 真实本地实测）----
    parser.add_argument("--dashboard", default=None,
                        help="跨端聚合控制台 action: health/overview/panel/handles/relay/request/collect/align/localtest/html (FastAPI风格聚合页)")
    parser.add_argument("--dashboard-html", action="store_true",
                        help="输出人可读 HTML 聚合控制页（全端大盘）")
    parser.add_argument("--dashboard-pr-ids", default=None,
                        help="--dashboard collect 云端PR列表(逗号分隔)")
    # ---- 评审段调度（Issue #150：减 CPU 损耗 · 攒批/复用/增量上下文）----
    parser.add_argument("--review-cycle", default=None,
                        help="评审段调度 action: run/overview/stats/demo")
    parser.add_argument("--rc-task", default=None, help="评审段任务标识 task_key")
    parser.add_argument("--rc-stable", default=None, help="稳定骨架 JSON（构建一次→冻结）")
    parser.add_argument("--rc-volatile", default=None, help="本轮变化 JSON（只传增量）")
    parser.add_argument("--rc-rounds", type=int, default=1, help="连续跑几轮评审段")
    parser.add_argument("--rc-real", action="store_true", help="真实执行（默认演练 dry-run）")
    args = parser.parse_args()

    if args.prescale_records:
        recs = prescale.prescale_records()
        if not recs:
            print("（暂无规模预设记录）")
        else:
            print(f"规模预设留痕记录（共 {len(recs)} 条）：")
            for key, rec in recs.items():
                p = rec.get("preset", {})
                print(f"  - [{rec.get('kind')}] {rec.get('req_key')}")
                print(f"      → team_size={p.get('team_size')} collab={p.get('collab_plan')} "
                      f"risk={p.get('risk_level')} source={p.get('source')}")
        return 0

    # ---- 三入口归一化（Issue #105）：entries 适配层入口 ----
    if args.platform_overview:
        from entries import route as _er
        ov = _er.overview()
        print(json.dumps(ov, ensure_ascii=False, indent=2))
        return 0

    # ---- 真实 cnb.cool 传输通道（Issue #105 · entries.cnb_live · v0.5.0）----
    if args.live:
        from entries import cnb_live
        out = cnb_live.cli_live(action=args.live)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # ---- 常驻 HTTP 聚合控制服务（Issue #105 上轮候选：html_page --serve）----
    if args.serve:
        from entries import dashboard as _dash_serve
        port = int(args.serve)
        print("[serve] 跨端聚合控制页 HTTP 服务启动 @ http://127.0.0.1:%s  (Ctrl+C 停止)"
              % port)
        _serve_http(_dash_serve, port)
        return 0

    # ---- 本地⇄云端桥接闭环（Issue #105 最常用链路 · entries.bridge）----
    if args.bridge:
        from entries import bridge
        pr_ids = None
        if args.bridge_pr_ids:
            pr_ids = [x.strip() for x in args.bridge_pr_ids.split(",") if x.strip()]
        # 三宿主真实传输（v0.6.0）：--bridge via-overview 看矩阵；--bridge request --bridge-via <host>
        if args.bridge == "via-overview":
            from entries import host_transport as _ht
            print(json.dumps(_ht.overview(), ensure_ascii=False, indent=2))
            return 0
        via = args.bridge_via
        # 真实 CLI：--bridge request 默认走真实 cnb.cool 通道（用户：模拟数据不可信）
        out = bridge.cli_bridge(
            args.req or "", entry=args.entry or "local", action=args.bridge,
            handle_id=args.handle, collect_state=args.collect_state, pr_ids=pr_ids,
            live=args.bridge_live or args.bridge == "request", via=via)
        if args.bridge == "overview":
            print(json.dumps(out, ensure_ascii=False, indent=2))
        elif args.bridge == "request":
            # 三宿主真实传输（v0.6.0 via）返回值裹在 {via, transport, handle} 下
            h = out.get("handle", out) if "handle" in out else out
            via_txt = (" | via=%s/%s" % (out.get("via"), out.get("transport"))) if "via" in out else ""
            print("[bridge 发起云端开发] handle=%s | status=%s | entry=%s%s"
                  % (h.get("handle_id"), h.get("status"), h.get("entry"), via_txt))
            if h.get("status") in ("blocked", "pending") and h.get("send_error"):
                print("  ✗ 请求未成功投递：%s" % h.get("send_error"))
                return 1
            print("  云开发请求已投递，句柄可跨对话/跨 PR 定位收集结果（真实宿主传输）")
        elif args.bridge == "collect":
            print("[bridge 收集云端产出] ok=%s | state=%s | pr_ids=%s"
                  % (out.get("ok"), out.get("handle", {}).get("cloud_result", {}).get("state"),
                     out.get("handle", {}).get("cloud_result", {}).get("pr_ids")))
        elif args.bridge == "align":
            print("[bridge 本地对齐] ok=%s | relay=%s | data=%s"
                  % (out.get("ok"), out.get("relay_aligned"), out.get("data_archived")))
        elif args.bridge == "localtest":
            print("[bridge 本地测试先行] ok=%s | 下放本地=%s | skipped_cloud_build=%s"
                  % (out.get("ok"), len(out.get("routed_local", [])),
                     out.get("skipped_cloud_build")))
            print("  成本注记: %s" % out.get("cost_note"))
        return 0

    # ---- 跨端聚合控制页（Issue #105 最常用链路 · entries.dashboard · v0.5.0 真实本地实测）----
    if args.dashboard or args.dashboard_html:
        from entries import dashboard as _dash
        action = args.dashboard or ("html" if args.dashboard_html else "overview")
        out = _dash.cli_dashboard(
            entry=args.entry or "local", action=action, handle_id=args.handle,
            collect_state=args.collect_state,
            pr_ids=args.dashboard_pr_ids, req=args.req)
        if action == "html" or args.dashboard_html or "html" in out:
            print(out.get("html", out.get("data", out)))
            return 0
        print("[跨端聚合控制台] action=%s | ok=%s | main_entry=架构·秘书 (module v0.5.0 真实本地实测)"
              % (action, out.get("ok")))
        if action in ("health", "overview"):
            d = out.get("data", {})
            print("  健康度: %s %s" % (d.get("health", {}).get("light", ""),
                                       d.get("health", {}).get("status", "")))
            print("  三端适配器: %s" % ", ".join(
                [e["entry"] for e in d.get("entries", [])]))
            print("  桥接句柄总数: %s | 按状态: %s"
                  % (d.get("handles", {}).get("total", 0),
                     {k: len(v) for k, v in d.get("handles", {}).get("by_status", {}).items()}))
        elif action == "panel":
            d = out.get("data", {})
            pan = d.get("panel", {})
            print("  面板: %s | 本端状态 %s %s | 本端句柄 %s | 可用动作 %s"
                  % (pan.get("title"), pan.get("health_light"), pan.get("status"),
                     pan.get("my_handles_total"),
                     ", ".join(a["action"] for a in pan.get("actions", []))))
        elif action == "request":
            print("  [控制台发起云开发] handle=%s | entry=%s" %
                  (out.get("data", {}).get("handle_id"), out.get("data", {}).get("entry")))
        elif action in ("collect", "align", "localtest"):
            d = out.get("data", {})
            if action == "collect":
                h = d.get("handle", {})
                print("  [控制台 %s] ok=%s | state=%s | pr_ids=%s"
                      % (action, d.get("ok"), (h.get("cloud_result") or {}).get("state"),
                         (h.get("cloud_result") or {}).get("pr_ids")))
            else:
                print("  [控制台 %s] ok=%s" % (action, d.get("ok", out.get("ok"))))
        elif action == "handles":
            print("  句柄总数: %s" % out.get("data", {}).get("total", 0))
        return 0

    # ---- 评审段调度（Issue #150）----
    if args.review_cycle:
        from review_cycle import Scheduler
        import json as _json
        act = args.review_cycle
        sch = Scheduler(dry_run=not args.rc_real)
        if act == "overview":
            print(_json.dumps(sch.overview(), ensure_ascii=False, indent=2))
            return 0
        if act == "stats":
            print(_json.dumps(sch.stats(), ensure_ascii=False, indent=2))
            return 0
        if act == "demo":
            out = sch.run("demo", {"goal": "评审不再逐轮复述整个项目",
                                   "boundary": "只优化上下文/构建复用，不改需求边界",
                                   "acceptance": "同 diff 指纹不重复触发构建"},
                          {"diff_summary": "首轮变更 ..."},
                          round_volatiles=[{"diff_summary": "首轮变更 ..."},
                                           {"diff_summary": "首轮变更 ..."}],
                          max_rounds=2)
            print(_json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        # act == run
        if not args.rc_task:
            parser.error("--review-cycle run 需要 --rc-task")
        stable = _json.loads(args.rc_stable) if args.rc_stable else {}
        volatile = _json.loads(args.rc_volatile) if args.rc_volatile else {}
        out = sch.run(args.rc_task, stable, volatile, max_rounds=args.rc_rounds)
        print("[评审段调度] task=%s | state=%s | 轮次=%d | 真发车=%d | 复用省构建=%d"
              % (out["task_key"], out["state"], len(out["rounds"]),
                 sum(1 for r in out["rounds"] if r["dispatched"]),
                 sum(1 for r in out["rounds"] if r["reused"])))
        print("  省下的复述 token ~%d | 说明：%s"
              % (out["stats"]["context_saved_tokens"], out["stats"]["note"]))
        return 0

    if args.entry:
        # 入口归一化：把「入口 + 任务」收敛到秘书主入口并落位适配器；
        # 若显式 @ 了某角色，先校验是否跳过秘书（强制入口护栏）。
        from entries import route as _er
        rt = _er.route(args.entry, args.req or "", role=args.direct_role,
                       direct_role=args.direct_role)
        print("[入口归一化] main_entry=架构·秘书 | entry=%s | guard_ok=%s | routed_to=%s"
              % (rt["entry"], rt["guard"]["ok"], rt.get("routed_to", "-")))
        if not rt["ok"]:
            print("强制入口护栏：%s" % rt["guard"]["message"])
            return 2
        # 落位适配器后继续走单份核心编排（不在此处 if 分支污染核心）
        print("  适配器: %s (locus=%s) -> 交单份核心编排处理" %
              (rt["adapter"]["key"], rt["adapter"]["locus"]))
    if args.guard_entry:
        if not args.req:
            parser.error("--guard-entry 需要 --req 需求文本")
        r = profile.guard_entry(
            (spec.parse(args.spec) if args.spec else {}).get("profile", "default"),
            direct_role=args.direct_role,
        )
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r["ok"] else 2

    if args.prescale:
        if not args.req:
            parser.error("--prescale 需要 --req 需求文本")
        kind = (spec.parse(args.spec) if args.spec else {}).get("profile", "default")
        pre = prescale.prescale(args.req, kind=kind, complexity_hint=args.complexity)
        print(prescale.to_json(pre))
        return 0

    if args.list_profiles:
        print("前置流程模板（不同位置不同流程）：")
        for p in profile.list_profiles():
            print(f"  - {p}: {profile.describe(p)}")
        return 0

    if args.list_roles:
        # 合并内置 + 插件角色（灵活增减）
        reg = plugin.merged_registry()
        print(f"团队角色（共 {len(reg)} 个，含插件）：")
        for r in reg:
            print(f"  - {r}")
        return 0

    if args.clear:
        relay.clear()
        print("已清空接力卡")
        return 0

    if args.scale:
        # 规模化流水线：声明团队大小/分工层级/并发度 + 前置流程区分
        spec_obj = {}
        if args.spec:
            spec_obj = spec.parse(args.spec)
        if args.profile:
            spec_obj["profile"] = args.profile
        if not args.req:
            parser.error("--scale 需要 --req 需求文本")
        report = engine.run_scaled(
            args.req,
            spec_obj=spec_obj,
            concurrency_override=args.concurrency,
            verbose=True,
        )
        print("\n===== 规模化交付报告 =====")
        print(engine.to_json(report))
        return 0

    if args.resume:
        card = relay.load()
        if not card:
            print("无接力卡可续跑，请先 --pipeline 或 --role 启动。")
            return 1
        print(f"[续跑] 从接力卡当前进度续跑：{card.get('current_progress')}")
        # 简化：续跑 = 重新跑完整流水线（保留 req）
        report = orchestrator.run_pipeline(card["req"], backend=args.backend)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if not args.req:
        parser.error("--req 必填（除非使用 --list-roles/--list-profiles/--resume/--clear）")

    if args.pipeline:
        report = orchestrator.run_pipeline(
            args.req,
            backend=args.backend,
            use_fusion=not args.no_fusion,
            force_topology=args.topo,
            complexity=args.complexity,
            subtasks=args.subtasks,
        )
        print("\n===== 交付报告 =====")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    if args.role:
        result = orchestrator.run_role(args.role, args.req, backend=args.backend)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.error("请指定 --pipeline 或 --role")


if __name__ == "__main__":
    sys.exit(main())
