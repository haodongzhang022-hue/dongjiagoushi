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
assert "假装" in v["reason"] or "演练" in v["reason"]
assert v.get("leader_plan"), "假装的任务必须给出小组长落实安排（活不掉地上）"
print("  ✅ 只回执不干活 → 判 fake → 转小组长落实（不再当已分工）")
print(f"      verdict={v['verdict']} disposition={v['disposition']}")

# 对端真开工（走标准工作面）→ 判 real，不误伤
from manager.work import RoleWorkFace
a = r["activated"][0]
face = RoleWorkFace(role=a["role"], agent_id=a["agent_id"])
face.accept(a["task_key"], task_id=a["task_id"])
face.start(a["task_key"], task_id=a["task_id"])
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
from manager.work import RoleWorkFace, WorkerRegistry
reg = WorkerRegistry().register("架构·开发",
                                RoleWorkFace(role="架构·开发", agent_id="ag-dev"))
m2 = ManagerEngine(dry_run=True, workers=reg, simulate={"架构·评审": "ignore"})
r2 = m2.execute_plan("1. 开发登录模块\n2. 评审登录模块")
assert len(r2["push"]["accepted"]) == 1, f"开发应真上工，实际 {r2['push']}"
assert len(r2["push"]["delegated"]) == 1, "评审无人接单必须转小组长"
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
# 铁律只增不减：3 条基础 + 承上启下/权责内自决/穷尽才上交
assert len(contract["iron_rules"]) >= 3, contract["iron_rules"]
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

echo "===== [manager] 12. 承上启下·承上段：翻译不是复述，裁掉必须给理由+替代路线 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr12.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.flow import translate

plan = """1. 登录模块实现（角色:架构·开发）
2. 登录代码评审（角色:架构·评审）
3. 这件事你们看着办"""
tr = translate(plan, north_star="登录功能上线")
# ① 复述北极星（经理得知道自己在往哪儿使劲，不是原样转发）
assert tr["north_star"] == "登录功能上线"
# ② 可执行项被翻译成带角色/域的派发项（不是一句原文）
assert [i["role"] for i in tr["items"]] == ["架构·开发", "架构·评审"], tr["items"]
assert all(i["domain"] and i["priority"] for i in tr["items"])
# ③ 裁掉不可执行项，且必须给理由 + 替代路线（不许默默丢，也不许原样下发）
assert len(tr["dropped"]) == 1, tr["dropped"]
d = tr["dropped"][0]
assert d["reason"] and d["alt_lane"], f"裁掉项必须带理由与替代路线：{d}"
# ④ 没给北极星时自己提炼一句（不编，诚实说明在往哪使劲）
tr2 = translate("1. 结算模块实现（角色:架构·开发）")
assert "结算模块实现" in tr2["north_star"]
print("  ✅ 承上：北极星复述 + 计划翻译成可派项 + 裁掉项给理由与替代路线")
print(f"      可执行 {len(tr['items'])} 条 / 裁掉 {len(tr['dropped'])} 条")
EOF

echo "===== [manager] 13. 找通路：一条断了换下一条，不是默认'没能力做' ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr13.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine, lanes as L

m = ManagerEngine(dry_run=True)
# ① 通路不是一条：平台/完整@/CodeBuddy/直接handle/组长/自己兜底都在册
all_lanes = [x["lane"] for x in m.lanes("架构·开发")]
for required in ("platform", "fullpath", "codebuddy", "lead", "self"):
    assert required in all_lanes, f"缺通路 {required}: {all_lanes}"
assert "codebuddy" in all_lanes, "用户点名：@CodeBuddy 这条也是通路，不能默认没能力"

# ② 就绪由代码判（不靠感觉）：无 repo 时 platform 不通并说明缺什么
r = L.readiness("platform", repo="", cnb=True)
assert r["ready"] is False and r["missing"]
assert L.readiness("platform", repo="org/repo", cnb=True)["ready"] is True

# ③ 多通路穷举：前两条真失败，第三条成功 → 整体成功，逐条留痕
calls = []
def fail(name):
    def _f():
        calls.append(name); return {"ok": False, "error": "通道被限"}
    return _f
def ok(name):
    def _f():
        calls.append(name); return {"ok": True, "via": name}
    return _f
