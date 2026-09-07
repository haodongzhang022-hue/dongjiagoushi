#!/usr/bin/env bash
# ============================================================
# [feature-verify] dev-team / 确定性状态机（dev 只做不判，全 APPROVED 才整合）
# ============================================================
# module:   dev-team（开发小组确定性状态机 · DevTeamEngine，Issue #118 / #109）
# feature:  dev 只做不判 / 客观验证器裁定 / 未通过不交付 / 超限熔断上报 Leader
# 五要素:
#   Given   一组开发（dev0..devN-1）产出已按"执行→客观验证"上报给 DevTeamEngine
#   When    真实实例化 DevTeamEngine，按调用顺序 developer_output() 上报验证结果，
#           再 decide() 由确定性状态机裁决是否放行整合
#   Then    1) dev 被客观验证器 REJECTED → decide 不放行（verdict=REWORK，reason 提示
#              "尚未全部产出通过客观验证"）—— dev 谎报完成若被放行即判红；
#           2) 仅部分 dev APPROVED（1/2）→ 仍不放行；全部 dev APPROVED → 才放行整合
#              （verdict ∈ {INTEGRATE, DONE}，非 REWORK）；
#           3) 单 dev 连续 REJECTED 超 max_attempts → 上报 Leader 熔断（verdict=ESCALATED，
#              reason 含"上报 Leader"），不无限重试；
#           4) 相同输入两次 decide() 结果完全一致（确定性，非 LLM 说了算）。
#   Evidence decide() 返回的 verdict / reason / approved_devs / total_devs /
#           developer_output() 返回的 escalated / attempts（可程序化断言）
# 为什么是"功能级"：纯 grep/读码看不到"引擎真的不放行、真熔断、真确定"——必须真实跑
#   DevTeamEngine 看 dev 谎报完成/未全通过/超限时 decide 是否诚实判 REWORK/ESCALATED、
#   不假装放行整合。跑不过 = "dev 只做不判、客观验证器裁定"功能没做完（合并闸门拦截）。
#
# 环境守卫：本样例依赖 python3 + local-agent（dev_team 引擎），无 python 优雅跳过
#   （视为通过），CI python 环境全量跑。对齐 dispatch/真实唤醒校验闸门 样例模式。
# 用法：bash scripts/feature-verify.sh --feature "dev-team/确定性状态机"
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "==== [feature-verify] dev-team/确定性状态机 ===="
if ! command -v python3 >/dev/null 2>&1; then
  echo "  ⏭️  python3 缺失，本 python 依赖样例优雅跳过（CI python 环境全量跑）"
  exit 0
fi
export PYTHONPATH="local-agent${PYTHONPATH:+:$PYTHONPATH}"
python3 - <<'PYEOF'
import sys
sys.path.insert(0, "local-agent")
from dev_team import DevTeamEngine

PASS = FAIL = 0
def ok(m):
    global PASS
    PASS += 1
    print("  ✅ " + m)
def bad(m):
    global FAIL
    FAIL += 1
    print("  ❌ " + m)

# ============================================================
# 用例 1 —— dev 只做不判：被客观验证器 REJECTED 的 dev 不放行整合
#   dev 谎报完成（主观自称 ok），但客观验证器判 REJECTED(ok=False) →
#   decide 必须 REWORK，绝不放行。
# ============================================================
team1 = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_attempts=3)
res = team1.developer_output("dev0", "t1", ok=False, evidence="测试红灯")
d = team1.decide()
if res["approved"] is False and res["escalated"] is False and res["attempts"] == 1:
    ok("用例1-a: 客观验证器 REJECTED 被如实记录（approved=False, attempts=1）")
else:
    bad("用例1-a: REJECTED 结果未如实记录 → " + str(res))
if d["verdict"] == "REWORK" and "尚未全部产出通过客观验证" in d["reason"]:
    ok("用例1-b: dev 被 REJECTED → decide 不放行（verdict=REWORK，提示尚未全通过客观验证）")
