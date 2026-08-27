#!/usr/bin/env bash
# 拓扑对比 · 混合调度(hybrid)与零散(scatter)差分测试（信号灯）
# =============================================================
# 验证用户 Issue #41 优化诉求：
#   T1 新拓扑注册：hybrid/scatter 已定义且标注适用任务性质
#   T2 hybrid 中央调控：前段(架构→分工) + 后段一窝蜂抢单，分阶段波次
#   T3 scatter 零散：架构师确认无架构→直接一窝蜂，全并行
#   T4 规模可调：scale 放大抢单/一窝蜂节点，并发/token/文件差异显现
#   T5 按任务性质差分：--suit architected 走 hybrid / scattered 走 scatter
#   T6 benchmark AB 对比：hybrid 并发/波次优于 linear，差异清晰
set -e
cd "$(dirname "$0")/.."

pass=0; fail=0
t() {
  local desc="$1"; shift
  if eval "$*" >/tmp/topo_out.txt 2>&1; then
    echo "  ✅ $desc"; pass=$((pass+1))
  else
    echo "  ❌ $desc"; cat /tmp/topo_out.txt; fail=$((fail+1))
  fi
}

echo "==== 拓扑对比 · 混合调度 / 零散差分测试 ===="

# ---- T1 新拓扑注册 + 适用任务性质标注 ----
t "T1 新拓扑 hybrid/scatter 已注册并标注适用性" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import topologies
ids=[t["id"] for t in topologies.list_topologies()]
assert "hybrid" in ids and "scatter" in ids, f"缺新拓扑: {ids}"
h=topologies.get_topology("hybrid"); s=topologies.get_topology("scatter")
assert h["suitable"]=="architected", "hybrid 应适用架构化任务"
assert s["suitable"]=="scattered", "scatter 应适用零散任务"
assert h["strategy"]=="hybrid" and s["strategy"]=="scatter"
assert len(h["nodes"])>11, "hybrid 节点应多于原 11 节点"
assert len(s["nodes"])>11, "scatter 节点应多于原 11 节点"
print("hybrid nodes:", len(h["nodes"]), "scatter nodes:", len(s["nodes"]))
PY'

# ---- T2 hybrid 中央调控：分阶段波次（前段架构→分工→后段一窝蜂） ----
t "T2 hybrid 分阶段执行（波次<线性，含抢单并行）" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import runner, tasksource
t=tasksource.list_real_tasks(suit_filter="architected")[0]
req=tasksource.task_to_req(t)
m=runner.run_one_topology("t-hybrid", req, "hybrid", use_llm=False)
assert m["output_ok"], "hybrid 应成功"
assert m["parallel_waves"] <= 4, f"hybrid 波次应少（分阶段），实为 {m[chr(112)+chr(97)+chr(114)+chr(97)+chr(108)+chr(108)+chr(101)+chr(108)+chr(95)+chr(119)+chr(97)+chr(118)+chr(101)+chr(115)]}"
# 步骤应为 17（原 11 + 6 抢单）
assert m["total_steps"] == 17, f"hybrid 步骤应 17，实为 {m[chr(116)+chr(111)+chr(116)+chr(97)+chr(108)+chr(95)+chr(115)+chr(116)+chr(101)+chr(112)+chr(115)]}"
print("hybrid steps:", m["total_steps"], "waves:", m["parallel_waves"])
PY'

# ---- T3 scatter 零散：直接一窝蜂全并行 ----
t "T3 scatter 零散任务一窝蜂并行" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import runner, tasksource
t=tasksource.list_real_tasks(suit_filter="scattered")[0]
req=tasksource.task_to_req(t)
m=runner.run_one_topology("t-scatter", req, "scatter", use_llm=False)
assert m["output_ok"], "scatter 应成功"
assert m["parallel_waves"] <= 4, "scatter 应分阶段少波次（确认→一窝蜂→收口）"
print("scatter steps:", m["total_steps"], "waves:", m["parallel_waves"])
PY'

