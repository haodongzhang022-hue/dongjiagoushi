# -*- coding: utf-8 -*-
"""
hybrid CLI 入口
===============
`python -m hybrid.cli <command>` 驱动 Hybrid 资源路由模块。

子命令：
  classify <script...>   判定脚本落地（local/cloud）
  route   --cpu <n>      批量路由（从 tasks 文件或内建清单）
  run     --local <files> 本地批量执行测试脚本
  sync                    把最近一次本地执行结果同步留痕
  cost                    输出成本报表
  all                    一键：route → run(local) → sync → cost
"""
import argparse
import json
import sys
import os

# 保证可从仓库根目录直接 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from hybrid.cost import CostReporter, default_cost_reporter


def _router():
    from hybrid.router import HybridResourceRouter
    return HybridResourceRouter()


def _worker(root=None, timeout=300, dry=False):
    from hybrid.worker import LocalWorker
    return LocalWorker(root_dir=root, timeout=timeout, dry_run=dry)


def _sync():
    from hybrid.sync import ResultSync
    return ResultSync()


def _monitor():
    from hybrid.cost import CostMonitor
    return CostMonitor()


# 内建：仓库全部 CPU 密集测试脚本（云端 37 个中的纯 CPU 部分）
BUILTIN_CPU_SCRIPTS = [
    "local-agent/tests/test_router_integration.sh",
    "local-agent/tests/test_scale.sh",
    "local-agent/tests/test_prescale_entry.sh",
    "local-agent/tests/test_platform_adapter.sh",
    "local-agent/tests/test_bridge_loop.sh",   # 本地⇄云端桥接闭环 (Issue #105)
    "local-agent/tests/test_dashboard.sh",    # 跨端聚合控制页 (Issue #105)
    "local-agent/tests/test_cnb_live.sh",     # 真实 cnb 传输通道 (Issue #105)
    "local-agent/tests/test_engine.sh",
    "local-agent/tests/test_data_layer.sh",
    "local-agent/tests/test_collab.sh",
    "local-agent/tests/test_peer_collab.sh",
    "local-agent/tests/test_peer_closure.sh",
    "local-agent/tests/test_disposition.sh",
    "local-agent/tests/test_sentinel.sh",
    "local-agent/tests/test_external_source.sh",
    "local-agent/tests/test_dispatcher.sh",
    "local-agent/tests/test_probe.sh",
    "local-agent/tests/test_dispatch_engine.sh",
    "local-agent/tests/test_depth_engine.sh",
    "local-agent/tests/test_ops_sim.sh",
    "local-agent/tests/test_topology_comparison.sh",
    "local-agent/tests/test_benchmark_ab.sh",
    "local-agent/tests/test_topology_hybrid.sh",
    "local-agent/tests/test_galton.sh",
    "local-agent/tests/test_topology_fusion.sh",
    "local-agent/tests/test_topology_slim.sh",
    "local-agent/tests/test_secretary_sense.sh",
    "local-agent/tests/test_prefix_cache.sh",
    "local-agent/tests/test_cache_layer.sh",
    "local-agent/tests/test_label_automation.sh",
    "local-agent/tests/test_review_tester_handoff.sh",
    "local-agent/tests/test_dual_axis_review.sh",
    "local-agent/tests/test_local_agent.sh",
    "local-agent/tests/test_dispatch_ability.sh",
    "tests/test_architect_system.sh",
    "tests/test_functional_links.sh",
    "tests/test_relay_workflow.sh",
    "tests/test_memory_store.sh",
    "tests/test_handle_ability.sh",
    "tests/test_company_model.sh",
    "tests/test_mini_e2e.sh",
    "tests/test_doc_consistency.sh",
]


def cmd_classify(args):
    r = _router()
    for name in args.scripts:
        print("%s → %s" % (name, r.classify(name)))


