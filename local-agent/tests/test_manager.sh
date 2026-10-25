#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 经理/小组长能力完善测试（信号灯 · Issue #239）
# ============================================================
# 用户痛点（Issue #239）：
#   ① 经理假装分工——只声明、不激活别的 Issue；
#   ② 只有一条路，计划都给他了，他还纠结要不要按计划走；
#   ③ 他不知道自己职责是什么，原地当嘴；
#   ④ 小组长也不及格——经理调配小组长也应该能完成。
# 本测试给这四条上红灯，红灯即能力缺失。
set -e
cd "$(dirname "$0")/.."
PY=python3

echo "===== [manager] 1. 计划即命令：单路无抉择，纠结不是合法结果 ====="
$PY - <<'EOF'
from manager.engine import resolve_choice, parse_plan
# ① 只有一条路 → 必然 EXECUTE（不存在"要不要按计划走"的分支）
r = resolve_choice(["按计划开发登录模块"])
assert r["decision"] == "EXECUTE", f"单路必须 EXECUTE，实际 {r}"
assert "唯一路径" in r["reason"]
# ② 多路 → 仍 EXECUTE（默认取首个，执行中纠偏），不返回"纠结/再想想/暂缓"
r2 = resolve_choice(["方案A", "方案B"])
assert r2["decision"] == "EXECUTE" and r2["choice"] == "方案A"
# ③ 空 → BLOCKED（没有路才该停，且要显式说要什么）
r3 = resolve_choice([])
assert r3["decision"] == "BLOCKED"
# ④ 任何路径都不会产出"纠结"类决策
for decision in (r["decision"], r2["decision"], r3["decision"]):
    assert decision in ("EXECUTE", "BLOCKED"), f"非法决策 {decision}"
# ⑤ 计划文本 → 可派发清单（计划进得来就一定能变成任务）
plan = parse_plan("1. 开发登录模块\n2. 评审登录模块\n3. 测试登录模块")
assert [p["role"] for p in plan] == ["架构·开发", "架构·评审", "架构·测试"], plan
print("  ✅ 单路=直接执行；多路=取首个；空=显式要计划；无『纠结』出口")
print(f"      单路判定={r['decision']} / 多路={r2['decision']} / 空={r3['decision']}")
EOF

echo "===== [manager] 2. ACTIVATE 闸门：只声明不算分工，必须真激活 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr2.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

# ① 空计划 → refused（唯一合法输出是显式要计划，不是原地纠结）
m = ManagerEngine(dry_run=True)
empty = m.activate("")
assert empty["refused"] is True and empty["count"] == 0

# ② 给了计划 → 逐条激活，每条都有 task gid / agent gid / 目标 Issue
r = m.execute_plan("1. 开发登录模块\n2. 评审登录模块")
assert r["refused"] is False
assert r["count"] == 2, f"应激活 2 条，实际 {r['count']}"
assert all(a["task_id"] and a["agent_id"] for a in r["activated"])
assert "activated" not in ("", None)
# 计划项被真派给对应角色（不是全堆给开发）
assert [a["role"] for a in r["activated"]] == ["架构·开发", "架构·评审"]
print("  ✅ 计划 → 逐条激活（任务 gid + 承接角色 + Issue 载体），空计划显式拒绝")
print(f"      激活 {r['count']} 条：{[a['role'] for a in r['activated']]}")
EOF

echo "===== [manager] 3. 反假装：回执了 [接单] 却没下文 = 假装分工，必须现形 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr3.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

# 对端只回执 [接单]，没有任何开工/进度 → 典型的"嘴上接单"
m = ManagerEngine(dry_run=True, simulate={"*": "accept"})
r = m.execute_plan("1. 开发登录模块")
sup = r["supervise"]
assert sup["summary"]["fake"] == 1, f"应识别 1 条假装，实际 {sup['summary']}"
v = sup["verdicts"][0]
assert v["verdict"] == "fake" and v["disposition"] == "hand_to_lead"
assert "假装" in v["reason"]
assert v.get("leader_plan"), "假装的任务必须给出小组长落实安排（活不掉地上）"
print("  ✅ 只回执不干活 → 判 fake → 转小组长落实（不再当已分工）")
print(f"      verdict={v['verdict']} disposition={v['disposition']}")

