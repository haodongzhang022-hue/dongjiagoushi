# -*- coding: utf-8 -*-
"""开发持续推进能力包（DevIterationAbility · 全员能力 · Issue #74）。

开发没开发完时可持续自循环推进（不交回评审/经理），记录进度不对话，
干完统一交付给经理。见 docs/DEV_ITERATION.md。
"""
from .ability import DevIterationAbility

__all__ = ["DevIterationAbility"]
