#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 开发小组闭环引擎测试（信号灯 · Issue #74 深化结构）
# 验证「把一套开发小组当一个整体」的确定性编排：
#   一套循环 N 个开发（默认2）· 执行-验证分离 · 确定性状态机 · 硬性熔断
#   · 进度北极星监督 · 记录优先对话统一交付 · 二级信息俯瞰
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_dev_team.db"

echo "===== [dev_team] 1. 目标门控：goal>0 才允许进小组闭环 ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
# 目标未量化(goal<=0) → 拒绝
team = DevTeamEngine(goal_total=0.0)
ok, reason = team.can_enter_loop()
assert ok is False and "目标未量化" in reason, reason
# 目标明确(goal>0) → 允许
team2 = DevTeamEngine(goal_total=10.0)
ok, reason = team2.can_enter_loop()
assert ok is True, reason
print("  ✅ 目标门控：goal<=0 拒绝 / goal>0 允许")
EOF

echo "===== [dev_team] 2. 一套循环 N 个开发（默认2） ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
team = DevTeamEngine(goal_total=10.0, devs_per_team=2)
assert team.devs_per_team == 2, team.devs_per_team
assert len(team.devs) == 2, list(team.devs)
assert sorted(team.devs) == ["dev0", "dev1"]
# devs_per_team 可配置（如 3/4）
team3 = DevTeamEngine(goal_total=10.0, devs_per_team=3)
assert team3.devs_per_team == 3 and len(team3.devs) == 3
# devs_per_team 下限保护
team1 = DevTeamEngine(goal_total=10.0, devs_per_team=0)
assert team1.devs_per_team == 1, team1.devs_per_team
print("  ✅ 一套循环 N 个开发：默认2 / 可配3 / 下限保护1")
EOF

echo "===== [dev_team] 3. 确定性状态机：未全APPROVED→REWORK，全APPROVED→整合 ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
team = DevTeamEngine(goal_total=10.0, devs_per_team=2)
r = team.start_round()
assert r["stage"] == "executing"
# 只有 dev0 通过 → REWORK
team.developer_output("dev0", "t", True, evidence="PASS")
d = team.decide()
assert d["verdict"] == "REWORK" and d["approved_devs"] == 1, d
# 未知 dev 应报错
try:
    team.developer_output("dev9", "t", True)
    raise AssertionError("未知 dev 应报错")
except Exception:
    pass
# dev1 也通过但目标未满 → INTEGRATE
team.developer_output("dev1", "t", True, evidence="PASS")
d2 = team.decide()
assert d2["verdict"] == "INTEGRATE" and d2["approved_devs"] == 2, d2
print("  ✅ 确定性状态机：未全通过→REWORK / 全通过→INTEGRATE / 未知dev拒绝")
EOF

echo "===== [dev_team] 4. 硬性熔断：重做超max_attempts→上报Leader ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
team = DevTeamEngine(goal_total=10.0, devs_per_team=1, max_attempts=2)
team.start_round()
last = None
for i in range(3):   # 超过 max_attempts=2
    last = team.developer_output("dev0", "t", False, evidence="FAIL")
assert last["escalated"] is True, last
assert last["attempts"] == 3, last
d = team.decide()
assert d["verdict"] == "ESCALATED", d
assert "上报 Leader" in d["reason"], d["reason"]
# 总迭代超 max_iterations → ESCALATED
team2 = DevTeamEngine(goal_total=10.0, devs_per_team=2, max_iterations=1)
team2.start_round()
team2.start_round()
assert team2.decide()["verdict"] == "ESCALATED"
print("  ✅ 硬性熔断：单dev超max_attempts→上报Leader / 总迭代超限→熔断")
EOF

echo "===== [dev_team] 5. 进度北极星监督（goal_meters） ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
from data import admin, schema
schema.init_schema()
admin.init()
team = DevTeamEngine(goal_total=10.0, devs_per_team=2)
team.advance(5.0)
m = team._record_meter(note="进度检查")
assert m["current"] == 5.0 and m["goal_total"] == 10.0
assert "analysis" in m  # 哨兵收敛检测返回
team.advance(5.0)
assert team._remaining() <= team.eps
print("  ✅ 进度北极星：advance 推进 / goal_meters 落库 / remaining 收敛")
EOF

echo "===== [dev_team] 6. 记录优先于对话：干完统一交付给经理 ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
from data import admin, schema
schema.init_schema(); admin.init()
team = DevTeamEngine(goal_total=10.0, devs_per_team=2)
team.advance(10.0)
team.developer_output("dev0", "登录模块", True, evidence="PASS")
team.developer_output("dev1", "登录模块", True, evidence="PASS")
rec = team.deliver_to_manager(task_id="登录模块", summary="完成登录小组交付")
assert rec["remaining"] == 0.0
assert rec["approved_devs"] == 2 and rec["total_devs"] == 2
assert rec["devs_per_team"] == 2
print("  ✅ 统一交付：进度回放 + 存档 + 经理零打扰")
EOF

echo "===== [dev_team] 7. 二级信息俯瞰（小组长/经理/人类监控） ====="
$PY - <<'EOF'
from dev_team import DevTeamEngine
team = DevTeamEngine(goal_total=10.0, devs_per_team=2, team_id="team-x")
team.advance(5.0)
team.developer_output("dev0", "t", True)
ov = team.overview()
assert ov["progress_pct"] == 50.0, ov
assert ov["team_id"] == "team-x"
assert "devs" in ov and len(ov["devs"]) == 2
assert ov["approved"] == 1 and ov["total_devs"] == 2
print("  ✅ 二级信息：progress_pct / approved / devs 状态 / remaining")
EOF

echo "===== [dev_team] 8. 通用能力挂载 + 透传 ====="
$PY - <<'EOF'
from roles.developer import DeveloperRole
dev = DeveloperRole()
assert dev.dev_team_ability is not None, "DevTeamAbility 未挂载"
cap = dev.capability()
assert "dev_team_ability" in cap, list(cap.keys())
methods = cap["dev_team_ability"]["methods"]
assert "create_team" in methods and "run_team_round" in methods
# 透传方法可用
team = dev.create_dev_team(goal_total=10.0, devs_per_team=2)
assert team.devs_per_team == 2
decision = dev.run_dev_team_round(team, [("dev0", True, "PASS"), ("dev1", True, "PASS")], task_id="t")
assert decision["verdict"] in ("INTEGRATE", "REWORK", "DONE"), decision
ov = dev.dev_team_overview(team)
assert "devs_per_team" in ov
print("  ✅ DevTeamAbility 全员挂载 + create_team/run_dev_team_round/dev_team_overview 透传")
EOF

echo
echo "===== [dev_team] 全部信号灯通过 ✅ ====="
