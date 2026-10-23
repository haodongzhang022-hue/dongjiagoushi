# -*- coding: utf-8 -*-
"""云端完成态的**自动判定**（补 entries.bridge 的 collect 缺口）。

原状：`collect_cloud_result(cloud_state=...)` 的云端状态**由调用方给**——
"本地发单 → 云端干活"之后，还得有人手动告诉本地「云端做完了」。这不是闭环。

本模块负责「自己去读」：
    读 Issue 评论流 → 判是否真有目标角色回执 → 给出确定/不确定的结论

## 为什么不直接复用 `comment_stream.has_receipt`

实测它会**假绿**：派发卡正文里就写着「请回执 [接单]」，于是「只有自己发的卡」
也会被判 `received=True`（`degraded=False`，看起来完全正常）。那是把派发当成接单。
所以这里加三道窄判据，缺一不算回执：

    ① 不含触发标记（`[触发:` 开头的舱是出站卡）
    ② 不是派发方自己发的（作者 ≠ 我方身份）
    ③ 命中 `[接单]`（或指定角色名）

## 判定必须区分三态，不许二值化

    confirmed  拿到真回执/真状态 → 可以推进
    pending    确认「还没有」      → 继续等
    unknown    读不全/读不到      → **不能当成 pending**，要显式报警

「判不出来 ≠ 通过」是仓库纪律；这里同样适用。
"""
import json
import re

try:
    from comment_stream.reader import read_comments
    _HAVE_STREAM = True
except Exception:                                    # noqa: BLE001
    _HAVE_STREAM = False

try:
    from .transport import run_cnb
except Exception:                                    # noqa: BLE001
    try:
        from transport import run_cnb                # type: ignore  # noqa: F401
    except Exception:                                # noqa: BLE001
        run_cnb = None

#: 触发标记：出站接力卡的标志（含它的评论不是回执）
TRIGGER_MARK = "[触发:"
#: 回执标记
RECEIPT_MARK = "[接单]"
#: 明确表示"需要返工"的信号（云端做完了但有阻塞）
BLOCK_SIGNS = ("need_fix", "blocked", "需要返工", "打回")

CONFIRMED, PENDING, UNKNOWN = "confirmed", "pending", "unknown"


def _author(c):
    a = c.get("author")
    if isinstance(a, dict):
        return str(a.get("username") or a.get("name") or "")
    return str(a or "")


def classify_comments(comments, role=None, self_author=None,
                      marker=RECEIPT_MARK):
    """把评论分成「真回执 / 可疑 / 出站卡」。纯函数，可单测。"""
    real, cards = [], []
    for c in comments or []:
        body = str(c.get("body") or c.get("content") or "")
        who = _author(c)
        item = {"id": str(c.get("id") or ""), "author": who,
                "body": body[:200], "created_at": c.get("created_at")}
        # ① 出站卡：带触发标记 —— 永远不是回执
        if TRIGGER_MARK in body:
            cards.append(item)
            continue
        # ② 自己发的不算
        if self_author and who == self_author:
            cards.append(dict(item, reason="self"))
            continue
        # ③ 命中回执标记即可；角色名只用于**标注**，不作硬性门槛
        #    （真实回执常写「[接单] 已接单，但 need_fix」，不会再重复一遍角色名；
        #     把角色名当必要条件会漏掉真回执 —— 实测踩过）
        if marker in body:
            item["role_match"] = bool(role and role in body)
            real.append(item)
    return {"receipts": real, "cards": cards}


