# -*- coding: utf-8 -*-
"""
拓扑对比执行器（Comparative Runner）
====================================
核心能力：在**真实开发场景**下，把同一个需求分别跑过不同拓扑线路，
收集量化指标，输出对比结果，支撑「长时间对比判断」。

用法：
    # 在 linear / dag / event 三条拓扑上跑同一个需求，输出对比
    python local-agent/topology/runner.py --req "做一个登录系统" --topologies linear,dag,event

    # 只跑某一条拓扑
    python local-agent/topology/runner.py --req "XX" --topologies dag

    # 跑 N 轮（长时间累积对比数据）
    python local-agent/topology/runner.py --req "XX" --rounds 5

    # 查看历史对比汇总
    python local-agent/topology/runner.py --summary

    # 查看某需求的对比
    python local-agent/topology/runner.py --compare "XX"
"""

import argparse
import json
import os
import sys
import time

# 允许直接以脚本运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph import DagEngine
from topology import metrics, topologies


def run_one_topology(req_key, req, topology_id, use_llm=True):
    """
    在指定拓扑上执行一次任务，返回执行指标。
    use_llm=False 时模拟执行（保留调度逻辑，验证框架正确性）。
    """
    topo = topologies.get_topology(topology_id)
    nodes = topo["nodes"]
    strategy = topo["strategy"]

    start = time.time()
    steps = 0
    reverts = 0
    blocks = 0
    waves_used = 0

    if strategy == "linear":
        # 直线串行：严格按顺序执行
        waves_used = len(nodes)
        for node in nodes:
            steps += 1
            output = _run_node(node, req, use_llm=use_llm)
            if _is_revert(output):
                reverts += 1
            if _is_block(output):
                blocks += 1

    elif strategy == "dag":
        # DAG 并行：按依赖波次执行
        engine = DagEngine(
            name=topology_id,
            description=topo["description"],
            nodes=nodes,
        )
        ok, err = engine.validate()
        if not ok:
            blocks += 1
        else:
            waves = engine.waves()
            waves_used = len(waves)
            for wave in waves:
                steps += len(wave)
                for nid in wave:
                    output = _run_node(engine.nodes[nid], req, use_llm=use_llm)
                    if _is_revert(output):
                        reverts += 1
                    if _is_block(output):
                        blocks += 1

    elif strategy == "event":
        # 事件驱动：节点按事件触发，部分产出即启动下游
        #
        # 核心语义差异（vs DAG）：
        #   DAG 的依赖是"上游**完全完成**才能启动下游"
        #   Event 的触发是"上游**发出进展事件**即可启动下游"
        #
        # 关键机制：**波内级联（within-wave cascade）**
        #   同一波次中，节点加入后立即发出"初始信号"，
        #   该信号可让更下游的节点在同一波次中也加入。
        #   因此事件拓扑可实现真正的"部分产出即启动"，大幅减少波次。
        events = {"user_request": True}
        pending = list(nodes)
        waves_used = 0

        while pending:
            # ① 波内级联：反复扫描 pending，把"触发条件已满足"的节点加入当前波次
            #    新加入的节点立即发出"初始信号"，可能触发更多节点加入
            wave = []
            found_new = True
            while found_new:
                found_new = False
                remaining = []
                for n in pending:
                    if n in wave:
                        remaining.append(n)
                        continue
                    trig = n.get("trigger", "")
                    if _can_fire(trig, events):
                        wave.append(n)
                        found_new = True
                        # 节点加入波次即发出"初始信号"（允许更下游节点同波加入）
                        _emit_start_events(n, events)
                    else:
                        remaining.append(n)
                pending = remaining

            if not wave:
                blocks += len(pending)
                break

            waves_used += 1

            # ② 执行当前波次的全部节点
            for n in wave:
                nid = n["id"]
                steps += 1
                output = _run_node(n, req, use_llm=use_llm)
                if _is_revert(output):
                    reverts += 1
                if _is_block(output):
                    blocks += 1
                # 节点完成 → 发出"完成"信号（供跨波次触发）
                _emit_done_events(n, events)

            # ③ pending 已经更新为仍未触发的节点

    elapsed = time.time() - start

    # 计算指标
    output_ok = blocks == 0

    return {
        "total_steps": steps,
        "parallel_waves": waves_used,
        "reverts": reverts,
        "blocks": blocks,
        "elapsed_ms": int(elapsed * 1000),
        "output_ok": output_ok,
        # 并行效率比 = 总节点数 / 波次数（越大表示并行度越高）
        "latency_ratio": max(1, len(nodes)) / max(1, waves_used),
    }


