#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 经理-小组长确定性「真干活」引擎
# ============================================================
# module:   manager（ManagerEngine / LeadEngine · Issue #239）
# feature:  经理真派发（建 Issue + L1→L4）/ 反假装 / 督促转小组长 /
#           监督停滞·横跳交哨兵 / 小组长带队客观验证整合 / 激活断链 YAML 解析回归
# 五要素:
#   Given   一组计划项（含角色标注）进入 ManagerEngine，对端行为可模拟（accept/ignore）
#   When    真实实例化 ManagerEngine + LeadEngine 走 execute_plan / drive 全流程
#   Then    ① 计划即命令：单路→EXECUTE，空→BLOCKED，无"纠结"出口；
#           ② ACTIVATE 闸门：逐条拿到 task gid + 承接角色 + Issue 载体，空计划显式拒绝；
#           ③ 反假装：只回执不干活→fake→转小组长；真开工→real 不误伤；
#           ④ 督促：无人接单→再唤醒→仍无→调配小组长（含首动作+验收口径）；
#           ⑤ 监督：停滞/横跳由进度尺判定→哨兵打断（sentinel interrupted）；
#           ⑥ 小组长：真派开发 + 客观验证（ok=False 不放行）+ 整合交付；
#           ⑦ 激活断链回归：cnb CLI 带引号编号 YAML 输出必须解析出 Issue 编号（不永建不出）。
#   Evidence ManagerEngine.execute_plan / LeadEngine.drive / _parse_issue_number
#           （可程序化断言的语义产物）
# 为什么是"功能级"：纯 grep/读码看不到"引擎真的不假装、真打断、YAML 真解析"——
#   必须真实跑引擎看行为。跑不过 = 经理/小组长仍是"嘴接手"，功能没做完。
#
# 环境守卫：依赖 python3 + local-agent 数据层；无 python 优雅跳过（视为通过）。
# 用法：bash scripts/feature-verify.sh --feature "manager/确定性真干活引擎"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] manager/确定性真干活引擎 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import os, tempfile, sys
sys.path.insert(0, "local-agent")
# ⚠️ 顺序敏感：DB_PATH 必须在**首次 import data.db 之前**设置。
#    db.py 的 DB_PATH 是**模块级常量**（导入时读一次环境变量即固化），导入后再改
#    os.environ 不会生效，会静默落到仓库里的 local-agent/data/runtime.db。
#    后果不是报错，而是「假绿/假红」二连：上一轮测试写在同一条任务 gid 上的历史事件
#    被本轮继承（progress 表里已有 work_started），于是本应判 fake 的判成 real。
if not os.environ.get("DB_PATH"):
    os.environ["DB_PATH"] = tempfile.mktemp(suffix="_fv_mgr.db")
from data import admin, schema
from manager import ManagerEngine, LeadEngine
from manager.engine import resolve_choice, parse_plan

FAIL = 0
def ok(m): print("  ✅ " + m)
def bad(m):
    global FAIL
    FAIL += 1
    print("  ❌ " + m)

# ⑦ 激活断链回归：cnb CLI 带引号编号 YAML 必须解析出整数 Issue 编号
# （病根：cnb issue list 输出 YAML 把编号写成 '123' 字符串，旧解析直接 when int 报错 → 永远建不出 Issue）
from dispatch_engine import _parse_issue_number
_yaml_double = "  number: '1234'\n  title: 登录模块\n"
_yaml_plain  = "number: 1234\n"
assert _parse_issue_number(_yaml_double) == 1234, "带引号编号未解析出整数"
assert _parse_issue_number(_yaml_plain) == 1234, "纯整数编号未解析"
assert _parse_issue_number("not a number") is None
ok("激活断链回归：cnb CLI 带引号编号 YAML 解析出 Issue 编号")

# ① 计划即命令：单路→EXECUTE；空→BLOCKED；无"纠结"出口
r1 = resolve_choice(["按计划开发登录模块"])
assert r1["decision"] == "EXECUTE", r1
r2 = resolve_choice([])
assert r2["decision"] == "BLOCKED", r2
for d in (r1["decision"], r2["decision"]):
    assert d in ("EXECUTE", "BLOCKED")
ok("计划即命令：单路=EXECUTE / 空=BLOCKED / 无纠结出口")

# ② ACTIVATE 闸门：逐条激活 + 空计划显式拒绝
# 断言用库路径已隔离（不是仓库里的共享 runtime.db），否则本样例的判据会被历史数据污染
_db_path = os.path.realpath(schema.db.DB_PATH)
_shared = os.path.realpath(os.path.join("local-agent", "data", "runtime.db"))
assert _db_path != _shared, (
    "证据库未隔离：实际用 %s —— DB_PATH 必须在 import data.db 之前设置" % _db_path)
