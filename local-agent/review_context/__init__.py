# -*- coding: utf-8 -*-
"""
评审上下文增量复用（review-context · Issue #150）
=================================================
解决用户痛点（Issue #150）：
  「现在的架构评审，如果项目较大，他其实每次复述项目是非常困难的……
   每次触发评审之后跑开发，然后评审，这样效率很慢，又触发大量的 CPU 构建和 CPU 开发的损耗。」

把「评审前每次重新复述整个项目 / 重讲大 spec」优化为**评审上下文增量复用**：
  - 项目 spec 拆成**稳定骨架**（构建一次、冻结、按摘要引用）+ **变化片段**（只传增量）；
  - 评审每轮只吃 **(冻结骨架摘要 + 本轮变化)**，不再复述全项目；
  - 内容指纹判定骨架**何时才需重算**（骨架相关来源变了才失效），否则零成本复用。

对外接口：
  - build(stable_parts, volatile_parts, prev=None)   构建评审上下文包
  - fingerprint(payload)                             内容指纹（唯一失效判据）
  - reuse_decision(prev, sources)                    能否复用冻结骨架 + 原因
  - estimate_saved_tokens(pack)                      量化省下的复述 token
  - repo_root()                                      仓库根解析（唯一事实源 · S8）

CLI：
  python -m review_context build --stable '{"a":"..."}' --volatile '{"b":"..."}'
  python -m review_context demo
"""
from . import spec, engine, paths
from .engine import (build, fingerprint, reuse_decision,
                     estimate_saved_tokens, reset_for_tests)
from .paths import repo_root

__all__ = [
    "spec", "engine", "paths",
    "build", "fingerprint", "reuse_decision",
    "estimate_saved_tokens", "reset_for_tests",
    "repo_root",
]
