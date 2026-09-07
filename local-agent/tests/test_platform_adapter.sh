#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 三入口归一化适配层 测试（Issue #105）
# 验证：
#   1. 主入口锁死「架构·秘书」（入口主从规则）：default 系入口（web/cnb）直接 @ 角色跳过秘书 = 红灯；
#      harness 系入口（local）允许跳过秘书 = 绿灯
#   2. 三入口差异收敛到适配层：web/cnb/local 各自实现最小宿主接口
#      trigger / read_card / run_dag / scale_swarm（核心编排仅一份）
#   3. 配置管差异（非 if 分支）：入口→(适配器/执行地/profile) 由 ENTRY_LOCI 配置承载
#   4. 本地/云端执行地分工走 CLOUD_LOCAL_COOP 边界（locus 配置，非逻辑硬编码）
#   5. run.py 集成：--platform-overview / --entry 归一化路由可调用
set -e
cd "$(dirname "$0")/.."
PY=python3

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/pa_out.txt 2>&1; then
  echo "  ✅ $d"; pass=$((pass+1))
else
  echo "  ❌ $d"; cat /tmp/pa_out.txt; fail=$((fail+1))
fi }

echo "===== [platform-adapter] 1. 主入口锁死秘书（入口主从规则）====="
t "default 入口(cnb) 直接 @产品 跳过秘书 → 红灯" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import route
r = route.route('cnb', '任务', direct_role='架构·产品')
assert r['ok'] is False, '直接@产品跳过了秘书却绿灯'
assert r['main_entry'] == '架构·秘书'
assert '已接管自秘书路由' not in r.get('ack',''), '未合规不应给接管回显'
print('红灯捕获: cnb 入口直接@产品 →', r['guard']['message'][:50], '...')
EOF
"

t "web 入口（default profile）同样强制秘书" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import route
g = route.entry_guard('web', direct_role='架构·产品')
assert g['ok'] is False
assert g['mandatory'] is True
assert g['main_entry'] == '架构·秘书'
print('web 强制秘书护栏红灯 ok')
EOF
"

t "harness 入口(local) 允许跳过秘书 → 绿灯" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import route
r = route.route('local', '任务', direct_role='架构·产品')
assert r['ok'] is True, 'harness 应放行'
assert r['routed_to'] == '架构·产品'
print('harness 放行绿灯 ok')
EOF
"

t "合规路径回显『已接管自秘书路由的 X』" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import route
r = route.route('local', '做一个简单系统')
assert r['ok'] is True
assert r['ack'] == '已接管自秘书路由的 架构·秘书'
assert r['main_entry'] == '架构·秘书'
print('接管回显:', r['ack'])
EOF
"

echo "===== [platform-adapter] 2. 三入口差异收敛适配层（最小宿主接口）====="
t "三个适配器都实现 trigger/read_card/run_dag/scale_swarm" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import adapter
min_int = ('trigger','read_card','run_dag','scale_swarm')
for entry in ('web','cnb','local'):
    a = adapter.get_adapter(entry)
    for m in min_int:
        assert callable(getattr(a, m)), f'{entry} 缺 {m}'
    assert a.locus in ('cloud','local','hybrid')
    assert a.profile
print('三入口均实现 4 个最小宿主接口')
EOF
"

t "核心编排仅一份：适配器 run_dag 委托单份 orchestrator.run_pipeline" "$PY - <<'EOF'
import sys, inspect; sys.path.insert(0,'.')
from entries import adapter
a = adapter.get_adapter('local')
src = inspect.getsource(type(a).run_dag)
assert 'orchestrator.run_pipeline' in src, '适配器未委托单份核心编排'
# 适配器代码内不应出现 if(entry==...) 分支污染核心
assert 'entry==' not in inspect.getsource(type(a))
print('适配层委托单份核心，无入口 if 分支')
EOF
"

t "scale_swarm 委托单份分形引擎(devs_per_team 可配)" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import adapter
a = adapter.get_adapter('cnb')
plan = a.scale_swarm(['t1','t2','t3','t4','t5'], n=2)
assert plan['devs_per_team'] == 2
assert plan['team_count'] >= 1
assert all('team_id' in tm for tm in plan['teams'])
print('scale_swarm:', plan['team_count'], '小组 x', plan['devs_per_team'], '开发')
EOF
"

echo "===== [platform-adapter] 3. 配置管差异（非 if 分支）====="
t "入口→(适配器/执行地/profile) 由 ENTRY_LOCI 配置承载" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import adapter
L = adapter.ENTRY_LOCI
assert L['web'][:3] == ('web','hybrid','default')
assert L['cnb'][:3] == ('cnb','cloud','default')
assert L['local'][:3] == ('local','local','harness')
print('三入口配置映射齐备: web/cnb/local')
EOF
"

t "resolve_entry 别名归一化（网页→web/cnb→cnb/本地→local）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import route
assert route.resolve_entry('网页对话')=='web'
assert route.resolve_entry('cnb.cool 云端 NPC')=='cnb'
assert route.resolve_entry('本地 harness run.py')=='local'
assert route.resolve_entry('')=='local'
print('别名归一化 ok')
EOF
"

echo "===== [platform-adapter] 4. 执行地分工走 CLOUD_LOCAL_COOP 边界（locus 配置）====="
t "每个适配器声明执行地 locus（cloud/local/hybrid）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import adapter, route
rows = adapter.list_adapters()
locus_map = {r['entry']: r['locus'] for r in rows}
assert locus_map == {'web':'hybrid','cnb':'cloud','local':'local'}, locus_map
# 执行地来自配置而非硬编码 if：adapter.py 不应依赖平台判断再改执行逻辑
import inspect
src = inspect.getsource(adapter)
assert 'locus' in src
print('执行地配置:', locus_map)
EOF
"

t "入口主从 + 执行地 汇聚到 overview 俯瞰（供决策）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import route
ov = route.overview()
assert ov['main_entry'] == '架构·秘书'
assert ov['main_entry_guard']['mandatory'] is True
assert len(ov['entries']) == 3
assert ov['core']  # 声明核心仅一份
print('overview 主入口=架构·秘书, 三入口=', [e['entry'] for e in ov['entries']])
EOF
"

echo "===== [platform-adapter] 5. run.py 集成（--entry / --platform-overview）====="
t "run.py --platform-overview 可调用" "python3 run.py --platform-overview"

t "run.py --entry cnb --direct-role @产品 → 退出码2(红灯)" "if python3 run.py --entry cnb --direct-role 架构·产品 --req '测试' >/tmp/pa_g.txt 2>&1; then false; else grep -q '强制入口护栏' /tmp/pa_g.txt; fi"

echo ""
echo "===== 三入口归一化适配层 测试结果：$pass 通过 / $fail 失败 ====="
[ "$fail" = "0" ] || exit 1
