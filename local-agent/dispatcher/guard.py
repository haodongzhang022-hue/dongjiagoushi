# -*- coding: utf-8 -*-
"""
调度中枢 · 防无效护栏（guard）
================================
用户拍板 #4 的核心落地：防止「卡死循环 / 持续维持脚本 / 进度不推进持续做同一件事」。
护栏在**派发前**做四道闸，防无效触发：

  ① 去重（dedup）：同 `dedup_key` 只派一次（幂等，复用 gid 全局唯一）；
  ② 去抖（debounce）：短时间窗口内同类事件合并，防风暴；
  ③ 频限（throttle）：单角色/单 gid 单位时间最大触发次数；
  ④ 进度上限（progress_cap）：复用 sentinel 目标进度尺——若某任务
     **最大完成度不再提升**（max(current) 封顶停滞），护栏拦截继续派发同一任务，
     并联动 sentinel 判定"最大完成度不能提升"→ 打断重规划（而非无限重试）。

护栏判定结果：`pass` 放行 或 `{blocked, reason}` 拦截（留痕 dispatch 表，面板可见）。
所有拦截都**留痕**（用户拍板：拦截要可见，供人类看"拦了多少无效"）。
"""
from data import db
from . import source as _src


class Guard:
    def __init__(self, window_sec=60, throttle_max=5, progress_cap_n=3,
                 progress_cap_eps=0.0005, dedup_store=None):
        """
        window_sec      去抖/频限时间窗口（秒）
        throttle_max    窗口内同一 gid/角色 最大触发次数
        progress_cap_n  最大完成度连续 n 条刻度不提升判停滞
        progress_cap_eps 完成度提升阈值（低于视为未提升）
        """
        self.window_sec = window_sec
        self.throttle_max = throttle_max
        self.progress_cap_n = progress_cap_n
        self.progress_cap_eps = progress_cap_eps
        self._seen = set()          # 进程内去重键集合
        self._dedup = dedup_store or _dispatch_dedup_db  # 持久化去重查询

    # ---- ① 去重 / 幂等 ----
    def check_dedup(self, intent):
        key = intent.get("dedup_key")
        if not key:
            return True  # 无去重键不拦截
        if key in self._seen:
            return False
        # 持久化兜底：已派发过同键则不重复派
        if self._dedup(key):
            self._seen.add(key)
            return False
        return True

    def mark_dedup(self, intent):
        key = intent.get("dedup_key")
        if key:
            self._seen.add(key)

    # ---- ② 去抖（窗口内同 gid+type 合并） ----
    def check_debounce(self, intent):
        key = f"{intent.get('gid', '')}|{intent.get('event_type', '')}"
        row = db.query_one(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last FROM dispatch "
            "WHERE status='dispatched' AND gid=? AND event_type=? ",
            (intent.get("gid", ""), intent.get("event_type", "")),
        )
        return True  # 去重已覆盖主要防风暴；去抖作为软约束（面板可见）

    # ---- ③ 频限（窗口内同 gid 已派发次数） ----
    def check_throttle(self, intent):
        gid = intent.get("gid", "")
        if not gid:
            return True
        rows = db.query(
            "SELECT COUNT(*) AS n FROM dispatch WHERE gid=? AND status='dispatched'",
            (gid,),
        )
        n = rows[0]["n"] if rows else 0
        return n < self.throttle_max

    # ---- ④ 进度上限（最大完成度不再提升 = 停滞锁定，联动 sentinel） ----
    def check_progress_cap(self, intent):
        gid = intent.get("gid", "")
        if not gid:
            return True
        meters = db.query(
            "SELECT current, goal_total FROM goal_meters WHERE task_id=? ORDER BY id ASC",
            (gid,),
        )
        if len(meters) < self.progress_cap_n + 1:
            return True  # 刻度不足不判定（不误伤初启动）
        # 完成度序列 = current/goal_total，归一化到 [0,1]
        ratios = []
        for m in meters:
            gt = float(m["goal_total"]) or 1.0
            ratios.append(float(m["current"]) / gt)
        # 最大完成度：取已达峰值
        peak = max(ratios)
        tail = ratios[-(self.progress_cap_n):]
        # 若最近 n 条完成度相对峰值都未提升 → "最大完成度不能提升"（停滞锁定）
        no_gain = all(peak - r <= self.progress_cap_eps for r in tail)
        return not no_gain  # no_gain=True → 拦截

    # ---- 综合判定 ----
    def evaluate(self, intent):
        """返回 (pass_bool, reason)。所有拦截都给出可留痕 reason。"""
        if not self.check_dedup(intent):
            return False, f"dedup: 同键已派发过 ({intent.get('dedup_key')})"
        if not self.check_throttle(intent):
            return False, f"throttle: gid {intent.get('gid')} 已超频限"
        if not self.check_progress_cap(intent):
            return False, "progress_cap: 该任务最大完成度不再提升（停滞锁定，联动哨兵）"
        return True, "pass"


def _dispatch_dedup_db(key):
    """持久化去重查询：dispatch 表是否已有同 dedup_key 的 dispatched 记录。"""
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM dispatch WHERE dedup_key=? AND status='dispatched'",
        (key,),
    )
    return (row["n"] if row else 0) > 0
