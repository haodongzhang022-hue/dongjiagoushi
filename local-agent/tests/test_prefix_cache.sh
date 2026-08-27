#!/usr/bin/env bash
# 前缀缓存·水龙头蔓延（prefix）测试（信号灯）
# =============================================================
# 验证用户 Issue #41 优化诉求（框架方向对但 bug 多、token 大 → 前缀缓存聚合优化）：
#   T1 prefix 拓扑已注册，PREFIX_NODES 在注册表前被引用
#   T2 prefix_cache 模块：共享前缀聚合 + 缓存命中索引 + 增量蔓延 token 模型
#   T3 prefix 拓扑水龙头蔓延：缓存命中率高、prefix_saved 节省大
#   T4 AB 对比：prefix(token/bug) 优于 hybrid(散沙) —— 降token、降bug
set -e
cd "$(dirname "$0")/.."

pass=0; fail=0
t() {
  local desc="$1"; shift
  if eval "$*" >/tmp/prefix_out.txt 2>&1; then
    echo "  ✅ $desc"; pass=$((pass+1))
  else
    echo "  ❌ $desc"; cat /tmp/prefix_out.txt; fail=$((fail+1))
  fi
}

echo "==== 前缀缓存·水龙头蔓延（prefix）测试 ===="

# ---- T1 prefix 拓扑已注册 ----
t "T1 prefix 拓扑已注册并标注 optimizes=hybrid" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import topologies
ids=[t["id"] for t in topologies.list_topologies()]
assert "prefix" in ids, f"缺 prefix 拓扑: {ids}"
p=topologies.get_topology("prefix")
assert p["strategy"]=="prefix", "strategy 应为 prefix"
assert p["suitable"]=="architected", "prefix 应适用架构化任务"
assert p.get("optimizes")=="hybrid", "prefix 应标注为 hybrid 的优化版"
assert len(p["nodes"])==17, f"prefix 节点应 17，实为 {len(p[chr(110)+chr(111)+chr(100)+chr(101)+chr(115)])}"
print("prefix nodes:", len(p["nodes"]), "suitable:", p["suitable"], "optimizes:", p["optimizes"])
PY'

# ---- T2 prefix_cache 模块：聚合 + 缓存命中 + 增量 token ----
t "T2 prefix_cache 聚合/命中/增量蔓延逻辑正确" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import prefix_cache
req="做一个登录系统"
nodes=[
  {"id":"a1","role":"架构·开发","action":"子任务A"},
  {"id":"a2","role":"架构·开发","action":"子任务B"},
  {"id":"a3","role":"架构·开发","action":"子任务C"},
  {"id":"review","role":"架构·评审","action":"评审"},
]
an=prefix_cache.analyze(nodes, req)
# 散沙：每节点独立全量前缀；水龙头：集群首节点全量+后续增量
assert an["node_count"]==4
assert an["cluster_count"]==2, f"应聚合为2集群（开发+评审），实为 {an[chr(99)+chr(108)+chr(117)+chr(115)+chr(116)+chr(101)+chr(114)+chr(95)+chr(99)+chr(111)+chr(117)+chr(110)+chr(116)]}"
assert an["cache_hits"]==2, f"3个开发节点中后2个命中缓存，实为 {an[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(115)]}"
assert an["faucet_tokens"] < an["scatter_tokens"], "水龙头 token 应低于散沙"
assert an["token_saved_pct"] > 0, "应节省 token"
print(f"集群={an[chr(99)+chr(108)+chr(117)+chr(115)+chr(116)+chr(101)+chr(114)+chr(95)+chr(99)+chr(111)+chr(117)+chr(110)+chr(116)]} 命中={an[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(115)]} "
      f"散沙token={an[chr(115)+chr(99)+chr(97)+chr(116)+chr(116)+chr(101)+chr(114)+chr(95)+chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(115)]} 水龙头token={an[chr(102)+chr(97)+chr(117)+chr(99)+chr(101)+chr(116)+chr(95)+chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(115)]} 节省%={an[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(115)+chr(97)+chr(118)+chr(101)+chr(100)+chr(95)+chr(112)+chr(99)+chr(116)]}")
PY'

