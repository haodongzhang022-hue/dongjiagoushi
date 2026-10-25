# -*- coding: utf-8 -*-
"""
执行体槽位调度（slot）· 池子取件顺序 + 可配队列 + 领取后自愈
=============================================================
用户原话（PR #247，2026-10-25）：

  「他不止一次这样了，这个池子让他有个近因效应吧，最新的优先领取，这样即使卡住
    也不会一直卡，最多卡一下，以及加长队列，然后领取一个后，尝试把其他接上，
    这样自动修了。」

抽象出三条**确定性**规则（不靠自觉，靠取件顺序 + 自愈判定）：

  ① **近因优先（recency-first / LIFO）**：取件按「最新入队优先」。
     旧的 FIFO 让一个卡死的老任务把后面全堵住——最新优先后，**卡住的只会卡一次**，
     下一次取件就跨过它（它留在队里等自愈/超时），后面的活照常出。
  ② **队列要拉长**（`queue_capacity`）：小队列 + 阻塞任务 = 池子立刻见底。
     加长队列让「跨过卡住的那一个」有位置可放，不至于一堵就空。
  ③ **领取后自愈接回（pick → repair rest）**：领走一件活之后，**顺带把同样被卡住的
     其它活重新接上**（重新入队/重触发），不需要人去一个个捞——「这样自动修了」。

与现有零件的关系（不重复造）：
  - 本模块只管「池子里取谁、取完之后怎么接回」；
  - 真实的排队/唤醒/接单回执仍走 `dispatcher`（事件→规则→队列→gid 路由、
    `dispatch_verify` 校验 `[接单]`）；`slot` 是**执行体槽位分配层**，可被
    dispatcher / 平台适配层调用（`reserve/do_get/repair_rest`）。
  - 与 `AGENTS.md` 的「任务驱动弹性扩缩容」「分发递进深度 L1→L4」同向：
    这里补的是「并发额度被卡死任务长期占住」这个具体病根。

对外入口：
  - `SlotPool(capacity=...)`   槽位池（容量 + 近因优先取件 + 领取后自愈）
  - `enqueue/do_get/reserve/repair_rest/overview` 池操作
  - `pool_from_config()`       从 `.cnb.yml` 的 `npc_task.slot_pool` 读配置（单一事实源）
  - `cli`                      `python -m slot ...` 俯瞰/自测

对齐 Issue #271 / docs/NPC_SLOT_POOL.md；测试 local-agent/tests/test_slot_pool.sh。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .pool import (  # noqa: E402
    SlotPool, Task, DEFAULTS, pool_from_config, load_npc_pool_config,
)

__all__ = ["SlotPool", "Task", "DEFAULTS", "pool_from_config", "load_npc_pool_config"]