res = L.attempt("架构·开发", {
    "platform": fail("platform"),
    "fullpath": fail("fullpath"),
    "codebuddy": ok("codebuddy"),
}, repo="org/repo", cnb=True, handle="架构·开发", allow_self=True)
assert res["ok"] is True and res["lane"] == "codebuddy", res
assert calls[:3] == ["platform", "fullpath", "codebuddy"], f"必须按序真试：{calls}"
# 逐条状态留痕：前两条 failed、第三条 ok（不是只记一句"失败"）
states = [(a["lane"], a["state"]) for a in res["attempts"]
          if a["state"] != "skipped_unready"]
assert states[:3] == [("platform", "failed"), ("fullpath", "failed"),
                      ("codebuddy", "ok")], states

# ④ 全断才判 hard：不静默，逐条记录试过哪几条
res2 = L.attempt("架构·开发", {
    "platform": fail("p"), "fullpath": fail("f"), "codebuddy": fail("c"),
    "direct_handle": fail("h"), "lead": fail("l"), "self": fail("s"),
}, repo="org/repo", cnb=True, handle="架构·开发")
assert res2["ok"] is False and res2["tried"] == ["platform", "fullpath",
                                                 "codebuddy", "direct_handle",
                                                 "lead", "self"], res2
print("  ✅ 多通路穷举：一条断了换下一条，逐条留痕；全断才 hard（带证据上交）")
print(f"      通路清单：{all_lanes}")
EOF

echo "===== [manager] 14. 权责内自决：职责范围内不再申请授权 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr14.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

m = ManagerEngine(dry_run=True)
# ① 权责内的调度动作 → SELF（自己干，不申请授权）
for act in ("调配小组长", "换角色承接", "跨岗借人", "再唤醒一次", "拆分任务",
            "加派开发", "选通路", "自己先顶上兜底"):
    d = m.authorize(act)
    assert d["decision"] == "SELF", f"权责内必须自决：{act} → {d}"
# ② 不可逆/超成本/越界 → HUMAN（那才该找人）
for act in ("合并 PR", "关闭 Issue", "改需求边界", "花钱买额度"):
    d = m.authorize(act)
    assert d["decision"] == "HUMAN", f"{act} 必须交人：{d}"
    assert d["reason"], "交人必须说明理由"
# ③ 实测可跑的通路不需要批准（不存在"申请授权才能派人"）
assert m.authorize("发接力卡")["decision"] == "SELF"
print("  ✅ 权责内自决 SELF / 不可逆·超成本·越界 HUMAN；'要不要授权'由代码判")
EOF

echo "===== [manager] 15. 启下：派不动就调人，手段逐轮升级（不是原地重复） ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr15.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.flow import staffing_options, ESCALATION_LADDER

# ① 未达标 → 必须给出人员手段（不是"再等等"）
opts = staffing_options("awaiting", rounds=1)
assert opts and opts[0][0] == "requeue", opts
# ② 逐轮升级：第 2 轮换调小组长、第 3 轮加派、第 4 轮跨岗借角色
ladder = [staffing_options("awaiting", rounds=n)[0][0] for n in range(1, 5)]
assert ladder == ["requeue", "delegate_lead", "add_devs", "borrow_role"], ladder
# ③ 跨岗借角色在册（用户点名：跨部门找角色过来帮忙都行）
codes = [c for c, _ in ESCALATION_LADDER]
assert "borrow_role" in codes and "self_take" in codes
# ④ 已达标 → 不动人（不折腾）
assert staffing_options("real", rounds=1) == []
print("  ✅ 启下升级梯：再唤醒 → 调小组长 → 加派 → 跨岗借角色 → 自己兜底")
print(f"      逐轮手段：{ladder}")
EOF

echo "===== [manager] 16. 反馈闭环：多轮调整到收敛或带证据上交，不假收敛 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr16.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

plan = "1. 登录实现（角色:架构·开发）\n2. 登录评审（角色:架构·评审）"

# ① 无人接单 → 跑满多轮（每轮换不同手段），仍无证据 → 显式上交且带"试过什么"
m = ManagerEngine(dry_run=True, simulate={"*": "ignore"})
r = m.carry(plan, max_rounds=4)
assert r["escalated"] is True, "无人接单必须显式上交，不许谎报收敛"
assert len(r["unresolved"]) == 2, r["unresolved"]
acts = [h["staffing"][0]["action"] for h in r["rounds"] if h["staffing"]]
assert len(set(acts)) >= 3, f"每轮必须换手段（不是原地重复）：{acts}"
assert "delegate_lead" in acts and "borrow_role" in acts, acts
esc = [a for a in m.actions if a["kind"] == "escalate"]
assert esc and esc[-1]["payload"]["tried"], "上交必须带'试过什么'，不是空手说做不了"
assert esc[-1]["payload"]["unresolved"], "上交必须带未解决明细"

