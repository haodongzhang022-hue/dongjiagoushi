# -*- coding: utf-8 -*-
"""模型路由 CLI（MCP 管线 · Issue #147）

用法：
  python -m model_routing.cli models    # 打印主/备渠道顺序
  python -m model_routing.cli overview  # 打印路由留痕统计
  python -m model_routing.cli dryrun    # 本地演练：主通道挂 → 降级到备用
"""
import sys
import json

if __name__ == "__main__" and __package__ is None:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_routing.engine import route_call, resolve_models, trace_overview


def main(argv=None):
    argv = argv or sys.argv[1:]
    cmd = argv[0] if argv else "models"
    if cmd == "models":
        print(json.dumps(resolve_models(), ensure_ascii=False))
    elif cmd == "overview":
        print(json.dumps(trace_overview(), ensure_ascii=False, indent=2))
    elif cmd == "dryrun":
        def caller(model, sp, ui, **kw):
            if model == resolve_models()[0]:
                raise RuntimeError("connection error: primary channel unavailable")
            return f"answered-by:{model}"
        res = route_call(caller, system_prompt="s", user_input="u")
        print(json.dumps({"ok": res["ok"], "used": res["model"], "role": res["role"],
                          "attempts": res["attempts"]}, ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
