#!/usr/bin/env bash
# ============================================================
# 复杂度递进式精简体系测试（test_topology_slim）
# ============================================================
# 验证 Issue #41 再设计（架构·总师迭代）与「规模金字塔→承接体系」互补：
#   复杂度递进式精简体系（micro/small/medium/large/huge 金字塔档位）
#   - 越小的部分占比越高、角色子集越精简（micro→单名开发）
#   - 缓存命中为主线贯穿所有档位（非仅大规模）
#   - 分工协作以能完成目标为准，高复杂/大型才兼顾快速提速
#   - 融合路由集成：micro→单名开发 / small→产品+开发，route 结果带 slim 角色子集
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SLIM="$ROOT/topology/slim.py"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

check() { # desc, actual, expect
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi
}

echo "== 复杂度递进式精简体系 =="

# 1. micro → 单名开发，最简角色子集
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;r=slim.slim_route('micro');print(r['tier'])")
check "micro 档存在" "$R" "micro"
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;r=slim.slim_route('micro');print(len(r['roles']))")
check "micro 角色子集仅1个（单名开发）" "$R" "1"

# 2. small → 产品+开发，2 角色
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;print(len(slim.slim_route('small')['roles']))")
check "small 角色子集2个（产品+开发）" "$R" "2"

# 3. medium → 需架构师，4 角色
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;print('架构·总师' in slim.slim_route('medium')['roles'])")
check "medium 含架构师" "$R" "True"

# 4. large → 公司结构拉满（含小组长/测试）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;r=slim.slim_route('large');print('架构·小组长' in r['roles'] and '架构·测试' in r['roles'])")
check "large 公司结构拉满" "$R" "True"

# 5. huge → 完整体系（含监控哨兵/数据管理员）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;r=slim.slim_route('huge');print('架构·监控哨兵' in r['roles'] and '架构·数据管理员' in r['roles'])")
check "huge 完整体系+动态扩容角色" "$R" "True"

# 6. 缓存命中为主线：所有档位都带 cache 主线
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;print(all('缓存命中' in slim.CACHE[t] for t in slim.ROLE_SUBSETS))")
check "所有档位 cache 均含主线" "$R" "True"

# 7. 占比递减：越小占比越高（micro 最高，huge 最低）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;print(slim.RATIO['micro']>slim.RATIO['small']>slim.RATIO['medium']>slim.RATIO['large']>slim.RATIO['huge'])")
check "占比递减（越小越高）" "$R" "True"

# 8. 融合路由：micro → route 结果带 slim 角色子集（单名开发）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(len(fusion.route(complexity=0,subtasks=1,concurrency=1)['slim']['roles']))")
check "融合路由 micro slim 单名开发" "$R" "1"

# 9. 融合路由：small → slim 产品+开发
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(len(fusion.route(complexity=2,subtasks=3,concurrency=1)['slim']['roles']))")
check "融合路由 small slim 产品+开发" "$R" "2"

# 10. 中规模不回归：medium 仍加架构师（dag）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.route(complexity=4,subtasks=10,concurrency=3)['selected'])")
check "中规模不回归仍选 dag" "$R" "dag"

# 11. slim_route 便捷 API
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import fusion;print(fusion.slim_route('micro')['tier'])")
check "fusion.slim_route 便捷 API" "$R" "micro"

# 12. slim overview 全档俯视图
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from topology import slim;ov=slim.overview();print(len(ov['tiers'])==5)")
check "slim overview 5档俯视图" "$R" "True"

echo ""
echo "==========================="
echo "复杂度递进式精简体系: PASS=$PASS FAIL=$FAIL"
echo "==========================="
