#!/usr/bin/env bash
# ============================================================
# 增量测试选择器 IncrementalSelector 功能测试（hybrid/selector v2.0）
# 仓库：dongjiagoushi（架构师体系 · 测试智能优化层 T2）
#
# 验证 IncrementalSelector 的 git diff → 受影响测试选择。
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

echo "== IncrementalSelector 增量测试选择器 =="

# 1. 选择器初始化 + 单例
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector, default_selector
s = IncrementalSelector(root_dir='$ROOT')
assert s is not None, 'failed to init'
assert default_selector is not None, 'singleton failed'
print('OK')
")
[ "$R" = "OK" ] && ok "IncrementalSelector 初始化 + 单例" || bad "初始化失败: $R"

# 2. select() 给定变更文件 → 返回受影响测试（含依赖传播）
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
# 变更 collab/engine.py → test_collab + test_peer_collab + test_peer_closure
selected = s.select(['collab/engine.py'])
assert 'local-agent/tests/test_collab.sh' in selected, f'missing collab: {selected}'
assert 'local-agent/tests/test_peer_collab.sh' in selected, f'missing peer_collab: {selected}'
# 变更 engine/state_machine.py → test_engine
selected2 = s.select(['engine/state_machine.py'])
assert selected2 == ['local-agent/tests/test_engine.sh'], f'got: {selected2}'
print('OK')
")
[ "$R" = "OK" ] && ok "select() 变更→受影响测试（含依赖传播）" || bad "select failed: $R"

# 2b. 路径归一化：local-agent/ 前缀与裸路径双向兼容（与 T1 registry v2.1 对齐）
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
# 带 local-agent/ 前缀的变更文件同样命中（裸 covers 场景）
selected = s.select(['local-agent/collab/engine.py'])
assert 'local-agent/tests/test_collab.sh' in selected, f'missing collab: {selected}'
assert 'local-agent/tests/test_peer_collab.sh' in selected, f'missing peer_collab: {selected}'
selected2 = s.select(['local-agent/engine/state_machine.py'])
assert selected2 == ['local-agent/tests/test_engine.sh'], f'got: {selected2}'
print('OK')
")
[ "$R" = "OK" ] && ok "路径归一化：local-agent/ 前缀与裸路径双向兼容" || bad "路径归一化失败: $R"

# 2c. registry covers 统一为 local-agent/ 前缀时（T1 v2.1），裸路径变更仍可命中
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
class PrefixedReg:
    def all_tests(self):
        return ['local-agent/tests/test_collab.sh','local-agent/tests/test_peer_collab.sh','local-agent/tests/test_engine.sh']
    def get(self, t):
        return {
          'local-agent/tests/test_collab.sh': {'covers':['local-agent/collab/engine.py'],'depends_on':[]},
          'local-agent/tests/test_peer_collab.sh': {'covers':['local-agent/collab/peer.py'],'depends_on':['local-agent/tests/test_collab.sh']},
          'local-agent/tests/test_engine.sh': {'covers':['local-agent/engine/state_machine.py'],'depends_on':[]},
        }[t]
s = IncrementalSelector(root_dir='$ROOT', registry=PrefixedReg())
selected = s.select(['collab/engine.py'])
assert 'local-agent/tests/test_collab.sh' in selected, f'missing collab: {selected}'
assert 'local-agent/tests/test_peer_collab.sh' in selected, f'missing peer_collab: {selected}'
selected2 = s.select(['engine/state_machine.py'])
assert selected2 == ['local-agent/tests/test_engine.sh'], f'got: {selected2}'
print('OK')
")
[ "$R" = "OK" ] && ok "前缀 covers + 裸路径变更双向命中（T1 v2.1 兼容）" || bad "v2.1 前缀 covers 兼容失败: $R"

# 3. select() 过滤测试文件自身
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
# 变更一个 .sh 测试文件本身 → 不触发任何测试
selected = s.select(['local-agent/tests/test_engine.sh'])
assert selected == [], f'selected={selected}'
print('OK')
")
[ "$R" = "OK" ] && ok "select() 过滤测试文件自身" || bad "过滤测试文件失败: $R"

# 4. select() 空变更 → 空列表
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
assert s.select([]) == [], 'empty should return empty'
print('OK')
")
[ "$R" = "OK" ] && ok "select() 空变更 → 空列表" || bad "空变更处理失败: $R"

# 5. full_suite() 全量兜底
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
suite = s.full_suite()
assert len(suite) >= 40, f'full suite too small: {len(suite)}'
assert 'local-agent/tests/test_engine.sh' in suite, 'test_engine.sh missing'
print('OK')
")
[ "$R" = "OK" ] && ok "full_suite() 全量兜底" || bad "full_suite failed: $R"

# 6. incremental() 用 git diff 获取变更 → 选择受影响测试
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
# 用当前提交和工作区变更测试 git diff（比较 main~1 到 main）
files = s.changed_files('HEAD~1', 'HEAD')
assert isinstance(files, list), f'changed_files should return list, got {type(files)}'
print('OK')
")
[ "$R" = "OK" ] && ok "changed_files() git diff 获取变更" || bad "changed_files failed: $R"

# 7. incremental_workdir() 工作区变更
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
files = s.changed_files_workdir()
assert isinstance(files, list), f'changed_files_workdir should return list'
# 当前分支应有未提交的 selector 相关文件
print('OK')
")
[ "$R" = "OK" ] && ok "changed_files_workdir() 工作区变更" || bad "changed_files_workdir failed: $R"

# 8. incremental() 完整链路
R=$(python3 -c "
import sys; sys.path.insert(0, '$ROOT')
from hybrid import IncrementalSelector
s = IncrementalSelector(root_dir='$ROOT')
selected = s.incremental()
assert isinstance(selected, list), f'selected should be list, got {type(selected)}'
# 可能为空（当前提交没改源码文件）但不应报错
print('OK')
")
[ "$R" = "OK" ] && ok "incremental() 完整链路不报错" || bad "incremental failed: $R"

echo ""
echo "===== IncrementalSelector 测试结果: PASS=$PASS FAIL=$FAIL ====="
[ "$FAIL" = "0" ] || exit 1
