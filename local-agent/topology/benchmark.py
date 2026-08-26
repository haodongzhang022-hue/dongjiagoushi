# -*- coding: utf-8 -*-
"""
增强对比执行器（Benchmark Runner · AB 隔离对比）
==================================================
在真实未完成任务上，对多条拓扑做 AB 隔离对比，采集用户诉求的**全维度指标**：

  并发量 / 速度 / 任务完成度 / bug量 / token消耗 / 产生文件数 /
  使用agent数 / 资源消耗量（CPU / 内存 / 网络）

核心特性：
  1. **真实任务**：从 tasksource 读取「架构完未分配」「经理分工未触发」的真实待办，
     而非只用虚拟需求"做一个登录系统"。
  2. **AB 隔离**：每条拓扑跑在独立工作目录（_bench/<req>/<topology>/），
     资源快照各自独立，杜绝串扰；同一需求在三条拓扑上互为对照组（A/B/C）。
  3. **资源监控**：CPU/内存/网络/文件产出 用标准库采集，零第三方依赖。
  4. **token 估算**：无真实 LLM 时按「输出字符 / 3」估算 token 消耗。

用法：
    # 用真实任务做 AB 隔离对比（三条拓扑）
    python3 local-agent/topology/benchmark.py --task all --topologies linear,dag,event

    # 只对比某阶段真实任务
    python3 local-agent/topology/benchmark.py --task stage:architected_unassigned

    # 查看真实任务清单
    python3 local-agent/topology/benchmark.py --list-tasks

    # 查看全维度对比汇总
    python3 local-agent/topology/benchmark.py --summary

    # 查看某需求对比
    python3 local-agent/topology/benchmark.py --compare "<req>"
"""
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph import DagEngine
from topology import metrics, tasksource
from topology.resource import ResourceMonitor, snapshot_files


