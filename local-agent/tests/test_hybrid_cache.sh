#!/usr/bin/env bash
# ============================================================
# FingerprintCache 测试（test_hybrid_cache.sh · Issue #65 T3）
# ============================================================
# 验证 FingerprintCache：
#   1. 文件指纹计算（SHA-256）
#   2. 目录指纹计算
#   3. 组合指纹（覆盖多个源码）
#   4. 缓存命中判定（源码未变化 → hit）
#   5. 缓存未命中（源码变化 → miss → 需重跑）
#   6. record 记录结果 + 二次命中
#   7. need_run 批量筛选
#   8. 数据层 test_cache 表
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== FingerprintCache 测试 =="

# ---------- 1. 文件指纹 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
c = FingerprintCache(repo_root='$REPO_ROOT', use_data_layer=False)
fp = c.fingerprint('local-agent/hybrid/router.py')
print(fp[:16] if fp else 'NONE')
")
check "文件指纹非空" "$([ "$R" != "NONE" ] && echo yes || echo no)" "yes"
check "文件指纹为 SHA-256" "$(echo -n "$R" | wc -c)" "16"

# ---------- 2. 目录指纹 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
c = FingerprintCache(repo_root='$REPO_ROOT', use_data_layer=False)
fp = c.fingerprint('local-agent/hybrid')
print(fp[:16] if fp else 'NONE')
")
check "目录指纹非空" "$([ "$R" != "NONE" ] && echo yes || echo no)" "yes"

# ---------- 3. 组合指纹 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
c = FingerprintCache(repo_root='$REPO_ROOT', use_data_layer=False)
fp = c.compute_fingerprint('test_hybrid_router.sh')
print(fp[:16] if fp else 'NONE')
")
check "组合指纹非空" "$([ "$R" != "NONE" ] && echo yes || echo no)" "yes"

# ---------- 4. 缓存命中（源码未变化） ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
import tempfile, os

# 用临时文件测试：不依赖真实仓库
tmpdir = tempfile.mkdtemp()
os.makedirs(os.path.join(tmpdir, 'src'), exist_ok=True)
with open(os.path.join(tmpdir, 'src', 'file1.py'), 'w') as f:
    f.write('x = 1\\n')
with open(os.path.join(tmpdir, 'src', 'file2.py'), 'w') as f:
    f.write('y = 2\\n')

c = FingerprintCache(repo_root=tmpdir, use_data_layer=False)
c.covers = {'test_a.sh': ['src/file1.py', 'src/file2.py']}

# 第一次运行：未命中
r1 = c.is_hit('test_a.sh')
print('first_hit=' + str(r1['hit']))

# 记录结果（模拟一次运行）
c.record('test_a.sh', {'exit_code': 0, 'duration': 1.5})

# 第二次运行：源码未变化 → 命中
r2 = c.is_hit('test_a.sh')
print('second_hit=' + str(r2['hit']))
")
R1=$(echo "$R" | grep "first_hit=" | cut -d'=' -f2)
R2=$(echo "$R" | grep "second_hit=" | cut -d'=' -f2)
check "首次运行未命中" "$R1" "False"
check "源码未变二次命中" "$R2" "True"

# ---------- 5. 缓存未命中（源码变化） ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
import tempfile, os

tmpdir = tempfile.mkdtemp()
os.makedirs(os.path.join(tmpdir, 'src'), exist_ok=True)
with open(os.path.join(tmpdir, 'src', 'file1.py'), 'w') as f:
    f.write('x = 1\\n')

c = FingerprintCache(repo_root=tmpdir, use_data_layer=False)
c.covers = {'test_b.sh': ['src/file1.py']}

c.record('test_b.sh', {'exit_code': 0})
# 修改源码
with open(os.path.join(tmpdir, 'src', 'file1.py'), 'w') as f:
    f.write('x = 999\\n')

r = c.is_hit('test_b.sh')
print('hit=' + str(r['hit']))
")
check "源码修改后未命中" "$(echo "$R" | grep "hit=" | cut -d'=' -f2)" "False"

# ---------- 6. need_run 批量筛选 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
import tempfile, os

tmpdir = tempfile.mkdtemp()
os.makedirs(os.path.join(tmpdir, 'src1'), exist_ok=True)
os.makedirs(os.path.join(tmpdir, 'src2'), exist_ok=True)
with open(os.path.join(tmpdir, 'src1', 'a.py'), 'w') as f:
    f.write('a')
with open(os.path.join(tmpdir, 'src2', 'b.py'), 'w') as f:
    f.write('b')

c = FingerprintCache(repo_root=tmpdir, use_data_layer=False)
c.covers = {
    'test_a.sh': ['src1/a.py'],
    'test_b.sh': ['src2/b.py'],
}
c.record('test_a.sh', {'exit_code': 0})

# test_a 命中，test_b 未命中
need = c.need_run(['test_a.sh', 'test_b.sh'])
print('|'.join(sorted(need)))
")
check "need_run 只返回未命中" "$R" "test_b.sh"

# ---------- 7. record 后记录数据 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
import tempfile, os

tmpdir = tempfile.mkdtemp()
os.makedirs(os.path.join(tmpdir, 'src'), exist_ok=True)
with open(os.path.join(tmpdir, 'src', 'a.py'), 'w') as f:
    f.write('aaa')

c = FingerprintCache(repo_root=tmpdir, use_data_layer=False)
c.covers = {'test_c.sh': ['src/a.py']}
entry = c.record('test_c.sh', {'exit_code': 0, 'duration': 0.5})
print('has_fp=' + str(entry.get('fingerprint') is not None))
print('has_ts=' + str(entry.get('ts') is not None))
")
check "record 含指纹" "$(echo "$R" | grep "has_fp=" | cut -d'=' -f2)" "True"
check "record 含时间戳" "$(echo "$R" | grep "has_ts=" | cut -d'=' -f2)" "True"

# ---------- 8. clear 清空缓存 ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid.cache import FingerprintCache
import tempfile, os

tmpdir = tempfile.mkdtemp()
os.makedirs(os.path.join(tmpdir, 'src'), exist_ok=True)
with open(os.path.join(tmpdir, 'src', 'a.py'), 'w') as f:
    f.write('aaa')

c = FingerprintCache(repo_root=tmpdir, use_data_layer=False)
c.covers = {'test_d.sh': ['src/a.py']}
c.record('test_d.sh', {'exit_code': 0})
print('before_clear=' + str(c.is_hit('test_d.sh')['hit']))
c.clear()
print('after_clear=' + str(c.is_hit('test_d.sh')['hit']))
")
check "clear 前命中" "$(echo "$R" | grep "before_clear=" | cut -d'=' -f2)" "True"
check "clear 后未命中" "$(echo "$R" | grep "after_clear=" | cut -d'=' -f2)" "False"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