def cmd_route(args):
    r = _router()
    tasks = []
    # 从内建清单带成本估算
    for i, name in enumerate(BUILTIN_CPU_SCRIPTS):
        tasks.append((name, 5 + (i % 10), 10 + (i % 20)))
    res = r.route_many(tasks)
    s = res["summary"]
    print(json.dumps({
        "total": s["total"], "local": s["local"], "cloud": s["cloud"],
        "local_scripts": res["local"], "cloud_scripts": res["cloud"],
    }, ensure_ascii=False, indent=2))


def cmd_run(args):
    w = _worker(root=args.root, timeout=args.timeout, dry=args.dry)
    scripts = args.local or BUILTIN_CPU_SCRIPTS
    result = w.run(scripts)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    _last_result = result
    # 持久化到内存文件供 sync 读取
    _save_last(result)
    if result["summary"]["fail"]:
        sys.exit(1)


_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".last_run.json")


def _save_last(result):
    try:
        with open(_LAST_FILE, "w") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:  # noqa
        pass


def _load_last():
    if os.path.exists(_LAST_FILE):
        try:
            with open(_LAST_FILE) as f:
                return json.load(f)
        except Exception:  # noqa
            return None
    return None


def cmd_sync(args):
    s = _sync()
    result = _load_last()
    if result is None:
        print("no last run found; run 'hybrid run' first", file=sys.stderr)
        sys.exit(2)
    out = s.sync(result, batch_name=args.batch)
    print(json.dumps({"synced": out["synced"], "target": out["target"]}))


def cmd_cost(args):
    r = _router()
    m = _monitor()
    tasks = [(n, 5 + (i % 10), 10 + (i % 20)) for i, n in enumerate(BUILTIN_CPU_SCRIPTS)]
    res = r.route_many(tasks)
    last = _load_last()
    rep = m.report(res, last)
    print(json.dumps(rep, ensure_ascii=False, indent=2))


def cmd_all(args):
    # 一键：route → run(local) → sync → cost
    r = _router()
    m = _monitor()
    tasks = [(n, 5 + (i % 10), 10 + (i % 20)) for i, n in enumerate(BUILTIN_CPU_SCRIPTS)]
    res = r.route_many(tasks)
    w = _worker(root=args.root, timeout=args.timeout, dry=args.dry)
    result = w.run(res["local"])
    _save_last(result)
    s = _sync()
    sync_out = s.sync(result, batch_name=args.batch)
    rep = m.report(res, result)
    print(json.dumps({
        "route": res["summary"],
        "run": result["summary"],
        "sync": {"synced": sync_out["synced"], "target": sync_out["target"]},
        "cost": rep,
    }, ensure_ascii=False, indent=2))


# ============ 公交车式批量测试计划执行器（BusRunner）CLI 接线 ============

def _bus():
    from hybrid.bus import BusRunner
    return BusRunner(dry_run=False)


def cmd_bus_enqueue(args):
    b = _bus()
    r = b.enqueue(args.tests, source=args.source or "cli",
                  note=args.note or "bus enqueue")
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_bus_status(args):
    b = _bus()
    print(json.dumps(b.status(), ensure_ascii=False, indent=2))


def cmd_bus_dispatch(args):
    # 立即整批发车：把队列里全部待跑测试作为一批计划，一次构建跑完
    from hybrid.bus import BusRunner
    b = BusRunner(dry_run=args.dry, timeout=args.timeout,
                  interval=args.interval, parallel=args.parallel)
    plan = b.dispatch(extra_tests=args.tests or None, note=args.note or "bus dispatch")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


def cmd_bus_tick(args):
    # 定时哨兵：到点且队列非空才发车（公交车逻辑），否则等下一班
    from hybrid.bus import BusRunner
    b = BusRunner(dry_run=args.dry, timeout=args.timeout,
                  interval=args.interval, parallel=args.parallel)
    plan = b.tick(extra_tests=args.tests or None, note=args.note or "bus tick")
    print(json.dumps(plan, ensure_ascii=False, indent=2))