# ② 对端真接单 → 收敛，不误报上交
m2 = ManagerEngine(dry_run=True, simulate={"*": "accept"})
r2 = m2.carry(plan, max_rounds=4)
assert r2["escalated"] is False, f"已接单不该上交：{r2['note']}"
# ③ 四段自检：承上/行下/启下/反馈全打到，缺一段即不及格
chk = m.self_check()
for seg in ("承上", "行下", "启下", "反馈"):
    assert chk[seg] is True, f"承上启下缺段：{seg} → {chk}"
print("  ✅ 多轮反馈：换手段直到收敛；不收敛则带证据上交；不假收敛")
print(f"      无人接单轮次手段={acts} / 已接单 escalated={r2['escalated']}")
EOF

echo "===== [manager] 17. 小组长接单不是终点：带证据上交 + 跨岗借角色 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr17.db")
from data import admin, schema; admin.init(); schema.init_schema()
from roles.team_lead import TeamLeadRole

lead = TeamLeadRole()
# ① 卡点超出本组能力 → 带「试过什么 + 缺什么」交回经理（不是一句"无人承接"）
esc = lead.lead_escalate({"task_key": "登录模块"},
                         tried=["requeue", "add_devs"], need="缺前端角色")
assert esc["tried"] == ["requeue", "add_devs"] and esc["need"] == "缺前端角色"
assert esc["shift"], "上交必须说明是向上移交（不甩锅）"
# ② 组内没人接得住 → 直接申请跨岗借角色（不自闭等死）
b = lead.lead_borrow("登录模块", role="架构·开发", reason="组内无人可承接")
assert b["borrow_role"] == "架构·开发" and b["handle"] is not None
# ③ 入口在契约里（可被调用，不是纸面承诺）
entry = lead.output_contract()["entry"]
assert "lead_escalate" in entry and "lead_borrow" in entry, entry
print("  ✅ 小组长：带证据上交 + 跨岗借角色；接单不等于使命完成")
EOF

echo "===== [manager] 18. 角色接线：经理承上启下入口全部可调用 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr18.db")
from data import admin, schema; admin.init(); schema.init_schema()
from roles.manager import ManagerRole

mgr = ManagerRole()
entry = mgr.output_contract()["entry"]
for name in ("manager_carry", "manager_lanes", "manager_try_lanes",
             "manager_authorize", "manager_self_check"):
    assert name in entry, f"契约缺入口 {name}"
    assert callable(getattr(mgr, name)), f"入口 {name} 不可调用"
# 真跑一遍：承上启下 + 找通路 + 自决 + 自检
mgr.manager_engine.dry_run = True
r = mgr.manager_carry("1. 文档整理（角色:架构·开发）", max_rounds=1)
assert r["north_star"] and "rounds" in r
assert mgr.manager_lanes()
assert mgr.manager_authorize("调配小组长")["decision"] == "SELF"
assert mgr.manager_self_check()["承上"] is True
# 铁律含承上启下/自决/穷尽才上交（人设不是摆设，契约可核验）
iron = " ".join(mgr.output_contract()["iron_rules"])
for kw in ("承上启下", "权责内自决", "穷尽才上交"):
    assert kw in iron, f"铁律缺 {kw}"
print("  ✅ 经理 5 个承上启下入口可调用；铁律含承上启下/自决/穷尽才上交")
EOF

echo "===== [manager] 19. 权责口径不误伤：换个说法不能把'找通路'翻成'申请授权' ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr19.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.lanes import authorize, HUMAN_AUTHORITY_EXTRA

# ① 找通路的近义说法必须判 SELF（用户原话就长这样，不能因措辞换字就翻 HUMAN）
for act in ("换方式", "换路线", "换通路", "换办法", "再试一次",
            "重新安排", "调整人员", "换人", "加人", "跨岗借人", "调配小组长"):
    d = authorize(act)["decision"]
    assert d == "SELF", f"「{act}」属权责内，判成了 {d}（挤牙膏式申请授权的病根）"
