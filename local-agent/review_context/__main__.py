# -*- coding: utf-8 -*-
"""评审上下文增量复用 CLI 入口：`python3 -m review_context <build|demo>`。

Issue #150 返工 S9：文档 CLI 必须真的跑通（此前只有 `review_context.cli`，
`python -m review_context` 无 `__main__` 会失败）。本入口与 `review_context.cli`
同源，不重复实现。

从仓库根运行（PYTHONPATH 指向 local-agent，与其它 local-agent 模块一致）：
  PYTHONPATH=local-agent python3 -m review_context demo
  PYTHONPATH=local-agent python3 -m review_context build --stable '{...}' --volatile '{...}'
"""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
