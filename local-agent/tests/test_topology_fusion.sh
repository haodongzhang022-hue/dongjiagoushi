#!/usr/bin/env bash
# ============================================================
# 融合拓扑规则引擎测试（test_topology_fusion）
# ============================================================
# 验证 Issue #41「按任务规模选择拓扑 + 融合触发门控」：
#   1. 小规模 → 轻量一窝蜂（scatter）
#   2. 中/大规模 → 公司式分工（dag），承载 ~98%
#   3. 超大规模（规模超默认承载）→ 触发融合（hybrid/prefix）
#   4. 散沙型高并发 → 直接用新框架一窝蜂
#   5. 四套配套方案（cache/division/reporting/merge）随选择产出
#   6. 提供 overview 二级信息供人类俯瞰
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/topology/fusion.py"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

check() { # desc, actual, expect
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi
}

echo "== 融合拓扑规则引擎 =="

# 1. 小规模 → 轻量一窝蜂 scatter
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=1,subtasks=2,concurrency=1)['selected'])")
check "小规模选轻量一窝蜂 scatter" "$R" "scatter"

# 2. 中规模 → 公司式分工 dag
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=4,subtasks=10,concurrency=3)['selected'])")
check "中规模选公司式分工 dag" "$R" "dag"

# 3. 大规模（未超载、非散沙）→ dag
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=7,subtasks=30,concurrency=5,is_scattered=False)['selected'])")
check "大规模非散沙选 dag" "$R" "dag"

# 4. 超大规模（规模超默认承载）→ 融合 prefix
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=9,subtasks=60,concurrency=5,is_scattered=False)['selected'])")
check "超大规模触发融合 prefix" "$R" "prefix"

# 5. 散沙型高并发 → 新框架一窝蜂 scatter
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=3,subtasks=20,concurrency=30,is_scattered=True)['selected'])")
check "散沙高并发选一窝蜂 scatter" "$R" "scatter"

# 6. scale_exceeded 信号在超大规模时为 True
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.evaluate_scale(complexity=10,subtasks=100,concurrency=5)['signals']['scale_exceeded'])")
check "超大规模 scale_exceeded=True" "$R" "True"

# 7. 四套配套方案随选择产出（cache/division/reporting/merge）
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
p=fusion.route(complexity=9,subtasks=60,concurrency=5,is_scattered=False)['plan']
print(sorted(p.keys())==['cache','division','merge','reporting'])")
check "四套配套方案齐全" "$R" "True"

# 8. 缓存命中方案内容（融合场景含水龙头蔓延）
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
p=fusion.route(complexity=9,subtasks=60,concurrency=5,is_scattered=False)['plan']
print('水龙头' in p['cache'])")
check "融合场景缓存方案含水龙头蔓延" "$R" "True"

# 9. overview 提供二级信息
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
from topology.fusion import evaluate_scale
ov=fusion.overview([evaluate_scale(complexity=1,subtasks=2,concurrency=1,is_scattered=True)])
print(len(ov['rows'])==1 and 'rule' in ov)")
check "overview 二级信息可用" "$R" "True"

# 10. CLI --overview 可运行
R=$(cd "$ROOT" && python3 topology/fusion.py --overview >/dev/null 2>&1 && echo "ok")
check "CLI overview 运行" "$R" "ok"

echo ""
echo "==========================="
echo "融合拓扑规则引擎: PASS=$PASS FAIL=$FAIL"
echo "==========================="
[ "$FAIL" = "0" ] || exit 1
