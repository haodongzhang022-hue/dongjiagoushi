#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 开发小组闭环「接线驱动」测试（方案 A · 把 DevTeam 接成真实可跑链路 · Issue #74）
# 验证总师方案 A 的 5 个接线点已落地：
#   ① 建组入口  —— 从拓扑 lead+dev 节点建 DevTeamEngine
#   ② 驱动循环  —— 确定性状态机 execute→verify→decide，不让 LLM 决定
#   ③ 进度北极星 —— advance() 写 goal_meters → 哨兵收敛判定
#   ④ 整合交付  —— 全部 APPROVED 后 deliver_to_manager + aggregate 收口
#   ⑤ 路由/分形 —— dev_enhanced 拓扑 lead 节点走驱动；agile/dag 不误触发
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dev_team_driver.db"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ✅ $1"; }
bad() { fail=$((fail+1)); echo "  ❌ $1"; }

echo "===== [dev_team_driver] 1. 建组入口：from_topology 识别 lead+dev_N ====="
$PY - <<'EOF'
from dev_team_driver import DevTeamDriver, collect_dev_nodes, estimate_goal_total
topo = {'nodes': [
  {'id':'product','role':'架构·产品'},
  {'id':'architect','role':'架构·总师'},
  {'id':'lead','role':'架构·小组长'},
  {'id':'dev_1','role':'架构·开发'},
  {'id':'dev_2','role':'架构·开发'},
  {'id':'review','role':'架构·评审'},
]}
devs = collect_dev_nodes(topo['nodes'])
assert [d['id'] for d in devs] == ['dev_1','dev_2'], devs
# 排除单独的 develop 节点（不应误判为小组成员）
mixed = topo['nodes'] + [{'id':'develop','role':'架构·开发'}]
assert [d['id'] for d in collect_dev_nodes(mixed)] == ['dev_1','dev_2']
d, dev_nodes = DevTeamDriver.from_topology(topo, req='实现登录模块的接口', devs_per_team=2)
assert d.team.devs_per_team == 2
assert estimate_goal_total('实现登录模块的接口，包括账号密码登录、手机验证码登录') >= 1
print("  ✅ 建组入口识别正确（dev_1/dev_2），排除 develop")
EOF
ok "建组入口"

echo "===== [dev_team_driver] 2. 驱动循环：确定性状态机 DONE ====="
$PY - <<'EOF'
from dev_team_driver import DevTeamDriver
d = DevTeamDriver(goal_total=2.0, devs_per_team=2)
res = d.drive(req='实现登录模块', task_id='T1', summary='s')
assert res['entered'] is True
assert res['rounds'][-1]['verdict'] == 'DONE', res['rounds'][-1]['verdict']
assert res['aggregate']['approved'] == 2 and res['aggregate']['total_devs'] == 2
assert res['delivery'] is not None
print("  ✅ 确定性驱动到 DONE + 交付")
EOF
ok "驱动循环"

echo "===== [dev_team_driver] 3. 执行-验证分离：REWORK→DONE / ESCALATED ====="
$PY - <<'EOF'
from dev_team_driver import DevTeamDriver
# REWORK→DONE
d = DevTeamDriver(goal_total=2.0, devs_per_team=2)
res = d.drive(req='x', task_id='T2', summary='s',
  dev_output_provider=lambda r, ids: [(0, False, 'bug') if r==1 else (0, True, 'fixed'), (1, True, 'ok')])
assert res['rounds'][0]['verdict'] == 'REWORK', res['rounds'][0]['verdict']
assert res['rounds'][-1]['verdict'] == 'DONE'
# ESCALATED（超 max_attempts 上报 Leader，不无限重试）
d2 = DevTeamDriver(goal_total=2.0, devs_per_team=2, max_attempts=2)
res2 = d2.drive(req='x', task_id='T3', summary='s',
  dev_output_provider=lambda r, ids: [(0, False, 'repeated bug'), (1, True, 'ok')], max_rounds=10)
assert res2['rounds'][-1]['verdict'] == 'ESCALATED', res2['rounds'][-1]['verdict']
print("  ✅ REWORK→DONE / ESCALATED（硬性熔断）")
EOF
ok "执行-验证分离 + 熔断"

echo "===== [dev_team_driver] 4. 进度北极星：advance 写 goal_meters ====="
$PY - <<'EOF'
from dev_team_driver import DevTeamDriver
d = DevTeamDriver(goal_total=10.0, devs_per_team=2)
d.advance(3.0)
p = d.progress()
assert p['progress_pct'] == 30.0, p['progress_pct']
d.advance(5.0)
p = d.progress()
assert p['progress_pct'] == 80.0, p['progress_pct']
# 不超过目标
d.advance(100.0)
assert d.progress()['progress_pct'] == 100.0
print("  ✅ 进度北极星刻度正确（30%→80%→封顶100%）")
EOF
ok "进度北极星"

echo "===== [dev_team_driver] 5. 全流程接线：dev_enhanced 拓扑端到端驱动 ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, '.')
from orchestrator import run_pipeline
# dev_enhanced 拓扑：lead 驱动开发小组，dev_1/dev_2 被消费，评审/测试仍跑
res = run_pipeline('实现登录模块的接口，包括账号密码登录、手机验证码登录，含安全校验',
                   use_fusion=True, force_topology='dev_enhanced')
outs = {s['step']: str(s['output']) for s in res.get('steps', [])}
assert 'lead' in outs and '[开发小组]' in outs['lead'], outs.get('lead')
assert '已由开发小组闭环驱动消费' in outs.get('dev_1','') and '已由开发小组闭环驱动消费' in outs.get('dev_2','')
assert 'review' in outs and 'test' in outs
print("  ✅ dev_enhanced 端到端：lead 驱动 + dev 消费 + 评审/测试保留")
EOF
ok "dev_enhanced 端到端"

echo "===== [dev_team_driver] 6. 路由接线：agile/dag 不误触发开发小组 ====="
$PY - <<'EOF'
import os, sys
sys.path.insert(0, '.')
from orchestrator import run_pipeline
for topo in ['agile', 'dag', 'linear']:
    res = run_pipeline('修复一个登录bug', use_fusion=True, force_topology=topo)
    triggered = any('[开发小组]' in str(s.get('output','')) for s in res.get('steps',[]))
    assert not triggered, f'{topo} 不应触发开发小组'
print("  ✅ agile/dag/linear 不误触发开发小组（仅 dev_enhanced 走驱动）")
EOF
ok "路由不误触发"

echo ""
echo "===== 结果: $pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ] || { echo "❌ 存在失败"; exit 1; }
echo "✅ test_dev_team_driver.sh 全部通过"
