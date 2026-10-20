# -*- coding: utf-8 -*-
"""MCP 汇聚注册表 · CLI（脚本/CI 直接调，不依赖对话）。

  python -m mcp_hub.cli catalog [--json]          # 端点/工具清单 + 可达状态
  python -m mcp_hub.cli tools                     # 一行一个工具名（grep 友好）
  python -m mcp_hub.cli call relay.check '{"text":"..."}' [--operator X]
  python -m mcp_hub.cli serve [--port 3092] [--host 127.0.0.1]
  python -m mcp_hub.cli launch [--port 3092] [--json]   # 拉起 + 探活回执（同一请求）
  python -m mcp_hub.cli status [--port 3092]
"""
import argparse
import json
import sys

from . import dispatch, registry, server, specs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mcp_hub", description="MCP 汇聚注册表")
    ap.add_argument("cmd", nargs="?", default="catalog",
                    choices=["catalog", "tools", "call", "serve", "launch", "status"])
    ap.add_argument("tool", nargs="?", default="", help="call 时：工具名")
    ap.add_argument("params", nargs="?", default="{}", help="call 时：params JSON")
    ap.add_argument("--operator", default=None)
    ap.add_argument("--port", type=int, default=3092)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "catalog":
        cat = registry.catalog(port=args.port, host=args.host)
        if args.json:
            print(json.dumps(cat, ensure_ascii=False, indent=2))
            return 0
        print(f"server: {cat['server']['name']} v{cat['server']['version']}"
              f"  前端: {'/'.join(cat['fronts'])}")
        print(f"端点 {len(cat['endpoints'])} 个 · 工具 {cat['tool_count']} 个")
        for e in cat["endpoints"]:
            port = e.get("port") or "-"
            print(f"  端点 {e['id']:<14} kind={e['kind']:<11} port={port:<6}"
                  f"fronts={'/'.join(e['fronts'])}  工具{len(e['tools'])}")
        st = cat["status"]
        print(f"服务 {st['url']} → {'🟢 可达' if st['alive'] else '🔴 未起'}")
        return 0

    if args.cmd == "tools":
        for t in specs.tool_names():
            print(t)
        return 0

    if args.cmd == "call":
        try:
            params = json.loads(args.params)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"ok": False, "reason": f"bad_params: {e}"}, ensure_ascii=False))
            return 2
        res = dispatch.call(args.tool, params, operator=args.operator)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    if args.cmd == "serve":
        server.serve(port=args.port, host=args.host, operator=args.operator)
        return 0

    if args.cmd == "launch":
        res = registry.launch(workspace=args.workspace, port=args.port, host=args.host)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1

    if args.cmd == "status":
        print(json.dumps(registry.status(args.port, args.host), ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
