#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 小组长「脑子」测试（Issue #232 · 经理智力不足要小组长当脑子 + 看着他别犯傻）
# 验证：
#   1. 脑子能力可加载（lead_brain 独立模块 + 角色挂载 + 全员可用）
#   2. 诊断：经理方案的窟窿被逐条点名（目标/负责人/干什么/输入/输出/验收/深度/编号）
#   3. 补全：缺口给修正动作（补字段/拆细/加派/升总师），ready 判定正确
#   4. 监察：跳深度/重复派发/超次返工/空转/抢单/无主派发 → pass|block|blocked_escalate
#   5. 端到端：编排里经理派活前真的过了脑子（report.lead_brain 留痕）
#   6. 云端人设：.cnb/settings.yml 里「架构·小组长」存在且带脑子职责
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_lead_brain.db"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ✅ $1"; }
bad() { fail=$((fail+1)); echo "  ❌ $1"; }

echo "== [lead_brain] 1. 能力可加载 + 角色挂载 + 全员可用 =="
$PY - <<'PY' && ok "能力加载与挂载" || bad "能力加载与挂载"
import sys; sys.path.insert(0,'.')
from lead_brain import LeadBrainAbility
from roles import get_role
b = LeadBrainAbility(owner="架构·小组长")
assert b.capability()["name"] == "LeadBrainAbility"
lead = get_role("架构·小组长")
assert lead.lead_brain_ability is not None
assert "lead_brain_ability" in lead.capability()
# 经理自己也挂得上（脑子不是小组长私有，派活前先过一遍）
mgr = get_role("架构·经理")
assert mgr.lead_brain_ability is not None
assert mgr.enhance_plan({"goal":"x","tasks":[{"id":"t1","owner":"架构·开发","task":"写接口",
    "input":"文档","output":"PR","done_when":"测试绿","depth":4}]})["ready"] is True
print("  ✅ lead_brain 可加载；小组长/经理均挂载")
PY

echo "== [lead_brain] 2. 诊断：窟窿逐条点名 =="
$PY - <<'PY' && ok "诊断缺口" || bad "诊断缺口"
import sys; sys.path.insert(0,'.')
from lead_brain import LeadBrainAbility
b = LeadBrainAbility()
bad_plan = {"goal":"", "tasks":[{"id":"t1","owner":"","task":"开发","input":"","output":"","done_when":"","depth":2}]}
d = b.diagnose(bad_plan)
fields = {g["field"] for g in d["gaps"]}
for f in ("goal","owner","task","input","output","done_when","depth"):
    assert f in fields, (f, fields)
assert d["ready"] is False and d["score"] == 0
# 空词任务单独判据
assert any("空词" in g["issue"] for g in d["gaps"])
# 干净方案应 ready
good = {"goal":"登录模块可登录", "tasks":[{"id":"t1","owner":"架构·开发","task":"实现登录接口",
        "input":"接口文档","output":"PR","done_when":"测试通过","depth":4}]}
assert b.diagnose(good)["ready"] is True
# 编号重复要被抓出来（gid 撞车）
dup = {"goal":"g","tasks":[dict(good["tasks"][0]), dict(good["tasks"][0])]}
assert any(g["field"]=="id" for g in b.diagnose(dup)["gaps"])
print("  ✅ 7 类缺口 + 空词 + 编号重复均被点名")
PY

echo "== [lead_brain] 3. 补全：修正动作 + ready 判定 =="
$PY - <<'PY' && ok "补全建议" || bad "补全建议"
import sys; sys.path.insert(0,'.')
from lead_brain import LeadBrainAbility
b = LeadBrainAbility()
adv = b.advise({"goal":"", "tasks":[{"id":"t1","owner":"","task":"开发","depth":2}]})
actions = {f["action"] for f in adv["fixes"]}
assert "补字段" in actions and "修正方案" in actions
assert adv["ready"] is False                    # 有占位缺口 → 不可直接派
# 大任务未声明分组 → 加派建议
big = b.advise({"goal":"g","tasks":[{"id":f"t{i}","owner":"架构·开发","task":f"实现模块{i}",
        "input":"i","output":"o","done_when":"测试","depth":4} for i in range(6)]})
