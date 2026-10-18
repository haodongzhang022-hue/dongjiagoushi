# -*- coding: utf-8 -*-
"""角色名册 · CLI（MCP 管线：脚本/CI 直接调，不依赖对话）。

  python -m roster.cli catalog [--json] [--no-gaps]
  python -m roster.cli resolve <目标>
  python -m roster.cli verify --file roles.json
  python -m roster.cli intake --target arch.developer --task "..." [--dry-run] [--entity X]
  python -m roster.cli drift            # 缺口明细（settings/team/registry/relay 谁缺）
  python -m roster.cli wire             # 一行一条，给 grep 用
"""
import argparse
import json
import sys

from . import payload, intake as _intake, specs as _specs


def _wire(cat):
    """一行一条的扁平形态（对端 grep/awk 可切，不依赖 JSON 解析）。"""
    lines = [
        f"contract：{cat['contract']}",
        f"repo：{cat['repo']}",
        f"entry_role_id：{cat['entry_role_id']}",
        f"count：{cat['count']}",
    ]
    for r in cat["roles"]:
        lines.append(
            f"role：{r['role_id']}|{r['name']}|impl={str(r['impl']).lower()}|"
            f"{r['at']}|{r['relay']}"
        )
    for d in (cat.get("gaps") or {}).get("drift", []):
        lines.append(f"gap：{d['role_id']}|{d['name']}|缺:{','.join(d['gaps'])}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="roster", description="角色名册 · 派单接入")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("catalog", help="能力清单（握手）")
    c.add_argument("--json", action="store_true")
    c.add_argument("--no-gaps", action="store_true")

    r = sub.add_parser("resolve", help="解析目标 → role_id")
    r.add_argument("target")

    v = sub.add_parser("verify", help="对端清单 ⇄ 本仓名册 核对")
    v.add_argument("--file", required=True, help="对端角色列表 JSON 文件")

    i = sub.add_parser("intake", help="派单入场")
    i.add_argument("--target", default="")
    i.add_argument("--task", required=True)
    i.add_argument("--entity", default="")
    i.add_argument("--source", default="roster.cli")
    i.add_argument("--dry-run", action="store_true")

    sub.add_parser("drift", help="缺口明细")
    sub.add_parser("wire", help="扁平文本（grep 用）")

    a = ap.parse_args(argv)

    if a.cmd == "catalog":
        cat = payload.catalog(include_gaps=not a.no_gaps)
        print(json.dumps(cat, ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "resolve":
        res = payload.resolve(a.target)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    if a.cmd == "verify":
        with open(a.file, "r", encoding="utf-8") as f:
            their = json.load(f)
        if isinstance(their, dict):
            their = their.get("roles") or []
        res = payload.verify(their)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1
    if a.cmd == "intake":
        res = _intake.intake({"target": a.target, "task": a.task,
                              "entity": a.entity, "source": a.source},
                             dispatch=not a.dry_run)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    if a.cmd == "drift":
        print(json.dumps({"drift": _specs.drift(),
                          "missing_ids": _specs.missing_ids()},
                         ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "wire":
        print(_wire(payload.catalog()))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