# ---- T3 prefix 拓扑水龙头蔓延：缓存命中率高、节省大 ----
t "T3 prefix 拓扑缓存命中率高、prefix_saved 节省大" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import benchmark, tasksource
t=tasksource.list_real_tasks(suit_filter="architected")[0]
req=tasksource.task_to_req(t)
m=benchmark.run_one_bench("t-prefix", req, "prefix", use_llm=False, scale=3)
assert m["output_ok"], "prefix 应成功"
# 放大 scale=3 后，faucet 阶段同集群开发节点多，缓存命中应显著
assert m["cache_hits"] >= 2, f"水龙头缓存命中应≥2，实为 {m[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(115)]}"
assert m["cache_hit_rate"] > 20, f"缓存命中率应>20%，实为 {m[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(95)+chr(114)+chr(97)+chr(116)+chr(101)]}"
assert m["prefix_saved_chars"] > 0, "应节省前缀字符"
print(f"prefix: 命中={m[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(115)]} 集群={m[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(99)+chr(108)+chr(117)+chr(115)+chr(116)+chr(101)+chr(114)+chr(115)]} 命中率={m[chr(99)+chr(97)+chr(99)+chr(104)+chr(101)+chr(95)+chr(104)+chr(105)+chr(116)+chr(95)+chr(114)+chr(97)+chr(116)+chr(101)]}% 节省字符={m[chr(112)+chr(114)+chr(101)+chr(102)+chr(105)+chr(120)+chr(95)+chr(115)+chr(97)+chr(118)+chr(101)+chr(100)+chr(95)+chr(99)+chr(104)+chr(97)+chr(114)+chr(115)]}")
PY'

# ---- T4 AB 对比：prefix 优于 hybrid（散沙）—— 降 token、降 bug ----
t "T4 AB 对比：prefix token/bug 低于 hybrid 散沙（规模放大）" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from topology import benchmark, tasksource
t=tasksource.list_real_tasks(suit_filter="architected")[0]
req=tasksource.task_to_req(t)
hy=benchmark.run_one_bench("ab-hy", req, "hybrid", use_llm=False, scale=3)
pf=benchmark.run_one_bench("ab-pf", req, "prefix", use_llm=False, scale=3)
assert hy["output_ok"] and pf["output_ok"], "两者都应成功"
# 核心优化验证：水龙头蔓延 token 显著低于散沙
assert pf["token_usage"] < hy["token_usage"], f"prefix token 应低于 hybrid，实为 prefix={pf[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(117)+chr(115)+chr(97)+chr(103)+chr(101)]} hybrid={hy[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(117)+chr(115)+chr(97)+chr(103)+chr(101)]}"
# bug 也应低于或等于散沙（共享上下文一致 → 出错面收窄）
assert pf["bug_count"] <= hy["bug_count"], f"prefix bug 应≤hybrid，实为 prefix={pf[chr(98)+chr(117)+chr(103)+chr(95)+chr(99)+chr(111)+chr(117)+chr(110)+chr(116)]} hybrid={hy[chr(98)+chr(117)+chr(103)+chr(95)+chr(99)+chr(111)+chr(117)+chr(110)+chr(116)]}"
# 水龙头用缓存复用换 token 效率，prefix_saved 为正
assert pf["prefix_saved_chars"] > 0
print(f"hybrid(散沙): token={hy[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(117)+chr(115)+chr(97)+chr(103)+chr(101)]} bug={hy[chr(98)+chr(117)+chr(103)+chr(95)+chr(99)+chr(111)+chr(117)+chr(110)+chr(116)]}")
print(f"prefix(水龙头): token={pf[chr(116)+chr(111)+chr(107)+chr(101)+chr(110)+chr(95)+chr(117)+chr(115)+chr(97)+chr(103)+chr(101)]} bug={pf[chr(98)+chr(117)+chr(103)+chr(95)+chr(99)+chr(111)+chr(117)+chr(110)+chr(116)]} 节省字符={pf[chr(112)+chr(114)+chr(101)+chr(102)+chr(105)+chr(120)+chr(95)+chr(115)+chr(97)+chr(118)+chr(101)+chr(100)+chr(95)+chr(99)+chr(104)+chr(97)+chr(114)+chr(115)]}")
print("✅ 优化验证通过：水龙头蔓延降 token、降 bug")
PY'

echo ""
echo "==== 结果: ${pass} 通过, ${fail} 失败 ===="
[ "$fail" -eq 0 ]
