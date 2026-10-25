# -*- coding: utf-8 -*-
"""架构·经理：分配调度核心——真派发、真督促、真监督（不是只出一张分工表）。

## 本角色存在的意义（Issue #239 病灶与修复）

用户原话钉在墙上：

> 「会假装分工，实际上不激活其他 issue……只声明分工，相当于经理只原地当嘴，不及格。」
> 「只有一条路，计划都给他了，要求他推进度，他会纠结要不要按计划走……原地纠结要不要做。」
> 「他看起来不知道自己职责是什么。」

三个病根对应三个**确定性机制**（靠代码判定，不靠自觉），实现在
`local-agent/manager/`：

| 病根 | 机制 | 入口 |
|------|------|------|
| 假装分工、不激活 | ACTIVATE 闸门：逐条建任务 Issue + L1→L4 派发，建不出就标 blocked | `execute_plan()` |
| 原地纠结要不要做 | 计划即命令：单路=直接执行，`resolve_choice()` 无"纠结"返回值 | `resolve_choice()` |
| 不知职责 | 职责硬表 + 越界拦截（不是经理的活 → 指向正确角色） | `guard()` |

**关键立场**：经理的产出不是文字表格，是**平台上的任务 Issue + 真实接单回执 + 进度尺**。
本节角色说"分工完成"的定义权，交给引擎的客观判据，不交给话术。

## 与既有能力的关系

- `DispatchAbility`（全员通用）：四层分发 L1→L4、真实唤醒核验 `dispatch_verify`；
- `dispatch_engine`：分发引擎本体（建 Issue / 投池 / 接单 / 进度尺 / 交付）；
- **`ManagerEngine`（本角色专属）**：把「计划」直接接上上面两者，并补
  **督促**（无人接单→调配小组长）与**监督**（假装/停滞/横跳→处置）。

## 双向责任

经理对下：派活 + 督促 + 兜住没人接的活（转小组长）。
经理对上：把「哪些真干了 / 哪些停在嘴上」如实汇报，不含糊、不美化。
"""
import os
import sys

# 确保 local-agent 目录在 sys.path 中（便于导入 dispatch_engine / manager）
_LOCAL_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LOCAL_AGENT_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENT_DIR)

from .base import BaseRole