def check_receipt(repo, number, role=None, self_author=None, kind="issues"):
    """读云端评论流，判定是否拿到**真回执**。返回三态结论。

    返回 {state, receipts, cards, count, complete, reason}
    """
    if not _HAVE_STREAM:
        return {"state": UNKNOWN, "reason": "comment_stream 不可用",
                "receipts": [], "cards": [], "count": 0, "complete": None}
    try:
        result = read_comments(kind=kind, number=number, repo=repo)
    except Exception as e:                           # noqa: BLE001
        return {"state": UNKNOWN, "reason": "读评论失败: {}".format(e),
                "receipts": [], "cards": [], "count": 0, "complete": None}

    comments = result.get("comments") or []
    complete = result.get("complete")
    cls = classify_comments(comments, role=role, self_author=self_author)
    out = {"receipts": cls["receipts"], "cards": cls["cards"],
           "count": len(comments), "complete": complete, "reason": ""}

    if cls["receipts"]:
        # 回执里有明确返工信号 → 仍然是"已回执"，但状态要带上阻塞
        blocked = any(any(s in r["body"] for s in BLOCK_SIGNS)
                      for r in cls["receipts"])
        out["state"] = CONFIRMED
        out["reason"] = "取到目标角色回执"
        out["blocked"] = blocked
        return out
    if complete is False:
        # 读不全时**不能**说"没有回执"——那会把截断误判成链悬空
        out["state"] = UNKNOWN
        out["reason"] = "评论流未读全（complete=False），不能断言无回执"
        return out
    out["state"] = PENDING
    out["reason"] = "读全但尚无真回执（{} 条出站卡，{} 条评论）".format(
        len(cls["cards"]), len(comments))
    return out


def label_state(repo, number):
    """读 Issue 标签（评审打标是云端状态的另一条正本：merge_ready/merged/need_fix）。

    读不到 → UNKNOWN（不猜）；拿到则映射到三态。
    """
    if run_cnb is None:
        return {"state": UNKNOWN, "reason": "cnb CLI 不可用", "labels": []}
    try:
        # 用 get-issue（带 --repo/--number）；`list-labels` 是快捷命令，只认 cwd 上下文
        rc, out, err = run_cnb(["issues", "get-issue", "--repo", repo,
                                "--number", str(number), "--verbose"], timeout=60)
    except Exception as e:                           # noqa: BLE001
        return {"state": UNKNOWN, "reason": "读标签失败: {}".format(e), "labels": []}
    if rc != 0:
        return {"state": UNKNOWN,
                "reason": "读标签失败 rc={}: {}".format(rc, (err or out)[:120]),
                "labels": []}
    names = re.findall(r'"name"\s*:\s*"([^"]+)"', out)
    if not names:
        names = re.findall(r'^\s*-\s*"?([A-Za-z_][\w\-]*)"?\s*$', out, re.M)
    known = [n for n in names if n in (
        "merge_ready", "merged", "need_fix", "need_review", "need_human",
        "blocked", "done")]
    if "merged" in known or "merge_ready" in known:
        state = CONFIRMED
    elif "need_fix" in known or "blocked" in known:
        state = CONFIRMED                      # 有结论，只是要返工
    elif known:
        state = PENDING
    else:
        state = UNKNOWN                        # 没有可识别标签 → 不知道
    return {"state": state, "labels": known, "reason": "标签正本"}


def cloud_state(repo, number, role=None, self_author=None, kind="issues"):
    """综合两路正本（评论回执 + 标签），给出云端完成态。

    任一为 confirmed 即 confirmed（有结论就能推进，是否返工看 blocked）；
    两者都 pending 才 pending；只要有一个 unknown，整体就带 unknown 提示。
    """
    rcpt = check_receipt(repo, number, role=role, self_author=self_author, kind=kind)
    lbl = label_state(repo, number)
    states = (rcpt["state"], lbl["state"])
    if CONFIRMED in states:
        state = CONFIRMED
    elif UNKNOWN in states:
        # 一路不知情、另一路也确认"还没有" → 仍不能算 pending（可能是读不全）
        state = UNKNOWN if lbl["state"] == UNKNOWN and rcpt["state"] == UNKNOWN else PENDING
    else:
        state = PENDING
    return {"state": state, "receipt": rcpt, "label": lbl,
            "blocked": bool(rcpt.get("blocked")),
            "checked_at": __import__("datetime").datetime.utcnow().isoformat()}


def to_cloud_state_kw(state):
    """把三态映射为 bridge 认的 `cloud_state` 取值（merged/done/need_fix/...）。

    只做**保守**映射：pending 不产生状态（让 collect 继续等），
    confirmed 才给具体结论，unknown 显式报错由调用方决定。
    """
    if state.get("state") != CONFIRMED:
        return None
    if state.get("blocked"):
        return "need_fix"
    labels = (state.get("label") or {}).get("labels") or []
    if "merged" in labels:
        return "merged"
    return "done"


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)
