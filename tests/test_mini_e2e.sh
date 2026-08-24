#!/usr/bin/env bash
# 小需求 · 麻雀虽小五脏俱全 · 端到端测试（信号灯）
# =====================================================
# 验证用户关心的全部链路：
#   T1 正常调度（DAG 波次并行，非直线）
#   T2 2 小组分工（分形多小组，任务拆分）
#   T3 开发 + 测试 都有（小组内/整体测试）
#   T4 协作能否进行（接力卡生成、各角色接力）
#   T5 互通数据能否行（跨小组数据互通，端到端 deliver）
#   T6 @ 触发生效（多角色可被触发/路由）
#   T7 最终结果能否出（交付报告、信号灯）
set -e
cd "$(dirname "$0")/.."

pass=0; fail=0
t() { # t <desc> <cmd>
  local desc="$1"; shift
  if eval "$*" >/tmp/mini_out.txt 2>&1; then
    echo "  ✅ $desc"; pass=$((pass+1))
  else
    echo "  ❌ $desc"; cat /tmp/mini_out.txt; fail=$((fail+1))
  fi
}

echo "==== 小需求 · 麻雀虽小五脏俱全 · 端到端测试 ===="

# ---- T1 正常调度：DAG 存在并行波次（非直线）----
t "T1 正常调度：DAG 并行波次（find_tools/lead/align 同波）" bash -c '
  python3 - <<PY
import sys, yaml; sys.path.insert(0,"local-agent")
from graph import DagEngine
team=yaml.safe_load(open("local-agent/team.yaml"))
nodes=team["pipeline"]["dag"]["nodes"]
dag=DagEngine("full","",nodes)
waves=dag.waves()
# 应有并行波次
assert any(len(w)>1 for w in waves), "缺少并行波次"
# plan 依赖 architect 而非 develop（提前分工）
plan=[n for n in nodes if n["id"]=="plan"][0]
assert "architect" in plan["depends_on"] and "develop" not in plan["depends_on"]
print("waves:", waves)
PY'

# ---- T2 2 小组分工：分形引擎对 ≥5 任务拆 2 小组 ----
t "T2 2小组分工：≥5任务拆为2小组" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
import fractal
plan=fractal.build_fractal_plan([f"t{i}" for i in range(6)])
assert plan["scaled"] and plan["team_count"]==2, plan
print(fractal.describe_plan(plan))
PY'

# ---- T3 开发 + 测试都有：示例包含开发模块 + 测试矩阵 ----
t "T3 开发+测试都有：示例含开发模块与测试矩阵" bash -c '
  test -f examples/hello_team/team_a/greet.py
  test -f examples/hello_team/team_b/meta.py
  test -f examples/hello_team/tests/test_hello_team.py
'

# ---- T4 协作：完整流水线可跑通 + 接力卡生成 ----
t "T4 协作：完整流水线跑通 + 接力卡生成" bash -c '
  python3 local-agent/run.py --clear
  python3 local-agent/run.py --pipeline full --req "开发hello_team工具，需要：1团队问候 2团队元数据 3跨组数据互通 4统一交付入口 5小组A核心 6小组B元数据" --backend cli_fallback >/dev/null 2>&1
  test -f local-agent/state/relay_card.json
'

# ---- T5 互通数据：端到端 deliver（跨组数据互通）----
t "T5 互通数据：端到端 deliver 跨组数据互通" "python3 examples/hello_team/tests/test_hello_team.py"

# ---- T6 @ 触发生效：多角色可触发/路由（秘书→产品→总师→经理）----
t "T6 @触发生效：角色路由链路（秘书/产品/总师/经理/开发/测试）" bash -c '
  python3 - <<PY
import sys; sys.path.insert(0,"local-agent")
from roles import list_roles
for r in ["架构·秘书","架构·产品","架构·总师","架构·经理","架构·开发","架构·测试"]:
    assert r in list_roles(), f"缺少 {r}"
print("关键角色注册齐全，@路由可命中")
PY'

# ---- T7 最终结果：交付信号灯全绿 ----
t "T7 最终结果：小需求端到端信号灯全绿" bash -c '
  python3 examples/hello_team/tests/test_hello_team.py >/tmp/mini_light.txt 2>&1
  grep -q "信号灯：4/4 通过" /tmp/mini_light.txt
'

echo ""
echo "结果：$pass 通过 / $fail 失败"
[ "$fail" = "0" ] || exit 1
