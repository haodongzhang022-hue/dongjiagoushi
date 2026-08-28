#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hybrid 资源路由 · CLI 统一入口
================================
用法：
  python3 local-agent/hybrid/cli.py route <task_name>
  python3 local-agent/hybrid/cli.py route-ci [.cnb.yml 路径]
  python3 local-agent/hybrid/cli.py run-all-tests
  python3 local-agent/hybrid/cli.py run-test <script_path>
  python3 local-agent/hybrid/cli.py sync [--branch BRANCH]
  python3 local-agent/hybrid/cli.py cost-report
  python3 local-agent/hybrid/cli.py full  # 全流程：测试→同步→成本报告
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 确保可独立运行：将 local-agent 加入 sys.path
ROOT = Path(__file__).resolve().parent.parent.parent  # 仓库根目录
sys.path.insert(0, str(ROOT / "local-agent"))

from hybrid.router import HybridResourceRouter, LOCAL_TEST_SCRIPTS, classify_task
from hybrid.worker import LocalWorker
from hybrid.sync import ResultSyncer
from hybrid.cost import CostMonitor


def cmd_route(args):
    """路由单条任务。"""
    target = classify_task(args.task_name)
    print(f"任务: {args.task_name}")
    print(f"路由: {target}")
    return 0


def cmd_route_ci(args):
    """分析 .cnb.yml 路由分布。"""
    router = HybridResourceRouter()
    yml_path = args.file or ".cnb.yml"
    try:
        content = Path(yml_path).read_text(encoding="utf-8")
    except OSError as e:
        print(f"无法读取 {yml_path}: {e}")
        return 1

    stats = router.analyze_ci_file(content)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_run_all_tests(args):
    """跑全量本地化测试。"""
    worker = LocalWorker(workspace=ROOT)
    results = worker.run_all_tests()
    worker.write_results()

    print(f"\n本地测试结果:")
    print(f"  总数: {results['total']}")
    print(f"  通过: {results['passed']}")
    print(f"  失败: {results['failed']}")
    print(f"  跳过: {results['skipped']}")
    print(f"  耗时: {results['duration']}s")
    print(f"  结果文件: .cnb-results/results.json")

    if results["failed"] > 0:
        print("\n失败项:")
        for t in results["tests"]:
            if t["status"] == "failed":
                print(f"  ✗ {t['name']}: {t['message'][:200]}")
        return 1
    return 0


def cmd_run_test(args):
    """跑单个测试脚本。"""
    worker = LocalWorker(workspace=ROOT)
    results = worker.run_test_suite([args.script])
    worker.write_results()

    t = results["tests"][0] if results["tests"] else {}
    status = t.get("status", "unknown")
    print(f"脚本: {args.script}")
    print(f"状态: {status}")
    if t.get("message"):
        print(f"输出: {t['message'][:500]}")
    return 0 if status == "passed" else 1


def cmd_sync(args):
    """同步结果到云端。"""
    syncer = ResultSyncer(workspace=ROOT, branch=args.branch)
    ok, msg = syncer.sync()
    print(msg)
    return 0 if ok else 1


def cmd_cost_report(args):
    """生成成本报告。"""
    monitor = CostMonitor()
    report = monitor.full_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_full(args):
    """全流程：测试 → 同步 → 成本报告。"""
    # 1. 跑全量测试
    worker = LocalWorker(workspace=ROOT)
    results = worker.run_all_tests()
    worker.write_results()
    print(f"[1/3] 本地测试完成: {results['passed']}/{results['total']} 通过")

    # 2. 同步结果
    syncer = ResultSyncer(workspace=ROOT, branch=args.branch)
    ok, msg = syncer.sync()
    print(f"[2/3] 同步结果: {msg}")

    # 3. 成本报告
    monitor = CostMonitor()
    report = monitor.full_report()
    print(f"[3/3] 成本报告:")
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # 如果测试失败，返回非零
    return 1 if results["failed"] > 0 else 0


def main():
    parser = argparse.ArgumentParser(
        description="Hybrid 资源路由模块 · CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # route
    p_route = sub.add_parser("route", help="路由单条任务")
    p_route.add_argument("task_name", help="任务名/命令")

    # route-ci
    p_route_ci = sub.add_parser("route-ci", help="分析 .cnb.yml 路由分布")
    p_route_ci.add_argument("-f", "--file", default=".cnb.yml", help=".cnb.yml 路径")

    # run-all-tests
    sub.add_parser("run-all-tests", help="跑全量本地化测试")

    # run-test
    p_run = sub.add_parser("run-test", help="跑单个测试脚本")
    p_run.add_argument("script", help="脚本路径")

    # sync
    p_sync = sub.add_parser("sync", help="同步结果到云端")
    p_sync.add_argument("--branch", default=None, help="推送分支")

    # cost-report
    sub.add_parser("cost-report", help="生成成本报告")

    # full
    p_full = sub.add_parser("full", help="全流程：测试→同步→成本报告")
    p_full.add_argument("--branch", default=None, help="推送分支")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    handlers = {
        "route": cmd_route,
        "route-ci": cmd_route_ci,
        "run-all-tests": cmd_run_all_tests,
        "run-test": cmd_run_test,
        "sync": cmd_sync,
        "cost-report": cmd_cost_report,
        "full": cmd_full,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
