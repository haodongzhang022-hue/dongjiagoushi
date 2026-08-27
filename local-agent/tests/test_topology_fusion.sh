#!/usr/bin/env bash
# ============================================================
# 融合拓扑规则引擎测试（test_topology_fusion）
# ============================================================
# 验证 Issue #41「按任务规模分层选择承接体系 + 拓扑」：
#   ★ 规模金字塔 → 承接体系（用户纠偏核心：小任务占比最高最该优化）
#   1. micro（单任务修改）→ 简化体系·敏捷（agile：产品→开发→审查）
#   2. small（低复杂度）  → 敏捷开发（agile，仍轻量）
#   3. medium（中等）     → 加架构师（architected → dag）
#   4. large（高复杂度）  → 公司结构拉满（company → dag）
#   5. huge（极高/大型）  → 完整体系 + 蔓延（full → prefix 融合）
#   6. 散沙型高并发 → 一窝蜂 scatter
#   7. 缓存命中为主线（cache-first）横贯所有档位
#   8. 四套配套方案随选择产出
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

echo "== 融合拓扑规则引擎（规模金字塔 → 承接体系，缓存命中为主线）=="

# 1. micro（单任务修改）→ 简化体系·敏捷 agile（占比最高最该优化）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;r=fusion.route(complexity=0,subtasks=1,concurrency=1);print(r['tier']+'|'+r['system']+'|'+r['selected'])")
check "micro 档=简化体系·敏捷 agile" "$R" "micro|agile|agile"

# 2. small（低复杂度）→ 敏捷开发 agile（仍轻量）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;r=fusion.route(complexity=2,subtasks=3,concurrency=1);print(r['tier']+'|'+r['system']+'|'+r['selected'])")
check "small 档=敏捷开发 agile" "$R" "small|agile|agile"

# 3. medium（中等）→ 加架构师 architected → dag
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;r=fusion.route(complexity=4,subtasks=10,concurrency=3);print(r['tier']+'|'+r['system']+'|'+r['selected'])")
check "medium 档=加架构师 dag" "$R" "medium|architected|dag"

# 4. large（高复杂度）→ 公司结构拉满 company → dag
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;r=fusion.route(complexity=7,subtasks=25,concurrency=3,is_scattered=False);print(r['tier']+'|'+r['system']+'|'+r['selected'])")
check "large 档=公司拉满 dag" "$R" "large|company|dag"

# 5. huge（极高复杂度/大型）→ 完整体系 full → prefix 融合（水龙头蔓延）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;r=fusion.route(complexity=9,subtasks=60,concurrency=3,is_scattered=False);print(r['tier']+'|'+r['system']+'|'+r['selected'])")
check "huge 档=完整体系 prefix" "$R" "huge|full|prefix"

# 6. 散沙型高并发 → 一窝蜂 scatter（优先级高于规模档位）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=3,subtasks=20,concurrency=30,is_scattered=True)['selected'])")
check "散沙高并发选一窝蜂 scatter" "$R" "scatter"

# 7. scale_exceeded 在 huge 时为 True
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.evaluate_scale(complexity=10,subtasks=100,concurrency=5)['signals']['scale_exceeded'])")
check "huge 档 scale_exceeded=True" "$R" "True"

# 8. 四套配套方案随选择产出（cache/division/reporting/merge）
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
p=fusion.route(complexity=9,subtasks=60,concurrency=5,is_scattered=False)['plan']
print(sorted(p.keys())==['cache','division','merge','reporting'])")
check "四套配套方案齐全" "$R" "True"

# 9. 缓存命中为主线（cache-first）：agile 简化体系方案也含水龙头/共享前缀复用
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
p=fusion.route(complexity=1,subtasks=2,concurrency=1)['plan']
print('主线·缓存命中' in p['cache'] and '共享需求前缀' in p['cache'])")
check "agile 缓存命中为主线（cache-first）" "$R" "True"

# 10. 融合场景缓存方案含水龙头蔓延
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
p=fusion.route(complexity=9,subtasks=60,concurrency=5,is_scattered=False)['plan']
print('水龙头' in p['cache'])")
check "融合场景缓存方案含水龙头蔓延" "$R" "True"

# 11. overview 提供二级信息（含承接体系映射）
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT');from topology import fusion
from topology.fusion import evaluate_scale
ov=fusion.overview([evaluate_scale(complexity=0,subtasks=1,concurrency=1)])
print(len(ov['rows'])==1 and 'tiers' in ov and 'micro' in ov['tiers'])")
check "overview 二级信息可用（含 micro 承接体系）" "$R" "True"

# 12. CLI --overview 可运行
R=$(cd "$ROOT" && python3 topology/fusion.py --overview >/dev/null 2>&1 && echo "ok")
check "CLI overview 运行" "$R" "ok"

echo ""
echo "==========================="
echo "融合拓扑规则引擎: PASS=$PASS FAIL=$FAIL"
echo "==========================="
[ "$FAIL" = "0" ] || exit 1
