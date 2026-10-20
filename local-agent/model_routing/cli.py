# -*- coding: utf-8 -*-
"""模型路由 CLI（MCP 管线 · Issue #147）

用法：
  python -m model_routing.cli config            # 打印唯一配置文件路径 + 当前生效内容
  python -m model_routing.cli models [角色]     # 打印渠道顺序（不传角色 → 通用默认）
  python -m model_routing.cli overview          # 打印路由留痕统计
  python -m model_routing.cli dryrun [角色]     # 本地演练：主通道挂 → 降级到备用
  python -m model_routing.cli roles             # 逐角色实际生效模型（含是否显式指定）
  python -m model_routing.cli audit             # 体检：角色/别名双轴（空壳链/别名断裂/别名未接线/缺链）
  python -m model_routing.cli tiers [角色]      # 三档语义：档1 指定 / 档2 与其他角色一样 / 档3 兜底
  python -m model_routing.cli params            # 平台 npc:go 可控参数（推理深度/上下文/输出/轮次）
  python -m model_routing.cli probe <模型ID>    # 真实探针：平台到底认不认这个 ID（唯一可信来源）
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
    elif cmd == "tiers":
        # 三档俯瞰（用户 2026-10-20 PR #185）：档1 指定 / 档2 与其他角色一样 / 档3 兜底
        roles = [arg] if arg else sorted(spec.role_overrides())
        print(json.dumps([spec.tier_view(r) for r in roles],
                         ensure_ascii=False, indent=2))
    elif cmd == "params":
        # 平台 npc:go 可控参数（与 .cnb.yml 的 .npc_task 一致性由 signal test 核验）
        print(json.dumps({"npc_go": spec.npc_go_params(),
                          "default_model": spec.default_chain()[0]},
                         ensure_ascii=False, indent=2))
    elif cmd == "probe":
        # 真实探针：不确定「平台可选列表里到底有没有这个 ID」时，用真调用验证，
        # 不靠猜。有一条真成功的响应才能往 models.yml / alias 里登记。
        import os
        model_id = arg or ""
        if not model_id:
            print("usage: python -m model_routing.cli probe <模型ID>", file=sys.stderr)
            return 2
        if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("LOCAL_AGENT_API_KEY")):
            print(json.dumps({"model": model_id, "ok": False, "skipped": True,
                              "reason": "未配置 OPENAI_API_KEY / LOCAL_AGENT_API_KEY，"
                                        "无法真实探针（不假装成功）"},
                             ensure_ascii=False, indent=2))
            return 2
        from model_routing.engine import is_unavailable
        try:
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY")
                            or os.environ.get("LOCAL_AGENT_API_KEY"),
                            base_url=os.environ.get("OPENAI_BASE_URL",
                                                    "https://api.openai.com/v1"))
            resp = client.chat.completions.create(
                model=spec.resolve_alias(model_id),
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=8,
            )
            print(json.dumps({"model": model_id, "ok": True,
                              "reply": (resp.choices[0].message.content or "")[:60]},
                             ensure_ascii=False, indent=2))
            return 0
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"model": model_id, "ok": False,
                              "unavailable": is_unavailable(e),
                              "error": str(e),
                              "hint": "not in the optional models list → ID 不存在，别登记；"
                                      "timeout/rate_limit → ID 可能对但通道不通，隔时重试"},
                             ensure_ascii=False, indent=2))
            return 1
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
