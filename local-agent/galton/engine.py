# -*- coding: utf-8 -*-
"""
高尔顿板（Galton Board）MVP 原型 · Python 引擎
================================================
与 bash 版 engine.sh 等价的 Python 实现，供云 CI / 有 python3 环境验证。

对外接口（见 __init__.py 导出）：
  - route_ball(item, index, strategy)   → 返回 worker_id (1..3)
  - worker_process(item, worker_id)     → 返回加工后的球
  - aggregate(worker_outputs)           → 合并并统计分布
  - run_galton(items, strategy)         → 一键跑完整闭环，返回汇总结果
"""

WORKER_COUNT = 3
STRATEGIES = ("round-robin", "hash", "random")

# 支持的路由策略
ROUND_ROBIN = "round-robin"
HASH = "hash"
RANDOM = "random"


def route_ball(item, index, strategy=ROUND_ROBIN):
    """将球（item）按策略路由到 worker_id（1..WORKER_COUNT）。

    策略：
      - round-robin : 轮询，index % WORKER_COUNT + 1
      - hash        : 字符串哈希取模
      - random      : 随机 1..WORKER_COUNT
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"未知路由策略 '{strategy}'，可选：{'/'.join(STRATEGIES)}")

    if strategy == ROUND_ROBIN:
        return index % WORKER_COUNT + 1
    elif strategy == HASH:
        h = 0
        for ch in str(item):
            h = (h * 31 + ord(ch)) % 100000
        return h % WORKER_COUNT + 1
    else:  # random
        import random as _r
        return _r.randint(1, WORKER_COUNT)


def worker_process(item, worker_id):
    """单个 worker 加工一个球，返回加工后的标记。

    加工逻辑：给球打上 [W<id>]<原内容> 标记（与 bash 版等价）。
    """
    if not 1 <= worker_id <= WORKER_COUNT:
        raise ValueError(f"worker_id 必须在 1..{WORKER_COUNT}，收到 {worker_id}")
    return f"[W{worker_id}]{item}"


def aggregate(worker_outputs):
    """汇总全部 worker 的产出，返回分布统计。

    worker_outputs: {worker_id: [processed_item, ...]}

    返回 dict：{total, distribution: {wid: {count, pct}}, merged: [str,...]}
    """
    total = 0
    distribution = {}
    merged = []

    for wid in range(1, WORKER_COUNT + 1):
        items = worker_outputs.get(wid, [])
        count = len(items)
        total += count
        distribution[wid] = {"count": count}
        merged.extend(items)

    # 计算百分比
    for wid in range(1, WORKER_COUNT + 1):
        count = distribution[wid]["count"]
        pct = round(count * 100 / total, 1) if total > 0 else 0.0
        distribution[wid]["pct"] = pct

    return {
        "total": total,
        "distribution": distribution,
        "merged": merged,
    }


def run_galton(items, strategy=ROUND_ROBIN):
    """一键跑完整闭环：Router → Worker → Aggregator。

    items: 待处理的数据项列表
    返回：aggregate 结果 dict
    """
    worker_outputs = {wid: [] for wid in range(1, WORKER_COUNT + 1)}

    for idx, item in enumerate(items):
        wid = route_ball(item, idx, strategy)
        processed = worker_process(item, wid)
        worker_outputs[wid].append(processed)

    return aggregate(worker_outputs)


if __name__ == "__main__":
    import json
    import sys

    # CLI：galton/engine.py <strategy> [items...]
    if len(sys.argv) < 2:
        print("用法: python3 galton/engine.py <round-robin|hash|random> [items...]")
        sys.exit(1)

    strategy = sys.argv[1]
    items = sys.argv[2:] or ["task-a", "task-b", "task-c", "task-d", "task-e"]

    result = run_galton(items, strategy)
    print(json.dumps(result, ensure_ascii=False, indent=2))
