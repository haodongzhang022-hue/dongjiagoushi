# -*- coding: utf-8 -*-
"""
上位机 · 状态机引擎（state_machine）
=====================================
把 AGENTS.md / SKILL.md 中「接力链路状态流转」从**文档约定**升级为**可运行的
显式状态机**，让「上位机（调度主控）」能精确管理每台「机器角色（agent）」的
任务状态，杜绝非法流转、提供可观测、可测试、可续跑的状态能力。

核心能力：
  1. **节点状态机（机器角色任务）**：一个任务实例拥有独立状态卡，状态在
     合法转移表内流转，非法转移直接报错拒绝，避免"乱跳状态"。
  2. **显式转移表**：`[触发]/[回转]/[打断]/[复评]/[放行]` 等协议动作映射到
     确定的合法转移，从"口头约定"变成"机器强制"。
  3. **可观测**：每次转移留痕（谁/何时/从哪到哪/原因），供测试复现与人工俯瞰。
  4. **与既有 store 对接**：默认复用 `scale/store.py` 的分片状态存储，状态卡
     落 `state/{card_id}.json`，与接力卡协议对齐。

状态集说明（机器角色生命周期）：
  pending     已创建待启动（调度主控分配）
  in_progress 正在执行（角色接手 / 触发）
  done        正常完成（信号灯通过 / 放行）
  reverted    被打回（[回转]），等待返工
  retry       返工重跑中（被打回角色重新触发）
  interrupted 被[打断]，留有续跑点（当前进度）
  blocked     阻塞（回转超 3 次 / 超时未续跑），上报总师/人类
  paused      CP 闸门暂停，等待人类放行
"""
import json
import threading
from datetime import datetime

try:
    from ..scale import store as _store  # 复用规模层分片状态存储
    _STORE_OK = True
except ImportError:  # 兼容 local-agent 作为 sys.path 根目录直接 import engine
    try:
        from scale import store as _store
        _STORE_OK = True
    except ImportError:
        _store = None
        _STORE_OK = False

# ---------------------------------------------------------------
# 状态集与合法转移表
# ---------------------------------------------------------------
STATES = [
    "pending", "in_progress", "done", "reverted",
    "retry", "interrupted", "blocked", "paused",
]

# 合法转移表（行=当前状态，值=允许转移到的目标状态集合）
# 由 AGENTS.md / SKILL.md 的接力链路 + 回转/打断协议推导而来。
TRANSITIONS = {
    "pending":      {"in_progress", "blocked"},            # 启动 / 因故不上场
    "in_progress":  {"done", "reverted", "interrupted", "paused", "blocked"},  # 完成/被打回/被打断/暂停/阻塞
    "reverted":     {"retry", "blocked"},                  # 返工重跑 / 超过回转上限
    "retry":        {"in_progress", "done", "reverted"},   # 再次执行 / 完成 / 仍不达标再打回
    "interrupted":  {"in_progress", "paused", "blocked"},  # 续跑 / 等闸门 / 长时间中断
    "paused":       {"in_progress", "blocked"},            # 人类放行续跑 / 永久阻塞
    "blocked":      {"in_progress", "paused"},             # 人工介入后恢复 / 转暂停复核
    "done":         {"in_progress", "reverted"},           # 复评被翻案重开 / 下游复审打回
}


def is_valid_transition(cur, nxt):
    """判断 cur -> nxt 是否为合法转移。"""
    return nxt in TRANSITIONS.get(cur, set())


# ---------------------------------------------------------------
# 状态机运行时
# ---------------------------------------------------------------
class StateMachine:
    """一台机器角色的状态机实例。绑定到某张状态卡（card_id）。

    用法：
      sm = StateMachine("dev_task_3")
      sm.start()                # pending -> in_progress
      sm.complete()             # in_progress -> done
      sm.revert(reason=...)     # done -> reverted
      sm.retry()                # reverted -> retry
    """

    def __init__(self, card_id, backend=None, initial="pending"):
        self.card_id = card_id
        self._backend = backend or _store
        # 已有状态卡则沿用其当前状态，否则初始化为 initial
        existing = self._backend.get(card_id)
        if existing and existing.get("status"):
            self._status = existing["status"]
        else:
            self._status = initial
            self._backend.new_card(card_id, status=initial, machine="state_machine")

    @property
    def status(self):
        return self._status

    def _transition(self, target, action, reason="", actor=""):
        if not is_valid_transition(self._status, target):
            raise ValueError(
                f"[状态机] 非法转移：{self.card_id} 从 '{self._status}' -> '{target}' "
                f"不在合法转移表内（动作={action}）。"
            )
        _from = self._status
        self._status = target
        self._backend.update(
            self.card_id,
            status=target,
            last_action=action,
            last_reason=reason,
            last_actor=actor,
        )
        self._backend.append_log(
            self.card_id,
            f"[状态机] {action}: {_from} -> {target}"
            + (f" (原因:{reason})" if reason else "")
            + (f" (执行:{actor})" if actor else ""),
        )
        return {"from": _from, "to": target, "action": action}

    # ---- 语义化动作封装（对应接力协议）----
    def start(self, actor="", reason=""):
        """启动：pending -> in_progress（[触发] 接手）"""
        return self._transition("in_progress", "触发/start", reason, actor)

    def complete(self, actor="", reason=""):
        """完成：in_progress -> done（信号灯通过 / 放行）"""
        return self._transition("done", "通过/complete", reason, actor)

    def revert(self, reason, actor="", retries_left=2):
        """打回：done/in_progress -> reverted（[回转]）"""
        tr = self._transition("reverted", "回转/revert", reason, actor)
        self._backend.update(self.card_id, retries_left=retries_left)
        return tr

    def retry(self, actor="", reason=""):
        """返工重跑：reverted -> retry（被打回角色重新触发）"""
        return self._transition("retry", "返工/retry", reason, actor)

    def interrupt(self, checkpoint="", actor="", reason=""):
        """打断：in_progress -> interrupted（[打断]，须留续跑点）"""
        tr = self._transition("interrupted", "打断/interrupt", reason, actor)
        self._backend.update(self.card_id, checkpoint=checkpoint)
        return tr

    def resume(self, actor="", reason=""):
        """续跑：interrupted/paused/blocked -> in_progress"""
        return self._transition("in_progress", "续跑/resume", reason, actor)

    def pause(self, actor="", reason=""):
        """CP 闸门暂停：in_progress -> paused（等待人类放行）"""
        return self._transition("paused", "暂停/pause", reason, actor)

    def block(self, actor="", reason=""):
        """阻塞：任意可转态 -> blocked（超时未续跑 / 回转超限），上报"""
        return self._transition("blocked", "阻塞/block", reason, actor)

    def peek(self):
        """读取当前状态卡（含历史、续跑点等），供人工俯瞰。"""
        return self._backend.get(self.card_id)


def new_machine(card_id, initial="pending", backend=None):
    """便捷工厂：创建一个状态机并返回 (machine, card)。"""
    sm = StateMachine(card_id, backend=backend, initial=initial)
    return sm, sm.peek()
