#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ci-bus-batch · 云端 CI 整批计划测试执行器（Issue #93 · Bus 接入云端 CI）
========================================================================
对应 Issue #93「Bus 公交车式批量测试执行接入云端 CI（攒批一次构建省核时）」：

本地 BusRunner（local-agent/hybrid/bus.py）负责把测试请求攒批入列、15 分钟一班发车，
已被 scripts/local-exec.sh 一键链路调用。但云端 CI 每次 push/PR 仍是**独立冷启动
构建环境**，.bus_queue.json 这类本地 JSON 队列**跨 CI 构建不共享**——云端侧无法做
"跨构建攒批"。因此本脚本把 Bus 在**单次构建内**的整批语义接进 CI：

  - 一次 CI 构建内，把本轮所选的一批测试作为【一个批次计划】在同一个进程/同一个
    构建环境里整批跑完（复用 BusRunner.dispatch 的整批执行 + 统一 sync + cost +
    quota 收尾），而不是逐脚本独立拉起构建 / 乒乓唤醒。
  - 并行度默认 parallel=1（串行）：云端 CI 构建并发由平台管控，bus 内部再开多线程
    并行可能与 CI 环境冲突（Issue #93 约束：Bus DEFAULT_PARALLEL=4 需评估）。
    整批的收益来自"一次环境摊全批 + 统一收尾"，不依赖并行。
  - 有任一测试失败 → 退出码 1（CI 判定该阶段失败）；全部通过 → 0。

用法（在 CI / 本地仓库根目录）：
  python3 scripts/ci-bus-batch.py tests/test_architect_system.sh tests/test_doc_consistency.sh
  python3 scripts/ci-bus-batch.py --dry tests/...                # 演练：不真跑只产等效汇总
  python3 scripts/ci-bus-batch.py --parallel 1 --timeout 600 ...
  python3 scripts/ci-bus-batch.py --help

退出码：
  0 = 整批全部通过
  1 = 存在失败测试 / 用法错误 / 无可执行批次
"""
import argparse
import os
import sys


def _repo_root():
    """仓库根目录（scripts/ 的上一级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bootstrap():
    """把 local-agent 加进 sys.path，使 hybrid.bus 可 import。"""
    root = _repo_root()
    la = os.path.join(root, "local-agent")
    if la not in sys.path:
        sys.path.insert(0, la)
    # 切到仓库根，让相对路径的测试脚本可解析
    os.chdir(root)
    return root


def build_parser():
    p = argparse.ArgumentParser(
        prog="ci-bus-batch",
        description="云端 CI 整批计划测试执行器（BusRunner 单次构建内整批语义）",
    )
    p.add_argument("tests", nargs="+", help="本轮选定的一批测试脚本（相对仓库根路径）")
    p.add_argument("--parallel", type=int, default=1,
                   help="整批并行度（默认 1=串行，规避云端 CI 并发冲突；Issue #93）")
    p.add_argument("--timeout", type=int, default=600, help="单个测试超时秒数")
    p.add_argument("--interval", type=int, default=900,
                   help="发车间隔（本脚本单次构建内立即整批发车，仅语义对齐用）")
    p.add_argument("--dry", action="store_true", help="演练：不真跑测试，只产等效整批汇总")
    p.add_argument("--note", default="ci-bus-batch", help="批次备注（写 bus 历史）")
    return p


def _summarize(plan):
    """从 bus dispatch 返回的 plan 里安全取整批汇总。"""
    summary = (plan or {}).get("summary") or {}
    return {
        "total": summary.get("total", 0),
        "pass": summary.get("pass", 0),
        "fail": summary.get("fail", 0),
        "wall_seconds": summary.get("wall_seconds", summary.get("total_duration", 0.0)),
        "parallel": summary.get("parallel", 1),
    }


def main(argv=None):
    _bootstrap()
    args = build_parser().parse_args(argv)

    tests = [t for t in args.tests if t]
    if not tests:
        print("[ci-bus-batch] 错误：没有可执行的测试（空批次）", file=sys.stderr)
        return 1

    # ---- 复用 BusRunner：整批跑完 + 统一 sync/cost/quota 收尾 ----
    try:
        from hybrid.bus import BusRunner
    except Exception as e:  # noqa
        print("[ci-bus-batch] 错误：无法 import hybrid.bus，BusRunner 不可用：%s"
              % e, file=sys.stderr)
        return 1

    print("==== [ci-bus-batch] 云端 CI 整批计划测试执行 ====")
    print("  模式: %s" % ("演练(dry-run)" if args.dry else "真实执行"))
    print("  并行度: %d（1=串行，规避云端 CI 并发冲突，Issue #93）" % args.parallel)
    print("  整批测试(%d 个):" % len(tests))
    for t in tests:
        print("    bash %s" % t)

    # 单次构建内立即整批发车：队列若空，extra_tests 即这一批（云端每次全新构建，队列为空）
    try:
        # 用独立临时队列文件：云端 CI 与本地攒批队列(.bus_queue.json)完全隔离，
        # 互不串扰（云端单次构建内整批，不依赖也不污染本地攒批语义）。
        import tempfile
        ci_qfile = os.path.join(tempfile.gettempdir(), 'bus_queue_ci.json')
        runner = BusRunner(queue_file=ci_qfile, timeout=args.timeout,
                           interval=args.interval, parallel=args.parallel,
                           dry_run=args.dry)
        plan = runner.dispatch(extra_tests=tests, note=args.note)
    except Exception as e:  # noqa
        print("[ci-bus-batch] 错误：整批执行异常：%s" % e, file=sys.stderr)
        return 1

    s = _summarize(plan)
    print("---- 整批汇总 ----")
    print("  total=%d  pass=%d  fail=%d  wall_seconds=%.1f  parallel=%d"
          % (s["total"], s["pass"], s["fail"], s["wall_seconds"], s["parallel"]))
    finish = (plan or {}).get("finish") or {}
    cost = finish.get("cost") or {}
    if cost:
        print("  cost 报表: 净省 %s 核·分钟（整批本地化/一次构建摊全批）"
              % cost.get("net_save", "0"))
    if finish.get("quota"):
        print("  quota 记账: 见 quota 状态（已 credit 本地化节省）")

    if s["fail"]:
        print("  ❌ 存在 %d 个失败测试 → 该 CI 阶段判定失败" % s["fail"])
        return 1
    print("  ✅ 整批全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
