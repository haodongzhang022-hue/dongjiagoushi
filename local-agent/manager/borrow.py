# -*- coding: utf-8 -*-
"""
借人台账（BorrowLedger · Issue #239 收尾轮）
============================================
跨岗借人是经理「启下」的最后一张牌：本组没人接得住，去别的功能域借个有权限的角色。
牌打得对不对，取决于一件很小的事——**借的结果有没有记下来**。

## 病灶（用户原话）

> 「借人改成按需，不再直接写死，尤其是记录一下是否成功，失败的话需要换其他的人，
>   他缺这一步结果的记录，会重复找不到人用。」

上一轮把借人从"写死「架构·开发」"改成"从名册派生"，方向对了，但**没记结果**：
借失败就悄悄过去了，下一轮再借还是从名册第一个开始试——
于是同一个借不到的人被反复借、反复失败，日志里一堆同样的无用人名，
真正的候选一个没试到。这不是"借不到人"，是**没有记忆**。

## 三件事（本模块只做这三件，别的不碰）

| 事 | 干什么 | 判据 |
|----|--------|------|
| **留痕** | 每次借人都落一条台账（谁、借谁、哪条通路、成没成、为什么） | `record()` 有返回值、可查 |
| **排除** | 该任务上"最近一次仍失败"的人，不再自动重复借 | `failed_roles()` 由台账算出 |
| **换人** | 一个失败就试下一个；候选全借光了就显式说"该换手段了" | `pick_candidates()` + `overview()` |

## 什么才算「借到了人」

不是 `wake.ok` 就算。唤醒结果里有两类**不是借人**的兜底：

- `lead`（转给小组长带编制）——人是经理组里的，不算跨岗借到的；
- `self`（经理自己顶上）——根本没借。

所以只有真把卡投到那个人身上的通路（`fullpath` / `codebuddy` /
`direct_handle` / `platform`）才算借到人（`BORROWED_LANES`）。
把 `self` 记成"借人成功"，就是又给自己作了一次证。
"""
import os
import sys

_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

#: 算「真把卡投给被借的人」的通路（lead/self 是兜底，不是借到人）
BORROWED_LANES = ("platform", "fullpath", "codebuddy", "direct_handle")

#: 任务文本 → 该去借谁（按需，不写死；一个任务命中多域就都给）
NEED_ROLES = (
    ("评审", "架构·评审"), ("走查", "架构·评审"), ("复评", "架构·评审"),
    ("测试", "架构·测试"), ("联调", "架构·测试"), ("验收", "架构·测试"),
    ("文档", "架构·开发"), ("实现", "架构·开发"), ("开发", "架构·开发"),
    ("代码", "架构·开发"), ("修复", "架构·开发"), ("重构", "架构·开发"),
    ("交付", "架构·交付"), ("合并", "架构·交付"), ("收尾", "架构·交付"),
    ("调研", "架构·找工具"), ("选型", "架构·找工具"),
    ("方案", "架构·总师"), ("架构", "架构·总师"),
    ("需求", "架构·产品"), ("澄清", "架构·产品"),
    ("数据", "架构·数据管理员"), ("统计", "架构·数据管理员"),
    ("监控", "架构·监控哨兵"), ("停滞", "架构·监控哨兵"),
)


def counts_as_borrowed(wake):
    """这次唤醒算不算「借到了人」：ok 且通路真投给了被借的人。"""
    if not isinstance(wake, dict) or not wake.get("ok"):
        return False
    return wake.get("lane") in BORROWED_LANES


def _why_not(wake):
    """没借到人时，说清卡在哪（不许只写"失败"）。"""
    if not isinstance(wake, dict):
        return "唤醒无返回"
    if not wake.get("ok"):
        missing = []
        for a in wake.get("attempts") or []:
            if a.get("state") == "skipped_unready":
                missing.extend(a.get("missing") or [])
        return ("全部通路不可用：" + "、".join(sorted(set(missing)))) if missing else \
            "所有通路都试过仍未投递成功"
    lane = wake.get("lane") or ""
    return f"只落到「{lane}」兜底（不是借到那个人），不算借人成功"


def need_roles(task=""):
    """按任务文本判断「该借谁」——按需，不写死某一个人。"""
    text = str(task or "")
    out = []
    for key, role in NEED_ROLES:
        if key in text and role not in out:
            out.append(role)
    return out


