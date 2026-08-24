#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 调度中枢（dispatcher）· 事件驱动自动化调度层功能测试
# 验证：事件规范化 / 规则匹配 / Action队列（自动优先+人工闸门）/ 防无效护栏
#       （去重·进度上限）/ 驳回迭代闭环（按gid回派）/ sentinel进度上限判定 / Web面板
# 对应 docs/DISPATCHER.md；纳入 local-agent 测试信号灯。
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH=$(mktemp /tmp/dispatcher-test-XXXX.db)
rm -f "$DB_PATH"

echo "===== [dispatcher] 1. 事件源规范化 + 外部适配器插槽 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import source

# 本仓库事件规范化
ev = source.normalize_event({'event_type':'rejection','gid':'tk-abc','detail':{'reason':'🔴必修'}})
assert ev['event_type'] == 'rejection' and ev['gid'] == 'tk-abc'
# issue.open 归一
ev2 = source.normalize_event({'event_type':'issue_update','entity':'x'})
assert ev2['event_type'] == 'issue.update'
# 外部适配器插槽可注册
class External(source.ExternalAdapter):
    def poll(self):
        return [{'event_type':'requirement','entity':'登录需求','source':'gitee','detail':{}}]
ext = External('gitee')
ev3 = ext.poll()[0]
assert ev3['entity'] == '登录需求'
print("  ✅ 事件规范化 + 外部适配器插槽通过")
EOF

echo "===== [dispatcher] 2. 触发规则引擎（自动优先/规则优先）===="
$PY - <<'EOF'
from dispatcher.rules import RuleEngine
re = RuleEngine()
assert len(re.rules()) >= 5, "应含默认规则表"
# 驳回 → rejection_reroute（按gid回派）
assert re.match({'event_type':'rejection'})['name'] == 'rejection_reroute'
# 岗位需求 → 架构·产品
r = re.match({'event_type':'requirement'})
assert r['target_role'] == '架构·产品'
# issue.open → 架构·评审
r = re.match({'event_type':'issue.open'})
assert r['target_role'] == '架构·评审'
print("  ✅ 规则引擎（四大场景）通过")
EOF

echo "===== [dispatcher] 3. Action 队列 · 自动优先 + 人工审核闸门 ====="
$PY - <<'EOF'
from data import schema, db
schema.init_schema()
from dispatcher.engine import Dispatcher
from dispatcher import source, queue as queue_mod

d = Dispatcher()
# 场景A：issue.open（auto）→ 自动派发，不卡进程
d.process_event(source.normalize_event({'event_type':'issue.open','entity':'订单模块需评审','gid':'tk-订单','detail':{}}))
# 场景B：missed.scan（hold 规则）→ 进人工审核闸门
r_hold = d.process_event(source.normalize_event({'event_type':'missed.scan','entity':'遗漏项','gid':'tk-遗漏','detail':{}}))
assert r_hold['status'] == 'hold', f"应进人工闸门, got {r_hold['status']}"
# auto 队列直接派发，hold 等人工
ov = queue_mod.overview()
assert 'dispatched' in ov, "auto 应已派发"
assert 'hold' in ov, "hold 应进闸门"
print(f"  队列全貌: {ov}")
print("  ✅ Action 队列（自动优先 + 人工审核闸门）通过")
EOF

echo "===== [dispatcher] 4. 驳回迭代闭环 · 按 gid 回派改进重提 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import reject as reject_mod
from dispatcher.engine import Dispatcher

rej = reject_mod.register(task_id='tk-结算', gid='tk-结算', agent_id='ag-结算开发',
                          reason='评审 🔴必修：并发竞态未处理', level='must')
assert rej['iteration'] == 1 and rej['status'] == 'pending'
# 触发迭代回派（按 gid 精准路由到负责 agent）
results = Dispatcher().scan_rejections()
assert results and results[0]['status'] == 'reassigned'
assert results[0]['target_agent'] == 'ag-结算开发', "应精准回派原负责 agent"
# 驳回非终点：再次驳回 → 迭代次数 +1
rej2 = reject_mod.register(task_id='tk-结算', gid='tk-结算', agent_id='ag-结算开发',
                           reason='复评 🔴必修：仍有缺陷', level='must')
assert rej2['iteration'] == 2, "驳回非终点，进入再次迭代"
# 通过 → 闭环收尾
reject_mod.mark_approved(rej2['rejection_id'])
assert reject_mod.latest('tk-结算')['status'] == 'approved'
print("  ✅ 驳回迭代闭环（按 gid 回派 + 迭代 + 非终点）通过")
EOF

