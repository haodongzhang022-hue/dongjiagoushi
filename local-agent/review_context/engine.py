# -*- coding: utf-8 -*-
"""评审上下文增量复用 · 确定性引擎（engine）—— 见 __init__ 文档。"""
import hashlib
import json
import os
import threading
import time

from . import spec

# 本地留痕（与 relay/其它 state 同目录习惯；不依赖数据层，跨项目可抽取）
_TRACE_LOCK = threading.Lock()
_TRACE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "review_context_trace.json",
)
_TRACE = None


# ---------------------------------------------------------------------------
# 一、内容指纹（唯一失效判据：来源一变指纹即变，骨架才需重算）
# ---------------------------------------------------------------------------
def fingerprint(payload):
    """对任意 JSON 可序列化对象求内容指纹（sha256 短摘要）。

    确定性：同内容必然同指纹；内容一变指纹必变——这是「稳定骨架何时失效」的
    唯一判据，不做主观判断、不靠"看起来差不多"。
    """
    if isinstance(payload, str):
        raw = payload
    else:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# 二、复用判定（稳定骨架冻结后，来源没变就零成本复用）
# ---------------------------------------------------------------------------
def reuse_decision(prev, sources):
    """判定能否复用上一轮冻结的稳定骨架。

    prev:    上一轮 build() 产物（None = 无历史，不能复用）
    sources: 本次稳定骨架来源 dict（segment → 原文）
    返回 {reusable, reason, prev_fp, cur_fp, changed_segments}
    """
    cur_fp = fingerprint({k: sources.get(k, "")
                          for k in spec.STABLE_SEGMENTS})
    if not prev:
        return {"reusable": False, "reason": "无历史冻结骨架（首轮必须构建）",
                "prev_fp": None, "cur_fp": cur_fp, "changed_segments": []}
    prev_fp = prev.get("stable_fp")
    if prev_fp == cur_fp:
        return {"reusable": True,
                "reason": "稳定骨架来源未变（指纹一致）→ 直接复用冻结摘要，零重算",
                "prev_fp": prev_fp, "cur_fp": cur_fp, "changed_segments": []}
    # 指纹变了：指出到底哪几段变了（便于只重建该段，不重讲全项目）
    changed = []
    prev_seg_fp = prev.get("segment_fps", {})
    for seg in spec.STABLE_SEGMENTS:
        if prev_seg_fp.get(seg) != fingerprint(sources.get(seg, "")):
            changed.append(seg)
    return {"reusable": False,
            "reason": "稳定骨架来源已变（%s 段）→ 增量重建骨架摘要" % "、".join(changed),
            "prev_fp": prev_fp, "cur_fp": cur_fp, "changed_segments": changed}


# ---------------------------------------------------------------------------
# 三、上下文包构建（冻结骨架 + 变化片段 → 评审只需吃的增量上下文）
# ---------------------------------------------------------------------------
def _ref(segment, text, max_chars=spec.SEGMENT_REF_CHARS):
    """把一段骨架压成"引用行"（不复述全文，只保关键信息）。"""
    text = (text or "").strip().replace("\n", " ")
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return spec.REF_FORMAT.format(segment=segment, summary=text)