assert any(f["action"]=="加派" for f in big["fixes"])
e = b.enhance({"goal":"g","tasks":[{"id":"t1","owner":"架构·开发","task":"实现接口",
        "input":"i","output":"o","done_when":"测试通过","depth":4}]})
assert e["ready"] is True and e["plan"]["brain"]["version"].startswith("lead_brain")
print("  ✅ 补字段/修正方案/加派建议 + ready 判定正确")
PY

echo "== [lead_brain] 4. 监察：经理犯傻被拦住 =="
$PY - <<'PY' && ok "看住经理" || bad "看住经理"
import sys; sys.path.insert(0,'.')
from lead_brain import LeadBrainAbility
b = LeadBrainAbility()
assert b.watch({"entity":"t1","depth":4})["verdict"] == "pass"
assert b.watch({"entity":"t1","depth":2})["verdict"] == "block"          # 跳深度
assert b.watch({"entity":"t1","depth":4,"count":3})["verdict"] == "block"  # 重复派发
assert b.watch({"entity":"t1","depth":4,"rework":4})["verdict"] == "block" # 超次返工
assert b.watch({"entity":"t1","depth":4,"progress_delta":0,"stall_rounds":3})["verdict"] == "block"  # 空转
assert b.watch({"entity":"t1","depth":4,"conflict":True})["verdict"] == "block"  # 抢单
assert b.watch({"entity":"t1","depth":4,"no_owner":True})["verdict"] == "block"  # 无主派发
# 二度命中 → 上报总师
w = b.watch({"entity":"t1","depth":2,"repeat_hit":True})
assert w["verdict"] == "blocked_escalate" and w["level"] == 2
# 拦截必须给替代动作（不只是说"不行"）
assert all(w["alternatives"] for w in [b.watch({"entity":"t1","depth":2})])
agg = b.watch_manager_orders([{"entity":"a","depth":2},{"entity":"b","depth":4}])
assert agg["blocked_count"] == 1
print("  ✅ 6 类犯傻全拦 + 二度上报 + 替代动作")
PY

echo "== [lead_brain] 5. 端到端：编排里经理派活前真过了脑子 =="
$PY - <<'PY' && ok "编排接线" || bad "编排接线"
import sys; sys.path.insert(0,'.')
from orchestrator import _lead_brain_enhance
import relay
card = relay.new_card("实现登录模块：账号密码登录、短信登录、密码找回、风控、审计、多端同步", "secretary", "架构·秘书")
node = {"id":"plan","role":"架构·经理","action":"任务拆解/角色分配/排期","depends_on":["architect"]}
plan, info = _lead_brain_enhance(node, "实现登录模块：账号密码登录、短信登录、密码找回、风控、审计、多端同步", card)
assert info is not None and info["role"].startswith("架构·小组长")
assert info["gaps"] > 0 and info["fixes"], info
assert plan is not None and plan["tasks"]
assert info["ready_after_fix"] is False   # 占位缺口未确认 → 不许直接往下派
assert info["watch"]["blocked"] > 0
print("  ✅ report.lead_brain 留痕：缺口=%d 修正=%d" % (info["gaps"], len(info["fixes"])))
PY

echo "== [lead_brain] 6. 云端人设：settings.yml 有「架构·小组长」+ 脑子职责 =="
$PY - <<'PY' && ok "云端人设" || bad "云端人设"
import yaml
d = yaml.safe_load(open("../.cnb/settings.yml", encoding="utf-8"))
roles = {r["name"]: r for r in d["npc"]["roles"]}
assert "架构·小组长" in roles, list(roles)
p = roles["架构·小组长"]["prompt"]
for kw in ("脑子", "别犯傻", "缺口", "跳深度", "重复派发", "L4"):
    assert kw in p, kw
print("  ✅ 架构·小组长人设含脑子/监察职责")
PY

echo
echo "---- lead_brain: pass=$pass fail=$fail ----"
[ "$fail" -eq 0 ] || exit 1