# 对端真开工 → 判 real，不误伤
import dispatch_engine
a = r["activated"][0]
admin.record_event(a["agent_id"], "work_started", {"note": "真开工"}, a["task_id"])
sup2 = m.supervise()
assert sup2["summary"]["real"] == 1, f"真干活应判 real，实际 {sup2['summary']}"
assert sup2["summary"]["ok"] is True
print("  ✅ 真开工有证据 → 判 real（不误伤正常推进）")
EOF

echo "===== [manager] 4. 督促：无人接单 → 调配小组长（活不掉地上，也不原地纠结） ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr4.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

# 对端完全不理（无回执）→ 再唤醒一次 → 仍无 → 交小组长
m = ManagerEngine(dry_run=True, simulate={"架构·开发": "ignore"})
r = m.execute_plan("1. 开发登录模块\n2. 评审登录模块")
p = r["push"]
assert len(p["awaiting"]) == 2, f"应暴露 2 条待真实唤醒，实际 {p['awaiting']}"
assert len(p["delegated"]) == 2, "无人接单必须调配小组长落实"
lp = p["delegated"][0]["leader_plan"]
assert lp["lead_role"] == "架构·小组长"
assert lp["devs_per_team"] >= 1
assert lp["first_action"] and lp["acceptance"], "小组长安排必须可执行（首动作+验收口径）"
assert p["verified_all_awake"] is False
print("  ✅ 无人接单 → 再唤醒 → 仍无 → 调配小组长（含首动作+验收口径）")
print(f"      待接单={len(p['awaiting'])} 转小组长={len(p['delegated'])}")

# 混合：一半真接一半不理 → 诚实统计，不谎报全部完成
m2 = ManagerEngine(dry_run=True, simulate={"架构·开发": "accept"})
r2 = m2.execute_plan("1. 开发登录模块\n2. 评审登录模块")
assert len(r2["push"]["accepted"]) == 1 and len(r2["push"]["delegated"]) == 1
assert r2["supervise"]["summary"]["ok"] is False
print("  ✅ 混合场景诚实统计（不谎报全部完成）")
EOF

echo "===== [manager] 5. 监督：停滞 / 横跳 用进度尺判定并交哨兵打断 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr5.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine
import dispatch_engine

m = ManagerEngine(dry_run=True, simulate={"*": "accept"})
r = m.execute_plan("1. 开发登录模块")
a = r["activated"][0]
admin.record_event(a["agent_id"], "work_started", {"note": "开工"}, a["task_id"])
# 连续两轮距离不变 → 停滞
for _ in range(2):
    dispatch_engine.track_progress(a["task_key"], a["agent_id"],
                                   target=3, goal_total=3, current=1, note="原地不动")
sup = m.supervise()
assert sup["summary"]["stall"] == 1, f"应判停滞，实际 {sup['summary']}"
assert sup["verdicts"][0]["disposition"] == "interrupt"
assert sup["verdicts"][0].get("sentinel") == "interrupted"

# 来回横跳：current 反复涨落，距离始终不缩 → 横跳（不是停滞）
m2 = ManagerEngine(dry_run=True, simulate={"*": "accept"})
r2 = m2.execute_plan("1. 开发报表模块")
b = r2["activated"][0]
admin.record_event(b["agent_id"], "work_started", {"note": "开工"}, b["task_id"])
for cur in (1, 1, 2, 1):
    dispatch_engine.track_progress(b["task_key"], b["agent_id"],
                                   target=5, goal_total=5, current=cur, note="横跳")
sup2 = m2.supervise()
assert sup2["summary"]["jump"] == 1, f"应判横跳，实际 {sup2['summary']}"
assert sup2["verdicts"][0]["disposition"] == "interrupt"
print("  ✅ 停滞/横跳由进度尺判定 → 哨兵打断（量化距离说话，不靠感觉）")
print(f"      停滞={sup['summary']['stall']} 横跳={sup2['summary']['jump']}")
EOF

