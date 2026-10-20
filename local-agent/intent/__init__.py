# -*- coding: utf-8 -*-
"""
云端承接侧能力（intent.inbound · module inbound-take v0.1.1）
=============================================================
定位：**运行时在用户本地电脑，云端只做「承接端」**——云端的职责是
「接得住、不丢件、说清楚」，而不是把活自己跑完。

用户原话要义（Issue #177）：
  "不用运行时，而是我本地的电脑负责运行时，你承接得住配合的部分就行，
   也就是说可能是分配的任务过来，你承接之后才触发跟着任务做，
   而你现在做的接单的卡，其实是方便你接受的用的。"

因此本模块只做三件事，且**只做这三件**：
  ① 承接卡（承接凭证）：把「我接了哪件活、按什么交付形态、验什么才算完」写成
     机器可核验的结构，顺带生成人类可读的 Markdown 回评；
  ② 承接判定（接得住 / 拒接说清楚）：按任务类型决定「我做 / 我做一半 / 我不做」，
     拒绝必须给替代动作，不静默吞件；
  ③ 交接单（本地运行时契约）：真正跑的东西落成交接单交给本地 runtime 执行，
     云端**不假装跑过**——`ran_remotely` 永远是 false。
  ④ 回收核对（本地结果回传验收）：本地跑完回传结果，按验收标准判 pass/reject，
     结论走 RELAY_CARD 双通道（给下游接力卡 + 人可读回执）。

不做的事（边界，防越界）：
  - 不建云端运行时、不启动流水线跑测试（云端 CPU 贵，见 CLOUD_LOCAL_COOP.md）；
  - 不把「已发卡」当「已交付」（处置标签只有 proceed / human，没有 merge）；
  - 不静默拒接、不空口承接（拒接必须带替代动作）。

边界与既有机制的关系（不重复造轮子）：
  - `relay_card`   只管「卡有没有 @ 到人、有没有 [触发]」（格式）；
  - `bridge`       只管「本地⇄云端异步开发的句柄与回传」（跨对话/跨 PR 定位）；
  - `dispatch`     只管「派发的四层深度」（有没有真接单）；
  - **`intent.inbound` 管「交接内容本身」**：交付形态 / 验收标准 / 本地运行时契约 /
    回收核对——这是「承接得住」的实质，前面几个都不管这一层。

用法：
    from intent import inbound
    card = inbound.make_card(title=..., deliverable=..., acceptance=[...],
                             runtime="local", kind="code")
    print(inbound.render_md(card))                 # 人可读承接卡（回评用）
    job  = inbound.handoff(card, runtime="local")  # 交接单（交本地 runtime）
    rec  = inbound.collect(card, result={...})     # 本地回传 → 按验收核对
"""
from . import take  # noqa: F401

__all__ = ["take"]
__version__ = "v0.1.1"
