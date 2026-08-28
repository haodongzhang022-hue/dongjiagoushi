#!/usr/bin/env bash
# ============================================================
# ParallelExecutor 测试（test_hybrid_parallel.sh · Issue #65 T4）
# ============================================================
# 验证 ParallelExecutor：
#   1. 并行执行多个测试脚本
#   2. 结果聚合（pass/fail/timeout 计数）
#   3. 超时聚合（脚本超时 → timeout 状态）
#   4. 失败隔离（单个失败不影响其他）
#   5. dry_run 演练模式
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== ParallelExecutor 测试 =="

# ---------- 1. dry_run 演练 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
ex = ParallelExecutor(max_workers=2, dry_run=True)
result = ex.run(['test_a.sh', 'test_b.sh'])
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail']))
")
check "dry_run 2脚本全通过" "$R" "2|2|0"

# ---------- 2. 并行执行多个测试 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
# 创建两个简单测试脚本
for i, name in enumerate(['test_p1.sh', 'test_p2.sh']):
    with open(os.path.join(tmpdir, name), 'w') as f:
        f.write('#!/usr/bin/env bash\necho ok' + str(i + 1) + '\nexit 0\n')
    os.chmod(os.path.join(tmpdir, name), 0o755)

ex = ParallelExecutor(max_workers=2, timeout=30, root_dir=tmpdir)
result = ex.run(['test_p1.sh', 'test_p2.sh'])
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail'])+'|'+str(s['timeout']))
")
check "并行2脚本全通过" "$R" "2|2|0|0"

# ---------- 3. 失败隔离：单个失败不影响其他 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
# 第一个失败，第二个通过
with open(os.path.join(tmpdir, 'test_fail.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho failing\nexit 1\n')
with open(os.path.join(tmpdir, 'test_pass.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho ok\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_fail.sh'), 0o755)
os.chmod(os.path.join(tmpdir, 'test_pass.sh'), 0o755)

ex = ParallelExecutor(max_workers=2, timeout=30, root_dir=tmpdir)
result = ex.run(['test_fail.sh', 'test_pass.sh'])
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail']))
# 检查失败脚本的 status
for r in result['results']:
    if 'test_fail' in r['script']:
        print('fail_status='+str(r['status']))
")
check "失败隔离 total=2" "$(echo "$R" | head -1 | cut -d'|' -f1)" "2"
check "失败隔离 pass=1" "$(echo "$R" | head -1 | cut -d'|' -f2)" "1"
check "失败隔离 fail=1" "$(echo "$R" | head -1 | cut -d'|' -f3)" "1"
check "失败脚本标记fail" "$(echo "$R" | grep 'fail_status=' | cut -d'=' -f2)" "fail"

# ---------- 4. 超时聚合 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
# 一个超时脚本（sleep 5），一个正常
with open(os.path.join(tmpdir, 'test_slow.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\nsleep 5\nexit 0\n')
with open(os.path.join(tmpdir, 'test_fast.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho fast\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_slow.sh'), 0o755)
os.chmod(os.path.join(tmpdir, 'test_fast.sh'), 0o755)

ex = ParallelExecutor(max_workers=2, timeout=1, root_dir=tmpdir)
result = ex.run(['test_slow.sh', 'test_fast.sh'])
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail'])+'|'+str(s['timeout']))
for r in result['results']:
    if 'test_slow' in r['script']:
        print('slow_status='+str(r['status']))
        print('slow_code='+str(r['exit_code']))
")
check "超时聚合 total=2" "$(echo "$R" | head -1 | grep -o '^2')" "2"
check "超时聚合 pass=1" "$(echo "$R" | head -1 | cut -d'|' -f2)" "1"
check "超时聚合 timeout=1" "$(echo "$R" | head -1 | cut -d'|' -f4)" "1"
check "超时脚本标timeout" "$(echo "$R" | grep 'slow_status=' | cut -d'=' -f2)" "timeout"
check "超时exit_code=124" "$(echo "$R" | grep 'slow_code=' | cut -d'=' -f2)" "124"

# ---------- 5. 空脚本列表 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
ex = ParallelExecutor(max_workers=2)
result = ex.run([])
s = result['summary']
print(str(s['total']))
")
check "空列表 total=0" "$R" "0"

# ---------- 6. run_many 兼容接口 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
with open(os.path.join(tmpdir, 'test_a.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_a.sh'), 0o755)

ex = ParallelExecutor(max_workers=2, timeout=30, root_dir=tmpdir)
result = ex.run_many(['test_a.sh'])
print(result['summary']['total'])
")
check "run_many 兼容接口" "$R" "1"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