echo "===== [manager] 6. 职责护栏：不是经理的活当场拦住并指向正确角色 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr6.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

m = ManagerEngine(dry_run=True)
cases = {
    "写代码实现登录": "架构·开发",
    "评审这段代码": "架构·评审",
    "跑测试验收": "架构·测试",
    "需求澄清一下": "架构·产品",
    "合并这个 PR": "架构·交付",
}
for action, expect in cases.items():
    g = m.guard(action)
    assert g["allowed"] is False, f"{action} 应被拦"
    assert g["hand_to"] == expect, f"{action} 应指向 {expect}，实际 {g['hand_to']}"

# 越界校验针对"经理自己要做的单个动作"，不是把派活当越界：
# 计划进入执行入口即派发意图 → 一律激活（计划里的"评审/测试/写代码"都是要派出去的）
res = m.execute_plan("写代码实现登录模块")
assert res["refused"] is False and res["count"] == 1
assert res["activated"][0]["role"] == "架构·开发", "计划项应派给开发，不是经理自己写"

# 经理自己的职责放行
assert m.guard("把任务派给开发并督促进度")["allowed"] is True
print("  ✅ 越界动作被拦并指向正确角色（不硬做、不装作会做）")
print(f"      拦截 {len(cases)} 类越界动作")
EOF

echo "===== [manager] 7. 小组长带队：真派开发 + 客观验证 + 整合交付 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_lead7.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import LeadEngine

l = LeadEngine(devs_per_team=2)
plan = l.dispatch_devs({"task_key": "登录模块"})
# ① 真派开发：组内 2 人，各独立 gid + 子任务切片
assert len(plan["devs"]) == 2
assert all(d["agent_id"] and d["task_key"] != plan["task_key"] for d in plan["devs"])
assert len({d["agent_id"] for d in plan["devs"]}) == 2, "每开发必须独立 gid"

# ② 一个没过 → 不放行（执行-验证分离）
r = l.run_round(plan, [("dev0", True, "pytest pass"), ("dev1", False, "lint fail")])
assert r["verdict"] == "REWORK"
assert l.aggregate(plan, r)["status"] == "continue", "未全过不得整合交付"

# ③ 全员客观通过 → 整合统一交付
r2 = l.run_round(plan, [("dev0", True, "pytest pass"), ("dev1", True, "lint pass")])
agg = l.aggregate(plan, r2)
assert agg["status"] == "delivered", f"全过应交付，实际 {agg}"
assert agg["record"]["approved_devs"] == 2
print("  ✅ 派 2 开发 → 未全过不放行 → 全过才整合交付（有交付留痕）")
print(f"      一次过 {r['verdict']} / 全过 {agg['status']}")
EOF

echo "===== [manager] 8. 小组长熔断：重做超限上报经理，不无限重试 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_lead8.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import LeadEngine

l = LeadEngine(devs_per_team=2, max_attempts=1)
plan = l.dispatch_devs({"task_key": "支付模块"})
last = None
for _ in range(3):
    last = l.run_round(plan, [("dev0", False, "测试红"), ("dev1", True, "过")])
    if last["verdict"] == "ESCALATED":
        break
assert last["verdict"] == "ESCALATED", f"超限应上报，实际 {last['verdict']}"
agg = l.aggregate(plan, last)
assert agg["status"] == "escalated" and "上报经理" in agg["next"]
print("  ✅ 重做超 max_attempts → ESCALATED 上报经理（不无限重试、不硬撑）")
EOF

echo "===== [manager] 9. 角色接线：经理/小组长真的会调，不是只有嘴 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_roles9.db")
from data import admin, schema; admin.init(); schema.init_schema()
from roles.manager import ManagerRole
from roles.team_lead import TeamLeadRole

mgr = ManagerRole()
for fn in ("manager_execute", "manager_activate", "manager_push",
           "manager_supervise", "manager_status", "manager_guard"):
    assert callable(getattr(mgr, fn, None)), f"经理缺 {fn}"