# ============ 云端配额护栏（QuotaGuard）CLI 接线 ============

def _quota():
    from hybrid.quota import QuotaGuard
    return QuotaGuard()


def cmd_quota(args):
    q = _quota()
    if args.action == "status":
        print(json.dumps(q.quota_status(), ensure_ascii=False, indent=2))
    elif args.action == "meter":
        r = q.meter_consume(args.task, float(args.amount), note=args.note or "")
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.action == "credit":
        r = q.credit_localized(float(args.amount), note=args.note or "")
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.action == "audit":
        print(json.dumps(q.audit(), ensure_ascii=False, indent=2))


# ============ 云端批量打包（CloudBatch）CLI 接线 ============

def _batch():
    from hybrid.batch import CloudBatch
    return CloudBatch()


def cmd_batch_enqueue(args):
    b = _batch()
    r = b.enqueue(args.title, description=args.description or "",
                  project=args.project or "", location=args.location or "",
                  priority=args.priority or "P2 中",
                  acceptance=args.acceptance.split("|") if args.acceptance else [])
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_batch_status(args):
    b = _batch()
    print(json.dumps(b.status(), ensure_ascii=False, indent=2))


def cmd_batch_flush(args):
    b = _batch()
    r = b.flush(dry_run=args.dry, post_comment=args.comment)
    print(json.dumps(r, ensure_ascii=False, indent=2))


# ============ 测试智能优化层（v2.0 T3-T6）CLI 接线 ============

def _policy():
    from hybrid.policy import PolicyEngine
    return PolicyEngine()


def _cache():
    from hybrid.cache import FingerprintCache
    return FingerprintCache()


def _executor(root=None, timeout=300, dry=False, parallel=4):
    from hybrid.parallel import ParallelExecutor
    return ParallelExecutor(root_dir=root, timeout=timeout, dry_run=dry, parallel=parallel)


def cmd_smart(args):
    """智能优化一键：增量选择 → 缓存命中剔除 → 并行执行 → 三合一成本报表。"""
    from hybrid import selector
    sel = selector.IncrementalSelector(root_dir=args.root or os.getcwd())
    pol = _policy()
    c = _cache()
    # 变更来源：--base/--head 指定 git 区间，否则用工作区未提交变更
    if args.base:
        changed = sel.changed_files(args.base, args.head or "HEAD")
    else:
        changed = sel.changed_files_workdir()

    suite = None
    if args.full:
        suite = lambda: sel.full_suite()

    # 决策
    decision = pol.decide(
        changed_files=changed,
        cache=c if args.cache else None,
        selector=sel if args.incremental else None,
        full_suite=suite,
        last_full_ts=args.last_full_ts,
        overrides={"incremental": args.incremental, "cache": args.cache,
                   "parallel": args.parallel, "full": args.full},
    )
    print(json.dumps({
        "mode": decision["mode"],
        "tests": decision["tests"],
        "cache_hits": decision["cache_hits"],
        "parallel": decision["parallel"],
        "reason": decision["reason"],
    }, ensure_ascii=False, indent=2))

    # 执行（只跑未命中缓存的）
    if not args.dry:
        ex = _executor(root=args.root, timeout=args.timeout, dry=False,
                       parallel=decision["parallel"])
        run_result = ex.run_parallel(decision["tests"], parallel=decision["parallel"])
        # 执行后写入缓存（通过项标记 pass）
        for r in run_result["results"]:
            if r["exit_code"] == 0:
                c.mark(r["script"], r, "pass")
        # 同步留痕
        _save_last(run_result)
        # 三合一成本报表
        cr = CostReporter() if "CostReporter" in globals() else _cost_reporter()
        full_count = len(sel.full_suite()) if decision["mode"] == "incremental" else len(decision["tests"])
        rep = cr.report_optimizer(
            {**decision, "full_count": full_count},
            run_result,
        )
        print(json.dumps({"run": run_result["summary"], "cost": rep},
                         ensure_ascii=False, indent=2))