def _emit_start_events(node, events):
    """节点加入波次（开始执行）时，发出"初始信号"事件。"""
    nid = node["id"]
    # 节点开始执行 → 发出"进展"信号（允许更下游同波次加入）
    if "secretary" in nid:
        events["secretary:routed"] = True
    if "clarify" in nid:
        events["clarify:initial"] = True
    if "architect" in nid:
        events["architect:initial"] = True
    if "plan" in nid:
        events["plan:assigned"] = True
    if "lead" in nid:
        events["lead:initial"] = True


def _emit_done_events(node, events):
    """节点完成时，发出"完成"信号事件。"""
    nid = node["id"]
    events[f"{nid}:done"] = True
    if "find_tools" in nid:
        events["find_tools:done"] = True
    if "align" in nid:
        events["align:done"] = True
    if "develop" in nid:
        events["develop:output_ready"] = True
    if "review" in nid:
        events["review:passed"] = True
    if "test" in nid:
        events["test:passed"] = True


def _can_fire(trigger, events):
    """判断事件触发条件是否满足。trigger 格式："event1 + event2" 或 "event1"。"""
    if not trigger:
        return True
    conditions = [t.strip() for t in trigger.split("+")]
    return all(c in events and events[c] for c in conditions)


def _run_node(node, req, use_llm=True):
    """执行单个节点。use_llm=False 时返回模拟输出。"""
    node_id = node.get("id", "unknown")
    role = node.get("role", "编排引擎")
    action = node.get("action", "")

    if not use_llm:
        return f"[模拟执行] {role} 处理 '{req}' 完成，节点 {node_id}"

    try:
        from llm import get_backend
        llm = get_backend()
        result = llm.generate(f"你是{role}，请处理：{req}。任务：{action}")
        return result
    except Exception as e:
        return f"[执行异常] {e}"


def _is_revert(output):
    if not output:
        return False
    if isinstance(output, str):
        return "[回转]" in output or "[revert]" in output.lower()
    return False


def _is_block(output):
    if not output:
        return False
    if isinstance(output, str):
        return "[阻塞]" in output or "[blocked]" in output.lower()
    return False


