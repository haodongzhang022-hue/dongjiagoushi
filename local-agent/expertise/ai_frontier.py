# -*- coding: utf-8 -*-
"""
AI 能力前沿注册表（expertise.ai_frontier）
==========================================
用户要求的第二个通用模块：**「了解当前 AI 的发展和下一步能解决的问题」**，
据此**明确帕累托前沿的线**，而不是笼统假设架构师全能。

它解决一个具体失真：**能力边界是时间相关的**。同一个需求，2024 年「做不了」，
2026 年可能「便宜可靠」，2027 年可能「商品化」——如果不带版本、不带日期地把
能力写死，架构判断就会基于陈旧认知。

因此本模块要求每条能力声明：
  - `state`：frontier（前沿可达）/ mainstream（主流可靠）/ commodity（商品化便宜）
            / emerging（萌芽，风险高）/ blocked（当前不可行，及原因）
  - `dated_at` + `source`：**时效性硬约束**（ifold 在 freshness.FRESHNESS_SPECS 的
    ai_model / ai_framework 上限内），过期即判 stale，不得用于「能做」的结论；
  - `evidence`：外部验证水平（benchmark / 生产验证 / 论文）。

数据源：`data/ai-frontier.yaml`（**运行时数据，不是代码**，可随 AI 进展持续更新）。
判定逻辑在本文件（确定性），数据在 yaml（易更新），两者解耦。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from . import freshness

_SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_AGENT = os.path.dirname(_SPEC_DIR)
_REPO_ROOT = os.path.dirname(_LOCAL_AGENT)
DEFAULT_DATA_PATH = os.path.join(_REPO_ROOT, "data", "ai-frontier.yaml")

VALID_STATES = ("frontier", "mainstream", "commodity", "emerging", "blocked")


def _parse_yaml(path):
    """读取 yaml；优先 pyyaml，缺失时用仓库既有的极简兜底（不新增依赖）。"""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _minimal_yaml(text)


def _minimal_yaml(text):
    """极简 yaml 兜底：只支持本数据文件用到的 `key: value`、`- name:` 列表形态。

    目的：让本模块在**零第三方依赖**环境下仍可判 unknown 而不是崩溃
    （CI 容器/其它机器未必装 pyyaml）。解析不完整时由上层按 unknown 处置。
    """
    root = {"capabilities": []}
    current = None
    list_key = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = {"name": stripped.split(":", 1)[1].strip()}
            root["capabilities"].append(current)
            list_key = None
            continue
        if current and ":" in stripped:
            key, val = stripped.split(":", 1)
            key, val = key.strip(), val.strip()
            if val == "":
                list_key = key
                current[key] = []
            else:
                current[key] = val.strip('"').strip("'")
                list_key = None
            continue
        if current is not None and list_key and stripped.startswith("- "):
            current[list_key].append(stripped[2:].strip().strip('"').strip("'"))
            continue
        if indent == 0 and ":" in stripped:
            key, val = stripped.split(":", 1)
            root[key.strip()] = val.strip().strip('"').strip("'")
    return root


class AIFrontier:
    """AI 能力前沿注册表句柄。"""

    def __init__(self, path=None):
        self.path = path or DEFAULT_DATA_PATH
        self.error = None
        self.data = {}
        self.capabilities = []
        self._load()

    def _load(self):
        try:
            if not os.path.exists(self.path):
                self.error = f"能力前沿注册表不存在：{self.path}"
                return
            raw = _parse_yaml(self.path)
            self.data = raw or {}
            caps = raw.get("capabilities") or []
            self.capabilities = [c for c in caps if isinstance(c, dict) and c.get("name")]
            if not self.capabilities:
                self.error = "注册表无有效 capability 条目"
        except Exception as exc:  # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def available(self):
        return bool(self.capabilities)

    def status(self):
        return {
            "available": self.available,
            "path": self.path,
            "count": len(self.capabilities),
            "version": self.data.get("version"),
            "updated_at": self.data.get("updated_at"),
            "error": self.error,
        }

    def _norm(self, name):
        return (name or "").strip().lower().replace(" ", "")

    def capability_at(self, name, now=None):
        """查某能力在**当前时点**的状态（含时效性判定）。"""
        target = self._norm(name)
        for cap in self.capabilities:
            names = [cap.get("name")] + list(cap.get("aliases") or [])
            if target in [self._norm(n) for n in names if n]:
                state = (cap.get("state") or "").strip().lower()
                dated = cap.get("dated_at")
                fresh = freshness.assess(
                    {"kind": cap.get("kind") or "ai_model",
                     "source": cap.get("source"),
                     "dated_at": dated},
                    now=now,
                )
                # 陈旧/无日期的能力声明**不得**支撑「能做」的结论
                usable = fresh.get("usable", False) and state in VALID_STATES
                if not usable and state in ("frontier", "mainstream", "commodity"):
                    verdict = "unverified"
                elif state == "blocked":
                    verdict = "blocked"
                elif state in ("emerging",):
                    verdict = "risky"
                elif usable:
                    verdict = "feasible"
                else:
                    verdict = "unverified"
                return {
                    "found": True,
                    "name": cap.get("name"),
                    "state": state if state in VALID_STATES else "unknown",
                    "verdict": verdict,
                    "date_at": dated,
                    "source": cap.get("source"),
                    "freshness": fresh,
                    "next_problem": cap.get("next_problem"),
                    "evidence": cap.get("evidence") or [],
                    "note": cap.get("note"),
                }
        return {
            "found": False,
            "verdict": "unknown",
            "reason": f"能力前沿注册表未收录 {name!r}：判不出来即 unknown，不得默认「能做」",
        }

    def solve_candidates(self, now=None):
        """「下一步能解决什么问题」——列出可被架构利用的前沿能力。"""
        out = []
        for cap in self.capabilities:
            res = self.capability_at(cap.get("name"), now=now)
            if res.get("verdict") in ("feasible", "risky"):
                out.append({
                    "name": res["name"],
                    "state": res["state"],
                    "verdict": res["verdict"],
                    "next_problem": res.get("next_problem"),
                })
        return out

    def stale_report(self, now=None):
        """陈旧/无日期的能力声明清单（供定期复核）。"""
        stale = []
        for cap in self.capabilities:
            res = self.capability_at(cap.get("name"), now=now)
            if res.get("freshness", {}).get("tier") in ("stale", "undated", "unknown"):
                stale.append({
                    "name": res.get("name"),
                    "tier": res.get("freshness", {}).get("tier"),
                    "reason": res.get("freshness", {}).get("reason"),
                })
        return stale
