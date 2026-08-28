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

    args = ap.parse_args(argv)
    if not getattr(args, "fn", None):
        ap.print_help()
        sys.exit(0)
    args.fn(args)


if __name__ == "__main__":
    main()
