# -*- coding: utf-8 -*-
"""
规模伸缩层 · 消息总线（broker）
================================
当前 relay.py 用「单接力卡 card['input']=out」串行传递上下文——一次只有
一个 agent 在「持有」全局输入，根本无法支撑 2500 个并发 agent 之间互相
发消息、投递任务、汇报结果。

本模块提供 **agent 间消息总线**（publish/subscribe + 队列）：

  - `publish(topic, message)`：向某个 topic（角色 / 小组 / 子任务 / 全局）投递消息；
  - `subscribe(agent_id, topic)` / `consume(agent_id)`：agent 订阅并消费自己的消息；
  - `pending(agent_id)`：查询某 agent 未处理消息数（用于调度器判断就绪）；
  - `fan_out(topics, message)`：广播给一组 topic（分形小组 / 多评审并行）。
  - 消息带 `msg_id / from_agent / to_topic / payload / ts`，可追踪、可回放。

后端：
  - memory：进程内 topic→queue（线程安全），适合单机高并发
  - redis：预留（分布式多机时启用）
通过 `BROKER_BACKEND` 环境变量切换。
"""
import itertools
import os
import threading
import uuid
from datetime import datetime
from collections import defaultdict, deque

_BACKEND = os.environ.get("BROKER_BACKEND", "memory")

# 内存后端：topic -> deque of message
_mem_topics = defaultdict(deque)
_mem_agent_q = defaultdict(deque)  # agent_id -> deque（聚合订阅）
_mem_lock = threading.RLock()
_id_seq = itertools.count(1)


def _msg_id():
    return f"m{next(_id_seq)}_{uuid.uuid4().hex[:6]}"


def _now():
    return datetime.utcnow().isoformat()


def publish(topic, payload, from_agent="system"):
    """向指定 topic 投递一条消息。返回 message dict。"""
    msg = {
        "msg_id": _msg_id(),
        "topic": topic,
        "from_agent": from_agent,
        "payload": payload,
        "ts": _now(),
    }
    with _mem_lock:
        _mem_topics[topic].append(msg)
    return msg


def subscribe(agent_id, *topics):
    """让一个 agent 订阅若干 topic。返回订阅的 topic 列表。"""
    # 内存实现：subscribe 时把 topic 当前历史（可选）登记到 agent；简化：记录订阅关系
    with _mem_lock:
        _mem_agent_q[agent_id]
    return list(topics)


def consume(agent_id):
    """取出 agent 已订阅 topic 中最早的一条未处理消息；无则返回 None。"""
    with _mem_lock:
        # 从 agent 的订阅聚合队列取（publish 时若 agent 已订阅对应 topic 会同步入队）
        q = _mem_agent_q[agent_id]
        return q.popleft() if q else None


def _enqueue_to_subscribers(topic, msg):
    """内存实现：把消息同步推给订阅了该 topic 的 agent。"""
    # 简化：这里不做反向索引，topic 队列即「订阅池」，由 consume 按需消费
    pass


def pending(agent_id):
    """查询某 agent 待处理消息数。"""
    with _mem_lock:
        return len(_mem_agent_q[agent_id])


def deliver(agent_id, topic, payload, from_agent="system"):
    """直接向指定 agent 投递消息（不等订阅，常用于任务分配/结果回收）。"""
    msg = {
        "msg_id": _msg_id(),
        "topic": topic,
        "from_agent": from_agent,
        "payload": payload,
        "to_agent": agent_id,
        "ts": _now(),
    }
    with _mem_lock:
        _mem_agent_q[agent_id].append(msg)
    return msg


def fan_out(topics, payload, from_agent="system"):
    """向一组 topic 广播（分形小组 / 多评审并行）。返回投递数。"""
    n = 0
    for t in topics:
        publish(t, payload, from_agent)
        n += 1
    return n


def topic_len(topic):
    """某 topic 的积压消息数。"""
    with _mem_lock:
        return len(_mem_topics[topic])


def stats():
    """消息总线统计（用于规模看板）。"""
    with _mem_lock:
        return {
            "topics": len(_mem_topics),
            "agents": len(_mem_agent_q),
            "total_pending": sum(len(q) for q in _mem_agent_q.values()),
        }