def pick_candidates(pool, task="", exclude=(), tried_failed=()):
    """排定这一轮该按什么顺序借人。

    规则（确定性，同输入同输出）：
      ① 排除 `exclude`（本岗/经理自己）与 `tried_failed`（台账里已经借败的人）；
      ② 按任务语义相关性排前（提"评审"就先借评审）；
      ③ 剩下的按名册原序兜底。
    返回 `[{"role", "why"}]`，`why` 说明为什么轮到他（可核验，不靠感觉）。
    """
    exclude = set(exclude or ())
    failed = set(tried_failed or ())
    wanted = need_roles(task)
    ordered, seen = [], set()
    for r in wanted:
        if r in exclude or r in failed or r in seen:
            continue
        if r in pool or not pool:
            ordered.append({"role": r, "why": f"任务需要「{r.split('·')[-1]}」"})
            seen.add(r)
    for r in pool:
        if r in exclude or r in failed or r in seen:
            continue
        ordered.append({"role": r, "why": "名册候选（前序未命中）"})
        seen.add(r)
    return ordered


# ---------------- 台账读写 ----------------
def record(task_key, role, ok, *, handle="", lane="", reason="", owner="",
           detail=None):
    """记一条借人结果（成功失败都记——失败不记＝下轮重复踩坑）。"""
    from data import admin, schema
    schema.init_schema()
    out = {"task_key": task_key, "role": role, "ok": bool(ok),
           "handle": handle, "lane": lane, "reason": reason, "owner": owner}
    try:
        admin.record_borrow(task_key=task_key, role=role, ok=bool(ok),
                            handle=handle, lane=lane, reason=reason,
                            owner=owner, detail=detail or {})
    except Exception as e:  # noqa: BLE001 落库失败要暴露，不能当记过了
        out["ledger_error"] = f"{type(e).__name__}: {e}"
    return out


def history(task_key=None, limit=200):
    """查借人台账（默认最近 200 条；可按任务过滤）。"""
    from data import repository as repo
    return repo.list_borrows(task_key=task_key, limit=limit)


def failed_roles(task_key):
    """该任务上「最近一次结果仍是失败」的角色——下轮自动跳过，不重复找。"""
    from data import repository as repo
    return repo.borrow_failed_roles(task_key)


def overview(task_key=None):
    """二级信息：借过谁、谁借到了、谁一直借不到（供人类/经理俯瞰）。"""
    rows = history(task_key=task_key, limit=500)
    by_role = {}
    # `history()` 是**新→旧**（`ORDER BY id DESC`）；`last_*` 要的是"最近一次"，
    # 所以按**旧→新**遍历，否则循环结束时留下的是最早一条，与 `failed_roles()`
    # （按 id 正序取最新）反着走——同一本台账两套口径，先败后成的角色会被报成"仍借不到"。
    for r in reversed(rows):
        cur = by_role.setdefault(r["role"], {"role": r["role"], "tries": 0,
                                             "ok": 0, "fail": 0,
                                             "last_ok": 0, "last_reason": "",
                                             "handles": []})
        cur["tries"] += 1
        if r.get("ok"):
            cur["ok"] += 1
            cur["last_ok"] = 1
            cur["last_reason"] = ""
        else:
            cur["fail"] += 1
            cur["last_ok"] = 0
            cur["last_reason"] = r.get("reason") or ""
        if r.get("handle") and r["handle"] not in cur["handles"]:
            cur["handles"].append(r["handle"])
    roles = sorted(by_role.values(), key=lambda x: (-x["tries"], x["role"]))
    return {
        "task_key": task_key or "(全部)",
        "attempts": len(rows),
        "ok": sum(1 for r in rows if r.get("ok")),
        "failed": sum(1 for r in rows if not r.get("ok")),
        "roles": roles,
        "stuck": [x["role"] for x in roles if not x["last_ok"]],
        "note": ("还没借过人" if not rows else
                 f"借了 {len(rows)} 次，借到 {sum(1 for r in rows if r.get('ok'))} 次；"
                 f"仍借不到的是 {[x['role'] for x in roles if not x['last_ok']] or '无'}"),
    }


def capability():
    """能力声明（供角色/文档/测试统一引用）。"""
    return {
        "name": "borrow_ledger",
        "version": "v0.1.0",
        "module": "manager-borrow",
        "entry": ["record", "history", "failed_roles", "overview",
                  "pick_candidates", "need_roles", "counts_as_borrowed"],
        "rules": {
            "留痕": "每次借人都记成功/失败（含通路与原因），失败不记＝下轮重复踩坑",
            "换人": "一个借不到就试下一个；候选全败则显式说该换手段，不原地重复",
            "按需": "该借谁由任务语义 + 名册派生（need_roles/pick_candidates），不写死",
            "借到人的判据": f"通路真投给被借者才算（{BORROWED_LANES}）；lead/self 兜底不算",
        },
    }
