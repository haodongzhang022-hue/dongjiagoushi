# -*- coding: utf-8 -*-
"""
monitor_bi · 工作过程监控 + 可视化 BI 大屏（模块入口）
====================================================
模块：monitor-bi (v0.1.0, type=init, Issue #55)

提供**工作过程监控 + 可视化 BI 大屏**能力：以 agent/岗位/对话/项目 四维口径
统计体系工作量、token 消耗、总产出、对话文字量、代码变化量，并做异常监控
（没工作/异常重复/分工失衡），形态为可视化 BI 大屏（人类俯瞰）。

对外能力统一收口到显式公开接口 `MonitorBI`（__init__ 导出 + docstring + 单测）：
  - workload_4d(dim)            四维统计工作量
  - token_summary(dim, trend)   token 四维聚合 + 趋势
  - code_changes(by)            代码变化统计
  - anomaly_scan()              异常扫描（复用 sentinel + 新增分工失衡）
  - render()                    生成 BI 大屏 Markdown

复用现有 data 层（repository/schema）+ sentinel 引擎，不重造核心能力。
"""
from monitor_bi.stats import workload_4d, status_summary, drill_down, DIMS
from monitor_bi.token import token_summary, token_trend, token_share_imbalance, estimate_tokens
from monitor_bi.code import code_changes, code_total, code_by_project, code_by_agent
from monitor_bi.anomaly import anomaly_scan, sentinel_anomalies, imbalance_anomalies
from monitor_bi.render import render, render_to_file


class MonitorBI:
    """工作过程监控 + 可视化 BI 大屏 · 统一入口。

    用法：
        bi = MonitorBI()
        bi.workload_4d("agent")          # 四维统计
        bi.token_summary("project")       # token 聚合
        bi.code_changes()                 # 代码变化
        bi.anomaly_scan()                 # 异常扫描
        bi.render()                       # 生成 BI 大屏
    """

    def __init__(self):
        pass

    # ---- M1 四维统计 ----
    @staticmethod
    def workload_4d(dim="agent"):
        return workload_4d(dim)

    @staticmethod
    def status_summary(dim="agent"):
        return status_summary(dim)

    @staticmethod
    def drill_down(dim, key, limit=50):
        return drill_down(dim, key, limit)

    # ---- M2 token 分析 ----
    @staticmethod
    def token_summary(dim="agent", trend=False):
        return token_summary(dim, trend)

    @staticmethod
    def token_trend(bucket="hour"):
        return token_trend(bucket)

    # ---- M3 代码变化 ----
    @staticmethod
    def code_changes(by=("project", "agent")):
        return code_changes(by)

    @staticmethod
    def code_total():
        return code_total()

    # ---- M4 异常监控 ----
    @staticmethod
    def anomaly_scan(thresholds=None):
        return anomaly_scan(thresholds)

    # ---- M5 可视化 ----
    @staticmethod
    def render():
        return render()

    @staticmethod
    def render_to_file(path=None):
        return render_to_file(path)


__all__ = [
    "MonitorBI",
    "workload_4d", "status_summary", "drill_down", "DIMS",
    "token_summary", "token_trend", "token_share_imbalance", "estimate_tokens",
    "code_changes", "code_total", "code_by_project", "code_by_agent",
    "anomaly_scan", "sentinel_anomalies", "imbalance_anomalies",
    "render", "render_to_file",
]
