#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ci-review-batch · 云端 CI 评审触发整批测试执行器（Issue #93 · Bus 接入云端 CI）
=============================================================================
对应 Issue #93「云端核时大头在评审触发的测试」：在评审动作（PR 审批）触发时，
不再"每次评审单发一次冷启动构建 / 逐测试单独拉起"，而是复用 Bus 的"整批计划
执行"语义——把本次变更感知所选（IncrementalSelector）+ 核心冒烟兜底，作为【一个
批次】交给 scripts/ci-bus-batch.py（BusRunner 单次构建内整批跑完 + 统一 sync +
cost + quota 收尾）。

设计要点（与 .cnb.yml change aware test 同源、不重复造轮子）：
  - 变更感知选择与 pull_request 阶段一致（base=PR 目标 main，head=PR 源最新），
    复用 hybrid.selector.IncrementalSelector，不各自取名。
  - 评审复批只在"变更真实影响"上再跑一次受影响批次，而不是每次审批都全量冷启动，
    契合 Bus"有需求才发车、一次环境摊全批"的防核时浪费语义。
  - 退出码 0 = 整批通过；非 0 = 该评审门禁判定失败（不静默放行）。

用法（CI / 本地仓库根目录）：
  python3 scripts/ci-review-batch.py [--base <ref>] [--head <ref>] [--dry]
  # 环境变量 CNB_PULL_REQUEST_TARGET_SHA 存在时优先作为 base；
  # 未指定 base/head 时退化为本地工作区增量（git diff）。

退出码：
  0 = 整批全部通过（或评审无真实受影响测试，判定门禁通过）
  1 = 存在失败测试 / 执行异常 / BusRunner 不可用
"""
import argparse
import os
import subprocess
import sys


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bootstrap():
    root = _repo_root()
    la = os.path.join(root, "local-agent")
    if la not in sys.path:
        sys.path.insert(0, la)
    os.chdir(root)
    return root


def _git_changed(base, head):
    """返回 base..head 之间的变更文件清单；任一侧为 None 时退化到工作区增量。"""
    cmd = ["git", "diff", "--name-only"]
    if base and head:
        cmd += [base, head]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa
        return [], "git diff 失败: %s" % e
    if proc.returncode != 0:
        # base 引用可能不完整 → 退化到工作区增量（仅含未提交改动），不致命
        try:
            p2 = subprocess.run(["git", "diff", "--name-only"],
                                capture_output=True, text=True, timeout=60)
            files = [f for f in p2.stdout.strip().split("\n") if f.strip()]
            return files, "base/head 引用不可用(%s)，退化为工作区增量" % proc.stderr.strip()[-200:]
        except Exception:  # noqa
            return [], "git diff 失败"
    files = [f for f in proc.stdout.strip().split("\n") if f.strip()]
    return files, ""


def _env_base_head():
    """从 CI 环境变量解析 base/head；无则返回 (None, None) 让调用方退化。"""
    base = os.environ.get("CNB_PULL_REQUEST_TARGET_SHA", "") or None
    head = os.environ.get("CNB_PULL_REQUEST_SOURCE_SHA", "") or None
    if head is None:
        head = os.environ.get("CNB_COMMIT", "") or None
    return base, head


def main(argv=None):
    _repo_root()  # 复用仓库根（含 _bootstrap 内 os.chdir）
    p = argparse.ArgumentParser(
        prog="ci-review-batch",
        description="云端 CI 评审触发整批测试执行器（Bus 单次构建内整批 + 变更感知）",
    )
    p.add_argument("--base", default=None, help="基准 ref（默认取 CI PR 目标 SHA / origin/main）")
    p.add_argument("--head", default=None, help="对比 ref（默认取 CI PR 源 SHA / HEAD）")
    p.add_argument("--dry", action="store_true", help="演练：不真跑测试，只打印将要执行的整批")
    p.add_argument("--parallel", type=int, default=1, help="整批并行度（默认 1=串行）")
    p.add_argument("--timeout", type=int, default=600, help="单个测试超时秒数")
    args = p.parse_args(argv)

    # 1) 解析 base/head：优先命令行，其次 CI 环境变量
    base = args.base
    head = args.head
    if not base or not head:
        env_base, env_head = _env_base_head()
        base = base or env_base or "origin/main"
        head = head or env_head or "HEAD"

    # 2) 变更感知选择
    root = _bootstrap()
    try:
        from hybrid.selector import IncrementalSelector
    except Exception as e:  # noqa
        print("[ci-review-batch] 错误：无法 import hybrid.selector：%s" % e, file=sys.stderr)
        return 1

    changed, warn = _git_changed(base, head)
    s = IncrementalSelector(root_dir=root)
    selected = []
    if changed:
        try:
            selected = s.select(changed)
        except Exception as e:  # noqa
            warn = (warn + "；select 失败: %s" % e).strip()
    # 无变更或未命中 → 核心冒烟兜底（与 .cnb.yml change aware test 一致）
    if not selected:
        selected = ["tests/test_architect_system.sh"]

    print("==== [ci-review-batch] 云端 CI 评审整批测试执行 ====")
    print("  base=%s  head=%s" % (base, head))
    if warn:
        print("  ⚠ %s" % warn)
    print("  变更文件数: %d  命中测试(%d 个):" % (len(changed), len(selected)))
    for t in selected:
        print("    bash %s" % t)

    # 3) 交给 ci-bus-batch.py：整批计划执行 + 统一 sync/cost/quota
    cmd = [sys.executable, "scripts/ci-bus-batch.py",
           "--parallel", str(args.parallel),
           "--timeout", str(args.timeout),
           "--note", "ci-review-batch"]
    if args.dry:
        cmd.append("--dry")
    cmd += selected
    rc = subprocess.call(cmd, cwd=root)
    return rc


if __name__ == "__main__":
    sys.exit(main())