# 角色一站式跑通（不碰平台的演练模式）
mgr.manager_engine.dry_run = True
r = mgr.manager_execute("1. 开发登录模块")
assert r["count"] == 1 and r["refused"] is False
contract = mgr.output_contract()
assert "真激活结果" in contract["contract"][1]
assert len(contract["iron_rules"]) == 3
assert "manager_engine" in mgr.capability()

lead = TeamLeadRole()
for fn in ("lead_dispatch_devs", "lead_run_round", "lead_aggregate",
           "lead_drive", "lead_overview", "group_convergence"):
    assert callable(getattr(lead, fn, None)), f"小组长缺 {fn}"
d = lead.lead_drive({"task_key": "登录模块"},
                    [("dev0", True, "pytest pass"), ("dev1", True, "pytest pass")])
assert d["aggregate"]["status"] == "delivered"
assert "lead_engine" in lead.capability()
print("  ✅ 经理 6 个入口 + 小组长 6 个入口全部可调用并跑通（嘴已接上手）")
EOF

echo "===== [manager] 10. 端到端：经理 → 小组长 → 整合交付（活不掉地上） ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_e2e10.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine, LeadEngine

# 经理真激活计划；但对端集体不理（真实世界最常见的断链）
m = ManagerEngine(dry_run=True, simulate={"*": "ignore"})
r = m.execute_plan("1. 开发登录模块\n2. 评审登录模块\n3. 测试登录模块")
assert r["count"] == 3
assert len(r["push"]["delegated"]) == 3, "三条都要有承接人"

# 经理把活交小组长 → 小组长真带队干完（客观验证通过才交）
delivered = []
for task in r["push"]["delegated"]:
    key = task["task_key"]
    n = task["leader_plan"]["devs_per_team"]
    lead = LeadEngine(devs_per_team=n)
    out = lead.drive({"task_key": key},
                     [(f"dev{i}", True, "pytest pass") for i in range(n)])
    delivered.append(out["aggregate"]["status"])
assert delivered == ["delivered"] * 3, f"三条应全部交付，实际 {delivered}"

s = r["summary"]
print("  ✅ 经理激活 3 条 → 无人接单 → 全部转小组长 → 小组长 3 条全部整合交付")
print(f"      {s}")
EOF

echo "===== [manager] 11. 激活断链回归：cnb CLI 的 YAML 输出必须解析出 Issue 编号 ====="
$PY - <<'EOF'
import os, sys, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_parse11.db")
from data import admin, schema; admin.init(); schema.init_schema()
import dispatch_engine as D

# 真实根因（Issue #239）：cnb CLI 输出的是 YAML 风格文本且编号带引号，
# 旧实现 int(val) 遇 "242" 直接 ValueError → 返回 None →
# 每条任务都被判 blocked_no_issue → 真实环境永远激活不出 Issue。
yaml_out = 'status: 201\ncontentType: application/json\n'
yaml_out += 'data:\n  number: "242"\n  state: open\n'
assert D._parse_issue_number(yaml_out) == 242, "YAML 带引号编号必须解析出 242"
assert D._parse_issue_number('{"data": {"number": 242}}') == 242
assert D._parse_issue_number('{"data": {"number": "242"}}') == 242
assert D._parse_issue_number("boom") is None
assert D._parse_issue_number("") is None

# 解析成功 → ACTIVATE 闸门才对真实环境给出 platform_active=True
from manager import ManagerEngine
class FakeRun:
    returncode = 0
    stdout = yaml_out
    stderr = ""
orig = D.subprocess.run
D.subprocess.run = lambda *a, **k: FakeRun()
try:
    m = ManagerEngine(repo="org/repo", dry_run=False)
    m.dry_run = False
    act = m.activate([{"task_key": "回归任务", "title": "回归任务",
                       "role": "架构·开发", "domain": "自检", "detail": "x"}])
    assert act["platform_activated"] == 1, act
    assert act["activated"][0]["issue"] == 242
    assert act["activated"][0]["state"] == "activated"
finally:
    D.subprocess.run = orig
print("  ✅ YAML/JSON 两种输出都能解析出编号 → 真实环境下不再恒判 blocked_no_issue")
EOF

echo "===== [manager] ALL PASS ====="
