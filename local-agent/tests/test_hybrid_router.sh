#!/usr/bin/env bash
# ============================================================
# HybridResourceRouter 路由核心测试（test_hybrid_router）
# ============================================================
# 验证 Issue #57「云原生构建-CPU 本地化」：
#   1. 纯 CPU 脚本 → local
#   2. LLM 强相关脚本 → cloud（能力保留）
#   3. 兜底默认 cloud（fail-safe 不误伤）
#   4. route_many 批量判定 + 聚合统计
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== HybridResourceRouter 路由核心 =="

# 1. 纯 CPU 脚本 → local
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('test_unit_cpu.sh'))")
check "纯CPU test_unit_cpu.sh → local" "$R" "local"

R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('benchmark_compare.sh'))")
check "benchmark_compare.sh → local" "$R" "local"

R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('local-agent/tests/test_scale.sh'))")
check "test_scale.sh → local" "$R" "local"

# 2. LLM 强相关 → cloud
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('llm_knowledge_update'))")
check "LLM llm_knowledge_update → cloud" "$R" "cloud"

R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('knowledge:update'))")
check "knowledge:update → cloud" "$R" "cloud"

R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('codewiki_generate'))")
check "codewiki_generate → cloud" "$R" "cloud"

R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('embedding_build'))")
check "embedding_build → cloud" "$R" "cloud"

# 3. 兜底默认 cloud
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.router import HybridResourceRouter;print(HybridResourceRouter().classify('some_random_task'))")
check "兜底 some_random_task → cloud" "$R" "cloud"

# 4. route_many 批量判定 + 聚合统计
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT')
from hybrid.router import HybridResourceRouter
r=HybridResourceRouter()
tasks=[('test_unit_cpu.sh',5,20),('test_scale.sh',10,30),('llm_knowledge_update',5,15),('mystery_task',1,2)]
res=r.route_many(tasks)
s=res['summary']
print(str(s['total'])+'|'+str(s['local'])+'|'+str(s['cloud']))
")
check "route_many 4任务" "$R" "4|2|2"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
