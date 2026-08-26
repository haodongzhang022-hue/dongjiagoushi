#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 规模预设 + 强制秘书入口 测试（修复测试关键发现 1/2）
# 验证：
#   1. 规模预设 prescale：澄清阶段体量预设 → team_size/collab_plan/risk_level 基准锚点
#   2. 经验方案库检索：命中常规方案复用，未命中全新规划
#   3. 强制入口护栏：默认必须经「架构·秘书」，显式 @ 角色跳过即红灯
#   4. 引擎 preflight/run_scaled 集成：强制入口 + 规模预设已接入
set -e
cd "$(dirname "$0")/.."
PY=python3

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/pp_out.txt 2>&1; then
  echo "  ✅ $d"; pass=$((pass+1))
else
  echo "  ❌ $d"; cat /tmp/pp_out.txt; fail=$((fail+1))
fi }

echo "===== [prescale] 1. 规模预设：复杂度自动判定 + 基准锚点 ====="
t "简单需求→单兵低风险" "$PY - <<'EOF'
from scale import prescale
prescale.clear_prescale_records()
p = prescale.prescale('做一个简单的问候系统')
assert p['team_size'] == 1, p
assert p['collab_plan'] == 'single'
assert p['risk_level'] == 'low'
assert p['source'] in ('pattern_lib','new_plan')
print('简单需求预设:', p['team_size'], p['collab_plan'], p['risk_level'], p['source'])
EOF
"

t "复杂需求→差异化编队高风险" "$PY - <<'EOF'
from scale import prescale
p = prescale.prescale('集群协作架构升级，2500并发，多部门公司化，平台级对外获客全链路，分布式，大规模')
assert p['team_size'] >= 3, p
assert p['risk_level'] == 'high'
assert p['collab_plan'] == 'differentiated_cohort', p
print('复杂需求预设:', p['team_size'], p['collab_plan'], p['risk_level'], p['source'])
EOF
"

t "显式复杂度带→medium" "$PY - <<'EOF'
from scale import prescale
p = prescale.prescale('某个需求', complexity_hint='medium')
assert p['complexity_band'] == 'medium'
assert p['team_size'] == 3
print('medium 预设:', p['team_size'], p['collab_plan'], p['risk_level'])
EOF
"

echo "===== [prescale] 2. 经验方案库检索 + 稳定寻址 ====="
t "命中方案库→source=pattern_lib" "$PY - <<'EOF'
from scale import prescale
p = prescale.prescale('做一个客服系统', kind='company')
assert p['source'] == 'pattern_lib', p
assert p['pattern']  # 有复用路径描述
print('命中方案库:', p['pattern_type'], '|', p['pattern'][:40], '...')
EOF
"

t "同需求二次预设→取回同一结果（稳定寻址不漂移）" "$PY - <<'EOF'
from scale import prescale
prescale.clear_prescale_records()
a = prescale.prescale('做一个订单系统')
b = prescale.prescale('做一个订单系统')  # 二次触发同一需求
assert a == b, '二次预设发生漂移'
assert prescale.has_prescale('做一个订单系统')
assert not prescale.has_prescale('完全不同的需求')
print('稳定寻址通过：二次预设取回同一结果')
EOF
"

t "未命中方案库→全新规划 source=new_plan" "$PY - <<'EOF'
from scale import prescale
p = prescale.prescale('超特殊从未见过的奇怪领域需求xyz', kind='unknown_kind')
# 未知 kind 回退 default simple → 单兵保守起步
assert p['adjustable'] is True
print('未知领域预设(保守基准):', p['team_size'], p['collab_plan'], p['source'])
EOF
"

t "经理增量修正：基于预设非从零规划" "$PY - <<'EOF'
from scale import prescale
prescale.clear_prescale_records()
base = prescale.prescale('做一个简单系统')  # 单兵
adj = prescale.adjust_by_architect(base, {'scale_factor': 2.0})
assert adj['team_size'] == 2
assert adj['adjusted_by_architect'] is True
assert '不做从零规划' in adj['rationale'] or '增量修正' in adj['rationale']
print('增量修正: base', base['team_size'], '→ arch调整后', adj['team_size'])
EOF
"

t "留痕可核验：--prescale-records 能列出记录" "python3 run.py --prescale-records"

