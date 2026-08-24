# -*- coding: utf-8 -*-
"""
sentinel · 目标收敛检测引擎（detect）
=====================================
「防无效努力」的核心判定逻辑：基于目标进度尺（goal_meters）的距离序列，
机器判定一个角色是否在**无效努力**——即：

  - **停滞（stagnation）**：连续 N 次记录，距目标距离几乎不变（delta 无实质推进）。
  - **横跳（oscillation）**：距离在某一区间内来回摆动（推进/回退交替，迟迟不收敛越过阈值）。
  - **重复错误（repeated_error）**：同一个任务上反复提交同一类失败/未推进的动作。

检测引擎不做事后兜底，而是**主动显式暴露**：一旦判定命中，返回触发级别，
由「架构·监控哨兵」按协议处置（见 docs/SENTINEL.md）：
  - 命中 1 次 → `level=1`：打断 + 依据「剩余距离」重新规划再分配；
  - 命中 2 次（或 2 级）→ `level=2`：上报「架构·总师助理」讨论局部架构调整。

判定参数可配置（默认保守，宁可"多留一次机会"也不误伤正常推进）。
"""
import math


# ---- 默认判定参数（可注入覆盖，面向全任务类型通用） ----
DEFAULTS = {
    # 停滞：连续 n 次距离变化绝对值都 < stagnation_eps，视为无效原地打转
    "stagnation_n": 3,
    "stagnation_eps": 0.001,
    # 横跳：在窗口内 max-min 超过 swing_span 但净收敛 net_delta 未超过
    # 目标净推进 net_threshold，且交替次数 >= oscillation_alt
    "oscillation_window": 5,
    "oscillation_alt": 3,
    "oscillation_swing_span": 0.01,     # 摆动幅度下限（相对 max-min）
    "oscillation_net_threshold": 0.05,  # 净推进占 goal_total 的比例下限
    # 重复错误：同一 agent 在同一任务提交相同 note/类别动作 >= n 次
    "repeated_error_n": 3,
}


def _norm_series(series, goal_total):
    """把距离序列归一化到 [0,1]（相对总量），避免不同量纲目标不可比。"""
    out = []
    gt = float(goal_total) if goal_total else 1.0
    for s in series:
        out.append(float(s.get("distance", 0.0)) / gt)
    return out


def _sign(x):
    if x > 1e-12:
        return 1
    if x < -1e-12:
        return -1
    return 0


def detect_stagnation(dist, params):
    """停滞：最近 n 个点距离几乎无变化（原地打转）。"""
    n = params["stagnation_n"]
    eps = params["stagnation_eps"]
    if len(dist) < n + 1:
        return False, 0.0
    window = dist[-(n + 1):]
    # 相邻差值绝对值的最大值
    max_abs_step = max(abs(window[i] - window[i - 1]) for i in range(1, len(window)))
    return max_abs_step < eps, max_abs_step


def detect_oscillation(dist, params, goal_total):
    """横跳：距离在一个区间内来回摆，净收敛不足。"""
    win = params["oscillation_window"]
    if len(dist) < win:
        return False, {}
    window = dist[-win:]
    mx, mn = max(window), min(window)
    swing = mx - mn
    net = window[0] - window[-1]  # >0 表示净推进
    # 交替次数：方向翻转次数
    alts = 0
    prev_sign = _sign(window[1] - window[0])
    for i in range(2, len(window)):
        s = _sign(window[i] - window[i - 1])
        if s != 0 and s != prev_sign:
            alts += 1
        prev_sign = s if s != 0 else prev_sign
    # 摆动够大 且 交替够多 且 净推进不足（占目标总量比例 < 阈值）
    net_ratio = net / goal_total if goal_total else 0.0
    hit = (
        swing >= params["oscillation_swing_span"] * max(mx, 1e-9)
        and alts >= params["oscillation_alt"]
        and net_ratio < params["oscillation_net_threshold"]
    )
    return hit, {"swing": swing, "net_ratio": net_ratio, "alts": alts}


_ERROR_MARKERS = ("失败", "报错", "出错", "error", "Error", "ERR", "重试", "retry", "不通过", "未通过")


def _is_error_note(note):
    """判断一条 note 是否显式标记为失败/出错（避免把普通进度 note 误判为重复错误）。"""
    return any(m in note for m in _ERROR_MARKERS)


def detect_repeated_error(series, params):
    """重复错误：同一 agent 在同一任务反复提交**同一失败动作**（note 显式标错）>= n 次。

    仅统计带失败标记的 note，普通推进 note（如"稳步推进"）不参与，避免误伤正常收敛。
    """
    n = params["repeated_error_n"]
    from collections import Counter
    error_notes = [str(s.get("note", "")) for s in series if _is_error_note(str(s.get("note", "")))]
    cnt = Counter(error_notes)
    hit = False
    repeated = ""
    for note, c in cnt.items():
        if note and c >= n:
            hit = True
            repeated = note
            break
    return hit, repeated


def analyze(series, goal_total=1.0, agent_id="", task_id="", params=None):
    """对某目标刻度的距离序列做综合检测。

    返回：
      {
        "hit": bool,            # 是否命中任一无效努力信号
        "reason": str,          # stagnation / oscillation / repeated_error
        "level": 1|2,           # 触发级别
        "detail": {...},        # 判定详情
        "distance": float,      # 当前剩余距离
        "series_len": int,
      }
    """
    params = {**DEFAULTS, **(params or {})}
    dist = _norm_series(series, goal_total)
    hit = False
    reason = ""
    detail = {}
    cur_dist = dist[-1] if dist else 0.0

    stag, stag_step = detect_stagnation(dist, params)
    if stag and len(dist) >= params["stagnation_n"] + 1:
        hit, reason, detail = True, "stagnation", {"max_abs_step": stag_step}
    else:
        osc, osc_d = detect_oscillation(dist, params, goal_total)
        if osc:
            hit, reason, detail = True, "oscillation", osc_d
        else:
            rep, note = detect_repeated_error(series, params)
            if rep:
                hit, reason, detail = True, "repeated_error", {"repeated_note": note}

    # 级别：已对该任务触发过 2 级（此前上报过架构师助理）→ 本次直接 2 级；
    # 否则 1 级（打断 + 重规划）。
    from sentinel import store
    prev_l2 = store.level2_count_for_task(task_id) if task_id else 0
    level = 2 if prev_l2 > 0 else 1

    return {
        "hit": hit,
        "reason": reason,
        "level": level if hit else 0,
        "detail": detail,
        "distance": cur_dist,
        "series_len": len(dist),
    }
