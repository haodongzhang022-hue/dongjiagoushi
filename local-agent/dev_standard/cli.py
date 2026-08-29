# -*- coding: utf-8 -*-
"""
开发规范 · CLI（MCP 管线 · 程序化入口 · Issue #83）
======================================================
让任何 agent/脚本/CI 通过命令行程序化查询规范、检查合规、生成报告，
形成"MCP 管线效果"——不靠 AI 对话告知，走程序化接口。

用法：
  # 规范查询（全员）
  python -m dev_standard.cli list                          # 全部规范
  python -m dev_standard.cli list --level L1               # 仅必做
  python -m dev_standard.cli list --category code          # 按类别
  python -m dev_standard.cli get --spec S01                # 单条详情
  python -m dev_standard.cli enforced --stage pre_pr       # 某阶段强制规范
  python -m dev_standard.cli summary                       # 概览

  # 合规检查（确定性）
  python -m dev_standard.cli check-pr --target main --source auto/x-1 \
      --test-files tests/a.sh --docs-files docs/A.md
  python -m dev_standard.cli check-code --file local-agent/x.py
  python -m dev_standard.cli check-all --target '{"pr_info": {...}}'
  python -m dev_standard.cli report --format json
"""
import argparse
import json
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)


def _ability(operator):
    from dev_standard import StandardAbility
    return StandardAbility(owner=operator or "系统")


def main(argv=None):
    p = argparse.ArgumentParser(prog="dev_standard.cli", description="开发规范 MCP 管线")
    sub = p.add_subparsers(dest="cmd")

    # ---- 规范查询 ----
    sp = sub.add_parser("list", help="列出规范条目")
    sp.add_argument("--level", default=None)
    sp.add_argument("--category", default=None)
    sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("get", help="取单条规范详情")
    sp.add_argument("--spec", required=True)
    sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("enforced", help="取某阶段强制规范清单")
    sp.add_argument("--stage", required=True)
    sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("summary", help="规范注册表概览")
    sp.add_argument("--operator", default="系统")

    # ---- 合规检查 ----
    sp = sub.add_parser("check-pr", help="PR 规范检查")
    sp.add_argument("--target", default="main", help="PR base 目标分支")
    sp.add_argument("--source", default="", help="PR 源分支")
    sp.add_argument("--test-files", default="", help="测试文件（逗号分隔）")
    sp.add_argument("--docs-files", default="", help="文档文件（逗号分隔）")
    sp.add_argument("--has-conflict", action="store_true", help="是否带冲突")
    sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("check-code", help="代码规范检查")
    sp.add_argument("--file", required=True, help="待检代码文件路径")
    sp.add_argument("--repo", default="")
    sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("check-all", help="全量规范检查（传入 target JSON）")
    sp.add_argument("--target", required=True, help="target JSON（含 pr_info/code_file 等）")
    sp.add_argument("--operator", default="系统")

    sp = sub.add_parser("report", help="合规报告")
    sp.add_argument("--format", default="json", choices=["json", "markdown"])
    sp.add_argument("--operator", default="系统")

    args = p.parse_args(argv)
    ab = _ability(args.operator if hasattr(args, "operator") else "系统")

    if args.cmd == "list":
        out = ab.list_standards(level=args.level, category=args.category)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "get":
        out = ab.get_standard(args.spec)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "enforced":
        out = ab.get_enforced_specs(args.stage)
        print(json.dumps([s["id"] for s in out], ensure_ascii=False))
    elif args.cmd == "summary":
        print(json.dumps(ab.standards_summary(), ensure_ascii=False, indent=2))
    elif args.cmd == "check-pr":
        target = {
            "pr_info": {
                "base": args.target,
                "source": args.source,
                "target": args.target,
                "has_conflict": args.has_conflict,
                "test_files": [x for x in args.test_files.split(",") if x],
                "docs_files": [x for x in args.docs_files.split(",") if x],
                "has_test": bool(args.test_files),
                "has_docs": bool(args.docs_files),
            }
        }
        results = ab.check_pr(target)
        print(json.dumps(ab.report_compliance("pr-check", results, format="json"),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "check-code":
        target = {"code_file": args.file, "repo_path": args.repo}
        results = ab.check_code(args.file, repo_path=args.repo)
        print(json.dumps(ab.report_compliance(args.file, results, format="json"),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "check-all":
        try:
            target = json.loads(args.target)
        except Exception as e:
            print(json.dumps({"ok": False, "error": f"target JSON 解析失败: {e}"}))
            return 1
        results = ab.check_standard(target)
        print(json.dumps(ab.report_compliance("all-check", results, format="json"),
                         ensure_ascii=False, indent=2))
    elif args.cmd == "report":
        print("用法：先运行 check-* 再 report；本命令为占位（报告由 check-* 自动生成）。")
    else:
        p.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
