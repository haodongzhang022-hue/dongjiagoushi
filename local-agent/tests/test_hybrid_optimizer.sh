#!/usr/bin/env bash
# ============================================================
# 测试智能优化层测试（test_hybrid_optimizer.sh）
# ============================================================
# 验证 Issue #65「测试智能优化层」：
#   T1 TestRegistry — 集中测试注册表 JSON，可程序化查询
#   T2 IncrementalSelector — git diff → 受影响测试选择器 + 依赖传播
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== 测试智能优化层：Registry + Selector =="

# ============ T1: TestRegistry ============
echo ""
echo "--- T1: TestRegistry 注册表 ---"

# 1. 注册表文件存在且可加载
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
print(str(len(r.all_script_names())))
")
check "注册表含 32 个测试脚本" "$R" "32"

# 2. 查询单个文件 → 对应测试
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
tests = r.tests_for_file('local-agent/hybrid/router.py')
print('|'.join(tests))
")
echo "  hybrid/router.py → $R"
if echo "$R" | grep -q "test_hybrid_router.sh"; then ok "router.py 命中 test_hybrid_router.sh"; else bad "router.py 未命中测试: $R"; fi

# 3. 目录匹配：模块目录 → 相关测试
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
tests = r.tests_for_file('local-agent/collab/engine.py')
print('|'.join(tests))
")
echo "  collab/engine.py → $R"
if echo "$R" | grep -q "test_collab.sh"; then ok "collab/engine.py 命中 test_collab.sh"; else bad "collab/engine.py 未命中: $R"; fi

# 4. 模块名查询
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
tests = r.tests_for_module('hybrid')
print('|'.join(tests))
")
echo "  hybrid 模块 → $R"
if echo "$R" | grep -q "test_hybrid_router.sh"; then ok "hybrid 模块命中 test_hybrid_router.sh"; else bad "hybrid 模块未命中: $R"; fi
if echo "$R" | grep -q "test_hybrid_pipeline.sh"; then ok "hybrid 模块命中 test_hybrid_pipeline.sh"; else bad "hybrid 模块未命中 pipeline: $R"; fi

# 5. 注册表摘要
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
s = r.summary()
print(str(s['total_scripts'])+'|'+str(s['total_covers']))
")
check "注册表摘要（32 脚本）" "$R" "32|35"

# 6. 依赖传播：改 data 层基础设施 → 所有依赖 data 的测试纳入
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
tests = r.affected(['local-agent/data/schema.py'])
print('|'.join(tests))
")
echo "  data/schema.py 变更 → $R"
# data 是公共基础设施，应该有大量测试依赖它
COUNT=$(echo "$R" | tr '|' '\n' | wc -l)
if [ "$COUNT" -ge 10 ]; then ok "data/schema.py 依赖传播（≥10 个测试）"; else bad "data/schema.py 传播过少（$COUNT 个）: $R"; fi

# 7. 依赖传播：改 hybrid 模块 → 相关测试纳入
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
tests = r.affected(['local-agent/hybrid/router.py'])
print('|'.join(tests))
")
echo "  hybrid/router.py 变更 → $R"
if echo "$R" | grep -q "test_hybrid_router.sh"; then ok "hybrid/router.py → test_hybrid_router.sh"; else bad "未命中: $R"; fi

# 8. 增量测试（非全量）：只返回受影响测试
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.registry import TestRegistry
r = TestRegistry()
tests = r.affected(['local-agent/hybrid/router.py'])
all_tests = r.all_script_names()
print(str(len(tests))+'/'+str(len(all_tests)))
")
echo "  增量比: $R（受影响/全量）"
NUM=$(echo "$R" | cut -d'/' -f1)
if [ "$NUM" -lt 32 ] && [ "$NUM" -gt 0 ]; then ok "增量选择生效（只跑 $NUM 个）"; else bad "增量选择失败: $R"; fi

# ============ T2: IncrementalSelector ============
echo ""
echo "--- T2: IncrementalSelector ---"

# 9. Selector 基于 Registry 选择测试
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.selector import IncrementalSelector
from hybrid.registry import TestRegistry
reg = TestRegistry()
sel = IncrementalSelector(registry=reg)
result = sel.select(changed_files=['local-agent/hybrid/router.py'])
print('|'.join(result['tests']))
")
echo "  git diff 变更 → $R"
if echo "$R" | grep -q "test_hybrid_router.sh"; then ok "selector 命中 hybrid 测试"; else bad "selector 未命中: $R"; fi

# 10. Selector 空变更 → 空测试清单
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.selector import IncrementalSelector
from hybrid.registry import TestRegistry
sel = IncrementalSelector(registry=TestRegistry())
result = sel.select(changed_files=[])
print(str(len(result['tests'])))
")
check "空变更 → 空测试清单" "$R" "0"

# 11. Selector 过滤非源码文件
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.selector import IncrementalSelector
from hybrid.registry import TestRegistry
sel = IncrementalSelector(registry=TestRegistry())
result = sel.select(changed_files=['README.md', '.gitignore'])
print(str(len(result['tests'])))
")
check "文档变更 → 不触发测试" "$R" "0"

# 12. 显式传入文件列表 → 精确选择
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.selector import IncrementalSelector
from hybrid.registry import TestRegistry
sel = IncrementalSelector(registry=TestRegistry())
result = sel.select(changed_files=['local-agent/collab/peer.py'])
tests = result['tests']
print('|'.join(tests))
")
echo "  collab/peer.py → $R"
if echo "$R" | grep -q "test_peer_collab.sh"; then ok "peer.py 命中 test_peer_collab.sh"; else bad "peer.py 未命中: $R"; fi

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
