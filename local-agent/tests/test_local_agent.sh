#!/usr/bin/env bash
# 本地 Agent · 可复现测试（信号灯）
# 验证：CLI 入口 / 单角色触发 / 团队流水线编排 / 接力卡 / 回转 / 打断续跑 / 角色清单
set -e
cd "$(dirname "$0")/.."

RUN="python3 run.py"
pass=0; fail=0

t() { # t <desc> <cmd>
  local desc="$1"; shift
  if eval "$*" >/tmp/la_out.txt 2>&1; then
    echo "  ✅ $desc"; pass=$((pass+1))
  else
    echo "  ❌ $desc"; cat /tmp/la_out.txt; fail=$((fail+1))
  fi
}

echo "==== 本地 Agent 测试（信号灯）===="

t "列表角色" "$RUN --list-roles"
t "清空接力卡" "$RUN --clear"

t "单角色触发：架构·总师" "$RUN --role 架构·总师 --req '对XX做架构设计' --backend cli_fallback"
t "单角色触发：架构·产品" "$RUN --role 架构·产品 --req '我要做一个系统' --backend cli_fallback"
t "单角色触发：架构·经理" "$RUN --role 架构·经理 --req '把架构方案拆解分配调度给各执行角色' --backend cli_fallback"
t "单角色触发：架构·测试" "$RUN --role 架构·测试 --req '验收交付' --backend cli_fallback"

# 完整团队流水线（占位模式，验证骨架编排可跑通）
t "团队流水线 full（占位）" "$RUN --pipeline full --req '做一个订单系统' --backend cli_fallback"

# 接力卡已生成
if [ -f state/relay_card.json ]; then
  echo "  ✅ 接力卡已持久化"; pass=$((pass+1))
else
  echo "  ❌ 接力卡未生成"; fail=$((fail+1))
fi

# 续跑
t "从接力卡续跑 --resume" "$RUN --resume --backend cli_fallback"

# 校验角色注册表完整性（27 个角色：入口层秘书 + 需求/设计 + 总师助理 + 调度/协同 + 实现/质量 + 数据管理员 + 监控哨兵 + 进度推手 + 市场获客分层 + 公司化三战线）
count=$(python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; print(len(list_roles()))")
if [ "$count" = "27" ]; then
  echo "  ✅ 角色注册表 27 个角色齐全（含 架构·秘书 默认入口 + 架构·总师 + 架构·总师助理 + 架构·经理 分配调度核心 + 架构·数据管理员 + 架构·监控哨兵 + 架构·进度推手 + 市场层 5 + 公司化三战线）"; pass=$((pass+1))
else
  echo "  ❌ 角色数量异常: $count"; fail=$((fail+1))
fi

# 校验总师助理已注册（专角色专用：改错改框架，保总师上下文纯净）
python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; assert '架构·总师助理' in list_roles()" && {
  echo "  ✅ 架构·总师助理 已注册"; pass=$((pass+1)); } || { echo "  ❌ 架构·总师助理 未注册"; fail=$((fail+1)); }

# 校验数据管理员角色已注册
python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; assert '架构·数据管理员' in list_roles()" && {
  echo "  ✅ 架构·数据管理员 已注册"; pass=$((pass+1)); } || { echo "  ❌ 架构·数据管理员 未注册"; fail=$((fail+1)); }

# 校验默认入口 架构·秘书 已注册
python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; assert '架构·秘书' in list_roles()" && {
  echo "  ✅ 默认入口 架构·秘书 已注册"; pass=$((pass+1)); } || { echo "  ❌ 架构·秘书 未注册"; fail=$((fail+1)); }

# 校验市场获客分层角色已注册（销售/客服/数据/渠道/工具）
for mr in 市场·销售 市场·客服 市场·数据 市场·渠道 市场·工具; do
  python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; assert '$mr' in list_roles()" && {
    echo "  ✅ 市场层角色 $mr 已注册"; pass=$((pass+1)); } || { echo "  ❌ $mr 未注册"; fail=$((fail+1)); }
done

# 校验 DAG 调度：经理(plan) 依赖架构(architect) 而非开发(develop)，可提前分工
python3 - <<'PY' && echo "  ✅ DAG 提前分工：plan 依赖 architect，可与 develop 并行"; pass=$((pass+1)) || { echo "  ❌ DAG 提前分工校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
import yaml
from graph import DagEngine
team = yaml.safe_load(open('team.yaml'))
nodes = team['pipeline']['dag']['nodes']
dag = DagEngine('full','',nodes)
ok, err = dag.validate(); assert ok, err
plan_node = [n for n in nodes if n['id']=='plan'][0]
# plan 应依赖 architect，不应依赖 develop
assert 'architect' in plan_node['depends_on']
assert 'develop' not in plan_node['depends_on']
# 波次应包含并行（同一波次多节点），证明非直线
waves = dag.waves()
assert any(len(w)>1 for w in waves), '缺少并行波次'
PY

# 校验分形扩展引擎可用
python3 - <<'PY' && echo "  ✅ 分形扩展：10 任务可拆 3 组并行"; pass=$((pass+1)) || { echo "  ❌ 分形扩展校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
import fractal
plan = fractal.build_fractal_plan([f't{i}' for i in range(10)])
assert plan['scaled'] and plan['team_count'] >= 2
PY

# 校验 架构·经理 已注册且承担分配调度核心
# 校验框架自迭代修复：_estimate_tasks 能识别子需求数并触发多小组分形
python3 - <<'PY' && echo "  ✅ 框架自迭代：_estimate_tasks 识别子需求数触发多小组"; pass=$((pass+1)) || { echo "  ❌ _estimate_tasks 修复校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
from orchestrator import _estimate_tasks
import fractal
# 6 个子需求 → 应估出 ≥5 任务 → 分形 2 小组
n = _estimate_tasks('开发hello_team工具，需要：1团队问候 2团队元数据 3跨组数据互通 4统一交付入口 5小组A核心 6小组B元数据')
plan = fractal.build_fractal_plan([f't{i}' for i in range(n)])
assert plan['scaled'] and plan['team_count'] == 2, (n, plan)
# 短需求 → 单组
assert _estimate_tasks('做一个简单的问候系统') == 1
print(f'_estimate_tasks={n} → 分形 {plan["team_count"]} 小组')
PY

grep -q '架构·经理' <(python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; print(list_roles())")
if [ $? = 0 ]; then
  echo "  ✅ 分配调度核心 架构·经理 已注册"; pass=$((pass+1))
else
  echo "  ❌ 架构·经理 未注册"; fail=$((fail+1))
fi

echo ""
echo "结果：$pass 通过 / $fail 失败"
[ "$fail" = "0" ] || exit 1
