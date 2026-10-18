# -*- coding: utf-8 -*-
"""dsh 适配辅助包（dsh_adapter）——供 dsh-adapter 桥接的真实 Python 侧能力。

本包是 **Python 侧版本事实源**，与 `dsh-adapter/src/compat.ts`（TS 侧）保持同一
版本矩阵/API 面表；两端各自可独立跑（TS 在 dsh 内、Python 在 local-agent/CI 内），
避免"只有一端才知道兼容性"的盲区（对齐 AGENTS.md 解耦式模块：接口显式化）。

注意：不在 `__init__` 里 eager import `compat`，避免 `python -m dsh_adapter.compat`
触发 runpy 重复导入告警（模块既可作包内导入、也可作 `-m` 入口）。
"""
__all__ = ["compat"]
