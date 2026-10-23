# -*- coding: utf-8 -*-
"""云端派单**探查**（probe，不是催办）。

## 为什么不能"没回执就重发"

回执需要时间。把「还没回执」当故障去重发，会造成：

    重复派单 → 云端角色被反复唤醒 → 同一张单派给多人 → 重复劳动/互相覆盖

那是自己造出来的 bug 循环。所以本模块**只探查、只定向返回结论**，
**永不自动发送、永不自动重试**。要不要重发由人（或显式调用方）决定。

## 三种"看起来都没回执"，其实完全不同

必须分开，否则运维会被误导：

    awaiting   流水线还在跑（pending/running）        → 正常，等
    slow       流水线成功但仍无回执，且在宽限期内      → 正常，再等一会儿
    lost       流水线成功/失败、超过宽限期仍无回执     → **真故障**，需人看
    failed     流水线 error（Prepare/npc go 失败）     → **真故障**，附 stage 原因

判据是**客观信号**（CNB 流水线状态），不是"等了多久"的主观感觉：
只有「流水线已终结 + 超过宽限期 + 仍无回执」才是 lost。

## 为什么必须有 slow 这一档

实测（Issue #236）：npc go stage 里角色已经写出了 `[接单] ... 已接管` 文本、
流水线 `success`，但**评论没真的落到 Issue 上**。如果只有 awaiting/lost 两档，
这条会被判成 lost 而触发重发 —— 但只要再等一会儿或看一眼日志就能分辨。
先给宽限，再判故障，是"稳着点"的落法。
"""
import time

try:
    from .cloud_state import check_receipt, label_state
except Exception:                                    # noqa: BLE001
    from cloud_state import check_receipt, label_state  # type: ignore  # noqa: F401

try:
    from .transport import run_cnb
except Exception:                                    # noqa: BLE001
    try:
        from transport import run_cnb                # type: ignore  # noqa: F401
    except Exception:                                # noqa: BLE001
        run_cnb = None

#: 各种结论（机器可判 + 人可读）
AWAITING = "awaiting"          # 流水线还在跑
SLOW = "slow"                  # 流水线结束但仍在宽限期内
LOST = "lost"                  # 流水线结束 + 超宽限 + 无回执 → 真故障
FAILED = "failed"              # 流水线报错
NO_PIPELINE = "no_pipeline"    # 连流水线都没起（卡没生效）
CONFIRMED = "confirmed"        # 已拿到真回执
UNKNOWN = "unknown"            # 读不到

#: 默认宽限（秒）。npc:go 一般 1-3 分钟出结果；给足余量避免误判。
DEFAULT_GRACE_S = 900
#: 流水线**启动**宽限（秒）。实测卡片发出后 3s 内查不到构建、12s 后才出现 pending，
#: 所以「没看到流水线」不能立刻算故障。
DEFAULT_STARTUP_GRACE_S = 120

_TERMINAL_BAD = ("error", "failed", "failure")
_TERMINAL_OK = ("success", "succeeded")


def _parse_builds(out):
    """从 `cnb build get-build-logs --verbose` 的 JSON 里取构建列表。"""
    import json
    s = (out or "").strip()
    start = s.find("{")
    if start < 0:
        return None
    try:
        data = json.loads(s[start:])
    except Exception:                                # noqa: BLE001
        return None
    node = data.get("data") or {}
    rows = node.get("data") if isinstance(node, dict) else None
    return rows if isinstance(rows, list) else None


def pipeline_state(repo, number, since_ts=None):
    """查这个 Issue 上 NPC 流水线的客观状态。返回 {state, builds, latest}。

    state ∈ running / success / failed / none / unknown
    """
    if run_cnb is None:
        return {"state": UNKNOWN, "reason": "cnb CLI 不可用", "builds": []}
    try:
        rc, out, err = run_cnb(["build", "get-build-logs", "--repo", repo,
                                "--page-size", "20", "--verbose"], timeout=90)
    except Exception as e:                           # noqa: BLE001
        return {"state": UNKNOWN, "reason": "读构建失败: {}".format(e), "builds": []}
    if rc != 0:
        return {"state": UNKNOWN, "builds": [],
                "reason": "读构建失败 rc={}: {}".format(rc, (err or out)[:120])}
    rows = _parse_builds(out)
    if rows is None:
        return {"state": UNKNOWN, "builds": [], "reason": "构建列表解析失败"}

    mine = []
    for b in rows:
        url = str(b.get("eventUrl") or "")
        if "/issues/{}".format(number) not in url:
            continue
        ev = str(b.get("event") or "")
        if "npc" not in ev:
            continue
        if since_ts:
            ct = str(b.get("createTime") or "")
            if ct and _iso_epoch(ct) < since_ts:
                continue
        mine.append(b)
    if not mine:
        return {"state": "none", "builds": [], "reason": "该 Issue 上没有 npc 流水线"}

    latest = min(mine, key=lambda b: str(b.get("createTime") or ""))
    st = str(latest.get("status") or "").lower()
    if st in _TERMINAL_BAD:
        state = "failed"
    elif st in _TERMINAL_OK:
        state = "success"
    elif st in ("pending", "queue", "queued", "running", "preparing"):
        state = "running"
    else:
        state = UNKNOWN
    return {"state": state, "builds": mine, "latest": latest,
            "sn": latest.get("sn"), "reason": "构建状态={}".format(st)}