# ② 真超成本/不可逆/越界仍必须 HUMAN（放宽不能放宽到没边界）
for act, why in (("扩容到 500 并发", "并发"), ("预算上调", "预算"),
                 ("提升额度", "额度"), ("合并 PR", "不可逆"),
                 ("改架构方向", "越界"), ("删数据", "不可逆")):
    d = authorize(act)
    assert d["decision"] == "HUMAN", f"「{act}」必须 HUMAN，判成了 {d['decision']}"
# ③ 超成本口径单列（不与 SELF 表混写，避免"扩容"两字被误伤/漏判）
assert "扩容" in HUMAN_AUTHORITY_EXTRA and "并发" in HUMAN_AUTHORITY_EXTRA
print("  ✅ 权责口径：11 类换说法仍自决 / 6 类红线仍交人；超成本口径单列不混写")
EOF

echo "===== [manager] 20. 唤醒失败不是终点：自动换下一条通路，逐条判就绪 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr20.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.engine import ManagerEngine

# 唤醒发不出去（发送层失败）时，经理不能原地停，必须往下一跳
e = ManagerEngine(repo="", dry_run=True)
fb = e._fallback_lane({"task_key": "t1", "role": "架构·开发"})
lanes = [c["lane"] for c in fb["candidates"]]
assert lanes == ["fullpath", "codebuddy", "direct_handle"], lanes
# 每条通路的就绪由代码判（不是"我觉得应该能"），失败的记 missing
assert any(c["missing"] for c in fb["candidates"]), "未就绪通路必须记 missing 原因"
assert fb["next_lane"] in ("codebuddy", "direct_handle"), fb["next_lane"]
# 通路留痕进 action（可回溯"试过哪几条"）
kinds = [a["kind"] for a in e.actions]
assert "lane_fallback" in kinds, kinds

# push 里唤醒失败 → 记录下一跳，仍继续交小组长（活不掉地上）
e2 = ManagerEngine(repo="", dry_run=True)
e2._reawake = lambda rec: {"sent": False, "error": "模拟发送失败"}
rec = {"task_key": "登录", "task_id": "tk-1", "agent_id": "ag-1",
       "role": "架构·开发", "issue": "1", "state": "activated"}
res = e2.push([rec])
assert rec.get("lane_fallback"), "唤醒失败必须留换通路的痕"
assert rec["state"] == "delegated_to_lead", rec["state"]
assert res["awaiting"], "无人接单要显式暴露，不谎报已落地"
print("  ✅ 唤醒失败 → 按序换通路（逐条判就绪）→ 仍无人接则交小组长，不空等不谎报")
EOF

echo "===== [manager] 21. 接线闸门：能力必须在主链路里真跑，不是写在旁边 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr21.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.engine import ManagerEngine

# 病根：上一版 lanes.py 写得很漂亮、单测 13/14 组全绿，
# 但 carry() 主流程从头到尾**一次都没调用过它** —— self_check 自己都报
# 找通路=false / 自决=false。这就是"功能写在旁边、主链路不接"的罢工形态。
m = ManagerEngine(repo="dongdongxiaozu/dongjiagoushi", dry_run=True)
res = m.carry("1. 开发登录模块\n2. 评审登录模块", max_rounds=3)
kinds = [a["kind"] for a in m.actions]

# ① 主链路必须真调通路层与自决层（否则就是孤岛）
assert "try_lanes" in kinds, f"carry() 没调通路穷举，lanes 是孤岛：{kinds}"
assert "lane_attempt" in kinds, f"没有逐条真试留痕：{kinds}"
assert "authorize" in kinds, f"carry() 没走权责判定，authorize 是孤岛：{kinds}"
sc = m.self_check()
assert sc["找通路"] is True, sc
assert sc["自决"] is True, sc

# ② 手段不能只是"动作名"——必须落到真动作（有外部可核验产出）
codes_seen = set()
for h in res["rounds"]:
    for a in h["staffing"]:
        codes_seen.add(a["action"])
        assert "authority" in a, f"{a['action']} 没走权责判定"
        assert a["executed"] is True, f"{a['action']} 只记了名字没真执行：{a}"
assert {"requeue", "delegate_lead", "add_devs"} <= codes_seen, codes_seen

# ③ 每个手段要有真凭据，不能只有 desc 文案
for h in res["rounds"]:
    for a in h["staffing"]:
        if a["action"] == "requeue":
            assert a.get("wake", {}).get("tried"), "再唤醒必须逐条留痕试过哪些通路"
            assert a["wake"].get("lane"), "再唤醒必须落到一条具体通路"
        elif a["action"] == "delegate_lead":
            assert a.get("lead_wake", {}).get("ok"), "调配小组长必须真唤醒他，不是只生成 plan"
        elif a["action"] == "add_devs":
            assert a.get("added"), "加派必须拿到新 agent gid，不是记个名字"
