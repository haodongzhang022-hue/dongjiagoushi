# -*- coding: utf-8 -*-
"""架构·经理：分配调度核心（把架构方案拆解为可执行任务，分配到角色并跟踪进度）。

本角色是「产品经理沟通为开始 → 架构师为设计核心 → 经理为分配调度核心」链路中的
分配调度核心：架构·总师给出方案后，由架构·经理负责任务拆解、角色分配、依赖编排、
进度跟踪与阻塞升级，让下游执行角色（开发/评审/对齐/测试）各司其职、不跑偏。

**核心升级（Issue #33 用户拍板）**：分发不只是"分了就完事"，而是有递进关系的
四层深度——**要的是最深层的"接单后继续工作"（L4）**。详见 docs/DISPATCH_DEPTH.md。
与 settings.yml / SKILL.md 中的「架构·经理」人设同源。

**派发能力全员化（Issue #33 用户继续拍板）**：派发工作是高频复用的模块能力，
已抽象为通用能力 `DispatchAbility` 并挂载到所有角色基类（BaseRole）——本角色
直接复用该通用能力（dispatch()/dispatch_depth()），同时作为分配调度核心对外
保持「经理统一协调」的职责。每个 agent 都具备派发能力 + 使用规则 + 时机，
团队构成真正可协作的体系（而非散兵）。
"""
import os
import sys

# 确保 local-agent 目录在 sys.path 中（便于导入 dispatch_engine）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from .base import BaseRole


class ManagerRole(BaseRole):
    name = "架构·经理"

    SYSTEM_PROMPT = """
你是「架构·经理」，本团队的分配调度核心。接手必交：
- 任务拆解（把架构·总师的方案拆成可执行任务项）
- 角色分配（每个任务项：负责人 / 输入 / 输出 / 依赖 / 优先级）
- 调度编排（并行/串行、关键路径、资源冲突预警）
- 进度跟踪（status: todo/in_progress/blocked/done + 阻塞升级）
- 分发深度层级（L1声明/L2分发/L3触发/L4工作，目标锁L4，验收口径=走到L4，不以分了为终点）
- 接单回执确认（[接单] + 开工 + 进度尺推进 + 交付）

**派发能力全员化（通用能力）**：
你通过 BaseRole 默认具备通用派发能力 `DispatchAbility`，与所有角色同源。
你作为分配调度核心，统一协调跨岗位派发；其他 agent 也能在自己的职责域内派发子任务。
派发四层深度闭环（四层递进深度模型）：L1声明→L2分发→L3触发→L4工作交付，目标锁 L4。

使用方式：
- `dispatch(repo, assignments)` → 四层分发一站式（L1→L4）
- `accept(task_key, agent_id, ...)` → 被派发时接单回执
- `track_progress(...)` → 进度尺推进（供哨兵收敛判定）
- `deliver(...)` → 向上交付
"""

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "任务拆解清单(tasks)",
                "角色分配(assignment: 负责人/输入/输出/依赖/优先级)",
                "调度编排(schedule: 并行/串行/关键路径)",
                "进度跟踪(status: todo/in_progress/blocked/done + 阻塞升级)",
                "分发深度层级(L1声明/L2分发/L3触发/L4工作，目标锁L4，验收口径=走到L4，不以分了为终点)",
                "接单回执确认([接单] + 开工 + 进度尺推进 + 交付)",
                "通用派发能力(复用 DispatchAbility，全员同源，可派发可接单)",
            ],
        }

    # dispatch / dispatch_depth 由 BaseRole 通用派发能力提供（保持兼容，无需重复实现）
    # 如需覆盖经理特有逻辑，可在此 override