def _iso_epoch(s):
    """'2026-10-23T20:02:37Z' → epoch 秒；解析不了返回 0。"""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            import datetime as dt
            return dt.datetime.strptime(str(s), fmt).replace(
                tzinfo=dt.timezone.utc).timestamp()
        except Exception:                            # noqa: BLE001
            continue
    return 0


def probe(repo, number, role=None, self_author=None, sent_at=None,
          grace_s=DEFAULT_GRACE_S, startup_grace_s=DEFAULT_STARTUP_GRACE_S,
          now=None):
    """探查一次。**只读，不发任何东西。**

    返回 {verdict, reason, evidence, next_action}
      verdict ∈ confirmed / awaiting / slow / lost / failed / no_pipeline / unknown
      next_action 是**建议**（给人和上层调用方看），本函数**不执行**它。
    """
    now = now if now is not None else time.time()
    rcpt = check_receipt(repo, number, role=role, self_author=self_author)
    ev = {"receipt": rcpt}

    if rcpt["state"] == "confirmed":
        return {"verdict": CONFIRMED, "evidence": ev,
                "reason": "已拿到真回执：{}".format(rcpt.get("reason")),
                "next_action": "可推进：交给 collect/align"}

    pipe = pipeline_state(repo, number, since_ts=sent_at)
    ev["pipeline"] = {k: pipe.get(k) for k in ("state", "sn", "reason")}

    if pipe["state"] == UNKNOWN:
        return {"verdict": UNKNOWN, "evidence": ev,
                "reason": "回执与流水线都读不到：{}".format(pipe.get("reason")),
                "next_action": "先查权限/网络，别重发（不知道状态时重发=重复派单）"}
    if pipe["state"] == "none":
        # ⚠️ 刚发出几分钟内没有流水线是**正常**的（实测 #237：卡发出后 3s 内查不到，
        #    12s 后才出现 pending 构建）。立刻判 no_pipeline 会导致误报 → 误重发。
        #    所以先给「启动宽限」，超了才算卡没生效。
        base = sent_at
        age = (now - base) if base else None
        if age is None or age < startup_grace_s:
            return {"verdict": AWAITING, "evidence": ev,
                    "reason": "卡已发出但流水线尚未出现（{:.0f}s，启动宽限 {}s）—— 正常".format(
                        age or 0, startup_grace_s),
                    "next_action": "等待，不要重发"}
        return {"verdict": NO_PIPELINE, "evidence": ev,
                "reason": "评论已在、超过启动宽限 {}s 仍无 npc 流水线 —— 卡没生效".format(
                    startup_grace_s),
                "next_action": "检查 .cnb.yml 的 issue.comment@npc（角色是否声明、"
                               "评论数是否超 100、@ 是否在普通段落）；"
                               "确认是配置问题后**人工决定**是否补发"}
    if pipe["state"] == "failed":
        return {"verdict": FAILED, "evidence": ev,
                "reason": "流水线失败：{}".format(pipe.get("reason")),
                "next_action": "读 stage 日志定位（Prepare 克隆失败 / npc go 报错），"
                               "**修因后**再决定是否补发"}
    if pipe["state"] == "running":
        return {"verdict": AWAITING, "evidence": ev,
                "reason": "流水线在跑（{}）—— 回执需要时间，正常等待".format(pipe.get("sn")),
                "next_action": "等待，不要重发"}

    # 流水线 success 但仍无回执：先给宽限，再判 lost
    base = sent_at
    if base is None and pipe.get("latest"):
        base = _iso_epoch(pipe["latest"].get("createTime"))
    age = (now - base) if base else None
    if age is None:
        return {"verdict": SLOW, "evidence": ev,
                "reason": "流水线成功但无回执，且不知道投递时刻（无法判超时）",
                "next_action": "带上 sent_at 再探查一次；在此之前不要重发"}
    if age < grace_s:
        return {"verdict": SLOW, "evidence": ev,
                "reason": "流水线成功但无回执，已过 {:.0f}s（宽限 {}s）".format(age, grace_s),
                "next_action": "继续等；实测存在“角色已生成回执文本但评论未落地”的情况，"
                               "先看 stage 日志再决定"}
    return {"verdict": LOST, "evidence": ev,
            "reason": "流水线成功、已过 {:.0f}s 仍无回执（宽限 {}s）—— 真故障".format(age, grace_s),
            "next_action": "读 npc go stage 日志确认是否“生成了回执但没发出”；"
                           "确认后再**人工决定**是否补发一次，禁止循环重发"}


def probe_by_handle(handle, **kw):
    """从句柄探查（bridge 句柄的 cloud_ref 里带 repo/issue）。只读。"""
    ref = (handle or {}).get("cloud_ref") or {}
    number = ref.get("issue_id")
    repo = ref.get("repo") or (handle or {}).get("target_repo")
    try:
        number = int(str(number))
    except (TypeError, ValueError):
        return {"verdict": UNKNOWN, "evidence": {},
                "reason": "句柄锚点不是真实 Issue 编号：{!r}".format(number),
                "next_action": "真实传输需 BRIDGE_TRANSPORT=cnb"}
    sent_at = kw.pop("sent_at", None)
    if sent_at is None:
        sent_at = _iso_epoch(handle.get("created_at"))
    role = ((handle or {}).get("meta") or {}).get("role")
    return probe(repo, number, role=role, sent_at=sent_at or None, **kw)
