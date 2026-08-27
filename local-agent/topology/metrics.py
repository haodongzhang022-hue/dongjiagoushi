# -*- coding: utf-8 -*-
"""
对比指标收集与持久化（Comparison Metrics · 全维度）
====================================================
为「长时间对比判断」提供量化指标，覆盖用户诉求的全部对比维度：

  - total_steps          总步骤数（效率）
  - parallel_waves       并行波次数（并行度）
  - max_concurrency      最大并发量（同时活跃的节点/agent 数峰值）
  - elapsed_ms           耗时（速度）
  - completion_pct       任务完成度（0~100%）
  - bug_count            bug 量（缺陷检出数）
  - token_usage          token 消耗估算（无真实 LLM 时按输出字符/3 估算）
  - files_created        产生文件数
  - agents_used          使用的 agent 数
  - reverts              回转次数（上游质量）
  - blocks               阻塞次数（稳定性）
  - output_ok            交付是否成功
  - latency_ratio        并行效率比
  - cpu_avg_pct          平均 CPU 使用率（资源消耗）
  - mem_delta_kb         内存增量
  - net_sent_bytes       网络发送字节（资源消耗）

持久化到本地 JSON，支持多次运行累积 + 对比视图 + 摘要汇总（二级信息）。
"""
import json
import os
from datetime import datetime

METRICS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_metrics")
METRICS_FILE = os.path.join(METRICS_DIR, "comparison_metrics.json")

# 全维度字段（用于对比表与摘要）
ALL_DIMENSIONS = [
    "total_steps", "parallel_waves", "max_concurrency", "elapsed_ms",
    "completion_pct", "bug_count", "token_usage", "files_created",
    "agents_used", "reverts", "blocks", "output_ok",
    "latency_ratio", "cpu_avg_pct", "mem_delta_kb",
    "net_sent_bytes", "net_recv_bytes",
    "cache_hits", "cache_clusters", "prefix_saved_chars", "cache_hit_rate",
]


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
    all_data[req_key][topology_id].append({
        **metrics,
        "ts": datetime.utcnow().isoformat(),
    })
    _save_all(all_data)
    return all_data


def get_comparison(req_key):
    """获取指定需求的跨拓扑对比视图（全维度）。"""
    all_data = _load_all()
    if req_key not in all_data:
        return {"req_key": req_key, "topologies": {}, "has_data": False}

    result = {"req_key": req_key, "topologies": {}, "has_data": True}
    for tid, runs in all_data[req_key].items():
        if not runs:
            continue
        latest = runs[-1]
        stats = {d: latest.get(d, 0) for d in ALL_DIMENSIONS}
        stats["run_count"] = len(runs)
        stats["last_run"] = latest.get("ts", "")
        result["topologies"][tid] = stats
    return result


def get_all_comparisons():
    """获取全部需求的对比汇总（长时间累积）。"""
    return _load_all()


# ------------------------------------------------------------
# 维度标签与"越好"方向（供摘要解读）
# ------------------------------------------------------------
DIMENSION_LABELS = {
    "total_steps": ("总步骤", "down"),
    "parallel_waves": ("并行波次", "down"),
    "max_concurrency": ("最大并发", "up"),
    "elapsed_ms": ("耗时ms", "down"),
    "completion_pct": ("完成度%", "up"),
    "bug_count": ("bug数", "down"),
    "token_usage": ("token", "down"),
    "files_created": ("文件数", "down"),
    "agents_used": ("agent数", "down"),
    "reverts": ("回转", "down"),
    "blocks": ("阻塞", "down"),
    "output_ok": ("成功", "up"),
    "latency_ratio": ("并行效率", "up"),
    "cpu_avg_pct": ("CPU%", "down"),
    "mem_delta_kb": ("内存KB", "down"),
    "net_sent_bytes": ("网络发送B", "down"),
    "net_recv_bytes": ("网络接收B", "down"),
    "cache_hits": ("缓存命中数", "up"),
    "cache_clusters": ("前缀集群数", "-"),
    "prefix_saved_chars": ("前缀节省字符", "up"),
    "cache_hit_rate": ("缓存命中率%", "up"),
}


def _avg(vals):
    return sum(vals) / len(vals) if vals else 0


def _avg_pct_ok(pairs):
    """output_ok 是布尔，单独算成功比例。"""
    if not pairs:
        return 0.0
    return round(sum(1 for v in pairs if v) / len(pairs) * 100, 1)


def summarize(tag="全部"):
    """生成全维度对比摘要（二级信息，供人类俯瞰）。"""
    all_data = _load_all()
    lines = []
    lines.append(f"📊 拓扑对比 · 全维度指标汇总（{tag}）")
    lines.append("")

    if not all_data:
        lines.append("  （暂无对比数据，请先用 benchmark runner 跑任务）")
        return "\n".join(lines)

    # 每维度按拓扑聚合（均值），output_ok 按成功比例
    topo_agg = {}
    for req_key, topo_runs in all_data.items():
        for tid, runs in topo_runs.items():
            agg = topo_agg.setdefault(tid, {d: [] for d in ALL_DIMENSIONS})
            agg["output_ok"] = []
            for r in runs:
                # 只统计含该维度的记录（旧版本缺新字段的记录跳过，不当作 0 混入）
                for d in ALL_DIMENSIONS:
                    if d not in r:
                        continue
                    v = r.get(d, 0)
                    if d == "output_ok":
                        agg[d].append(1 if v else 0)
                    else:
                        agg[d].append(v)

    # 输出对比表
    header = ["拓扑"]
    for d in ALL_DIMENSIONS:
        label, _ = DIMENSION_LABELS[d]
        header.append(label)
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))

    for tid, agg in topo_agg.items():
        row = [tid]
        for d in ALL_DIMENSIONS:
            vals = agg[d]
            if not vals:
                row.append("-")
                continue
            if d == "output_ok":
                row.append(f"{_avg(vals)*100:.0f}%")
            elif d in ("completion_pct",):
                row.append(f"{_avg(vals):.1f}")
            elif d in ("elapsed_ms", "mem_delta_kb", "token_usage", "net_sent_bytes", "net_recv_bytes"):
                row.append(f"{_avg(vals):.0f}")
            else:
                row.append(f"{_avg(vals):.1f}")
        lines.append("| " + " | ".join(row) + " |")

    # 解读
    lines.append("")
    lines.append("💡 维度解读（↑=越大越好 ↓=越小越好）：")
    interpretations = [
        ("total_steps/parallel_waves/max_concurrency", "步骤/波次越少且并发越高 → 流水线精简且并行充分"),
        ("elapsed_ms", "耗时越短 → 速度越快、吞吐越高"),
        ("completion_pct", "完成度越高 → 交付越完整"),
        ("bug_count/reverts/blocks", "bug/回转/阻塞越少 → 质量与稳定性越好"),
        ("token_usage", "token 越少 → 成本越低"),
        ("files_created/agents_used", "文件/agent 越少 → 越精简、资源占用越少"),
        ("cpu_avg_pct/mem/net", "CPU/内存/网络越低 → 资源消耗越少"),
    ]
    for k, v in interpretations:
        lines.append(f"  - {k}: {v}")
    lines.append("")
    lines.append("  ⚠️ 判断需多次运行+长时间累积，单次仅供参考。")
    return "\n".join(lines)
