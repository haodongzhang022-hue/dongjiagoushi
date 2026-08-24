# -*- coding: utf-8 -*-
"""
规模伸缩层 · 状态分片存储（store）
==================================
当前 relay.py 用**单个** `relay_card.json` 承载整条流水线的进度，只能支撑
「单实例串行」协作；一旦并发 agent 数上升（几十→几百→几千），单文件读写
会变成热点、且不同 agent 状态互相覆盖，无法支撑大规模协作。

本模块把「接力卡」升级为**按 agent 分片**的状态存储：

  - 每个 agent（角色实例 / 小组 / 子任务）拥有独立的 card_id；
  - 状态按 `state/{card_id}.json` 分文件落盘（可替换为内存/Redis/MQ 后端）；
  - 提供 `get/set/update/append_log` 等原子读写接口，与 relay.py 协议对齐；
  - 保留 `relay.py` 作为「单例接力卡」的向后兼容入口。

后端抽象：
  - filesystem：默认，按 card_id 分文件（开发/单机可用）
  - memory：进程内 dict（高并发高频读写，可配合线程池）
  - redis：预留（大规模分布式时启用，需 redis 依赖）
通过 `STATE_BACKEND` 环境变量切换。
"""
import json
import os
import threading
from datetime import datetime

STATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state"
)
_BACKEND = os.environ.get("STATE_BACKEND", "filesystem")

# 内存后端用的进程内存储（+锁）
_mem_store = {}
_mem_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(STATE_DIR, exist_ok=True)


# ---------- 后端：内存 ----------
def _mem_read(card_id):
    with _mem_lock:
        return json.loads(json.dumps(_mem_store.get(card_id))) if card_id in _mem_store else None


def _mem_write(card_id, data):
    with _mem_lock:
        _mem_store[card_id] = json.loads(json.dumps(data))


def _mem_del(card_id):
    with _mem_lock:
        _mem_store.pop(card_id, None)


def _mem_list():
    with _mem_lock:
        return list(_mem_store.keys())


# ---------- 后端：文件系统（按 card_id 分文件）----------
def _fs_path(card_id):
    return os.path.join(STATE_DIR, f"{card_id}.json")


def _fs_read(card_id):
    p = _fs_path(card_id)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _fs_write(card_id, data):
    _ensure_dir()
    with open(_fs_path(card_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _fs_del(card_id):
    p = _fs_path(card_id)
    if os.path.exists(p):
        os.remove(p)


def _fs_list():
    _ensure_dir()
    return [
        f[:-5]
        for f in os.listdir(STATE_DIR)
        if f.endswith(".json") and f != "relay_card.json"
    ]


# ---------- 统一读写接口 ----------
def _reader():
    if _BACKEND == "memory":
        return _mem_read
    return _fs_read


def _writer():
    if _BACKEND == "memory":
        return _mem_write
    return _fs_write


def new_card(card_id, **fields):
    """创建一个分片状态卡。"""
    card = {
        "card_id": card_id,
        "status": "in_progress",
        "history": [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        **fields,
    }
    _writer()(card_id, card)
    return card


def get(card_id):
    """读取一张卡；不存在返回 None。"""
    return _reader()(card_id)


def set_card(card_id, **fields):
    """整体覆盖写一张卡（先读合并再写，避免丢字段）。"""
    card = _reader()(card_id) or {"card_id": card_id, "history": []}
    card.update(fields)
    card["updated_at"] = datetime.utcnow().isoformat()
    _writer()(card_id, card)
    return card


def update(card_id, **fields):
    """部分更新一张卡的字段。"""
    return set_card(card_id, **fields)


def append_log(card_id, message):
    """向卡的 history 追加一条日志（支持高频并发打点）。"""
    card = _reader()(card_id) or {"card_id": card_id, "history": []}
    card.setdefault("history", []).append(
        {"at": datetime.utcnow().isoformat(), "msg": message}
    )
    card["updated_at"] = datetime.utcnow().isoformat()
    _writer()(card_id, card)
    return card


def delete(card_id):
    """删除一张卡。"""
    _del = _mem_del if _BACKEND == "memory" else _fs_del
    _del(card_id)


def list_cards():
    """列出所有活跃卡 id。"""
    lister = _mem_list if _BACKEND == "memory" else _fs_list
    return lister()


def count():
    """当前活跃卡数量（用于并发度统计/看板）。"""
    return len(list_cards())


def clear_all():
    """清空所有分片卡（保留单例接力卡文件）。"""
    for cid in list_cards():
        delete(cid)