admin.init(); schema.init_schema()
m = ManagerEngine(dry_run=True)
empty = m.activate("")
assert empty["refused"] is True and empty["count"] == 0
r = m.execute_plan("1. 开发登录模块\n2. 评审登录模块")
assert r["refused"] is False and r["count"] == 2
assert all(a["task_id"] and a["agent_id"] for a in r["activated"])
assert [a["role"] for a in r["activated"]] == ["架构·开发", "架构·评审"]
ok("ACTIVATE 闸门：逐条激活(承接角色) / 空计划显式拒绝")

# ③ 反假装 + ⑤ 监督停滞/横跳
import dispatch_engine
mm = ManagerEngine(dry_run=True, simulate={"*": "accept"})
rr = mm.execute_plan("1. 开发登录模块")
a = rr["activated"][0]
sup = rr["supervise"]
assert sup["summary"]["fake"] == 1 and sup["verdicts"][0]["disposition"] == "hand_to_lead", sup["summary"]
leader_plan = sup["verdicts"][0].get("leader_plan")
assert leader_plan, "假装的活必须转小组长"
# 真开工 → real
admin.record_event(a["agent_id"], "work_started", {"note": "真开工"}, a["task_id"])
sup2 = mm.supervise()
assert sup2["summary"]["real"] == 1 and sup2["summary"]["ok"] is True, sup2["summary"]
ok("反假装：只接单不干→fake→转小组长 / 真开工→real 不误伤")

# ⑤ 监督停滞/横跳 → 哨兵打断
mm2 = ManagerEngine(dry_run=True, simulate={"*": "accept"})
rr2 = mm2.execute_plan("1. 开发报表模块")
b = rr2["activated"][0]
admin.record_event(b["agent_id"], "work_started", {"note": "开工"}, b["task_id"])
for _ in range(2):
    dispatch_engine.track_progress(b["task_key"], b["agent_id"],
                                   target=3, goal_total=3, current=1, note="原地不动")
ss = mm2.supervise()
assert ss["summary"]["stall"] == 1, ss["summary"]
assert ss["verdicts"][0]["disposition"] == "interrupt"
assert ss["verdicts"][0].get("sentinel") == "interrupted"
ok("监督停滞：进度尺判停滞→哨兵打断(interrupted)")

# ④ 督促：无人接单→转小组长
# ⚠️ 用**全新任务 key**：「接单回执」是 progress 表里按任务 gid 的事实，
#    ③ 那一轮已经给「开发登录模块」写过 accepted，同名沿用会让本轮直接判已接单
#    （这正是本文件开头修过的「历史数据污染判据」的另一面）。
mm3 = ManagerEngine(dry_run=True, simulate={"架构·开发": "ignore"})
rr3 = mm3.execute_plan("1. 开发结算模块\n2. 评审结算模块")
p = rr3["push"]
assert len(p["awaiting"]) == 2 and len(p["delegated"]) == 2, p
assert p["delegated"][0]["leader_plan"]["lead_role"] == "架构·小组长"
assert p["delegated"][0]["leader_plan"]["first_action"]
assert p["verified_all_awake"] is False
ok("督促：无人接单→再唤醒→仍无→调配小组长(含首动作)")

# ⑥ 小组长：真派开发 + 客观验证(fake=false 不放行) + 整合交付
lead = LeadEngine(devs_per_team=2)
plan = lead.dispatch_devs({"task_key": "登录模块", "goal_total": 2})
rd = lead.run_round(plan, dev_outputs=[("dev0", True, "pytest 通过"), ("dev1", False, "lint 失败")])
assert rd["verdict"] != "DONE", "有未通过客观验证者绝不放行整合"
agg = lead.aggregate(plan, rd)
assert agg["status"] in ("continue", "escalated"), agg
# 全通过才交付
plan2 = lead.dispatch_devs({"task_key": "登录模块2", "goal_total": 2})
rd2 = lead.run_round(plan2, dev_outputs=[("dev0", True, "pytest 通过"), ("dev1", True, "lint 通过")])
agg2 = lead.aggregate(plan2, rd2)
assert agg2["status"] == "delivered", agg2
ok("小组长：客观验证不放行 / 全通过才整合交付")

print("")
if FAIL > 0:
    print("🔴 manager/确定性真干活引擎 未达成 → 功能没做完")
    sys.exit(1)
else:
    print("🟢 manager/确定性真干活引擎 通过（计划即命令 / 真派发 / 反假装 / 督促 / 监督打断 / 小组长闭环 / YAML 解析回归）")
    sys.exit(0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 manager/确定性真干活引擎 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 manager/确定性真干活引擎 通过"
  exit 0
fi