echo "===== [dispatcher] 5. 防无效护栏 · 去重 + 进度上限 ====="
$PY - <<'EOF'
from data import schema, db
schema.init_schema()
from dispatcher.engine import Dispatcher
from dispatcher import source
from dispatcher.guard import Guard

d = Dispatcher()
# 同一驳回只派一次（防死循环/防反复刷）
r1 = d.process_event(source.normalize_event({'event_type':'rejection','gid':'tk-x','detail':{'task_id':'tk-x','agent_id':'ag-x'}}))
r2 = d.process_event(source.normalize_event({'event_type':'rejection','gid':'tk-x','detail':{'task_id':'tk-x','agent_id':'ag-x'}}))
assert r1['status'] == 'dispatched'
assert r2['status'] == 'rejected' and 'dedup' in r2['note'], "同一驳回应被去重拦截"
# 进度上限：最大完成度不再提升 → 拦截继续派发
g = Guard()
for i in range(5):
    db.execute("INSERT INTO goal_meters (meter_id,task_id,agent_id,target,goal_total,current,distance,delta,note,ts) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (f'cap-{i}','tk-stuck','ag-stuck','修复','1.0','0.7','0.3','0.0','没进展', db.now_iso()))
ok, reason = g.evaluate({'gid':'tk-stuck','event_type':'rejection','dedup_key':'k','target_agent':'ag-stuck'})
assert not ok and 'progress_cap' in reason, "进度上限应拦截"
print("  ✅ 防无效护栏（去重 + 进度上限）通过")
EOF

echo "===== [dispatcher] 6. sentinel 进度上限判定（最大完成度封顶）===="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from sentinel import detect
# 最大完成度封顶于 70%，最近3条不再提升 → progress_cap_stall
series = [
    {'current':0.5,'goal_total':1.0,'distance':0.5,'note':'推进'},
    {'current':0.7,'goal_total':1.0,'distance':0.3,'note':'推进'},
    {'current':0.7,'goal_total':1.0,'distance':0.3,'note':'卡住'},
    {'current':0.7,'goal_total':1.0,'distance':0.3,'note':'同一步'},
    {'current':0.7,'goal_total':1.0,'distance':0.3,'note':'没进展'},
]
res = detect.analyze(series, goal_total=1.0, task_id='tk-cap')
assert res['hit'] and res['reason'] == 'progress_cap_stall'
assert '未完成' in res['detail']['note']
# 正常单调推进 → 不误伤
ok_series = [
    {'current':0.3,'goal_total':1.0,'distance':0.7,'note':'稳步'},
    {'current':0.5,'goal_total':1.0,'distance':0.5,'note':'稳步'},
    {'current':0.7,'goal_total':1.0,'distance':0.3,'note':'稳步'},
    {'current':0.9,'goal_total':1.0,'distance':0.1,'note':'稳步'},
]
res2 = detect.analyze(ok_series, goal_total=1.0, task_id='tk-ok')
assert not res2['hit'], f"正常推进不应误伤, got {res2['reason']}"
print("  ✅ sentinel 进度上限判定（最大完成度封顶 + 不误伤）通过")
EOF

echo "===== [dispatcher] 7. Web 可视化面板 ====="
$PY - <<'EOF'
from data import schema
schema.init_schema()
from dispatcher import webui
from dispatcher.engine import Dispatcher
from dispatcher import source, reject as reject_mod
d = Dispatcher()
d.process_event(source.normalize_event({'event_type':'issue.open','entity':'报表需评审','gid':'tk-报表','detail':{}}))
reject_mod.register(task_id='tk-结算', gid='tk-结算', agent_id='ag-结算开发', reason='🔴必修 竞态')
d.scan_rejections()
payload = webui._overview_payload()
html_out = webui.render_html(payload)
for k in ['调度中枢监控面板','待路由队列','驳回迭代闭环','哨兵断点','目标进度尺','守卫拦截']:
    assert k in html_out, f"面板缺 {k}"
print(f"  面板 HTML {len(html_out)} 字节，含全部核心板块")
print("  ✅ Web 可视化面板通过")
EOF

echo "===== [dispatcher] 8. CLI 入口 ====="
$PY -m dispatcher.cli overview >/dev/null && echo "  ✅ dispatcher.cli overview 可运行"
$PY -m dispatcher.cli reject --task tk-demo --agent ag-demo --reason "🔴必修 演示" >/dev/null && echo "  ✅ dispatcher.cli reject 可运行"

rm -f "$DB_PATH"
echo ""
echo "✅ [dispatcher] 全部测试通过"
