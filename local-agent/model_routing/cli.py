# -*- coding: utf-8 -*-
"""模型路由 CLI（MCP 管线 · Issue #147）

用法：
  python -m model_routing.cli config            # 打印唯一配置文件路径 + 当前生效内容
  python -m model_routing.cli models [角色]     # 打印渠道顺序（不传角色 → 通用默认）
  python -m model_routing.cli overview          # 打印路由留痕统计
  python -m model_routing.cli dryrun [角色]     # 本地演练：主通道挂 → 降级到备用
  python -m model_routing.cli roles             # 逐角色实际生效模型（含是否显式指定）
  python -m model_routing.cli audit             # 体检：settings.yml 声明的角色是否都配了
"""
import sys
import json

if __name__ == "__main__" and __package__ is None:
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_routing import spec
from model_routing.engine import route_call, resolve_models, trace_overview  # noqa: E402


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
    elif cmd == "chain":
        print(json.dumps({"role": arg, "chain": list(spec.role_chain(arg))},
                         ensure_ascii=False, indent=2))
    elif cmd == "roles":
        # 逐角色俯瞰：主档模型 / 是否显式指定 / 降级链（人类一眼看完）
        rows = []
        for role in sorted(spec.role_overrides()):
            pol = spec.role_policy(role)
            rows.append({"role": role, "primary": pol["primary"],
                         "chain": pol["chain"], "specified": pol["specified"]})
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif cmd == "audit":
        # 体检：全称 + 短名双体检（空壳链 / 别名断裂 / 缺链）
        bad = spec.audit_roles()
        print(json.dumps({"ok": not bad, "issues": bad,
                          "total_declared": len(spec.declared_roles())},
                         ensure_ascii=False, indent=2))
        return 0 if not bad else 2
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
