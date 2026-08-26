# -*- coding: utf-8 -*-
"""
对比指标收集与持久化（Comparison Metrics）
==========================================
为「长时间对比判断」提供量化指标：
  - 每次在同一需求上跑完一条拓扑线路后，记录该线路的表现指标；
  - 指标持久化到本地 JSON 记录（后续可迁移到数据库层 data/）；
  - 提供「对比视图」：同一需求在多条线路上的横向对比。

指标维度（对比核心）：
  - total_steps      总步骤数（步骤越少 = 效率越高）
  - parallel_waves   并行波次数（越少 = 并行度越高）
  - reverts          回转次数（越少 = 上游产出质量越高）
  - blocks           阻塞/失败次数（越少 = 稳定性越高）
  - elapsed_ms       耗时毫秒（越短 = 吞吐越高）
  - output_ok        交付是否成功（是否产出有效交付物）
  - latency_ratio    并行效率比（linear=1，dag/event 越小越好）
"""

import json
import os
import time
from datetime import datetime

METRICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_metrics")
METRICS_FILE = os.path.join(METRICS_DIR, "comparison_metrics.json")


def _ensure_dir():
    os.makedirs(METRICS_DIR, exist_ok=True)


def _load_all():
    _ensure_dir()
    if not os.path.exists(METRICS_FILE):
        return {}
    try:
        with open(METRICS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all(data):
    _ensure_dir()
    with open(METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def record_run(req_key, topology_id, metrics):
    """记录一次在指定拓扑上跑某个需求的指标。"""
    all_data = _load_all()
    if req_key not in all_data:
        all_data[req_key] = {}
    if topology_id not in all_data[req_key]:
        all_data[req_key][topology_id] = []
    # 追加记录（支持同一拓扑多次跑同一需求的历史累积）
    all_data[req_key][topology_id].append({
        **metrics,
        "ts": datetime.utcnow().isoformat(),
    })
    _save_all(all_data)
    return all_data


def get_comparison(req_key):
    """获取指定需求的跨拓扑对比视图。"""
    all_data = _load_all()
    if req_key not in all_data:
        return {"req_key": req_key, "topologies": {}, "has_data": False}

    result = {"req_key": req_key, "topologies": {}, "has_data": True}
    for tid, runs in all_data[req_key].items():
        if not runs:
            continue
        # 取最近一次记录做对比，保留历史供趋势分析
        latest = runs[-1]
        # 汇总统计
        stats = {
            "total_steps": latest.get("total_steps", 0),
            "parallel_waves": latest.get("parallel_waves", 0),
            "reverts": latest.get("reverts", 0),
            "blocks": latest.get("blocks", 0),
            "elapsed_ms": latest.get("elapsed_ms", 0),
            "output_ok": latest.get("output_ok", False),
            "latency_ratio": latest.get("latency_ratio", 1.0),
            "run_count": len(runs),
            "last_run": latest.get("ts", ""),
        }
        result["topologies"][tid] = stats
    return result


def get_all_comparisons():
    """获取全部需求的对比汇总（长时间累积）。"""
    all_data = _load_all()
    return all_data


def summarize(tag="全部"):
    """生成对比摘要（二级信息，供人类俯瞰）。"""
    all_data = _load_all()
    lines = []
    lines.append(f"📊 拓扑对比 · 指标汇总（{tag}）")
    lines.append("")

    if not all_data:
        lines.append("  （暂无对比数据，请先用 comparative runner 跑任务）")
        return "\n".join(lines)

    # 汇总每个拓扑在所有需求上的平均指标
    topo_agg = {}
    for req_key, topo_runs in all_data.items():
        for tid, runs in topo_runs.items():
            if tid not in topo_agg:
                topo_agg[tid] = {
                    "total_steps": [], "parallel_waves": [], "reverts": [],
                    "blocks": [], "elapsed_ms": [], "output_ok_count": 0, "total_runs": 0
                }
            agg = topo_agg[tid]
            for r in runs:
                agg["total_steps"].append(r.get("total_steps", 0))
                agg["parallel_waves"].append(r.get("parallel_waves", 0))
                agg["reverts"].append(r.get("reverts", 0))
                agg["blocks"].append(r.get("blocks", 0))
                agg["elapsed_ms"].append(r.get("elapsed_ms", 0))
                agg["output_ok_count"] += 1 if r.get("output_ok") else 0
                agg["total_runs"] += 1

    lines.append("| 拓扑 | 总步骤(均) | 并行波次(均) | 回转(均) | 阻塞(均) | 耗时ms(均) | 成功率 | 运行数 |")
    lines.append("|------|-----------|-------------|---------|---------|-----------|--------|--------|")
    for tid, agg in topo_agg.items():
        n = len(agg["total_steps"]) or 1
        lines.append(
            f"| {tid} | {sum(agg['total_steps'])/n:.1f} | "
            f"{sum(agg['parallel_waves'])/n:.1f} | "
            f"{sum(agg['reverts'])/n:.1f} | "
            f"{sum(agg['blocks'])/n:.1f} | "
            f"{sum(agg['elapsed_ms'])/n:.0f} | "
            f"{agg['output_ok_count']}/{agg['total_runs']} | {agg['total_runs']} |"
        )

    lines.append("")
    lines.append("💡 对比解读：")
    lines.append("  - 步骤/波次越少 → 流水线越精简、并行度越高")
    lines.append("  - 回转越少 → 上游产出质量越高、返工越少")
    lines.append("  - 耗时越短 → 吞吐越高、交付越快")
    lines.append("  - 成功率越高 → 稳定性越强、更可依赖")
    return "\n".join(lines)
