#!/usr/bin/env bash
# ============================================================
# 测试智能优化层（hybrid v2.0 T3-T6）功能测试
# 仓库：dongjiagoushi（架构师体系 · Issue #65）
#
# 验证：
#   T3 FingerprintCache   指纹缓存 + test_cache 表
#   T4 ParallelExecutor   并行执行器（-P）
#   T5 PolicyEngine       策略引擎（增量/缓存/并行/全量开关）
#   T6 CostReporter       成本报表三合一节省
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

# 隔离测试 DB（避免污染运行时库）
export DB_PATH=/tmp/hybrid_optimizer_test.db
rm -f "$DB_PATH"

echo "== 测试智能优化层 T3-T6 =="

# ---------- T3 FingerprintCache ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from data import schema; schema.init_schema()
from hybrid import cache, FingerprintCache, default_cache
assert FingerprintCache is not None and default_cache is not None
c = cache.default_cache
# 指纹计算（覆盖源码 git blob hash）
fp = c.fingerprint('local-agent/tests/test_engine.sh')
assert fp and fp.startswith('sha1:'), f'指纹异常: {fp}'
# 初始未命中
hit, _ = c.is_hit('local-agent/tests/test_engine.sh')
assert hit == False, '初始应未命中'
# 标记通过 → 命中
c.mark('local-agent/tests/test_engine.sh', {'exit_code':0}, 'pass')
hit, _ = c.is_hit('local-agent/tests/test_engine.sh')
assert hit == True, '标记后应命中'
# filter_hits 批量
hits, misses = c.filter_hits(['local-agent/tests/test_engine.sh','local-agent/tests/test_collab.sh'])
assert len(hits)==1 and len(misses)==1, f'hits={len(hits)} misses={len(misses)}'
print('OK')
")
[ "$R" = "OK" ] && ok "T3 FingerprintCache 指纹计算+命中+批量过滤" || bad "T3 FingerprintCache: $R"

# T3 test_cache 表落库
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from data import schema, repository
schema.init_schema()
assert 'test_cache' in schema.list_tables(), 'test_cache 表缺失'
repository.upsert_test_cache('t.sh','sha1:x',{'exit_code':0},'pass')
row = repository.get_test_cache('t.sh','sha1:x')
assert row and row['status']=='pass', f'缓存记录异常: {row}'
assert repository.count_test_cache() >= 1
print('OK')
")
[ "$R" = "OK" ] && ok "T3 test_cache 表落库+查询" || bad "T3 test_cache 表: $R"

# ---------- T4 ParallelExecutor ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid import parallel, ParallelExecutor, default_executor
import os
os.makedirs('/tmp/para', exist_ok=True)
for i in range(4):
    with open(f'/tmp/para/t{i}.sh','w') as f:
        f.write('#!/usr/bin/env bash\\nsleep 0.1\\necho ok%d\\n' % i)
ex = ParallelExecutor(root_dir='/tmp/para')
res = ex.run_parallel(['t0.sh','t1.sh','t2.sh','t3.sh'], parallel=2)
assert res['summary']['pass']==4, f'全过: {res[chr(115)+chr(117)+chr(109)+chr(109)+chr(97)+chr(114)+chr(121)]}'
assert res['summary']['parallel']==2, 'parallel=2'
assert 'wall_seconds' in res['summary'], '缺 wall_seconds'
# 串行退化
res2 = ex.run_parallel(['t0.sh','t1.sh'], parallel=1)
assert res2['summary']['parallel']==1
print('OK')
")
[ "$R" = "OK" ] && ok "T4 ParallelExecutor 并行执行+串行退化" || bad "T4 ParallelExecutor: $R"

