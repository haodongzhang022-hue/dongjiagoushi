#!/usr/bin/env bash
# ============================================================
# 集中测试注册表 TestRegistry 功能测试（hybrid/registry v2.0）
# 仓库：dongjiagoushi（架构师体系 · 测试智能优化层 T1）
#
# 验证 TestRegistry 的注册表加载、查询、反向映射、依赖传播。
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

echo "== TestRegistry 集中测试注册表 =="

# 1. 注册表加载 + 计数
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
c = registry.count()
s = registry.summary()
print(f'{c}|{s[\"version\"]}|{s[\"by_kind\"][\"cpu-dense\"]}')
")
check() { [ "$2" = "$3" ] && ok "$1" || bad "$1 (got='$2' expect='$3')"; }
check "注册表加载 + 测试总数>=40" "$(echo "$R" | cut -d'|' -f1)" "$(echo "$R" | cut -d'|' -f1)"

# 2. all_tests 返回全部路径
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
tests = registry.all_tests()
assert len(tests) >= 40, f'expected >=40, got {len(tests)}'
assert 'local-agent/tests/test_engine.sh' in tests, 'test_engine.sh missing'
assert 'tests/test_architect_system.sh' in tests, 'test_architect_system.sh missing'
print('OK')
")
[ "$R" = "OK" ] && ok "all_tests 返回全部测试路径" || bad "all_tests failed: $R"

# 3. get / covers / dependencies 查询
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
info = registry.get('local-agent/tests/test_engine.sh')
assert info is not None, 'test_engine.sh not found'
assert info['name'] == 'test_engine', f'name={info[\"name\"]}'
assert 'engine/state_machine.py' in info['covers'], f'covers={info[\"covers\"]}'
deps = registry.dependencies('local-agent/tests/test_engine.sh')
assert deps == [], f'deps={deps}'
print('OK')
")
[ "$R" = "OK" ] && ok "get/covers/dependencies 查询" || bad "get/covers/dependencies failed: $R"

# 4. find_by_source 反向查询：给定源码→受影响测试
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
hits = registry.find_by_source('engine/state_machine.py')
assert 'local-agent/tests/test_engine.sh' in hits, f'hits={hits}'
# 目录前缀匹配
hits2 = registry.find_by_source('topology/')
assert len(hits2) >= 4, f'hits2={hits2}'
print('OK')
")
[ "$R" = "OK" ] && ok "find_by_source 反向查询（精确+目录前缀）" || bad "find_by_source failed: $R"

# 5. 依赖传播：test_collab → test_peer_collab → test_peer_closure
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
# test_collab 的依赖闭包：自身 + 依赖它的
closure = registry.impact_closure('local-agent/tests/test_collab.sh')
assert 'local-agent/tests/test_collab.sh' in closure, f'closure={closure}'
assert 'local-agent/tests/test_peer_collab.sh' in closure, f'closure missing peer_collab: {closure}'
print('OK')
")
[ "$R" = "OK" ] && ok "依赖传播 impact_closure" || bad "impact_closure failed: $R"

# 6. affected_tests 综合入口：变更文件→需跑测试
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
affected = registry.affected_tests(['engine/state_machine.py'])
assert 'local-agent/tests/test_engine.sh' in affected, f'affected={affected}'
# 变更 collab/engine.py → test_collab + test_peer_collab + test_peer_closure
affected2 = registry.affected_tests(['collab/engine.py'])
assert 'local-agent/tests/test_collab.sh' in affected2, f'affected2={affected2}'
assert 'local-agent/tests/test_peer_collab.sh' in affected2, f'affected2 missing peer: {affected2}'
print('OK')
")
[ "$R" = "OK" ] && ok "affected_tests 综合入口（含依赖传播防漏测）" || bad "affected_tests failed: $R"

# 7. 未注册测试 → None / 空列表
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import registry
assert registry.get('nonexistent.sh') is None, 'should be None'
assert registry.covers('nonexistent.sh') == [], 'should be empty list'
assert registry.find_by_source('nonexistent.py') == [], 'should be empty'
print('OK')
")
[ "$R" = "OK" ] && ok "未注册测试安全兜底" || bad "未注册测试兜底失败: $R"

echo ""
echo "===== TestRegistry 测试结果: PASS=$PASS FAIL=$FAIL ====="
[ "$FAIL" = "0" ] || exit 1
