# -*- coding: utf-8 -*-
"""模型路由 CLI（MCP 管线 · Issue #147）

用法：
  python -m model_routing.cli config            # 打印唯一配置文件路径 + 当前生效内容
  python -m model_routing.cli models [角色]     # 打印渠道顺序（不传角色 → 通用默认）
  python -m model_routing.cli overview          # 打印路由留痕统计
  python -m model_routing.cli dryrun [角色]     # 本地演练：主通道挂 → 降级到备用
"""
import sys
import json

if __name__ == "__main__" and __package__ is None:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_routing import spec
from model_routing.engine import route_call, resolve_models, trace_overview


def main(argv=None):
    argv = argv or sys.argv[1:]
    cmd = argv[0] if argv else "models"
    arg = argv[1] if len(argv) > 1 else None
    if cmd == "config":
        print(json.dumps({
            "config_file": spec.config_path(),
            "default": spec.default_policy(),
            "role_overrides": spec.role_overrides(),
        }, ensure_ascii=False, indent=2))
    elif cmd == "models":
        print(json.dumps({"role": arg, "order": resolve_models(role=arg)},
                         ensure_ascii=False))
    elif cmd == "overview":
        print(json.dumps(trace_overview(), ensure_ascii=False, indent=2))
    elif cmd == "dryrun":
        order = resolve_models(role=arg)

        def caller(model, sp, ui, **kw):
            if model == order[0]:
                raise RuntimeError("connection error: primary channel unavailable")
            return f"answered-by:{model}"
        res = route_call(caller, system_prompt="s", user_input="u", role=arg)
        print(json.dumps({"role": arg, "ok": res["ok"], "used": res["model"],
                          "used_role": res["role"], "attempts": res["attempts"]},
                         ensure_ascii=False, indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