print("  ✅ 主链路真接通路/自决/真动作：手段有 executed + 外部凭据，不是动作名")
print(f"      手段={sorted(codes_seen)} / self_check(找通路,自决)={sc['找通路'],sc['自决']}")
EOF

echo "===== [manager] 22. 真动作可核验：借角色/加派/拆分的产出必须带 gid 或 handle ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr22.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.engine import ManagerEngine

m = ManagerEngine(repo="dongdongxiaozu/dongjiagoushi", dry_run=True)
rec = {"task_key": "开发登录模块", "task_id": "tk-x1", "issue": None,
       "role": "架构·开发"}

# ① 加派：必须产出新的 agent gid（真拆出分支，不是打标签）
added = m.add_devs(rec)
assert added and all(a["agent_id"].startswith("ag-") for a in added), added
assert all(a.get("split_id") for a in added), "加派要走 ops.apply_more_agents 留痕"

# ② 借角色：必须真解析出 handle 并真去召唤（不是写一句"调用 HandleAbility"）
b = m.borrow_role("架构·开发", task_key="开发登录模块")
assert b["handle"].startswith("@") and "架构·开发" in b["handle"], b
assert b["wake"].get("ok") is True, "借角色必须真召唤，不能只解析不召唤"
assert b["wake"].get("tried"), "借角色召唤也要逐条留痕通路"

# ③ 拆分：必须产出子任务 gid
sp = m.split_task(rec)
assert sp["subtasks"] and all(x.get("split_id") for x in sp["subtasks"]), sp

# ④ 唤醒：多通路逐条判就绪，不可用的记 missing（诚实，不假试）
w = m.wake_role("架构·评审", task_key="评审登录模块")
assert w["attempts"], "必须逐条留痕尝试过的通路"
assert any(a["state"] == "skipped_unready" for a in w["attempts"]), \
    "不可用通路必须显式标 skipped_unready，不许假装试过"
print("  ✅ 借角色真解析 handle 真召唤 / 加派真拿 gid / 拆分真出子任务 / 不可用通路诚实留痕")
EOF

echo "===== [manager] 23. 证据闸门：演练回执不能当分工（绿的不能是模拟器） ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr23.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine

# 只开演练（simulate=accept）：链路上确实有 [接单]，但**没有承接方真开工**
m = ManagerEngine(dry_run=True, simulate={"*": "accept"})
r = m.execute_plan("1. 开发登录模块")
v = r["supervise"]["verdicts"][0]
assert v["credential"] == "simulated", f"演练证据必须标 simulated，实际 {v['credential']}"
assert v["verdict"] != "real", "演练回执被判成 real = 绿的其实是模拟器"
assert v["credential_ready"] is False

# 只有真承接方上工，才算"安排成功"
from manager.work import RoleWorkFace, WorkerRegistry
reg = WorkerRegistry().register("架构·开发",
                                RoleWorkFace(role="架构·开发", agent_id="ag-real"))
m2 = ManagerEngine(dry_run=True, workers=reg)
r2 = m2.execute_plan("1. 开发登录模块")
v2 = r2["supervise"]["verdicts"][0]
assert v2["credential"] in ("role", "external"), v2
assert v2["verdict"] == "real", f"真上工应判 real，实际 {v2}"
print("  ✅ 演练=simulated 不算干活 / 真承接方上工=role 才算；判据由代码分级")
print(f"      演练→{v['verdict']}({v['credential']}) / 真上工→{v2['verdict']}({v2['credential']})")
EOF

echo "===== [manager] 24. 交小组长不是换主体：必须真驱动 LeadEngine 开组干活 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr24.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine, LeadEngine

# 过去 delegate_to_lead 只返回一个 leader_plan 字典，小组长引擎从没被调用过
m = ManagerEngine(dry_run=True, simulate={"*": "ignore"})
r = m.execute_plan("1. 开发登录模块")
lp = r["push"]["delegated"][0]["leader_plan"]
drive = lp.get("drive") or {}
assert drive, "调配小组长必须真开组（返回 drive 结果），不能只给安排表"
assert drive.get("status") in ("delivered", "continue", "escalated"), drive
assert drive.get("approved") is not None and drive.get("total"), \
    f"必须产出客观验证结果（approved/total），实际 {drive}"