def run_comparison(req, topology_ids=None, use_llm=True, rounds=1):
    """在指定拓扑集合上跑同一需求，记录指标，输出对比报告。"""
    req_key = req[:50]
    if not topology_ids:
        topology_ids = list(topologies.TOPOLOGIES.keys())

    print(f"🚀 拓扑对比执行开始")
    print(f"  需求: {req}")
    print(f"  对比拓扑: {', '.join(topology_ids)}")
    print(f"  轮次: {rounds} 轮")
    print(f"  LLM: {'启用' if use_llm else '模拟（无 LLM）'}")
    print()

    # 多轮累积
    for round_idx in range(1, rounds + 1):
        if rounds > 1:
            print(f"--- 第 {round_idx}/{rounds} 轮 ---")

        for tid in topology_ids:
            metrics_data = run_one_topology(req_key, req, tid, use_llm=use_llm)
            metrics.record_run(req_key, tid, metrics_data)

    if rounds > 1:
        print(f"已累积 {rounds} 轮指标，查看对比：")
        print(f"  python local-agent/topology/runner.py --compare \"{req_key}\"")
        print()
        return

    # 单轮时输出完整对比结果
    results = {}
    for tid in topology_ids:
        comparison = metrics.get_comparison(req_key)["topologies"].get(tid, {})
        results[tid] = comparison
        print(f"  ⚙️  执行拓扑 [{tid}] ...")
        print(f"      ✓ 完成: {comparison.get('total_steps', 0)} 步, "
              f"{comparison.get('parallel_waves', 0)} 波次, "
              f"{comparison.get('reverts', 0)} 回转, "
              f"{comparison.get('blocks', 0)} 阻塞, "
              f"{comparison.get('elapsed_ms', 0)}ms")

    print()
    print("=" * 60)
    print("📊 对比结果")
    print("=" * 60)
    print(f"| 拓扑 | 步骤 | 并行波次 | 回转 | 阻塞 | 耗时ms | 成功 | 并行效率 |")
    print(f"|------|------|---------|------|------|--------|------|---------|")
    for tid in topology_ids:
        r = results[tid]
        print(f"| {tid} | {r.get('total_steps', 0)} | {r.get('parallel_waves', 0)} | "
              f"{r.get('reverts', 0)} | {r.get('blocks', 0)} | {r.get('elapsed_ms', 0)} | "
              f"{'✅' if r.get('output_ok', False) else '❌'} | {r.get('latency_ratio', 1.0):.2f} |")

    print()
    print("💡 对比判断要点：")
    print("  - 并行波次越少 → 并行度越高")
    print("  - 回转/阻塞越少 → 链路稳定性越好")
    print("  - 判断需**多次运行 + 长时间累积**，单次结果仅供参考")
    print()

    print(metrics.summarize(f"本次运行: {req[:30]}..."))
    return results


def main():
    parser = argparse.ArgumentParser(description="拓扑对比执行器")
    parser.add_argument("--req", default="做一个登录系统", help="要跑的需求")
    parser.add_argument("--topologies", default=None,
                        help="逗号分隔的拓扑列表，如 linear,dag,event（默认全部）")
    parser.add_argument("--rounds", type=int, default=1,
                        help="跑 N 轮累积对比数据（长时间对比用）")
    parser.add_argument("--summary", action="store_true", help="查看历史对比汇总")
    parser.add_argument("--compare", default=None, help="查看某需求的对比视图")
    parser.add_argument("--list", action="store_true", help="列出全部拓扑")
    parser.add_argument("--no-llm", action="store_true",
                        help="不使用 LLM（模拟执行，仅验证调度逻辑）")
    args = parser.parse_args()

    if args.list:
        for t in topologies.list_topologies():
            print(f"  [{t['id']}] {t['name']}: {t['description']} ({t['node_count']} 节点)")
        return

    if args.summary:
        print(metrics.summarize("长时间累积"))
        return

    if args.compare:
        result = metrics.get_comparison(args.compare)
        if not result["has_data"]:
            print(f"未找到需求「{args.compare}」的对比数据")
        else:
            print(f"📊 需求「{result['req_key']}」的跨拓扑对比：")
            for tid, stats in result["topologies"].items():
                print(f"  [{tid}] 步骤={stats['total_steps']}, "
                      f"波次={stats['parallel_waves']}, "
                      f"回转={stats['reverts']}, "
                      f"阻塞={stats['blocks']}, "
                      f"耗时={stats['elapsed_ms']}ms, "
                      f"成功={'✅' if stats['output_ok'] else '❌'}, "
                      f"运行{stats['run_count']}次")
        return

    topology_ids = None
    if args.topologies:
        topology_ids = [t.strip() for t in args.topologies.split(",")]

    run_comparison(args.req, topology_ids, use_llm=not args.no_llm, rounds=args.rounds)


if __name__ == "__main__":
    main()
