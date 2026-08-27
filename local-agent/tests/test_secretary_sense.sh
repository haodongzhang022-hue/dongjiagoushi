#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 秘书·感知能力层测试（Issue #41 秘书价值强化 + 规模匹配落位澄清阶段）
# 验证：
#   1. 规模匹配：秘书→产品澄清阶段评估项目层级 → 承接体系/拓扑/角色子集（非第一步/非优先级）
#   2. 决策博弈：多选项摊开（解决"A or B 都不够好"）+ 对抗校验 + 本地环境
#   3. 测试兜底接管：开发说完成但测试跑不通 → 秘书接管 → 交人继续开发
#   4. 秘书角色集成：SecretaryRole 暴露 scale_match/recommend/takeover 三能力
#   5. orchestrator 接入：run_pipeline 秘书阶段产出去 scale_match 字段
set -e
cd "$(dirname "$0")/.."
PY=python3

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/sense_out.txt 2>&1; then
  echo "  ✅ $d"; pass=$((pass+1))
else
  echo "  ❌ $d"; cat /tmp/sense_out.txt; fail=$((fail+1))
fi }

echo "===== [规模匹配] 1. 落位澄清阶段（非第一步/非优先级） ====="
t "单点修改→micro/agile/单开发" "$PY - <<'EOF'
from roles import secretary_sense as ss
m = ss.scale_match(complexity=0, subtasks=1)
assert m['tier']=='micro', m['tier']
assert m['system']=='agile'
assert m['topology']=='agile'
assert m['roles']==['架构·开发'], m['roles']   # 最小角色子集
assert m['matched_in_clarify'] is True          # 落位澄清阶段
print('micro →', m['tier'], '/', m['system'], '/', m['topology'], '/', m['roles'])
EOF
"
t "低复杂→small/agile/产品+开发" "$PY - <<'EOF'
from roles import secretary_sense as ss
m = ss.scale_match(complexity=2, subtasks=3)
assert m['tier']=='small' and m['system']=='agile', (m['tier'], m['system'])
assert '架构·开发' in m['roles']
print('small →', m['tier'], '/', m['system'], '/', m['topology'], '/', m['roles'])
EOF
"
t "中等→medium/architected/加架构师" "$PY - <<'EOF'
from roles import secretary_sense as ss
m = ss.scale_match(complexity=4, subtasks=10)
assert m['tier']=='medium' and m['system']=='architected', (m['tier'], m['system'])
assert '架构·总师' in m['roles']   # 中等开始有架构师
print('medium →', m['tier'], '/', m['system'], '/', m['topology'], '/', m['roles'])
EOF
"
t "大型→huge/full/完整体系+蔓延" "$PY - <<'EOF'
from roles import secretary_sense as ss
m = ss.scale_match(complexity=9, subtasks=60)
assert m['tier']=='huge' and m['system']=='full', (m['tier'], m['system'])
assert m['topology']=='prefix'   # 水龙头蔓延
assert len(m['roles'])>=8        # 完整体系
print('huge →', m['tier'], '/', m['system'], '/', m['topology'], '/', len(m['roles']),'roles')
EOF
"
t "四套方案齐备(cache主线)" "$PY - <<'EOF'
from roles import secretary_sense as ss
m = ss.scale_match(complexity=9, subtasks=60)
assert set(m['plan'].keys()) == {'cache','division','reporting','merge'}, m['plan'].keys()
assert '缓存命中' in m['plan']['cache']   # cache 为主线
print('四套方案:', list(m['plan'].keys()))
EOF
"

echo "===== [决策博弈] 2. 多选项摊开 + 对抗校验 + 本地环境 ====="
t "展开5类or分支(解决二选一都不够好)" "$PY - <<'EOF'
from roles import secretary_sense as ss
e = ss.expand_candidates('A快但返工高,B稳但慢,选哪个?')
labels = [b['label'] for b in e['branches']]
assert '合并保留·区分场景' in labels
assert '换道' in labels
assert '补集' in labels
assert '开放探索' in labels
assert 'local_context' in e   # 多了本地环境
print('or分支:', labels)
EOF
"
t "对抗校验收敛出更稳建议" "$PY - <<'EOF'
from roles import secretary_sense as ss
a = ss.adversarial_check('两个方案都不够好')
assert a['stance_a']=='秘书' and a['stance_b']=='落地开发'
assert len(a['blind_spots'])==2
assert '对抗收敛' in a['converged_suggestion']
print('对抗盲区数:', len(a['blind_spots']))
EOF
"
t "recommend综合决策+默认自决" "$PY - <<'EOF'
from roles import secretary_sense as ss
r = ss.recommend('A or B 都不够好')
assert r['need_human'] is False          # 默认秘书能自决大部分疑问
assert r['recommendation']
assert '本地环境' in r['note'] or '信息' in r['note']
print('自决(不需交人):', r['need_human'])
EOF
"

