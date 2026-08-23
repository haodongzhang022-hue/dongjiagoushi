# -*- coding: utf-8 -*-
"""
本地 Agent · 接力卡（relay card）
================================
与云端「接力卡」协议对齐：进度/回转/打断 持久化。

接力卡字段：
    step            当前步骤名
    role            当前角色名
    input           输入（需求/上游产物）
    output          本步输出
    status          todo / in_progress / done / blocked / reverted
    current_progress 已做到哪一步 + 卡点（打断续跑用）
    next_step       下一步
    revert_to       回转时回退到哪个步骤
    revert_reason   回转原因
"""

import json
import os
from datetime import datetime

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
CARD_FILE = os.path.join(STATE_DIR, "relay_card.json")


def _ensure_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


def new_card(req, first_step="clarify", first_role="架构·产品"):
    _ensure_dir()
    card = {
        "req": req,
        "step": first_step,
        "role": first_role,
        "input": req,
        "output": "",
        "status": "in_progress",
        "current_progress": f"流水线启动，第一步 {first_step}（{first_role}）",
        "next_step": "",
        "revert_to": "",
        "revert_reason": "",
        "history": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    save(card)
    return card


def save(card):
    _ensure_dir()
    card["updated_at"] = datetime.utcnow().isoformat()
    with open(CARD_FILE, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)


def load():
    if not os.path.exists(CARD_FILE):
        return None
    with open(CARD_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def clear():
    if os.path.exists(CARD_FILE):
        os.remove(CARD_FILE)


def log(card, message):
    card.setdefault("history", []).append(
        {"at": datetime.utcnow().isoformat(), "msg": message}
    )


def revert(card, to_step, reason):
    """回转：将当前进度回退到指定步骤。"""
    card["status"] = "reverted"
    card["revert_to"] = to_step
    card["revert_reason"] = reason
    card["step"] = to_step
    log(card, f"[回转] 退回:{to_step} / 原因:{reason}")
    save(card)


def interrupt(card, progress, next_step):
    """打断：记录续跑点，供 --resume 续跑。"""
    card["status"] = "in_progress"
    card["current_progress"] = progress
    card["next_step"] = next_step
    log(card, f"[打断] 续跑点: {progress} / 下一步:{next_step}")
    save(card)
