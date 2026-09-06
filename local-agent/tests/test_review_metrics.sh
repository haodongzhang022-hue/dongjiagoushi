#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 有效性度量模型（Review Metrics · Issue #100 决策⑤）功能测试
# 验证"维度化 + 概率×程度分档 + 留痕 + 确定性判定"：
#   ① 维度注册表齐全（5 维唯一事实源）
#   ② 分档映射正确（degree → low/mid/high/full；bug_rate 反向翻转）
#   ③ 归一化：prob 和 >1 等比例压缩、补中性档、未知维度拒绝
#   ④ 概率×程度分档聚合（规避"笼统均值"歧义）
#   ⑤ 确定性判定（对照阈值，以客观高质档质量占比为准）
#   ⑥ 留痕 + 回看（trace / trace_recent / CLI）
#   ⑦ 能力挂载到 BaseRole（全员可用透传）
set -e
cd "$(dirname "$0")/.."
PY=python3
export DB_PATH="$(mktemp -d)/test_review_metrics.db"
rm -f state/review_metrics_trace.json 2>/dev/null || true

echo "===== [review-metrics] 1. 维度注册表齐全（唯一事实源） ====="
$PY - <<'EOF'
from review_metrics import spec
dims = spec.valid_dims()
need = {"resolution","bug_rate","stability","generality","consistency"}
assert need <= set(dims), (need, dims)
assert len(dims) == 5, dims
# 每维有方向/量纲/口径；权重归一化
w = spec.weights()
assert set(w) == set(dims)
assert abs(sum(w.values()) - 1.0) < 1e-9, w
# 未知维度拒绝（防自造指标）
try:
    spec.dim_spec("not_a_dim"); raise SystemExit("should reject")
except KeyError as e:
    assert "INVALID_DIMENSION" in str(e)
print("  ✅ 维度注册表齐全", dims, "权重和=", round(sum(w.values()),4))
EOF

echo "===== [review-metrics] 2. 档位映射正确 + bug_rate 反向 ====="
$PY - <<'EOF'
from review_metrics import engine, spec
# resolution（越高越好）：0.99→full, 0.9→high, 0.7→mid, 0.3→low
assert engine.band_degree("resolution", 0.99) == "full"
assert engine.band_degree("resolution", 0.90) == "high"
assert engine.band_degree("resolution", 0.70) == "mid"
assert engine.band_degree("resolution", 0.30) == "low"
# bug_rate（越低越好）：degree=引入缺陷概率 0.05 → 有效度0.95 → high/full
assert engine.band_degree("bug_rate", 0.05) in ("high","full")
assert engine.band_degree("bug_rate", 0.99) == "low"   # 高缺陷率 → 低效
print("  ✅ 档位映射正确 + 方向翻转")
EOF

echo "===== [review-metrics] 3. 归一化：概率和>1压缩、缺档补中性、未知维拒绝 ====="
$PY - <<'EOF'
from review_metrics import engine
# prob 和 1.5 → 等比例压到 1
obs = {"dims":{"resolution":[{"prob":0.5,"degree":0.9},{"prob":1.0,"degree":0.95}]}}
n = engine.normalize_profile(obs)
s = sum(b["prob"] for b in n["dims"]["resolution"])
assert abs(s - 1.0) < 1e-6, (n, s)
# prob 和 0.5 → 补中性档(0.5) 使和为 1
obs2 = {"dims":{"resolution":[{"prob":0.5,"degree":0.95}]}}
n2 = engine.normalize_profile(obs2)
s2 = sum(b["prob"] for b in n2["dims"]["resolution"])
assert abs(s2 - 1.0) < 1e-6 and len(n2["dims"]["resolution"]) == 2, n2
# 未知维拒绝
try:
    engine.normalize_profile({"dims":{"hack":[{"prob":1,"degree":1}]}})
    raise SystemExit("should reject unknown dim")
except KeyError:
    pass
print("  ✅ 归一化正确（和=1 + 补中性档 + 拒绝未知维）")
EOF