# ---------- T5 PolicyEngine ----------
R=$(python3 -c "
import sys,time; sys.path.insert(0,'$ROOT')
from hybrid import policy, selector as selmod, PolicyEngine, default_policy
p = PolicyEngine()
# 全量回归到期 → full
d = p.decide(changed_files=['collab/engine.py'], full_suite=['x.sh'], last_full_ts=None)
assert d['mode']=='full', f'到期应 full: {d[chr(109)+chr(111)+chr(100)+chr(101)]}'
# 未到期 → 增量
s = selmod.IncrementalSelector(root_dir='.')
d = p.decide(changed_files=['collab/engine.py'], selector=s, full_suite=lambda:['a.sh','b.sh'], last_full_ts=time.time())
assert d['mode']=='incremental', '应增量'
assert 'local-agent/tests/test_collab.sh' in d['tests'], d['tests']
assert d['parallel']==4, 'parallel 开'
# parallel 开关
d = p.decide(changed_files=['collab/engine.py'], selector=s, full_suite=lambda:['a.sh'], last_full_ts=time.time(), overrides={'parallel':False})
assert d['parallel']==1
print('OK')
")
[ "$R" = "OK" ] && ok "T5 PolicyEngine 增量/全量/并行开关" || bad "T5 PolicyEngine: $R"

# T5 缓存命中剔除
R=$(python3 -c "
import sys,time; sys.path.insert(0,'$ROOT')
from data import schema; schema.init_schema()
from hybrid import policy, selector as selmod, cache
p = policy.default_policy
s = selmod.IncrementalSelector(root_dir='.')
c = cache.default_cache
c.mark('local-agent/tests/test_engine.sh',{'exit_code':0},'pass')
d = p.decide(changed_files=['engine/state_machine.py'], selector=s, cache=c, full_suite=lambda:['a.sh'], last_full_ts=time.time())
hits = [h['script'] for h in d['cache_hits']]
assert 'local-agent/tests/test_engine.sh' in hits, f'engine 应命中: {hits}'
assert 'local-agent/tests/test_engine.sh' not in d['tests'], 'engine 不应在待跑清单'
print('OK')
")
[ "$R" = "OK" ] && ok "T5 PolicyEngine 缓存命中剔除" || bad "T5 缓存剔除: $R"

# ---------- T6 CostReporter ----------
R=$(python3 -c "
import sys; sys.path.insert(0,'$ROOT')
from hybrid import cost, CostReporter, default_cost_reporter
assert CostReporter and default_cost_reporter
cr = CostReporter()
policy = {'mode':'incremental','tests':['t1.sh','t2.sh'],'cache_hits':[{'script':'t3.sh'},{'script':'t4.sh'}],'parallel':4,'full_count':10}
exec_result = {'summary':{'total':2,'pass':2,'wall_seconds':5.0,'total_duration':20.0}}
rep = cr.report_optimizer(policy, exec_result, baseline_serial_seconds=20.0)
assert rep['incremental']['skipped']==6, f'skipped={rep[chr(105)+chr(110)+chr(99)+chr(114)+chr(101)+chr(109)+chr(101)+chr(110)+chr(116)+chr(97)+chr(108)][chr(115)+chr(107)+chr(105)+chr(112)+chr(112)+chr(101)+chr(100)]}'
assert rep['cache']['hit_count']==2
assert rep['parallel']['speedup_ratio']==0.25, rep['parallel']
assert rep['total']['saved_cpu_core_min']==8.0
print('OK')
")
[ "$R" = "OK" ] && ok "T6 CostReporter 三合一节省报表" || bad "T6 CostReporter: $R"

# ---------- CLI smart 接线 ----------
R=$(cd "$ROOT" && python3 -m hybrid.cli smart --dry --root "$(dirname "$ROOT")" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['mode']+'|'+str(d['parallel']))")
echo "  cli smart --dry: $R"
MODE=$(echo "$R" | cut -d'|' -f1)
PAR=$(echo "$R" | cut -d'|' -f2)
if [ "$MODE" = "incremental" ] && [ "$PAR" = "4" ]; then
  ok "CLI smart 接线（增量+并行=4）"
else
  bad "CLI smart 接线: $R"
fi

# ---------- __init__ 公开接口 ----------
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');import hybrid;print(hasattr(hybrid,'FingerprintCache') and hasattr(hybrid,'ParallelExecutor') and hasattr(hybrid,'PolicyEngine') and hasattr(hybrid,'CostReporter'))")
check "hybrid __init__ 公开 T3-T6 接口" "$R" "True"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
