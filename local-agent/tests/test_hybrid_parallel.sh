#!/usr/bin/env bash
# ============================================================
# ParallelExecutor 测试（test_hybrid_parallel.sh · Issue #65 T4）
# ============================================================
# 验证 ParallelExecutor（继承 LocalWorker 的并行执行器）：
#   1. 并行执行多个测试脚本（run_parallel, parallel=N）
#   2. 串行退化（parallel=1 / 单脚本）
#   3. 超时聚合（脚本超时 → exit_code=124，不阻塞其他）
#   4. 失败隔离（单个失败不影响其他执行）
#   5. dry_run 演练模式
#   6. 空脚本列表
#   7. 结果结构兼容（results + summary，含 wall_seconds/parallel）
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
ex = ParallelExecutor(dry_run=True)
result = ex.run_parallel(['test_a.sh', 'test_b.sh'], parallel=2)
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail'])+'|'+str(s['parallel']))
")
check "dry_run 2脚本全通过" "$R" "2|2|0|2"

# ---------- 2. 并行执行多个测试 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
for i, name in enumerate(['test_p1.sh', 'test_p2.sh', 'test_p3.sh']):
    with open(os.path.join(tmpdir, name), 'w') as f:
        f.write('#!/usr/bin/env bash\necho ok%d\nexit 0\n' % i)
    os.chmod(os.path.join(tmpdir, name), 0o755)

ex = ParallelExecutor(timeout=30, root_dir=tmpdir)
result = ex.run_parallel(['test_p1.sh', 'test_p2.sh', 'test_p3.sh'], parallel=2)
s = result['summary']
assert s['parallel']==2, 'parallel=2'
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail']))
")
check "并行3脚本全通过" "$R" "3|3|0"

# ---------- 3. 失败隔离：单个失败不影响其他 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
with open(os.path.join(tmpdir, 'test_fail.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho failing\nexit 1\n')
with open(os.path.join(tmpdir, 'test_pass.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho ok\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_fail.sh'), 0o755)
os.chmod(os.path.join(tmpdir, 'test_pass.sh'), 0o755)

ex = ParallelExecutor(timeout=30, root_dir=tmpdir)
result = ex.run_parallel(['test_fail.sh', 'test_pass.sh'], parallel=2)
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail']))
")
check "失败隔离 total=2" "$(echo "$R" | cut -d'|' -f1)" "2"
check "失败隔离 pass=1" "$(echo "$R" | cut -d'|' -f2)" "1"
check "失败隔离 fail=1" "$(echo "$R" | cut -d'|' -f3)" "1"

# ---------- 4. 超时聚合：超时 exit_code=124，不阻塞其他 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
with open(os.path.join(tmpdir, 'test_slow.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\nsleep 5\nexit 0\n')
with open(os.path.join(tmpdir, 'test_fast.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho fast\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_slow.sh'), 0o755)
os.chmod(os.path.join(tmpdir, 'test_fast.sh'), 0o755)

ex = ParallelExecutor(timeout=1, root_dir=tmpdir)
result = ex.run_parallel(['test_slow.sh', 'test_fast.sh'], parallel=2)
s = result['summary']
print(str(s['total'])+'|'+str(s['pass'])+'|'+str(s['fail']))
for r in result['results']:
    if 'test_slow' in r['script']:
        print('slow_code='+str(r['exit_code']))
    if 'test_fast' in r['script']:
        print('fast_code='+str(r['exit_code']))
")
check "超时聚合 total=2" "$(echo "$R" | head -1 | cut -d'|' -f1)" "2"
check "超时聚合 fail=1(超时计fail)" "$(echo "$R" | head -1 | cut -d'|' -f3)" "1"
check "慢脚本 exit_code=124" "$(echo "$R" | grep 'slow_code=' | cut -d'=' -f2)" "124"
check "快脚本 exit_code=0" "$(echo "$R" | grep 'fast_code=' | cut -d'=' -f2)" "0"

# ---------- 5. 空脚本列表 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
ex = ParallelExecutor()
result = ex.run_parallel([])
s = result['summary']
print(str(s['total']))
")
check "空列表 total=0" "$R" "0"

# ---------- 6. 串行退化（parallel=1）----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor
import tempfile, os

tmpdir = tempfile.mkdtemp()
for name in ['test_s1.sh', 'test_s2.sh']:
    with open(os.path.join(tmpdir, name), 'w') as f:
        f.write('#!/usr/bin/env bash\necho ok\nexit 0\n')
    os.chmod(os.path.join(tmpdir, name), 0o755)

ex = ParallelExecutor(timeout=30, root_dir=tmpdir)
result = ex.run_parallel(['test_s1.sh', 'test_s2.sh'], parallel=1)
s = result['summary']
print(str(s['parallel'])+'|'+str(s['pass'])+'|'+str(s['total']))
")
check "串行退化 parallel=1" "$R" "1|2|2"

# ---------- 7. run() 默认并行（兼容 LocalWorker 接口）----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.parallel import ParallelExecutor, default_executor
import tempfile, os

tmpdir = tempfile.mkdtemp()
with open(os.path.join(tmpdir, 'test_r1.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho ok\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_r1.sh'), 0o755)

ex = ParallelExecutor(timeout=30, root_dir=tmpdir, parallel=2)
result = ex.run(['test_r1.sh'])
s = result['summary']
assert 'wall_seconds' in s, '缺 wall_seconds'
print(str(s['pass'])+'|'+str(s['parallel']))
")
check "run() 默认并行 + wall_seconds" "$R" "1|2"

# ---------- 8. 结果结构兼容（results + summary）----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid import parallel, ParallelExecutor, default_executor
import tempfile, os

tmpdir = tempfile.mkdtemp()
with open(os.path.join(tmpdir, 'test_c1.sh'), 'w') as f:
    f.write('#!/usr/bin/env bash\necho ok\nexit 0\n')
os.chmod(os.path.join(tmpdir, 'test_c1.sh'), 0o755)

ex = ParallelExecutor(timeout=30, root_dir=tmpdir)
result = ex.run_parallel(['test_c1.sh'])
s = result['summary']
r0 = result['results'][0]
# 结构兼容：results 条目含 script/exit_code/duration，summary 含 total/pass/fail
print('has_fields='+str(('script' in r0 and 'exit_code' in r0 and 'duration' in r0)))
print('has_summary='+str(all(k in s for k in ['total','pass','fail','wall_seconds','parallel'])))
print('default_executor_ok='+str(isinstance(default_executor, ParallelExecutor)))
")
check "results 结构字段完整" "$(echo "$R" | grep 'has_fields=' | cut -d'=' -f2)" "True"
check "summary 字段完整" "$(echo "$R" | grep 'has_summary=' | cut -d'=' -f2)" "True"
check "default_executor 可用" "$(echo "$R" | grep 'default_executor_ok=' | cut -d'=' -f2)" "True"

echo ""
echo "==== 测试结果: PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" -eq 0 ] && echo "ALL GREEN ✅" || echo "SOME RED ❌"
exit "$FAIL"
