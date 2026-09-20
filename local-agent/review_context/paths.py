# -*- coding: utf-8 -*-
"""仓库根解析 · 唯一事实源（S8 修正）

评审相关模块（评审角色 `roles/reviewer.py` / 评审段调度器 `review_cycle/cycle.py`）
都要用「仓库根」做变更感知选测（`git diff` 的 cwd）。此前两处各自解析、
**语义分裂**：调度器解析到仓库根，评审角色解析到 `local-agent`（多/少一层 dirname）。
本模块把解析收口到一处，杜绝再次分裂。

本文件位置 `<repo>/local-agent/review_context/paths.py` → 上溯三级 = 仓库根。
"""
import os


def repo_root():
    """仓库根目录（与 cwd 无关，不依赖调用方所在目录）。"""
    return os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))


__all__ = ["repo_root"]