else:
    bad("用例1-b: dev 被 REJECTED 却放行整合（verdict=%s）→ 'dev 只做不判'语义失效" % d["verdict"])

# ============================================================
# 用例 2 —— 全 APPROVED 才整合：仅部分通过不放行，全部通过才放行
# ============================================================
team2 = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_attempts=3)
team2.developer_output("dev0", "t2", ok=True)   # dev0 通过
team2.developer_output("dev1", "t2", ok=False)  # dev1 被 REJECTED
d_part = team2.decide()
if d_part["verdict"] == "REWORK" and d_part["approved_devs"] == 1 and d_part["total_devs"] == 2:
    ok("用例2-a: 1/2 通过 → 不放行（REWORK，approved=1/2）")
else:
    bad("用例2-a: 仅部分 APPROVED 却放行（verdict=%s, %s/%s）→ 未全通过不得交付失效"
        % (d_part["verdict"], d_part["approved_devs"], d_part["total_devs"]))
team2.developer_output("dev1", "t2", ok=True)   # dev1 补做通过（客观验证 APPROVED）
d_all = team2.decide()
if d_all["verdict"] in ("INTEGRATE", "DONE") and d_all["approved_devs"] == 2 and d_all["total_devs"] == 2:
    ok("用例2-b: 2/2 全 APPROVED → 放行整合（verdict=%s, approved=2/2）" % d_all["verdict"])
else:
    bad("用例2-b: 全 APPROVED 却未放行整合（verdict=%s）→ 小组长整合时机失效" % d_all["verdict"])

# ============================================================
# 用例 3 —— 硬性熔断：单 dev 连续 REJECTED 超 max_attempts → 上报 Leader 不无限重试
#   max_attempts 设小（1）即可触发，避免默认 20 次空转。
# ============================================================
team3 = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_attempts=1)
r_first = team3.developer_output("dev0", "t3", ok=False)      # 第 1 次 REJECTED（=max_attempts）
r_second = team3.developer_output("dev0", "t3", ok=False)     # 第 2 次 REJECTED → 超限
d_esc = team3.decide()
if r_first["escalated"] is False and r_first["attempts"] == 1:
    ok("用例3-a: 首轮 REJECTED 未越限（attempts=1，未上报）")
else:
    bad("用例3-a: 首轮即误熔断 → " + str(r_first))
if r_second["escalated"] is True and r_second["attempts"] == 2 \
        and "上报 Leader" in r_second["reason"]:
    ok("用例3-b: 超 max_attempts → developer_output 上报 Leader（escalated=True，reason 含'上报 Leader'）")
else:
    bad("用例3-b: 超限未上报 Leader → " + str(r_second))
if d_esc["verdict"] == "ESCALATED" and "上报 Leader" in d_esc["reason"]:
    ok("用例3-c: 熔断后 decide 判定 ESCALATED（reason 含'上报 Leader'）→ 不再无限重试")
else:
    bad("用例3-c: 超限未 ESCALATED（verdict=%s）→ 无限重试熔断失效" % d_esc["verdict"])

# ============================================================
# 用例 4 —— 确定性：相同输入两次 decide() 结果完全一致（机器判定，非 LLM 说了算）
# ============================================================
team4 = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_attempts=2)
team4.developer_output("dev0", "t4", ok=False)
dec_a = team4.decide()
dec_b = team4.decide()
if dec_a == dec_b:
    ok("用例4: 相同状态两次 decide() 返回完全一致（verdict=%s）→ 确定性状态机成立"
       % dec_a["verdict"])
else:
    bad("用例4: 相同输入两次 decide() 结果漂移 → 非确定性")
    FAIL += 1

