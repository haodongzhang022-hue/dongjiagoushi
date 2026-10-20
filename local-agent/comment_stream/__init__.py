# -*- coding: utf-8 -*-
"""
评论流统一读取入口（comment_stream · Issue #166）
================================================
把「读 Issue/PR 评论流」从**散落的裸调**收敛为一个**默认读全量**的入口，杜绝
CNB 评论接口默认 `page_size=10` 造成的**静默截断**——截断后读到的"最新一条"
其实是 N 条之前的一条，直接污染「上游是否已回执 / 评审链是否悬空」这类
**派发前置判据**，引发无效派发与无谓构建损耗（PR #161 真实踩坑）。

设计理念（对齐 AGENTS.md「不靠自觉，靠机制」）：
  - **默认全量**：显式带 `page_size`，必要时按 `page` 翻页取尽，调用方不必记得加参数；
  - **可核验元信息**：返回体带 `count` / `pages` / `has_more` / `complete`，
    上层能判断"读全了没有"，而不是看条数"看起来正常"就当真；
  - **防退化断言**：裸调（不带分页）在夹具上必然读不全 → 断言 RED，把坑锁死；
  - **纯读取侧加固**：不改 CNB 接口行为、不改派发判定规则。

用法：
    from comment_stream import read_comments, comment_meta
    r = read_comments(kind="pulls", number=161, repo="dongdongxiaozu/dongjiagoushi")
    r["comments"]; r["count"]; r["complete"]
    comment_meta(r)          # 供派发判据消费的紧凑元信息
    read_comments(..., transport=fake)   # 注入传输层，离线可测

CLI：
    python -m comment_stream --kind pulls --number 161 [--json]
"""
from .reader import (
    READER, Transport, HttpTransport, PagedTransport,
    NaiveTransport,  # 裸调（不分页）参照实现，仅供防退化断言
    read_comments, comment_meta, has_receipt,
)

__all__ = [
    "READER", "Transport", "HttpTransport", "PagedTransport", "NaiveTransport",
    "read_comments", "comment_meta", "has_receipt",
]