# ---- T4 规模可调：scale 放大后并发/token/bug 差异显现 ----
t "T4 scale 放大后 hybrid 并发与 token 差异显现" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import benchmark, tasksource
t=tasksource.list_real_tasks(suit_filter="architected")[0]
req=tasksource.task_to_req(t)
s1=benchmark.run_one_bench("t1", req, "hybrid", use_llm=False, scale=1)
s5=benchmark.run_one_bench("t5", req, "hybrid", use_llm=False, scale=5)
assert s5["max_concurrency"] > s1["max_concurrency"], "规模放大后并发应增加"
assert s5["total_steps"] > s1["total_steps"], "规模放大后步骤应增加"
assert s5["token_usage"] > s1["token_usage"], "规模放大后 token 应增加"
assert s5["files_created"] > s1["files_created"], "规模放大后文件应增加"
print(f"scale1: 并发={s1[chr(109)+chr(97)+chr(120)+chr(95)+chr(99)+chr(111)+chr(110)+chr(99)+chr(117)+chr(114)+chr(114)+chr(101)+chr(110)+chr(99)+chr(121)]} 步骤={s1[chr(116)+chr(111)+chr(116)+chr(97)+chr(108)+chr(95)+chr(115)+chr(116)+chr(101)+chr(112)+chr(115)]} token={s1[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(117)+chr(115)+chr(97)+chr(103)+chr(101)]}")
print(f"scale5: 并发={s5[chr(109)+chr(97)+chr(120)+chr(95)+chr(99)+chr(111)+chr(110)+chr(99)+chr(117)+chr(114)+chr(114)+chr(101)+chr(110)+chr(99)+chr(121)]} 步骤={s5[chr(116)+chr(111)+chr(116)+chr(97)+chr(108)+chr(95)+chr(115)+chr(116)+chr(101)+chr(112)+chr(115)]} token={s5[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(117)+chr(115)+chr(97)+chr(103)+chr(101)]}")
PY'

# ---- T5 按任务性质差分 ----
t "T5 tasksource 支持按 suit 差分选择" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import tasksource
arch=tasksource.list_real_tasks(suit_filter="architected")
scat=tasksource.list_real_tasks(suit_filter="scattered")
assert len(arch)>=4, f"架构化任务应≥4，实为{len(arch)}"
assert len(scat)>=1, f"零散任务应≥1，实为{len(scat)}"
assert all(t.get("suit")=="architected" for t in arch)
assert all(t.get("suit")=="scattered" for t in scat)
print(f"架构化:{len(arch)} 零散:{len(scat)}")
PY'

# ---- T6 benchmark AB 对比：hybrid 并发优于 linear ----
t "T6 hybrid 并发/波次优于 linear（规模放大后差异清晰）" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import benchmark, tasksource
t=tasksource.list_real_tasks(suit_filter="architected")[0]
req=tasksource.task_to_req(t)
li=benchmark.run_one_bench("li", req, "linear", use_llm=False, scale=5)
hy=benchmark.run_one_bench("hy", req, "hybrid", use_llm=False, scale=5)
assert hy["max_concurrency"] > li["max_concurrency"], "hybrid 并发应高于 linear"
assert hy["parallel_waves"] < li["parallel_waves"], "hybrid 波次应少于 linear"
assert hy["output_ok"] and li["output_ok"], "两者都应成功"
print(f"linear: 并发={li[chr(109)+chr(97)+chr(120)+chr(95)+chr(99)+chr(111)+chr(110)+chr(99)+chr(117)+chr(114)+chr(114)+chr(101)+chr(110)+chr(99)+chr(121)]} 波次={li[chr(112)+chr(97)+chr(114)+chr(97)+chr(108)+chr(108)+chr(101)+chr(108)+chr(95)+chr(119)+chr(97)+chr(118)+chr(101)+chr(115)]}")
print(f"hybrid: 并发={hy[chr(109)+chr(97)+chr(120)+chr(95)+chr(99)+chr(111)+chr(110)+chr(99)+chr(117)+chr(114)+chr(114)+chr(101)+chr(110)+chr(99)+chr(121)]} 波次={hy[chr(112)+chr(97)+chr(114)+chr(97)+chr(108)+chr(108)+chr(101)+chr(108)+chr(95)+chr(119)+chr(97)+chr(118)+chr(101)+chr(115)]}")
PY'

echo ""
echo "==== 结果: ${pass} 通过, ${fail} 失败 ===="
[ "$fail" -eq 0 ]