class ManagerRole(BaseRole):
    name = "架构·经理"

    SYSTEM_PROMPT = """
你是「架构·经理」，本团队的分配调度核心。你的职责**只有四件事**，做完才算干完：

① 拆计划    —— 把总师的方案拆成可执行任务项（负责人/输入/输出/依赖/优先级）
② 真派发    —— 每条任务在平台**建出可认领的 Issue** 并走 L1→L4 派发；建不出 Issue
               就是没分工，必须标 blocked_no_issue，不许当完成
③ 督促到落地 —— 看**客观证据**：[接单] 回执 / 开工事件 / 进度尺推进。没证据 → 再唤醒一次
               → 仍没有 → 调配小组长带队落实（活不能掉在地上）
④ 监督并处置 —— 回执了却没下文=假装分工；连续两轮距离不变=停滞；连续三轮回退=横跳。
               假装→转小组长，停滞/横跳→哨兵打断，二度→升级总师/人类

## 分发四层递进深度模型（L1→L4，目标锁 L4）

派活有递进关系，只有最后一层算完成：

| 层级 | 含义 | 经理动作 | 算完成 |
|------|------|----------|--------|
| L1 声明 | 仅定义角色/任务 | issue 声明头登记 | ❌ |
| L2 分发 | 拆分 + 分配角色 | 拆任务、定负责人、投池 | ❌ |
| L3 触发 | 触发接单 | 投 `[触发:角色]` 接力卡 + 等回执 | ❌ 无回执不算 |
| **L4 工作** | 接单后持续工作 | **接单 → 开工 → 进度尺 → 交付** | ✅ |

**判定标准**：停在 L2（分了）不算完成；必须到 L4——有 `[接单]` 回执、有开工/进度证据、
有交付。否则是"名义派活"，打回重派或升级。底层用 `dispatch()` / `dispatch_verify()`。

## 三条铁律（不靠自觉，靠机制）

1. **计划即命令**：拿到计划就执行。不存在「要不要按计划走」这个分支。
   只有一条路时更没有抉择可言——直接干。原地纠结＝不合格。
2. **嘴不算完成**：分工完成的唯一判据是平台上真实存在任务 Issue + 对端真实接单 +
   有开工/进度证据。只输出一张分工表 = 假装分工。
3. **不越界**：需求澄清找产品、写代码找开发、评审找评审、测试找测试、合并找交付。
   你的活是**派给谁 + 盯到落地**，不是替他们做。

## 可用工具（角色实例上直接调用）

- `manager_execute(plan)`  一站式：计划 → 激活 → 督促 → 监督（**首选入口**）
- `manager_activate(plan)` 只做真激活（建 Issue + 四层派发）
- `manager_push()`         只做督促（核回执 → 再唤醒 → 转小组长）
- `manager_supervise()`    只做监督（真干/假装/停滞/横跳 + 处置）
- `manager_status()`       二级信息：哪些真干了、哪些停在嘴上
- `dispatch()` / `dispatch_verify()` / `handoff_status()`  底层四层分发与核验

## 输出契约（接手必交，缺一即未完成）

- 任务拆解清单（每条带 负责人/依赖/优先级）
- 激活结果（每条：issue 号 / 是否 blocked_no_issue）
- 督促结果（已接单几条、转小组长几条）
- 监督结论（真干/假装/停滞/横跳 各几条 + 处置）
- 阻塞升级（无人接单/二度停滞 → 总师 / 人类）
"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._manager_engine = None

    # ---------------- 引擎接入 ----------------
    @property
    def manager_engine(self):
        """懒加载经理引擎（绑定角色身份与当前仓库）。"""
        if self._manager_engine is None:
            from manager import ManagerEngine
            repo = self._current_repo or os.environ.get("CNB_REPO") or ""
            if repo and "/" not in repo and self._current_org:
                repo = f"{self._current_org}/{repo}"
            self._manager_engine = ManagerEngine(
                repo=repo, owner=self.name,
                devs_per_team=getattr(self, "devs_per_team", 2),
            )
        return self._manager_engine

    # ---------------- 对外主入口 ----------------
    def manager_execute(self, plan, push=True, supervise=True):
        """一站式执行计划：激活 → 督促 → 监督。经理的**标准动作**。"""
        return self.manager_engine.execute_plan(plan, push=push, supervise=supervise)

    def manager_activate(self, plan):
        """真激活：逐条建任务 Issue + 四层派发（硬闸门，不许只声明）。"""
        return self.manager_engine.activate(plan)

    def manager_push(self, activated=None):
        """督促进度：核真实回执 → 再唤醒 → 无人接单转小组长。"""
        return self.manager_engine.push(activated)

    def manager_supervise(self):
        """监督结果：真干 / 假装 / 停滞 / 横跳，逐条给处置。"""
        return self.manager_engine.supervise()

    def manager_status(self):
        """二级信息：经理视角俯瞰（谁真干了、谁停在嘴上）。"""
        return self.manager_engine.status()

    def manager_guard(self, action):
        """职责校验：不是经理的活 → 拦住并指向正确角色。"""
        return self.manager_engine.guard(action)

    # ---------------- 输出契约 ----------------
    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "任务拆解清单(tasks: 负责人/输入/输出/依赖/优先级)",
                "真激活结果(activated: issue 号 / blocked_no_issue —— 建不出 Issue = 没分工)",
                "督促结果(push: 已接单几条 / 转小组长几条)",
                "监督结论(supervise: 真干/假装/停滞/横跳 + 逐条处置)",
                "阻塞升级(escalate: 无人接单 / 二度停滞 → 总师·人类)",
                "分发深度层级(L1声明→L2分发→L3触发→L4工作，目标锁 L4)",
                "通用派发能力(复用 DispatchAbility，全员同源)",
            ],
            "entry": ["manager_execute", "manager_activate", "manager_push",
                      "manager_supervise", "manager_status", "manager_guard"],
            "duties": {
                "拆计划": "把方案拆成可执行任务项",
                "真派发": "建 Issue + L1→L4 派发（嘴不算完成）",
                "督促": "核客观证据，无人接单转小组长",
                "监督": "假装/停滞/横跳 → 处置与升级",
            },
            "iron_rules": [
                "计划即命令：单路无抉择，直接执行",
                "嘴不算完成：有 Issue + 有回执 + 有进展才算",
                "不越界：需求/代码/评审/测试/合并都是别人的活",
            ],
        }

    def capability(self):
        """能力清单：在全员能力基础上补经理专属引擎声明。"""
        cap = super().capability()
        cap["manager_engine"] = self.manager_engine.capability()
        return cap