def _cost_reporter():
    from hybrid.cost import CostReporter
    return CostReporter()



def _station():
    from hybrid.station import StationAnchor
    return StationAnchor()


def cmd_station(args):
    """站点锚定模型 CLI：list / anchor / plan / replay / cache / review。"""
    a = _station()
    import json as _json
    if args.action == "list":
        print(_json.dumps(a.list_stations(), ensure_ascii=False, indent=2))
    elif args.action == "anchor":
        rec = a.anchor(role=args.role, branch=args.branch,
                       commit=args.commit, tag=args.tag, note=args.note or "")
        print(_json.dumps(rec, ensure_ascii=False, indent=2))
    elif args.action == "plan":
        plan = a.replay_plan(from_role=args.from_role, to_role=args.to_role)
        print(_json.dumps(plan, ensure_ascii=False, indent=2))
    elif args.action == "replay":
        plan = a.replay_apply(from_role=args.from_role, to_role=args.to_role,
                              dry=args.dry)
        print(_json.dumps(plan, ensure_ascii=False, indent=2))
    elif args.action == "cache":
        print(a.build_cache_key(role=args.role, suffix=args.suffix or "tests"))
    elif args.action == "review":
        if args.verdict:
            r = a.review_round(args.role, args.verdict)
        elif args.reset:
            r = a.review_reset(args.role)
        else:
            r = a.review_status(args.role)
        print(_json.dumps(r, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hybrid.cli", description="Hybrid 资源路由 CLI")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("classify", help="判定脚本落地")
    p.add_argument("scripts", nargs="+")
    p.set_defaults(fn=cmd_classify)

    p = sub.add_parser("route", help="批量路由")
    p.set_defaults(fn=cmd_route)

    p = sub.add_parser("run", help="本地批量执行")
    p.add_argument("--local", nargs="*", default=None, help="指定本地脚本清单")
    p.add_argument("--root", default=None, help="工作根目录")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--dry", action="store_true", help="演练模式不真跑")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("sync", help="同步结果留痕")
    p.add_argument("--batch", default="hybrid-local")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("cost", help="成本报表")
    p.set_defaults(fn=cmd_cost)

    p = sub.add_parser("all", help="一键链路")
    p.add_argument("--root", default=None)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--dry", action="store_true")
    p.add_argument("--batch", default="hybrid-local")
    p.set_defaults(fn=cmd_all)

    p = sub.add_parser("station", help="站点锚定模型（M1-M3 + M4缓存 + M5评审闸门）")
    p.add_argument("action", choices=["list", "anchor", "plan", "replay", "cache", "review"])
    p.add_argument("--role", default="local", help="站点角色（cloud/local）")
    p.add_argument("--branch", default=None, help="分支（anchor 用）")
    p.add_argument("--commit", default=None, help="commit（anchor 用）")
    p.add_argument("--tag", default=None, help="标签（anchor 用）")
    p.add_argument("--note", default=None, help="备注")
    p.add_argument("--from-role", default="cloud", help="源站点（plan/replay 用）")
    p.add_argument("--to-role", default="local", help="目标站点（plan/replay 用）")
    p.add_argument("--suffix", default="tests", help="缓存键后缀（cache 用）")
    p.add_argument("--verdict", default=None, help="评审结论（review 用：merge/fix_bug/...）")
    p.add_argument("--reset", action="store_true", help="评审通过后复位轮次")
    p.add_argument("--dry", action="store_true", help="演练模式（replay 不真改 git）")
    p.set_defaults(fn=cmd_station)

    p = sub.add_parser("quota", help="云端核时配额护栏")
    p.add_argument("action", choices=["status", "meter", "credit", "audit"])
    p.add_argument("--task", default=None, help="任务 id（meter 用）")
    p.add_argument("--amount", default="0", help="核·分钟数（meter/credit 用）")
    p.add_argument("--note", default=None, help="备注")
    p.set_defaults(fn=cmd_quota)

    p = sub.add_parser("batch", help="云端批量打包（攒批防频繁唤醒）")
    bs = p.add_subparsers(dest="batch_cmd")
    pe = bs.add_parser("enqueue", help="任务入批（本地 0 成本）")
    pe.add_argument("title", help="任务标题（必填）")
    pe.add_argument("--description", default=None, help="任务描述")
    pe.add_argument("--project", default=None, help="所属项目")
    pe.add_argument("--location", default=None, help="成果落地路径")
    pe.add_argument("--priority", default=None, help="P0 紧急/P1 高/P2 中/P3 低")
    pe.add_argument("--acceptance", default=None, help="验收条件，用 | 分隔多条")
    pe.set_defaults(fn=cmd_batch_enqueue)
    ps = bs.add_parser("status", help="查看攒批队列")
    ps.set_defaults(fn=cmd_batch_status)
    pf = bs.add_parser("flush", help="提交攒批到云端（一次唤醒）")
    pf.add_argument("--dry", action="store_true", help="只生成不创建")
    pf.add_argument("--comment", action="store_true", help="提交后补 @CodeBuddy 评论")
    pf.set_defaults(fn=cmd_batch_flush)

    p = sub.add_parser("bus", help="公交车式批量测试计划执行器（攒批一次构建跑完）")
    bs2 = p.add_subparsers(dest="bus_cmd")
    be = bs2.add_parser("enqueue", help="测试入列（0 成本，等发车）")
    be.add_argument("tests", nargs="+", help="待跑测试脚本")
    be.add_argument("--source", default=None, help="入列来源")
    be.add_argument("--note", default=None, help="备注")
    be.set_defaults(fn=cmd_bus_enqueue)
    bs2.add_parser("status", help="站台信息（队列/下一班车）").set_defaults(fn=cmd_bus_status)
    bd = bs2.add_parser("dispatch", help="立即整批发车（跑完队列全部，一次构建）")
    bd.add_argument("tests", nargs="*", help="可选临时追加测试")
    bd.add_argument("--dry", action="store_true", help="演练不真跑")
    bd.add_argument("--timeout", type=int, default=600)
    bd.add_argument("--interval", type=int, default=900)
    bd.add_argument("--parallel", type=int, default=4)
    bd.add_argument("--note", default=None)
    bd.set_defaults(fn=cmd_bus_dispatch)
    bt = bs2.add_parser("tick", help="定时哨兵：到点且非空才发车")
    bt.add_argument("tests", nargs="*", help="可选临时追加测试")
    bt.add_argument("--dry", action="store_true", help="演练不真跑")
    bt.add_argument("--timeout", type=int, default=600)
    bt.add_argument("--interval", type=int, default=900)
    bt.add_argument("--parallel", type=int, default=4)
    bt.add_argument("--note", default=None)
    bt.set_defaults(fn=cmd_bus_tick)

    p = sub.add_parser("smart", help="智能优化一键（增量+缓存+并行+成本）")
    p.add_argument("--root", default=None)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--dry", action="store_true", help="只决策不执行")
    p.add_argument("--base", default=None, help="git diff 起点（默认用工作区变更）")
    p.add_argument("--head", default=None, help="git diff 终点")
    p.add_argument("--incremental", action="store_true", default=True, help="启用增量选择")
    p.add_argument("--cache", action="store_true", default=True, help="启用缓存命中跳过")
    p.add_argument("--parallel", action="store_true", default=True, help="启用并行执行")
    p.add_argument("--full", action="store_true", help="强制全量回归")
    p.add_argument("--last-full-ts", default=None, help="上次全量回归时间戳")
    p.set_defaults(fn=cmd_smart)

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        sys.exit(0)
    args.fn(args)


if __name__ == "__main__":
    main()


