#!/usr/bin/env bash
# ============================================================
# 开发增强配比机制测试（test_dev_enhanced）
# ============================================================
# 验证 Issue #74「开发才是真正推进度的，辅助多则浪费」：
#   1. 分形引擎支持 devs_per_team（每小组开发数，默认 2 = 一套循环 2 个开发）
#   2. dev_ratio() 量化开发密度（辅助过多时直观暴露浪费）
#   3. 小组内结构深化：一套小组 = 小组长 + N 开发，辅助质量闸门在小组外
#   4. dev_enhanced 开发增强拓扑可被 router 显式选用
# ============================================================
cd "$(dirname "$0")/.."
pass=0; fail=0
echo "== 开发增强配比（Dev-Ratio · Issue #74）=="

# 1) fractal 默认每小组 2 个开发（一套循环 2 个开发）
python3 - <<'PY' && echo "  ✅ 分形默认 devs_per_team=2（一套循环 2 个开发）"; pass=$((pass+1)) || { echo "  ❌ devs_per_team 校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
import fractal
plan = fractal.build_fractal_plan([f't{i}' for i in range(10)])
assert plan['devs_per_team'] == 2, plan
for t in plan['teams']:
    assert len(t['devs']) == 2, t   # 每个小组 2 个开发实例
print(f"  team_count={plan['team_count']}, devs_per_team={plan['devs_per_team']}")
PY

# 2) dev_ratio 量化开发密度（开发是实干主力，占比应>50%）
python3 - <<'PY' && echo "  ✅ dev_ratio 量化开发密度（开发占比>50%）"; pass=$((pass+1)) || { echo "  ❌ dev_ratio 校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
import fractal
plan = fractal.build_fractal_plan([f't{i}' for i in range(10)])
d = fractal.dev_ratio(plan)
print(f"  devs={d['devs']} leads={d['leads']} ratio={d['ratio']:.0%}")
assert d['ratio'] > 0.5, d   # 开发占比过半，辅助不喧宾夺主
PY

# 3) describe_plan 体现"一套循环 2 个开发"
python3 - <<'PY' && echo "  ✅ describe_plan 体现一套循环 2 个开发"; pass=$((pass+1)) || { echo "  ❌ describe_plan 校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
import fractal
plan = fractal.build_fractal_plan([f't{i}' for i in range(6)])
txt = fractal.describe_plan(plan)
print(txt.splitlines()[0])
assert '2 个开发' in txt or '2个开发' in txt
assert '开发密度' in txt
PY

# 4) dev_enhanced 开发增强拓扑可被 router 显式选用
python3 - <<'PY' && echo "  ✅ dev_enhanced 拓扑可被 router 选用（8节点·2开发）"; pass=$((pass+1)) || { echo "  ❌ dev_enhanced 拓扑校验失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
from topology import router
r = router.route_pipeline('中等复杂度的系统开发', force='dev_enhanced')
assert r['selected'] == 'dev_enhanced', r
devs = [n for n in r['nodes'] if n['role']=='架构·开发']
print(f"  selected={r['selected']}, 节点={len(r['nodes'])}, 开发数={len(devs)}")
assert len(devs) == 2, devs   # 一套循环 2 个开发
assert r['plan'] is not None
PY

# 5) 兼容旧调用（不带 devs_per_team 参数仍正常分形）
python3 - <<'PY' && echo "  ✅ 兼容旧调用（build_fractal_plan 无 devs_per_team 参数）"; pass=$((pass+1)) || { echo "  ❌ 兼容旧调用失败"; fail=$((fail+1)); }
import sys; sys.path.insert(0,'.')
import fractal
plan = fractal.build_fractal_plan([f't{i}' for i in range(10)])
assert plan['scaled'] and plan['team_count'] >= 2
print(f"  team_count={plan['team_count']}（默认参数仍分形）")
PY

echo ""
echo "结果：$pass 通过 / $fail 失败"
[ "$fail" = "0" ] || exit 1
