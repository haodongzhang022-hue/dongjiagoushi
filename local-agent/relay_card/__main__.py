# -*- coding: utf-8 -*-
"""relay_card CLI 入口。

用法：
    python -m relay_card check "<交付/接力文本>"
    python -m relay_card check --role 架构·评审 "<文本>"
    python -m relay_card check --file path.txt
    python -m relay_card gen --to 架构·评审
"""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="relay_card", description="接力卡触发校验工具（防断链）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # check
    p_check = sub.add_parser("check", help="校验文本是否含合规 @+[触发] 标记")
    p_check.add_argument("text", nargs="?", help="待校验文本")
    p_check.add_argument("--role", help="目标角色（如 架构·评审 / 评审）")
    p_check.add_argument("--file", help="从文件读取文本")
    p_check.add_argument("--required", action="store_true",
                         help="强制版：缺标记即 exit 1（CI 拦截）")

    # gen
    p_gen = sub.add_parser("gen", help="生成合规接力卡 @ 模板")
    p_gen.add_argument("--to", required=True, help="目标角色（如 架构·评审）")
    p_gen.add_argument("--repo", help="显式指定 org/repo（缺省自动探测）")

    args = parser.parse_args(argv)

    from relay_card import check, check_required, gen

    if args.cmd == "check":
        text = args.text or ""
        if args.file:
            try:
                with open(args.file, "r", encoding="utf-8") as f:
                    text = f.read()
            except OSError as e:
                print(f"读取文件失败: {e}", file=sys.stderr)
                return 1
        if not text:
            print("错误：未提供文本（--file 或位置参数）", file=sys.stderr)
            return 1
        try:
            if args.required:
                check_required(text, role=args.role)
            else:
                ok, reasons = check(text, role=args.role)
                if not ok:
                    print("INVALID_RELAY ❌")
                    for r in reasons:
                        print("  -", r)
                    return 1
            print("RELAY_VALID ✅")
            return 0
        except ValueError as e:
            print("INVALID_RELAY ❌", e, file=sys.stderr)
            return 1

    elif args.cmd == "gen":
        try:
            print(gen(args.to, repo=args.repo))
            return 0
        except ValueError as e:
            print("错误：", e, file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
