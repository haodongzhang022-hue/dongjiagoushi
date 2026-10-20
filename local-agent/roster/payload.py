# -*- coding: utf-8 -*-
"""
角色名册 · 握手载荷（给对端的稳定接口面）
=========================================
外部对端（管理-派单控制面 / 本地中控 / 网关）只需要问一次：

    「你这边有哪些角色、ID 是什么、能跑吗？」

然后按 ID 派单过来。所以载荷要**稳定、自描述、可校验**：

  - `catalog()`  能力清单：版本 + 全部角色 + 缺口（对方拿这份渲染下拉/校验目标）
  - `resolve()`  按 ID / 中文名 / 别名 / @串 解析出规范角色（对方派单前先对一次）
  - `verify()`   对端清单 ⇄ 本仓名册 双向核对，返回差集（谁多、谁少、谁不可跑）

`catalog` 里的 `contract` 字段是**协议版本**：新增角色不升版（向后兼容），
**删/改 `role_id` 才升版**——对端据此判断要不要重拉清单。
"""
import re

from . import specs as _specs

__all__ = ["CONTRACT", "catalog", "resolve", "verify"]

# 名册契约版本：加字段/加角色不升版；删角色、改 role_id 升 v2。
CONTRACT = "dongjiagoushi.roster/v1"


def _compact(spec):
    """对端渲染用的紧凑形态（去掉内部字段，保留可决策的信息）。"""
    return {
        "role_id": spec["role_id"],
        "name": spec["name"],
        "slogan": spec["slogan"],
        "trigger_words": spec["trigger_words"],
        "impl": spec["impl"],
        "at": spec["at"],
        "relay": spec["relay"],
        "pipeline": spec["pipeline"],
    }


def catalog(entry="arch.secretary", include_gaps=True):
    """能力清单：对方注册/派单/渲染角色下拉都用这一份。

    entry 是**主入口**（本仓规则：默认入口永远是秘书，其余角色是它路由出来的）。
    对端不需要知道这条规则，但它需要知道「没指定角色时该发给谁」——所以给出来。
    """
    all_specs = _specs.specs()
    roles = [_compact(s) for _, s in sorted(all_specs.items(), key=lambda kv: kv[0])]
    out = {
        "contract": CONTRACT,
        "repo": _specs.repo(),
        "entry_role_id": entry,
        "roles": roles,
        "count": len(roles),
    }
    if include_gaps:
        # 缺口对外也是信息：对端派单前就知道哪些角色「登记了但跑不起来」，
        # 不用等派过去失败一次才发现。
        out["gaps"] = {
            "drift": _specs.drift(),
            "missing_ids": _specs.missing_ids(),
        }
    return out


_AT_RE = re.compile(r"@([\w.-]+/[\w.-]+)\(([^)]+)\)")
_RELAY_RE = re.compile(r"\[触发[:：]\s*([^\]]+)\]")


def resolve(target):
    """把对端给的目标（ID / 中文名 / 别名 / @org/repo(角色) / [触发:角色]）解析成规范角色。

    返回 {ok, role_id, name, impl, source}；认不出 → ok=False + 候选建议，
    **不猜**（猜错就是派给错误的人，比失败更糟）。
    """
    if not target:
        return {"ok": False, "reason": "empty_target", "suggestions": []}
    raw = str(target).strip()

    # ① 直接就是 ID
    spec = _specs.get_spec(raw)
    if spec:
        return _ok(spec, "role_id")

    # ② @org/repo(角色)  → 取括号里的角色名
    m = _AT_RE.search(raw)
    if m:
        return _resolve_name(m.group(2), "at")

    # ③ [触发:角色]
    m = _RELAY_RE.search(raw)
    if m:
        return _resolve_name(m.group(1), "relay")

    # ④ 中文名 / 别名（含「架构·」前缀的规范名）
    return _resolve_name(raw, "name")


def _resolve_name(name, source):
    rid = _specs.role_by_name(name)
    if rid:
        spec = _specs.get_spec(rid)
        if spec:
            return _ok(spec, source)
    # 认不出：给出最接近的候选（按子串/前缀），让人一眼看出该填什么
    needle = name.strip()
    cands = [
        s for _, s in _specs.specs().items()
        if needle and (needle in s["name"] or s["name"].split("·", 1)[-1] in needle)
    ][:5]
    return {
        "ok": False,
        "reason": "unknown_role",
        "target": name,
        "suggestions": [{"role_id": c["role_id"], "name": c["name"]} for c in cands],
    }


def _ok(spec, source):
    return {
        "ok": True,
        "role_id": spec["role_id"],
        "name": spec["name"],
        "impl": spec["impl"],
        "source": source,
    }


def verify(their_roles):
    """对端清单 ⇄ 本仓名册 双向核对。

    their_roles: 对端上报的角色列表，元素可以是 role_id / 中文名 / {"role_id":..}
    返回 {ok, only_theirs, only_ours, name_mismatch, unimplemented, count}——
    **不隐藏差集**：谁多了谁少了都摆出来，直接可贴回对接评论。
    """
    mine = _specs.specs()
    mine_by_name = {s["name"]: rid for rid, s in mine.items()}

    theirs = {}
    for item in their_roles or []:
        if isinstance(item, dict):
            cand = item.get("role_id") or item.get("name") or ""
        else:
            cand = item
        r = resolve(cand)
        if r.get("ok"):
            theirs[r["role_id"]] = cand
        else:
            theirs.setdefault(f"unknown::{str(cand)}", cand)

    only_theirs = [{"role_id": k, "given": v} for k, v in theirs.items() if k not in mine]
    only_ours = [{"role_id": rid, "name": s["name"]} for rid, s in mine.items()
                 if rid not in theirs]
    unimplemented = [
        {"role_id": rid, "name": s["name"]}
        for rid, s in mine.items() if rid in theirs and not s["impl"]
    ]
    return {
        "ok": not only_theirs and not only_ours,
        "contract": CONTRACT,
        "count": {"mine": len(mine), "theirs": len(theirs)},
        "only_theirs": only_theirs,
        "only_ours": only_ours,
        "unimplemented": unimplemented,
        "name_mismatch": [],
    }