# ============================================================
# 负向自证 —— 真实引擎被改坏（误放行未全通过的 dev）时本样例必须判红
#   判据【挂在真实引擎上】而非自造子类自比：
#     护栏只信引擎真实内部 devs 状态（approved==total 与否），
#     只要 decide() 返回 DONE/INTEGRATE（放行/交付类）而实际未全部
#     APPROVED，即判违规。真实引擎坏成"谎报 DONE"时本护栏必须抓红。
# ============================================================
def _delivery_guard(engine, verdict):
    """护栏判据（确定性、挂在任意引擎实例的真实状态上）：
    返回 (violation, real_approved, real_total)。
    violation = True 当且仅当 verdict 是放行/交付类(DONE/INTEGRATE)
    而引擎内部真实 approved < total —— 即"未全通过却被放行整合"（谎报）。
    ESCALATED/REWORK 不是交付放行，不触发本护栏（ESCALATED 是超限熔断上报）。"""
    real_approved = sum(1 for dv in engine.devs.values() if dv["approved"])
    real_total = len(engine.devs)
    if verdict in ("DONE", "INTEGRATE"):
        violation = real_approved < real_total
    else:
        violation = False   # REWORK / ESCALATED 非交付放行，不判违规
    return violation, real_approved, real_total

# —— ① 正向护栏：真实引擎正确时，dev 被 REJECTED → decide 是 REWORK，不触发违规
g_team = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_attempts=3)
g_team.developer_output("dev0", "t6", ok=False)          # 0/2 客观验证 REJECTED
g_v = g_team.decide()
g_viol, g_ap, g_tot = _delivery_guard(g_team, g_v["verdict"])
if g_v["verdict"] == "REWORK" and not g_viol and g_ap == 0 and g_tot == 2:
    ok("负向①(真实引擎): REJECTED 未全通过 → decide=REWORK，护栏无违规（真实引擎守住'只做不判'）")
else:
    bad("负向①(真实引擎): 真实引擎未守'只做不判'（verdict=%s, violation=%s）→ 引擎已坏" % (g_v["verdict"], g_viol))
    FAIL += 1

# —— ② 变异验证：把【真实 DevTeamEngine.decide 改坏成谎报 DONE】（这才是该被护栏抓住的
#   回归——真实引擎坏掉），护栏必须抓红；证明护栏不是"自造子类自比"的空转。
_orig_decide = DevTeamEngine.decide
def _fake_done_decide(self, *a, **k):
    # 真实引擎被"修坏"成：无视 dev 被 REJECTED，谎称全通过直接 DONE 放行
    return {
        "verdict": "DONE", "stage": "done", "remaining": 0.0,
        "reason": "全部通过（谎报）", "approved_devs": self.devs_per_team,
        "total_devs": self.devs_per_team,
    }
DevTeamEngine.decide = _fake_done_decide               # 变异：污染真实类
try:
    m_team = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_attempts=3)
    m_team.developer_output("dev0", "t6", ok=False)     # 真实状态 0/2 未通过
    m_d = m_team.decide()                               # 坏 decide 谎报 DONE
    m_viol, m_ap, m_tot = _delivery_guard(m_team, m_d["verdict"])
    if m_d["verdict"] == "DONE" and m_viol and m_ap == 0 and m_tot == 2:
        ok("负向②(变异): 真实 DevTeamEngine.decide 被改坏谎报 DONE、实际 %d/%d 未通过 → 护栏判红"
           % (m_ap, m_tot))
    else:
        bad("负向②(变异): 真实引擎坏成谎报 DONE 而护栏未抓红（verdict=%s, violation=%s）→ 假护栏"
            % (m_d["verdict"], m_viol))
        FAIL += 1
finally:
    DevTeamEngine.decide = _orig_decide                 # 恢复真实 decide，避免污染后续

print("")
if FAIL > 0:
    print("🔴 dev-team/确定性状态机 未达成 → 功能没做完")
    sys.exit(1)
else:
    print("🟢 dev-team/确定性状态机 通过（dev 只做不判 / 全 APPROVED 才整合 / 熔断上报 Leader 语义成立）")
    sys.exit(0)
PYEOF
RC=$?
if [ $RC -ne 0 ]; then
  echo "  🔴 dev-team/确定性状态机 未达成 → 功能没做完"
  exit 1
else
  echo "  🟢 dev-team/确定性状态机 通过（dev 只做不判语义成立）"
  exit 0
fi
