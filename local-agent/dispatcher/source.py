# -*- coding: utf-8 -*-
"""
调度中枢 · 事件源监听器（source）
==================================
把「事件源」（本仓库 Issue/PR/评论/驳回标记/哨兵告警 + 外部适配器插槽）统一
规范化为**标准事件对象**，供规则引擎匹配。外部事件源通过 `ExternalAdapter`
插槽接入（用户拍板：包含外部、可联网、通用解决，不局限本仓库）。

标准事件对象（event dict）：
  {
    "event_id":   "ev-<uuid>",        # 事件全局唯一 id（去重键基础）
    "event_type": "issue.open",       # 事件类型（见 _TYPE_KEYS）
    "source":     "repo",             # 事件源名（repo / 外部适配器名）
    "entity":     "标题/任务key",      # 关联实体 key
    "gid":        "tk-...",           # 关联实体的全局唯一 gid（如有）
    "detail":     {...},              # 事件详情（评论内容/状态/驳回原因…）
    "ts":         "ISO时间",
  }

`ExternalAdapter` 是扩展插槽：用户可注册任意外部事件源（GitHub/Gitee/工单系统/
webhook 轮询等），实现 `poll()` 返回一批原始事件，dispatcher 会统一 normalize。
本模块内置：`RepoPollAdapter`（本仓库 Issue/PR 状态扫描，通过 `cnb issues` CLI
或调用方注入的数据源扫描）。
"""
import uuid
from datetime import datetime


def now_iso():
    return datetime.utcnow().isoformat()


# 事件类型 key 规范化（避免不同来源同义事件漂移）
_TYPE_KEYS = {
    "issue.open": "issue.open",
    "issue_update": "issue.update",
    "issue.update": "issue.update",
    "comment": "comment",
    "issue.comment": "comment",
    "rejection": "rejection",
    "reject": "rejection",
    "sentry": "sentinel.alert",
    "sentinel": "sentinel.alert",
    "timeout": "timeout",
    "missed": "missed.scan",     # 遗漏未处理扫描
    "requirement": "requirement",  # 岗位/需求出现
}


def normalize_event(raw):
    """把一条原始事件统一规范化为标准事件对象（幂等：已规范则原样返回）。

    raw 可来自本仓库扫描或外部适配器。兼容 dict 或 (type, entity) 简写。
    """
    if isinstance(raw, dict) and "event_id" in raw and "event_type" in raw:
        return raw  # 已规范化
    if isinstance(raw, dict):
        et = _TYPE_KEYS.get(str(raw.get("event_type", raw.get("type", ""))),
                            str(raw.get("event_type", raw.get("type", "unknown"))))
        return {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "event_type": et,
            "source": raw.get("source", "repo"),
            "entity": raw.get("entity", raw.get("key", "")),
            "gid": raw.get("gid", ""),
            "detail": raw.get("detail", {}),
            "ts": raw.get("ts", now_iso()),
        }
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        et = _TYPE_KEYS.get(str(raw[0]), str(raw[0]))
        return {
            "event_id": f"ev-{uuid.uuid4().hex}",
            "event_type": et,
            "source": "repo",
            "entity": str(raw[1]),
            "gid": "",
            "detail": {},
            "ts": now_iso(),
        }
    raise ValueError(f"无法规范化事件: {raw!r}")


class ExternalAdapter:
    """外部事件源适配器插槽（用户拍板：通用解决，包含外部）。

    子类实现 `poll()` 返回原始事件 list；dispatcher 会统一 normalize 并入流。
    """

    def __init__(self, name="external"):
        self.name = name

    def poll(self):
        """轮询该外部事件源，返回原始事件 list（每项 dict）。"""
        raise NotImplementedError

    def describe(self):
        return f"{self.name}: 外部事件源适配器"


class RepoPollAdapter(ExternalAdapter):
    """本仓库事件源：通过注入的数据源（如 cnb issues）扫描 Issue/PR 状态。

    默认以 `issues_provider`（可调用，返回 open issue 列表）驱动；若未提供，
    尝试用 `cnb issues list` 拉取。适配器只负责**产出规范化前的原始事件**，
    具体判断（待审核/遗漏/驳回）交给 rules 与 reject 层。
    """

    def __init__(self, issues_provider=None, name="repo"):
        super().__init__(name)
        self._provider = issues_provider

    def _fetch(self):
        if self._provider:
            return self._provider() or []
        # 兜底：尝试调用 cnb CLI 拉取 open issues
        try:
            import subprocess
            out = subprocess.run(
                ["cnb", "issues", "list", "--state", "open"],
                capture_output=True, text=True, timeout=30,
            ).stdout
            return _parse_cnb_out(out)
        except Exception:
            return []

    def poll(self):
        """扫描本仓库 open issues，产出「待审核 / 岗位需求 / 遗漏」原始事件。"""
        events = []
        for issue in self._fetch():
            title = issue.get("title", "") if isinstance(issue, dict) else str(issue)
            state = issue.get("state", "open") if isinstance(issue, dict) else "open"
            if state != "open":
                continue
            events.append({
                "event_type": "issue.open",
                "source": self.name,
                "entity": title,
                "gid": issue.get("gid", "") if isinstance(issue, dict) else "",
                "detail": {"title": title, "state": state},
                "ts": now_iso(),
            })
        return events


def _parse_cnb_out(text):
    """把 `cnb issues list` 的文本输出解析为 dict 列表（尽力解析，失败返回空）。"""
    issues = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("status", "contentType", "page", "total", "data")):
            continue
        issues.append({"title": line})
    return issues