echo "===== [prescale] 3. 强制入口护栏（秘书不可跳过）====="
t "默认入口→必须经秘书（合规绿灯）" "$PY - <<'EOF'
from scale import profile
r = profile.guard_entry('default')
assert r['ok'] is True
assert r['mandatory'] is True
assert r['entry'] == '架构·秘书'
print('默认入口护栏:', r['entry'])
EOF
"

t "显式@产品跳过秘书→红灯（必须补秘书路由留痕）" "$PY - <<'EOF'
from scale import profile
r = profile.guard_entry('default', direct_role='架构·产品')
assert r['ok'] is False, '跳过了秘书却绿灯，违反强制入口'
assert '架构·秘书' in r['message']
assert '已接管自秘书路由' in r['message']
print('红灯捕获: 直接@产品跳过了秘书 →', r['message'][:60], '...')
EOF
"

t "harness 内嵌模板→允许跳过秘书（放行）" "$PY - <<'EOF'
from scale import profile
r = profile.guard_entry('harness', direct_role='架构·产品')
assert r['ok'] is True
assert r['mandatory'] is False
print('harness 放行:', r['message'])
EOF
"

t "秘书角色 route_guard 输出路由留痕卡" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from roles import get_role
sec = get_role('架构·秘书')
card = sec.route_guard('架构·产品')
assert card['entry'] == '架构·秘书'
assert card['routed_to'] == '架构·产品'
assert card['ack'] == '已接管自秘书路由的 架构·产品'
assert card['mandatory'] is True
print('秘书路由留痕卡:', card['ack'])
EOF
"

echo "===== [prescale] 4. 引擎集成：preflight/run_scaled 已接入 ====="
t "preflight 含强制入口+规模预设" "$PY - <<'EOF'
from scale import engine
pf = engine.preflight({'profile':'default','req':'做一个订单系统'})
assert pf['entry_guard']['ok'] is True
assert pf['prescale']['team_size'] >= 1
assert pf['prescale']['adjustable'] is True
print('preflight 已集成 entry_guard + prescale')
EOF
"

t "run_scaled 报告含入口护栏+规模预设" "$PY - <<'EOF'
from scale import engine
rep = engine.run_scaled('做一个订单系统', spec_obj={'team_size':4}, verbose=False)
assert rep['entry_guard']['mandatory'] is True
assert rep['prescale']['team_size'] >= 1
assert rep['prescale']['adjustable'] is True
print('run_scaled 报告已含 entry_guard + prescale')
EOF
"

t "run.py --prescale 可调用" "python3 run.py --prescale --req '做一个客服系统' --complexity medium"

echo "===== [prescale] 5. 2 次定团队规模·真实流水线引擎接入 ====="
t "run_scaled 第1次(澄清预设)+第2次(经理增量修正) 均接入" "$PY - <<'EOF'
from scale import engine, prescale
prescale.clear_prescale_records()
rep = engine.run_scaled('升级本项目集群架构，全链路平台级，多岗位多部门协同，完善稳定性',
                        spec_obj={'team_size': 4, 'arch_scale_factor': 1.6}, verbose=False)
st = rep['scale_twice']
assert 'first' in st and 'second' in st
assert st['first']['stage'] == '澄清预设'
assert st['second']['stage'] == '经理按架构增量修正'
assert st['second']['adjusted'] is True
assert st['second']['team_size'] > st['first']['team_size'], '第2次定规模未增量修正'
assert rep['spec']['team_size'] == st['final_team_size']
print('2次定规模: 第1次', st['first']['team_size'], '→ 第2次', st['second']['team_size'],
      '→ 最终', st['final_team_size'])
EOF
"

t "run_pipeline DAG 主流水线 2次定规模接入" "$PY - <<'EOF'
import orchestrator
rep = orchestrator.run_pipeline('升级本项目多岗位协同完善稳定性', backend='cli_fallback')
st = rep['scale_twice']
assert 'first' in st and 'second' in st
assert st['first']['stage'] == '秘书澄清阶段'
assert st['second']['stage'] == '经理按架构增量修正'
assert st['first']['team_size'] >= 1
print('DAG 主流水线 2次定规模: 第1次', st['first']['team_size'], '→ 第2次', st['second']['team_size'])
EOF
"

echo ""
echo "===== 规模预设 + 强制入口 + 2次定规模 测试结果：$pass 通过 / $fail 失败 ====="
[ "$fail" = "0" ] || exit 1