echo "===== [测试兜底接管] 3. 开发说完成但测试跑不通 ====="
t "测试通过→无需接管" "$PY - <<'EOF'
from roles import secretary_sense as ss
tk = ss.takeover({'status':'done'}, {'passed':True})
assert tk['mode']=='test_passed'
assert tk['handover_to_human'] is False
print('通过 →', tk['mode'])
EOF
"
t "测试跑不通→秘书接管+交人继续开发" "$PY - <<'EOF'
from roles import secretary_sense as ss
tk = ss.takeover({'status':'done'}, {'passed':False,'reason':'接口返回500'})
assert tk['takeover'] is True
assert tk['mode']=='test_takeover'
assert tk['handover_to_human'] is True
assert '继续开发' in tk['continue_development_input']
assert len(tk['human_risk_points'])>=1
print('跑不通 →', tk['mode'], '| 交人:', tk['handover_to_human'])
EOF
"

echo "===== [秘书角色集成] 4. SecretaryRole 暴露三能力 ====="
t "角色实例可调 scale_match/recommend/takeover" "$PY - <<'EOF'
from roles.secretary import SecretaryRole
sr = SecretaryRole()
assert sr.name=='架构·秘书'
m = sr.scale_match(complexity=1, subtasks=1)
assert m['tier'] in ('micro','small')
r = sr.recommend('二选一都不够好怎么办')
assert r['recommendation']
tk = sr.takeover({'status':'done'},{'passed':False,'reason':'x'})
assert tk['mode']=='test_takeover'
# 输出契约含新能力
contract = sr.output_contract()['contract']
assert any('规模匹配' in c for c in contract)
assert any('测试兜底接管' in c for c in contract)
assert any('决策博弈' in c for c in contract)
print('秘书角色集成 OK')
EOF
"

echo "===== [留痕] 5. 秘书感知动作可回溯 ====="
t "留痕可查" "$PY - <<'EOF'
from roles import secretary_sense as ss
ss.clear_actions()
ss.scale_match(complexity=0, subtasks=1)
ss.recommend('选A还是B')
ss.takeover({'status':'done'},{'passed':False})
acts = ss.secretary_actions()
kinds = {a['kind'] for a in acts}
assert 'scale_match' in kinds and 'decision_game_recommend' in kinds and 'test_takeover' in kinds
print('留痕动作数:', len(acts), '| 类型:', sorted(kinds))
EOF
"

echo "===== [编排接入] 6. orchestrator 规模匹配字段 ====="
t "capability 声明" "$PY - <<'EOF'
from roles import secretary_sense as ss
cap = ss.capability()
assert cap['name']=='SecretarySense'
assert set(cap['abilities'].keys()) == {'scale_match','decision_game','test_takeover'}
print('能力声明:', list(cap['abilities'].keys()))
EOF
"

echo ""
echo "===== 结果: $pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ] || exit 1
exit 0

echo "===== [编排接入] 7. orchestrator 端到端规模匹配字段 ====="
t "run_pipeline 秘书阶段产出 scale_match" "$PY - <<'EOF'
import sys, os
sys.path.insert(0, os.getcwd())
from data import schema
schema.init_schema()
class MockLLM:
    def call(self, system_prompt, user_input, **kw): return 'ok'
    def generate(self, user_input, **kw): return 'ok'
    def run(self, role, user_input, **kw): return 'ok'
import orchestrator
report = orchestrator.run_pipeline('帮我改一下登录接口的 bug', llm=MockLLM())
sm = report.get('scale_match')
assert sm is not None, '未产出 scale_match'
assert sm['stage'].startswith('秘书澄清')
assert sm['tier'] in ('micro','small','medium','large','huge')
assert 'system' in sm and 'topology' in sm and 'roles' in sm
print('run_pipeline scale_match:', sm['tier'], '/', sm['system'], '/', sm['topology'])
EOF
"