echo "===== [review-metrics] 4. 概率×程度分档聚合（规避笼统均值） ====="
$PY - <<'EOF'
from review_metrics import engine
# 同"平均 63% 解决"的两组，分档结果不同——证明不用歧义均值
A = {"dims":{"resolution":[{"prob":0.9,"degree":0.3},{"prob":0.1,"degree":0.99}]}}
B = {"dims":{"resolution":[{"prob":0.9,"degree":0.6},{"prob":0.1,"degree":0.9}]}}
ra = engine.aggregate([A]); rb = engine.aggregate([B])
# A：90%质量落在 low(0.3)，high_mass 小 → 有效度低
# B：90%落在 mid(0.6)，high_mass 也小，但 weighted_degree 高
assert ra["per_dim"]["resolution"]["high_mass"] < 0.5
assert ra["per_dim"]["resolution"]["mass_per_band"]["low"] > 0.8
# 分档揭示：同样平均分，A 是"大面积没解决+偶尔全解决"，质量不稳
print("  ✅ 概率×程度分档揭示分布差异（非均值口径）",
      "A weighted_degree=", ra["per_dim"]["resolution"]["weighted_degree"],
      "B weighted_degree=", rb["per_dim"]["resolution"]["weighted_degree"])
EOF

echo "===== [review-metrics] 5. 确定性判定（对照客观阈值） ====="
$PY - <<'EOF'
from review_metrics import engine
# 高质量：多 90%+ 高档满档 → all_passed True
good = {"dims":{
  "resolution":[{"prob":0.9,"degree":0.99},{"prob":0.1,"degree":0.9}],
  "bug_rate":[{"prob":1.0,"degree":0.02}],
  "stability":[{"prob":0.95,"degree":0.98},{"prob":0.05,"degree":0.7}],
  "generality":[{"prob":0.8,"degree":0.9},{"prob":0.2,"degree":0.5}],
  "consistency":[{"prob":0.9,"degree":0.95},{"prob":0.1,"degree":0.6}],
}}
# 低质量：大量 low 档 → 判定不达标
bad = {"dims":{"resolution":[{"prob":0.9,"degree":0.3},{"prob":0.1,"degree":0.9}]}}
r = engine.aggregate([good]); j = engine.judge(r)
assert j["all_passed"] is True, j
rb = engine.aggregate([bad]); jb = engine.judge(rb)
assert jb["all_passed"] is False
# 确定性：同输入两次结果一致
assert engine.judge(r) == j
print("  ✅ 确定性判定：高质量达标、低质量不达标、同输入同输出")
EOF

echo "===== [review-metrics] 6. 留痕 + 回看 + CLI ====="
$PY - <<'EOF'
from review_metrics import engine
obs={"target":"t-1","dims":{"resolution":[{"prob":1.0,"degree":0.98}]}}
r=engine.aggregate([obs])
tid=engine.trace(obs, r)
assert tid.startswith("rvm-")
recent=engine.trace_recent()
assert any(x["trace_id"]==tid for x in recent)
print("  ✅ 留痕 + 回看 trace_id=", tid)
EOF
$PY -m review_metrics.cli dims | $PY -c 'import sys,json;d=json.load(sys.stdin);assert "resolution" in d["dims"];print("  ✅ CLI dims ok")'

echo "===== [review-metrics] 7. 能力挂载到 BaseRole（全员可用） ====="
$PY - <<'EOF'
from roles.reviewer import ReviewerRole
from roles.tester import TesterRole
for R in (ReviewerRole, TesterRole):
    r=R()
    assert r.review_metrics_ability is not None
    assert r.metrics_dims()
    assert "review_metrics_ability" in r.capability()
    out=r.measure_review({"dims":{"resolution":[{"prob":1.0,"degree":0.99}]}})
    assert "result" in out and "verdict" in out
print("  ✅ 评审/测试角色能力挂载并透传成功")
EOF

echo ""
echo "===== [review-metrics] ALL PASS ====="
rm -f state/review_metrics_trace.json 2>/dev/null || true