# ------------------------------------------------------------
# 节点执行（真实逻辑 + 可注入 bug/完成度）
# ------------------------------------------------------------
def _exec_node(node, req, work_dir, use_llm=True, concurrency=1):
    """执行单个节点，返回 (output_str, node_meta)。

    node_meta 记录该节点的 token 估算、产出文件数、是否产生 bug 信号。
    concurrency 为当前波次并行节点数——并行越高，共享上下文越长，
    token 消耗按上下文系数放大（贴近真实 LLM 并行调用的上下文累积成本）。
    """
    node_id = node.get("id", "unknown")
    role = node.get("role", "编排引擎")
    action = node.get("action", "")

    # 模拟在隔离目录产生一个节点级产出文件（真实文件产出统计）
    if work_dir:
        os.makedirs(work_dir, exist_ok=True)
        fn = os.path.join(work_dir, f"{node_id}.out.txt")
        try:
            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"[{role}] {action}\n需求: {req}\n")
        except Exception:
            pass

    ctx_factor = 1 + (concurrency - 1) * 0.12  # 并发越高中上下文越长
    if not use_llm:
        # 模拟输出：token ≈ 输出字符数/3 × 上下文系数，bug 按节点风险因子（不依赖外部库）
        text = f"[模拟执行] {role} 处理 '{req}' 完成，节点 {node_id}"
        token_est = max(1, int(len(text) // 3 * ctx_factor))
        bug = 1 if ("develop" in node_id and len(req) % 7 == 0) else 0
        return text, {"token": token_est, "files": 1, "bug": bug}

    try:
        from llm import get_backend
        llm = get_backend()
        result = llm.generate(f"你是{role}，请处理：{req}。任务：{action}")
        token_est = max(1, int(len(result) // 3 * ctx_factor))
        bug = 1 if ("develop" in node_id and ("Bug" in result or "缺陷" in result)) else 0
        return result, {"token": token_est, "files": 1, "bug": bug}
    except Exception as e:
        return f"[执行异常] {e}", {"token": 1, "files": 1, "bug": 0}


def _is_revert(output):
    return bool(output) and isinstance(output, str) and \
        ("[回转]" in output or "[revert]" in output.lower())


def _is_block(output):
    return bool(output) and isinstance(output, str) and \
        ("[阻塞]" in output or "[blocked]" in output.lower())


# ------------------------------------------------------------
# 单拓扑单任务执行（含资源监控 + 全维度采集）
# ------------------------------------------------------------
def run_one_bench(req_key, req, topology_id, use_llm=True, base_dir=None):
    """在指定拓扑上跑一个真实任务，采集全维度指标（含资源消耗）。"""
    from topology import topologies

    topo = topologies.get_topology(topology_id)
    nodes = topo["nodes"]
    strategy = topo["strategy"]

    # AB 隔离工作目录：_bench/<req_key>/<topology_id>/
    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bench")
    work_dir = os.path.join(base_dir, _safe(req_key), topology_id)
    os.makedirs(work_dir, exist_ok=True)
    # 清空该拓扑目录，保证隔离（每个拓扑独立基准）
    for f in os.listdir(work_dir):
        fp = os.path.join(work_dir, f)
        if os.path.isfile(fp):
            os.remove(fp)
        elif os.path.isdir(fp):
            shutil.rmtree(fp, ignore_errors=True)

    # 资源监控（绑定隔离目录）
    rm = ResourceMonitor(work_dir=work_dir).start()

    start = time.time()
    steps = 0
    reverts = 0
    blocks = 0
    bugs = 0
    tokens = 0
    files = 0
    agents_used = set()
    waves_used = 0
    max_concurrency = 0

    def _run_batch(batch_nodes, wave_no):
        nonlocal steps, reverts, blocks, bugs, tokens, files, max_concurrency
        # 并发量 = 单波次内同时活跃的节点数（该波次真实并行度）
        active = len(batch_nodes)
        max_concurrency = max(max_concurrency, active)
        for n in batch_nodes:
            steps += 1
            agents_used.add(n.get("role", "编排引擎"))
            out, meta = _exec_node(n, req, work_dir, use_llm=use_llm,
                                    concurrency=active)
            tokens += meta.get("token", 0)
            files += meta.get("files", 0)
            bugs += meta.get("bug", 0)
            if _is_revert(out):
                reverts += 1
            if _is_block(out):
                blocks += 1
            # 每步采一次资源（模拟持续消耗）
            rm.tick()

    if strategy == "linear":
        waves_used = len(nodes)
        for node in nodes:
            _run_batch([node], 0)

    elif strategy == "dag":
        engine = DagEngine(name=topology_id, description=topo["description"], nodes=nodes)
        ok, err = engine.validate()
        if not ok:
            blocks += 1
        else:
            waves = engine.waves()
            waves_used = len(waves)
            for wave in waves:
                _run_batch([engine.nodes[nid] for nid in wave], 0)

    elif strategy == "event":
        events = {"user_request": True}
        pending = list(nodes)
        waves_used = 0
        while pending:
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
                        _emit_start_events(n, events)
                    else:
                        remaining.append(n)
                pending = remaining
            if not wave:
                blocks += len(pending)
                break
            waves_used += 1
            _run_batch(wave, waves_used)
            for n in wave:
                _emit_done_events(n, events)

    elapsed_ms = int((time.time() - start) * 1000)
    resource = rm.stop()

    # 完成度：被执行的节点数 / 总节点数（真实调度完成比例）
    total_nodes = len(nodes)
    completion_pct = round((total_nodes - max(0, blocks)) / total_nodes * 100, 1)

    output_ok = blocks == 0

    return {
        # 调度维度
        "total_steps": steps,
        "parallel_waves": waves_used,
        "max_concurrency": max_concurrency,
        "elapsed_ms": elapsed_ms,
        "completion_pct": completion_pct,
        # 质量维度
        "bug_count": bugs,
        "reverts": reverts,
        "blocks": blocks,
        "output_ok": output_ok,
        # 成本维度
        "token_usage": tokens,
        "files_created": files + resource.get("file_count_delta", 0),
        "agents_used": len(agents_used),
        # 并行效率
        "latency_ratio": max(1, total_nodes) / max(1, waves_used),
        # 资源消耗
        "cpu_avg_pct": resource.get("cpu_avg_pct", 0),
        "mem_delta_kb": resource.get("mem_delta_kb", 0),
        "net_sent_bytes": resource.get("net_sent_bytes", 0),
        "net_recv_bytes": resource.get("net_recv_bytes", 0),
    }


def _can_fire(trigger, events):
    if not trigger:
        return True
    conditions = [t.strip() for t in trigger.split("+")]
    return all(c in events and events[c] for c in conditions)


def _emit_start_events(node, events):
    nid = node["id"]
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


def _safe(s):
    import re
    return re.sub(r'[^\w\u4e00-\u9fff-]', '_', s)[:40]


# ------------------------------------------------------------
# 顶层：跑真实任务 AB 对比
# ------------------------------------------------------------
def run_bench(tasks, topology_ids=None, use_llm=True, rounds=1):
    """在多个真实任务上做 AB 隔离对比。"""
    from topology import topologies
    if not topology_ids:
        topology_ids = list(topologies.TOPOLOGIES.keys())

    print("🚀 真实任务 AB 隔离对比执行开始")
    print(f"  任务数: {len(tasks)}")
    print(f"  对比拓扑(AB组): {', '.join(topology_ids)}")
    print(f"  轮次: {rounds}")
    print(f"  LLM: {'启用' if use_llm else '模拟（无LLM，token按字符估算）'}")
    print()

    for round_idx in range(1, rounds + 1):
        if rounds > 1:
            print(f"--- 第 {round_idx}/{rounds} 轮 ---")
        for task in tasks:
            req = tasksource.task_to_req(task)
            req_key = task.get("task_id", req[:30])
            print(f"  ⚙️  任务[{task.get('stage')}]: {task.get('title')}")
            for tid in topology_ids:
                m = run_one_bench(req_key, req, tid, use_llm=use_llm)
                metrics.record_run(req_key, tid, m)
            if rounds == 1:
                _print_ab_table(task, req_key, topology_ids)
                print()

    if rounds > 1:
        print(f"✅ 已累积 {rounds} 轮 AB 对比数据")
    print("查看全维度汇总：")
    print("  python3 local-agent/topology/benchmark.py --summary")
    print()


def _print_ab_table(task, req_key, topology_ids):
    """打印单任务 AB 对比表（全维度）。"""
    comp = metrics.get_comparison(req_key)
    rows = {tid: comp["topologies"].get(tid, {}) for tid in topology_ids}

    dims = [
        ("max_concurrency", "最大并发", ""),
        ("elapsed_ms", "耗时ms", ""),
        ("completion_pct", "完成度%", ""),
        ("bug_count", "bug数", ""),
        ("token_usage", "token", ""),
        ("files_created", "文件数", ""),
        ("agents_used", "agent数", ""),
        ("total_steps", "总步骤", ""),
        ("parallel_waves", "并行波次", ""),
        ("reverts", "回转", ""),
        ("blocks", "阻塞", ""),
        ("output_ok", "成功", ""),
        ("cpu_avg_pct", "CPU%", ""),
        ("mem_delta_kb", "内存KB", ""),
        ("net_sent_bytes", "网络发送B", ""),
    ]
    print(f"  📊 AB对比 [{task.get('title')[:28]}...]")
    print(f"  | {'维度':<12} | " + " | ".join(f"{tid:<8}" for tid in topology_ids) + " |")
    print(f"  |" + "---|" * (len(topology_ids) + 1))
    for key, label, _ in dims:
        vals = [str(rows.get(tid, {}).get(key, "-")) for tid in topology_ids]
        print(f"  | {label:<12} | " + " | ".join(f"{v:<8}" for v in vals) + " |")


# ------------------------------------------------------------
# CLI
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="真实任务 AB 隔离拓扑对比")
    parser.add_argument("--task", default="all",
                        help="任务选择：all / stage:<stage> / 具体 task_id，默认 all")
    parser.add_argument("--topologies", default=None, help="逗号分隔，如 linear,dag,event")
    parser.add_argument("--rounds", type=int, default=1, help="跑 N 轮累积")
    parser.add_argument("--no-llm", action="store_true", help="模拟执行（无LLM）")
    parser.add_argument("--list-tasks", action="store_true", help="列出真实任务")
    parser.add_argument("--summary", action="store_true", help="全维度汇总")
    parser.add_argument("--compare", default=None, help="查看某需求对比")
    args = parser.parse_args()

    if args.list_tasks:
        print(tasksource.show_tasks())
        return
    if args.summary:
        print(metrics.summarize("长时间累积"))
        return
    if args.compare:
        comp = metrics.get_comparison(args.compare)
        if not comp["has_data"]:
            print(f"未找到需求「{args.compare}」的对比数据")
            return
        print(f"📊 需求「{comp['req_key']}」跨拓扑对比：")
        for tid, s in comp["topologies"].items():
            print(f"  [{tid}] 并发={s['max_concurrency']} 耗时={s['elapsed_ms']}ms "
                  f"完成={s['completion_pct']}% bug={s['bug_count']} token={s['token_usage']} "
                  f"文件={s['files_created']} agent={s['agents_used']} "
                  f"CPU={s['cpu_avg_pct']}% 网络↑{s['net_sent_bytes']}B")
        return

    # 选择真实任务
    if args.task.startswith("stage:"):
        stage = args.task.split(":", 1)[1]
        tasks = tasksource.list_real_tasks(stage_filter=stage)
    elif args.task == "all":
        tasks = tasksource.list_real_tasks()
    else:
        tasks = [t for t in tasksource.list_real_tasks()
                 if t.get("task_id") == args.task]
        if not tasks:
            # 尝试按内置样例精确命中
            tasks = [t for t in tasksource.SAMPLE_TASKS if t.get("task_id") == args.task]
    if not tasks:
        print(f"⚠️  未找到匹配任务: {args.task}")
        print("可用任务见：")
        print(tasksource.show_tasks())
        return

    topology_ids = None
    if args.topologies:
        topology_ids = [t.strip() for t in args.topologies.split(",")]

    run_bench(tasks, topology_ids, use_llm=not args.no_llm, rounds=args.rounds)


if __name__ == "__main__":
    main()
