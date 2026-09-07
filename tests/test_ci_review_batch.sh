#!/usr/bin/env bash
# ci_review_batch（Issue #93 · Bus 接入云端 CI · 评审触发整批）信号灯测试
# ---------------------------------------------------------------
# 校验 scripts/ci-review-batch.py 云端评审整批执行器 + .cnb.yml 评审节点接线。
# 需要 python3（CI docker 为 python:3.11）。无 python3 时 SKIP。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "== [SKIP] test_ci_review_batch：本环境无 python3，留待 CI/本地（python3）执行 =="
  exit 0
fi

echo "== ci_review_batch 云端 CI 评审整批测试信号灯（Issue #93） =="

# 1. 脚本存在且可执行
if [ -x scripts/ci-review-batch.py ]; then ok "scripts/ci-review-batch.py 存在且可执行"; else bad "scripts/ci-review-batch.py 缺失/不可执行"; fi

# 2. --help 正常
HELP="$(python3 scripts/ci-review-batch.py --help 2>&1)"
if echo "$HELP" | grep -q -- "--base" && echo "$HELP" | grep -q -- "--dry"; then ok "--help 输出帮助与参数(--base + --dry)"; else bad "--help 输出异常: $HELP"; fi

# 3. --dry 演练：无变更时命中核心冒烟兜底并产出整批等效汇总（非空批次）
DRY_OUT="$(python3 scripts/ci-review-batch.py --base origin/main --head HEAD --dry 2>&1)"
if echo "$DRY_OUT" | grep -qE "core|test_architect_system|total=[0-9]+ +pass=[0-9]+ +fail=0"; then
  ok "--dry 演练产出整批汇总（变更未命中 → 冒烟兜底一批）"
else
  bad "--dry 演练汇总异常: $DRY_OUT"
fi

# 4. 整批里只要有一个真实失败的测试脚本 → ci-bus-batch 会以非 0 退出（评审门禁红）
#    验证失败路径透传：ci-review-batch 把整批交给 ci-bus-batch 并透传其退出码，故用
#    "不存在的测试脚本"直测 ci-bus-batch 失败透传（评审门禁红）。不能对 ci-review-batch.py
#    做非 --dry 真跑——其变更感知会把自己命中并递归选中 test_ci_review_batch.sh 自身，
#    造成整批无限递归 / CI 超时红（v1.1 缺陷）。
RC_FAIL=$(python3 scripts/ci-bus-batch.py tests/__ci_review_nonexistent__.sh >/dev/null 2>&1; echo $?)
if [ "$RC_FAIL" -ne 0 ]; then ok "整批含失败测试 → ci-bus-batch 非 0 退出（评审门禁红透传）"; else bad "失败测试应令 ci-bus-batch 非 0 退出，实际为 $RC_FAIL"; fi

# 5. .cnb.yml 已接线评审整批（pull_request.approved · review gate batch test）
CNB_REF=$(grep -c "ci-review-batch.py" .cnb.yml)
if [ "$CNB_REF" -ge 1 ]; then ok ".cnb.yml 已接线 ci-review-batch.py 评审整批执行"; else bad ".cnb.yml 未找到 ci-review-batch.py 接线"; fi

# 6. .cnb.yml 结构仍合法（YAML 语法校验由 CI 承担，此处做最简引用完整性检查）
if grep -q "pull_request.approved:" .cnb.yml; then ok ".cnb.yml 含 pull_request.approved 评审事件节点"; else bad ".cnb.yml 缺 pull_request.approved 节点"; fi

echo ""
echo "== 结果: $PASS 通过 / $FAIL 失败 =="
exit $((FAIL > 0 ? 1 : 0))
