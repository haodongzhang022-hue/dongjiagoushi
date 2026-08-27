# -*- coding: utf-8 -*-
"""
monitor_bi · CLI 入口（M6 · cli.py）
======================================
`python -m monitor_bi.cli <command>` 命令行工具：

  - `overview`      实时查询（终端打印概览）
  - `render`        生成 BI 大屏文档（docs/BI_DASHBOARD.md）
  - `token`         查看 token 消耗聚合
  - `code`          查看代码变化统计
  - `anomaly`       扫描异常
  - `stats`         查看四维统计

与现有 `generate-dashboard.py` 并存（各自独立模块，不耦合）。
"""
import sys


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0

    cmd = argv[0]
    try:
        if cmd == "overview":
            _overview()
        elif cmd == "render":
            _render()
        elif cmd == "token":
            _token()
        elif cmd == "code":
            _code()
        elif cmd == "anomaly":
            _anomaly()
        elif cmd == "stats":
            _stats()
        elif cmd in ("-h", "--help"):
            print(__doc__)
        else:
            print(f"未知命令: {cmd}")
            print(__doc__)
            return 1
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def _overview():
    from monitor_bi.render import render as render_fn
    print(render_fn())


def _render():
    from monitor_bi.render import render_to_file
    path = render_to_file()
    print(f"✅ BI 大屏已生成: {path}")


def _token():
    from monitor_bi import token
    tk = token.token_summary("agent", trend=True)
    print(f"Token 总消耗: {tk['total']:,}")
    print(f"按 agent 分布:")
    for b in tk["breakdown"][:10]:
        print(f"  {b['key']}: {b['tokens']:,} tokens ({b['records']} 条)")
    if tk.get("trend"):
        print(f"趋势(最近10条):")
        for t in tk["trend"][-10:]:
            print(f"  {t['bucket']}: {t['tokens']:,}")


def _code():
    from monitor_bi import code
    by_project = code.code_by_project()
    print("代码变化（按项目）:")
    for r in by_project:
        print(f"  {r['key']}: +{r['added']}/-{r['deleted']} (净 {r['net']:+d})")


def _anomaly():
    from monitor_bi import anomaly
    anoms = anomaly.anomaly_scan()
    if not anoms:
        print("✅ 未检测到异常")
    else:
        print(f"⚠️ 发现 {len(anoms)} 项异常:")
        for a in anoms:
            print(f"  [{a['severity']}] {a['entity']} - {a['reason']}")


def _stats():
    from monitor_bi import stats
    for dim in ("agent", "role", "conversation", "project"):
        rows = stats.workload_4d(dim)
        print(f"\n{dim} 维度:")
        for r in rows[:5]:
            print(f"  {r['key']}: {r['total']} (progress={r['progress_count']}, msg={r['message_count']}, archive={r['archive_count']})")


if __name__ == "__main__":
    sys.exit(main())
