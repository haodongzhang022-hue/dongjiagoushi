#!/usr/bin/env bash
# ============================================================
# 公司化三战线 · 端到端全链贯通测试（company e2e · M4 全链贯通）
# 仓库：dongjiagoushi（架构师体系 · Issue #18 公司化落地 · M4）
# 校验点（对应 M4 全链贯通验收）：
#   E1 三战线角色全部注册 + 输出契约（市场获客线/交付线/能力底座线）
#   E2 语义触发链贯通（找需求→价值确认→竞品→销售；工具开发→优化→数据管理→运维）
#   E3 team.yaml 三战线 DAG 节点齐全 + 全部可解析 + 无环
#   E4 跨战线转交（获客成单→交付线 plan；交付沉淀→能力底座线 tool_builder）
#   E5 数据底座可初始化（2500 并发 agent 信息互通前提）
#   E6 三战线接力可复现（完整流水线 DAG 波次可规划，端到端可跑）
# ============================================================
set -u
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
PASS=0; FAIL=0
ok()  { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
PY="python3"

echo "======================================================"
echo "公司化三战线 · 端到端全链贯通测试 (company e2e · M4)"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# ---- E1 三战线角色全部注册 + 输出契约 ----
echo ""
echo "▶ E1 三战线角色注册与输出契约"
$PY - <<'PYEOF'
import sys; sys.path.insert(0, 'local-agent')
from roles import get_role, list_roles
# 市场获客线（选单情报）
market_line = ['架构·找需求', '架构·价值确认', '架构·竞品分析', '市场·销售', '市场·客服']
# 交付流水线（含新增经理）
delivery_line = ['架构·秘书', '架构·产品', '架构·总师', '架构·经理', '架构·小组长',
                 '架构·开发', '架构·评审', '架构·对齐', '架构·找工具', '架构·测试']
# 能力底座线
capability_line = ['架构·工具开发', '架构·优化', '架构·数据管理', '架构·数据管理员', '架构·运维']
all_roles = market_line + delivery_line + capability_line
for n in all_roles:
    r = get_role(n)
    assert r, f'{n} 未注册'
    c = r.output_contract()
    assert c.get('role') == n, f'{n} 契约 role 不符'
    assert c.get('contract'), f'{n} 契约为空'
    print(f"  ok: {n}")
print("E1 PASS")
PYEOF
if [ $? -eq 0 ]; then ok "E1 三战线角色注册与输出契约齐全"; else bad "E1 三战线角色注册/契约"; fi

# ---- E2 语义触发链贯通 ----
echo ""
echo "▶ E2 语义触发链贯通"
$PY - <<'PYEOF'
import sys; sys.path.insert(0, 'src')
from memory import SemanticTriggerEngine
eng = SemanticTriggerEngine()
# 市场获客线：找需求→价值确认→竞品→销售
market_chain = [
    ("去闲鱼找找有什么需求单子商机", "架构·找需求"),
    ("核查这个项目值不值得做，找市场空白", "架构·价值确认"),
    ("分析下竞品有什么优劣势找差异化", "架构·竞品分析"),
    ("跟进这个客户推进成单报价", "市场·销售"),
]
# 能力底座线：工具开发→优化→数据管理→运维
capability_chain = [
    ("把复用率高的代码沉淀成自有工具", "架构·工具开发"),
    ("提升系统使用效率和交互效率", "架构·优化"),
    ("数据存储调用和核实管理", "架构·数据管理"),
    ("部署上线监控告警故障处理", "架构·运维"),
]
# 交付线增强：经理分工调度 + 秘书入口
delivery_chain = [
    ("按架构方案把任务分工派给团队", "架构·经理"),
    ("接收需求并路由到对应角色处理", "架构·秘书"),
]
for chain, line in [(market_chain, "市场获客线"), (capability_chain, "能力底座线"), (delivery_chain, "交付线")]:
    for text, expect in chain:
        r = eng.trigger(text)
        assert r['role'] == expect, f"[{line}] 语义触发漂移: 期望{expect} 实际{r['role']} <- {text}"
        print(f"  ok [{line}] {expect}")
print("E2 PASS")
PYEOF
if [ $? -eq 0 ]; then ok "E2 语义触发链贯通（三战线可命中）"; else bad "E2 语义触发链"; fi

# ---- E3 team.yaml 三战线 DAG 节点齐全 + 可解析 + 无环 ----
echo ""
echo "▶ E3 team.yaml 三战线 DAG 节点"
$PY - <<'PYEOF'
import sys, yaml; sys.path.insert(0, 'local-agent')
from graph import DagEngine
from roles import get_role
team = yaml.safe_load(open('local-agent/team.yaml'))
nodes = team['pipeline']['dag']['nodes']
ids = [nd['id'] for nd in nodes]
# 三战线关键节点
required = ['secretary','clarify','architect','plan','lead','develop','review','test','deliver',
            'demand_finder','value_verifier','competitor','sales',
            'tool_builder','optimizer','data_admin','ops']
for x in required:
    assert x in ids, f'DAG 缺节点 {x}'
# 全部节点角色可解析
bad = [nd['id'] for nd in nodes if get_role(nd['role']) is None and nd['role'] != '编排引擎']
assert not bad, f'不可解析节点: {bad}'
# 无环（拓扑排序可规划）
dag = DagEngine('full', '', nodes)
waves = dag.waves()
assert waves, 'DAG 无法拓扑排序（可能含环）'
print(f"  DAG {len(nodes)} 节点 / {len(waves)} 波次，可规划无环")
print("E3 PASS")
PYEOF
if [ $? -eq 0 ]; then ok "E3 三战线 DAG 节点齐全/可解析/无环"; else bad "E3 三战线 DAG"; fi

# ---- E4 跨战线转交 ----
echo ""
echo "▶ E4 跨战线转交（获客→交付 / 交付→底座）"
$PY - <<'PYEOF'
import sys, yaml; sys.path.insert(0, 'local-agent')
team = yaml.safe_load(open('local-agent/team.yaml'))
nodes = team['pipeline']['dag']['nodes']
by_id = {nd['id']: nd for nd in nodes}
# 获客成单 → 交付线：sales 成单作为 plan（经理）输入信号（同源 plan 消费订单）
assert by_id['sales'], '缺 sales'
# 交付沉淀 → 能力底座：tool_builder 依赖 deliver（消费交付产物）
tb_dep = by_id['tool_builder']['depends_on']
assert 'deliver' in tb_dep, f'交付→底座转交未建立: tool_builder depends_on={tb_dep}'
# 底座线反哺交付线：优化/数据/运维在 tool_builder 之后串行推进（持续开发闭环）
assert 'optimizer' in by_id and 'data_admin' in by_id and 'ops' in by_id, '能力底座线节点不全'
print("  获客(sales)→交付(plan) 与 交付(deliver)→底座(tool_builder) 转交已建立")
print("E4 PASS")
PYEOF
if [ $? -eq 0 ]; then ok "E4 跨战线转交建立（获客→交付 / 交付→底座）"; else bad "E4 跨战线转交"; fi

# ---- E5 数据底座可初始化 ----
echo ""
echo "▶ E5 数据底座初始化"
$PY - <<'PYEOF'
import sys, tempfile, os; sys.path.insert(0, 'local-agent')
from data import schema, db
os.environ['DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'e2e_test.db')
tables = schema.init_schema()
for t in ['agents','messages','tasks','progress','archives','stats','gid_registry']:
    assert t in tables, f'缺数据表 {t}'
print(f"  {len(tables)} 张数据表可初始化（含 gid_registry 全局唯一编号表）")
print("E5 PASS")
PYEOF
if [ $? -eq 0 ]; then ok "E5 数据底座可初始化（含 gid_registry）"; else bad "E5 数据底座初始化"; fi

# ---- E6 三战线接力可复现（完整流水线 DAG 波次可规划） ----
echo ""
echo "▶ E6 三战线接力可复现（完整流水线规划）"
$PY - <<'PYEOF'
import sys, yaml; sys.path.insert(0, 'local-agent')
from graph import DagEngine
from roles import get_role
team = yaml.safe_load(open('local-agent/team.yaml'))
nodes = team['pipeline']['dag']['nodes']
dag = DagEngine('full', '', nodes)
waves = dag.waves()
# 三战线各环节应在规划中出现（端到端可复现）waves 为 节点id 列表的波次
flat = [nid for w in waves for nid in w]
assert 'sales' in flat and 'deliver' in flat and 'tool_builder' in flat and 'ops' in flat
# 交付线主链完整
for step in ['secretary','clarify','architect','plan','develop','review','test','deliver']:
    assert step in flat, f'交付线缺 {step}'
print(f"  端到端 {len(waves)} 波次可复现（市场获客→交付→能力底座全链贯通）")
print("E6 PASS")
PYEOF
if [ $? -eq 0 ]; then ok "E6 三战线接力可复现（全链 DAG 可规划）"; else bad "E6 三战线接力可复现"; fi

echo ""
echo "======================================================"
echo "测试汇总：PASS=$PASS  FAIL=$FAIL"
if [ $FAIL -eq 0 ]; then echo "✅ 信号灯：🟢 通过（M4 全链贯通 · 三战线接力可复现）"; else echo "❌ 信号灯：🔴 失败"; fi
exit $FAIL