def build(stable_parts=None, volatile_parts=None, prev=None, task_key=""):
    """构建评审上下文包（评审前调用一次；下轮只传 volatile 增量）。

    参数：
      stable_parts:   稳定骨架来源 {segment: 原文}（goal/boundary/acceptance/...）
      volatile_parts: 变化片段 {segment: 增量}（diff_summary/test_signals/findings/...）
      prev:           上一轮 build() 产物（用于判定/复用冻结骨架）
      task_key:       任务标识（留痕用）

    返回评审上下文包：
      { module, task_key, stable_fp, segment_fps, frozen,
        stable_refs[引用行], stable_digest（冻结骨架摘要文本）,
        volatile, reuse（复用判定）, context（喂给评审的最小上下文）,
        full_chars, context_chars, saved_chars, saved_ratio, trace_id }
    """
    stable_parts = dict(stable_parts or {})
    volatile_parts = dict(volatile_parts or {})
    seg_fps = {seg: fingerprint(stable_parts.get(seg, ""))
               for seg in spec.STABLE_SEGMENTS}
    stable_fp = fingerprint({seg: stable_parts.get(seg, "")
                             for seg in spec.STABLE_SEGMENTS})

    decision = reuse_decision(prev, stable_parts)

    # 冻结骨架：可复用则直接引用上轮引用行（不重算、不重讲）；否则重建引用行
    if decision["reusable"] and prev:
        stable_refs = list(prev.get("stable_refs", []))
        # frozen=True 语义：本轮骨架**整块未变**、直接冻结复用（未重算、未重讲）
        frozen = True
        rebuilt = False
    else:
        stable_refs = [_ref(seg, stable_parts.get(seg, ""))
                       for seg in spec.STABLE_SEGMENTS]
        # frozen=False：本轮骨架已重算（首次构建 / 有段变更），不是"整块复用"
        frozen = False
        rebuilt = True
        # 指纹变了但只是部分段变：**只保留未变更段的旧引用**，变更段必须用新值重建
        # （否则评审会吃到过期骨架 —— 变更段旧引用一旦命中即掩盖新值）
        if prev and decision["changed_segments"]:
            changed = set(decision["changed_segments"])
            prev_refs = {r.split("]")[0].lstrip("["): r
                         for r in prev.get("stable_refs", [])}
            stable_refs = [
                (prev_refs.get(seg) if seg not in changed else None)
                or _ref(seg, stable_parts.get(seg, ""))
                for seg in spec.STABLE_SEGMENTS
            ]

    stable_digest = "\n".join(stable_refs)
    volatile_note = "\n".join(
        "[{k}] {v}".format(k=seg, v=str(volatile_parts.get(seg, "")).strip())
        for seg in spec.VOLATILE_SEGMENTS if volatile_parts.get(seg)
    )
    # 表头如实反映本轮骨架状态（复用 vs 重算），不让"已复用"掩盖"刚重建"
    if decision["reusable"] and prev:
        head = "【稳定骨架（整块未变，已复用，勿复述）】"
    elif prev and decision["changed_segments"]:
        head = "【稳定骨架（变更段已重建：%s，未变段复用）】" % "、".join(
            decision["changed_segments"])
    else:
        head = "【稳定骨架（首轮构建，后续轮将复用）】"
    context = (
        head + "\n" + stable_digest +
        ("\n\n【本轮变化（增量，仅此即可评审）】\n" + volatile_note
         if volatile_note else "\n\n【本轮无变化片段】")
    )

    # 量化：先构造「未优化形态」——把稳定骨架原文**照旧复述**一遍 + 变化片段，
    # 这是用户痛点里的现状（每次评审复述整个项目）。增量上下文与它之差 = 省下的复述成本。
    naive_context = (
        "【全量复述（未优化形态）】\n" +
        "\n".join(str(stable_parts.get(seg, "")) for seg in spec.STABLE_SEGMENTS) +
        ("\n\n【本轮变化】\n" + volatile_note if volatile_note else "")
    )
    full_chars = len(naive_context)
    context_chars = len(context)
    saved_chars = max(0, full_chars - context_chars)
    saved_ratio = round(saved_chars / full_chars, 4) if full_chars else 0.0

    pack = {
        "module": spec.MODULE,
        "module_version": spec.MODULE_VERSION,
        "task_key": task_key or "",
        "stable_fp": stable_fp,
        "segment_fps": seg_fps,
        "frozen": frozen,
        "rebuilt": rebuilt,
        "stable_refs": stable_refs,
        "stable_digest": stable_digest,
        "volatile": volatile_parts,
        "reuse": decision,
        "context": context,
        "full_chars": full_chars,
        "context_chars": context_chars,
        "saved_chars": saved_chars,
        "saved_ratio": saved_ratio,
        "ts": _now(),
    }
    pack["trace_id"] = _record(pack)
    return pack


def estimate_saved_tokens(pack, chars_per_token=3):
    """把省下的复述字符折算成 token（供成本报表，chars/3 为保守中英混排口径）。"""
    saved = int(pack.get("saved_chars", 0))
    return max(0, saved // max(1, chars_per_token))


# ---------------------------------------------------------------------------
# 四、留痕（可回溯；尽力同步 data/archives，失败不影响主流程）
# ---------------------------------------------------------------------------
def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _record(pack):
    trace_id = "rctx-%s" % fingerprint(
        {k: pack.get(k) for k in ("task_key", "stable_fp", "ts")})[7:19]
    entry = {
        "trace_id": trace_id,
        "task_key": pack.get("task_key"),
        "stable_fp": pack.get("stable_fp"),
        "reused": bool(pack.get("reuse", {}).get("reusable")),
        "rebuilt": pack.get("rebuilt"),
        "saved_chars": pack.get("saved_chars"),
        "saved_ratio": pack.get("saved_ratio"),
        "ts": pack.get("ts"),
    }
    global _TRACE
    with _TRACE_LOCK:
        _TRACE = _load()
        _TRACE.append(entry)
        _save(_TRACE)
    # 尽力同步数据层（跨项目/无数据层时静默跳过）
    try:
        from data import admin
        admin.archive(trace_id, "review_context",
                      "[评审上下文] 增量复用 %s" % ("命中" if entry["reused"] else "重建"),
                      entry, source="review-context")
    except Exception:  # noqa: BLE001
        pass
    return trace_id


def _load():
    global _TRACE
    if _TRACE is not None:
        return _TRACE
    try:
        if os.path.exists(_TRACE_FILE):
            with open(_TRACE_FILE, "r", encoding="utf-8") as f:
                _TRACE = json.load(f)
                return _TRACE
    except Exception:  # noqa: BLE001
        pass
    _TRACE = []
    return _TRACE


def _save(entries):
    try:
        os.makedirs(os.path.dirname(_TRACE_FILE), exist_ok=True)
        with open(_TRACE_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


def trace_recent(limit=20):
    """最近 N 条评审上下文留痕（供监控/看板俯瞰）。"""
    with _TRACE_LOCK:
        return list(_load()[-limit:])


def reset_for_tests():
    """清空内存留痕（仅供测试隔离使用）。"""
    global _TRACE
    with _TRACE_LOCK:
        _TRACE = []
    try:
        if os.path.exists(_TRACE_FILE):
            os.remove(_TRACE_FILE)
    except Exception:  # noqa: BLE001
        pass