assert drive.get("rounds", 0) >= 1, "小组必须真跑至少一轮闭环"

# 小组长派开发时 dev_id 必须是组引擎的键（dev0/dev1…），否则 run_round 直接报未知开发
lead = LeadEngine(devs_per_team=2)
plan = lead.dispatch_devs({"task_key": "登录模块", "goal_total": 1.0})
assert [d["dev_id"] for d in plan["devs"]] == ["dev0", "dev1"], plan["devs"]
rd = lead.run_round(plan, dev_outputs=[("dev0", True, "ok"), ("dev1", True, "ok")])
assert rd["approved_devs"] == 2 and rd["total_devs"] == 2, rd
assert lead.aggregate(plan, rd)["status"] == "delivered"
print("  ✅ 交小组长 → 真开组：派开发 → 跑闭环 → 整合/继续/上报（不再是换个人停原地）")
print(f"      drive.status={drive.get('status')} approved={drive.get('approved')}/{drive.get('total')}")
EOF

echo "===== [manager] 25. 通路就绪不冒充：整条链不通时不许全绿 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr25.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import lanes as lane_mod

# 没有 repo / 没有 cnb：平台与接力卡通路必须判未就绪（不许"我觉得应该能"）
rows = {r["lane"]: r for r in lane_mod.lanes_for("架构·开发")}
assert rows["platform"]["ready"] is False
assert rows["fullpath"]["ready"] is False
assert rows["codebuddy"]["ready"] is False, "没有会话载体还判 @CodeBuddy 就绪 = 假装试过"

# direct_handle 必须真解析出完整 @org/repo(角色)，角色名本身不算 handle
assert lane_mod.is_full_handle("架构·开发") is False
assert lane_mod.is_full_handle("@dongdongxiaozu/dongjiagoushi(架构·开发)") is True
print("  ✅ 无 repo/无 cnb 时平台·接力·@CodeBuddy 一律未就绪；handle 只认完整 @org/repo(角色)")
print(f"      {[(r['lane'], r['ready']) for r in rows.values()]}")
EOF

echo "===== [manager] 26. 角色工作面：任何角色都能真上工，产出可核验证据 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr26.db")
from data import admin, schema; admin.init(); schema.init_schema()
from manager.work import RoleWorkFace, credential_of, is_ready

face = RoleWorkFace(role="架构·开发", agent_id="ag-x")
a = face.accept("任务A", task_id="tk-a")
assert a["accepted"] and a["level"] == "role", a
face.start("任务A", task_id="tk-a")
face.progress("任务A", task_id="tk-a", goal_total=2.0, current=1.0, delta=1.0)
c = credential_of("tk-a")
assert c["level"] == "role" and is_ready(c), c
assert c["meters"] >= 1, f"真推进必须写进度尺，实际 {c['meters']}"

face.deliver("任务A", output="已交付", task_id="tk-a", evidence="pull#999")
assert credential_of("tk-a")["level"] == "external"
print("  ✅ 承接方标准工作面（accept/start/progress/deliver）产出 role→external 凭据")
print(f"      level={credential_of('tk-a')['level']} meters={c['meters']}")
EOF

echo "===== [manager] 27. 整条能力链：四段做过或已具备即及格，不因一单没调人就判红 ====="
$PY - <<'EOF'
import os, tempfile
os.environ["DB_PATH"] = tempfile.mktemp(suffix="_mgr27.db")
from data import admin, schema; admin.init(); schema.init_schema()
from roles.manager import ManagerRole

m = ManagerRole(current_org="dongdongxiaozu", current_repo="dongjiagoushi")
m._workers = m.manager_workers()
assert m._workers.roles(), "经理必须能装出承接方注册表（否则派下去没人干）"
assert m._workers.has("架构·开发")

r = m.manager_carry("1. 开发登录模块\n2. 评审登录模块\n3. 测试登录模块")
assert r["escalated"] is False, r["note"]
assert all(v["verdict"] == "real" for v in r["verdicts"]), r["verdicts"]
sc = m.manager_self_check()
for k in ("承上", "行下", "启下", "反馈", "找通路", "自决"):
    assert sc[k] is True, f"{k} 应具备/做到，实际 {sc}"
print("  ✅ 经理带真承接方：三条开工全判 real；六项能力全具备（不是每单都要调人）")
print(f"      {r['note']} / 承接方={m._workers.roles()}")
EOF

echo "===== [manager] ALL PASS ====="
