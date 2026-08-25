#!/usr/bin/env bash
# ============================================================
# 公司化三战线模型测试 (company model v1.init)
# 仓库：dongjiagoushi（架构师体系 · Issue #18 公司化落地）
# 校验点：
#   T1 选单情报角色注册与输出契约（找需求/价值确认/竞品分析）
#   T2 能力底座线角色注册与输出契约（工具开发/优化/数据管理/运维）
#   T3 team.yaml 全角色可解析 + DAG 节点可解析
#   T4 公司化文档落位
#   T5 云端 settings.yml 人设落位
# ============================================================
cd "$(dirname "$0")/.."
PASS=0; FAIL=0
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo "======================================================"
echo "公司化三战线模型测试 (company model v1.init)"
echo "仓库: $(pwd)"
echo "======================================================"

echo ""
echo "▶ T1 选单情报角色（找需求/价值确认/竞品分析）"
python3 - <<'PY'
import sys; sys.path.insert(0, 'local-agent')
from roles import get_role
names = ['架构·找需求', '架构·价值确认', '架构·竞品分析']
for n in names:
    r = get_role(n)
    assert r, f'{n} 未注册'
    assert r.output_contract().get('role') == n, f'{n} 契约role不符'
    assert r.output_contract().get('contract'), f'{n} 契约为空'
print("  PASS")
PY
if [ $? -eq 0 ]; then ok "T1 选单情报角色注册与输出契约"; else bad "T1 选单情报角色"; fi

echo "▶ T2 能力底座线角色（工具开发/优化/数据管理/运维）"
python3 - <<'PY'
import sys; sys.path.insert(0, 'local-agent')
from roles import get_role
names = ['架构·工具开发', '架构·优化', '架构·数据管理', '架构·运维']
for n in names:
    r = get_role(n)
    assert r, f'{n} 未注册'
    assert r.output_contract().get('role') == n, f'{n} 契约role不符'
    assert r.output_contract().get('contract'), f'{n} 契约为空'
print("  PASS")
PY
if [ $? -eq 0 ]; then ok "T2 能力底座线角色注册与输出契约"; else bad "T2 能力底座线角色"; fi

echo "▶ T3 team.yaml 全角色可解析 + DAG 可解析"
python3 - <<'PY'
import sys, yaml; sys.path.insert(0, 'local-agent')
from roles import get_role
team = yaml.safe_load(open('local-agent/team.yaml'))
missing = [r['name'] for r in team['roles'] if get_role(r['name']) is None]
assert not missing, f'不可解析角色: {missing}'
dag = team['pipeline']['dag']['nodes']
# DAG 节点除"编排引擎"（非角色汇总节点）外应可解析
bad_nodes = [nd['role'] for nd in dag if get_role(nd['role']) is None and nd['role'] != '编排引擎']
assert not bad_nodes, f'不可解析DAG节点: {bad_nodes}'
print("  PASS")
PY
if [ $? -eq 0 ]; then ok "T3 team.yaml 角色与 DAG 可解析"; else bad "T3 team.yaml"; fi

echo "▶ T4 公司化文档落位"
[ -f docs/COMPANY_MODEL.md ] && ok "T4 COMPANY_MODEL.md 存在" || bad "T4 COMPANY_MODEL.md 缺失"

echo "▶ T5 云端 settings.yml 人设落位"
for name in 架构·找需求 架构·价值确认 架构·竞品分析 架构·工具开发 架构·优化 架构·数据管理 架构·运维; do
  grep -q "name: \"$name\"" .cnb/settings.yml || { bad "T5 settings.yml 缺角色 $name"; continue; }
done
grep -q "name: \"$name\"" .cnb/settings.yml && echo "  ✅ T5 settings.yml 公司化人设齐全" || echo "  ❌ T5 settings.yml 缺角色"

echo ""
echo "======================================================"
echo "测试汇总：PASS=$PASS  FAIL=$FAIL"
if [ $FAIL -eq 0 ]; then echo "✅ 信号灯：🟢 通过（公司化三战线模型注册/契约/解析/文档/人设全部核验）"; else echo "❌ 信号灯：🔴 失败"; fi
exit $FAIL
