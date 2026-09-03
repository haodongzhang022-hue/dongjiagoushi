#!/usr/bin/env bash
# ci_bus_batch（Issue #93 · Bus 接入云端 CI）信号灯测试
# ---------------------------------------------------------------
# 校验 scripts/ci-bus-batch.py 云端整批执行器 + .cnb.yml 整批接线。
# 需要 python3（CI docker 为 python:3.11；本地亦需）。无 python3 时 SKIP。
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "== [SKIP] test_ci_bus_batch：本环境无 python3，留待 CI/本地（python3）执行 =="
  exit 0
fi

echo "== ci_bus_batch 云端 CI 整批测试执行信号灯（Issue #93） =="

# 1. 脚本存在且可执行
if [ -x scripts/ci-bus-batch.py ]; then ok "scripts/ci-bus-batch.py 存在且可执行"; else bad "scripts/ci-bus-batch.py 缺失/不可执行"; fi

# 2. --help 正常
HELP="$(python3 scripts/ci-bus-batch.py --help 2>&1)"
if echo "$HELP" | grep -q "--parallel" && echo "$HELP" | grep -q "tests"; then ok "--help 输出帮助与参数(--parallel + tests)"; else bad "--help 输出异常: $HELP"; fi

# 3. --dry 演练：传一批测试，应产出整批等效汇总（整批一次跑完语义）
DRY_OUT="$(python3 scripts/ci-bus-batch.py --dry tests/test_architect_system.sh tests/test_doc_consistency.sh 2>&1)"
echo "$DRY_OUT" | grep -qE "total=[0-9]+ +pass=[0-9]+ +fail=0" && ok "--dry 演练产出整批汇总(total=N pass=N fail=0)" || bad "--dry 演练汇总异常: $DRY_OUT"

# 4. 空批次 → 退出码非 0（明确报错，不吞异常 / C01）
RC_EMPTY=$(python3 scripts/ci-bus-batch.py 2>&1 >/dev/null; echo $?)
if [ "$RC_EMPTY" != "0" ]; then ok "空批次/缺参数 → 非 0 退出（报错不吞）"; else bad "空批次应报错退出，实际为 0"; fi

# 5. .cnb.yml 已接线整批计划执行（pull_request · change aware test 不再逐脚本独立跑）
CNB_REF=$(grep -c "ci-bus-batch.py" .cnb.yml)
if [ "$CNB_REF" -ge 1 ]; then ok ".cnb.yml 已接线 ci-bus-batch.py 整批执行"; else bad ".cnb.yml 未找到 ci-bus-batch.py 接线"; fi

# 6. 文档存在（AC3）
if [ -f docs/HYBRID_CI_BUS.md ]; then ok "docs/HYBRID_CI_BUS.md 存在（AC3 文档）"; else bad "docs/HYBRID_CI_BUS.md 缺失"; fi

# 7. 失败路径：真实跑一个不存在的测试脚本 → fail → 退出码非 0（不静默放行）
RC_FAIL=$(python3 scripts/ci-bus-batch.py tests/__no_such_test_xxx__.sh --timeout 30 >/dev/null 2>&1; echo $?)
if [ "$RC_FAIL" != "0" ]; then ok "失败测试 → 退出码非 0（不静默放行）"; else bad "失败测试应退出非 0，实际为 0"; fi

echo ""
echo "== 结果: $PASS 通过 / $FAIL 失败 =="
exit $((FAIL > 0 ? 1 : 0))
