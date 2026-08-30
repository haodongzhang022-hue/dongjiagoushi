# -*- coding: utf-8 -*-
"""
QuotaGuard · 云端核时配额护栏（M6 · 地铁站点方案落地）
========================================================
云端 @架构·总师 在 Issue #90 设计了 M1-M6 机制，其中 M6 quota-guard：
按任务计量云端核时消耗 + 免费额度护栏（160 核时/月）+ 异常哨兵。

本地实现语义：
  - 记录每次云端构建/测试预估核时消耗（cost 模块已能量化本地化节省）；
  - 维护月度免费额度账本（FREE_MONTHLY_CORE_MINUTES = 160）；
  - meter_consume(task_id, amount) 累计任务消耗
  - quota_status() 返回 ok/warning/over 三态，over 触发哨兵告警
  - 本地化节省（hybrid cost net_save）自动抵扣账本 -> 护栏真实反映云端实付

与云端统一口径：核·分钟（core-minutes）。
"""
import json
import os
import time

# 月度免费额度（用户实述：160 核时/月免费 + 100 核时已付费）
FREE_MONTHLY_CORE_MINUTES = 160
WARN_RATIO = 0.8          # 消耗达 80% 预警
OVER_RATIO = 1.0          # 达 100% 护栏拦截 + 哨兵告警

# 账本文件（与 batch 队列同目录）
LEDGER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".quota_ledger.json")


class QuotaGuard(object):
    """云端核时配额护栏：按任务计耗 + 月度额度账本 + 三态哨兵。"""

    def __init__(self, free_minutes=FREE_MONTHLY_CORE_MINUTES,
                 warn_ratio=WARN_RATIO, over_ratio=OVER_RATIO,
                 ledger_file=LEDGER_FILE):
        self.free_minutes = free_minutes
        self.warn_ratio = warn_ratio
        self.over_ratio = over_ratio
        self.ledger_file = ledger_file

    # ---------- 账本 ----------
    def _load(self):
        try:
            if os.path.exists(self.ledger_file):
                with open(self.ledger_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    if isinstance(d, dict) and "tasks" in d:
                        return d
        except Exception:  # noqa
            pass
        return {"monthly_used": 0.0, "localized_saved": 0.0,
                "paid_extra": 0.0, "tasks": {}, "month": time.strftime("%Y-%m")}

    def _save(self, d):
        with open(self.ledger_file, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)

    def _roll_month(self, d):
        """跨月自动滚动账本，保留上月摘要。"""
        cur = time.strftime("%Y-%m")
        if d.get("month") != cur:
            d = {"monthly_used": 0.0, "localized_saved": 0.0,
                    "paid_extra": 0.0, "tasks": {}, "month": cur,
                    "last_month": {"used": d.get("monthly_used", 0),
                                   "saved": d.get("localized_saved", 0)}}
        return d

    # ---------- 核心：计耗 ----------
    def meter_consume(self, task_id, amount, note=""):
        """记录一次云端核时消耗（核·分钟）。返回当前状态。"""
        d = self._roll_month(self._load())
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        d["monthly_used"] = round(d.get("monthly_used", 0.0) + amount, 3)
        t = d["tasks"].setdefault(task_id, {"total": 0.0, "count": 0, "note": ""})
        t["total"] = round(t.get("total", 0.0) + amount, 3)
        t["count"] = t.get("count", 0) + 1
        t["note"] = note or t.get("note", "")
        self._save(d)
        return self.quota_status()

    def credit_localized(self, amount, note="本地化节省抵扣"):
        """本地化节省自动抵扣云端账本（hybrid net_save 汇入）。

        语义：本地跑掉的 CPU 测试原本会在云端消耗核时，
        本地化后该笔云端成本为 0 -> 抵扣账本已用额度。
        """
        d = self._roll_month(self._load())
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        d["localized_saved"] = round(d.get("localized_saved", 0.0) + amount, 3)
        d["monthly_used"] = round(max(0.0, d.get("monthly_used", 0.0) - amount), 3)
        self._save(d)
        return self.quota_status()

    # ---------- 状态 ----------
    def quota_status(self):
        """三态：ok / warning / over（over 触发哨兵告警）。"""
        d = self._load()
        used = float(d.get("monthly_used", 0.0))
        ratio = used / self.free_minutes if self.free_minutes else 1.0
        if ratio >= self.over_ratio:
            state = "over"
        elif ratio >= self.warn_ratio:
            state = "warning"
        else:
            state = "ok"
        return {
            "state": state,
            "monthly_used": round(used, 3),
            "free_minutes": self.free_minutes,
            "ratio": round(ratio, 4),
            "localized_saved": round(float(d.get("localized_saved", 0.0)), 3),
            "net_used": round(max(0.0, used - float(d.get("localized_saved", 0.0))), 3),
            "month": d.get("month", time.strftime("%Y-%m")),
        }

    # ---------- 审计 ----------
    def audit(self):
        """完整账本（任务粒度 + 月度 + 上月）。"""
        return self._load()


# 便捷单例
default_guard = QuotaGuard()

