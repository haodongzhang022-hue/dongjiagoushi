#!/usr/bin/env bash
# ============================================================
# 标签管理 + 进度自动化能力（LabelAbility · Issue #51）可复现测试
# 仓库：dongjiagoushi
#
# 覆盖用户诉求（Issue #51）：
#   T-L1 建表           —— labels / label_requests 表存在
#   T-L2 规范标签集     —— LABEL_SPECS 5分类20+标签，非规范拦截
#   T-L3 一线直接打标    —— 白名单角色 apply_label 直接打标
#   T-L4 越权拦截       —— 非白名单角色直接打标被拒（须提议）
#   T-L5 全员提议+审批   —— propose_label → 管理员 review approved 自动落标
#   T-L6 事件驱动自动打标 —— AutoLabelEngine 8 类规则（issue.open/progress.advance/pr.merged/review.need_fix/sentinel.alert）
#   T-L7 进度百分比折算  —— progress_pct 人可读百分比（40%/60%/100%）
#   T-L8 MCP 管线 CLI   —— python -m label.cli progress/status/auto 程序化查询
#   T-L9 进度推手角色    —— ProgressPusherRole 专项角色可跑（push_progress/push_priority/check_auto）
#   T-L10 BaseRole 全员挂载 —— 任意角色实例 query/apply/auto_trigger 可用
#   T-L11 程序化进度查询 —— query_progress 合并 goal_meters+progress 不靠对话
# ============================================================

set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PASS=0; FAIL=0
declare -a FAILED_ITEMS=()
assert_contains() { local n="$1" h="$2" nd="$3"; if [[ "$h" == *"$nd"* ]]; then PASS=$((PASS+1)); echo "  ✅ $n"; else FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$n] 缺: $nd"); echo "  ❌ $n (实际: $h)"; fi; }
assert_eq() { local n="$1" a="$2" e="$3"; if [[ "$a" == "$e" ]]; then PASS=$((PASS+1)); echo "  ✅ $n"; else FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$n] 期望=$e 实际=$a"); echo "  ❌ $n (期望=$e 实际=$a)"; fi; }
assert_pass() { local n="$1" o="$2"; if [[ "$o" == *"'ok': True"* || "$o" == *'"ok": true'* ]]; then PASS=$((PASS+1)); echo "  ✅ $n"; else FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$n] ok!=true: $o"); echo "  ❌ $n ($o)"; fi; }
assert_fail() { local n="$1" o="$2"; if [[ "$o" == *"'ok': False"* || "$o" == *'"ok": false'* ]]; then PASS=$((PASS+1)); echo "  ✅ $n"; else FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$n] 应失败: $o"); echo "  ❌ $n ($o)"; fi; }

echo "======================================================"
echo "标签管理 + 进度自动化（LabelAbility · Issue #51）测试"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# 隔离数据库：用临时 DB 避免污染主库
export DB_PATH="$REPO_ROOT/.tmp-label-test.db"
rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"
export PYTHONPATH="$REPO_ROOT/local-agent:$REPO_ROOT/local-agent/roles"

PY() { python3 -c "$1"; }

# T-L1 建表
TABLES=$(PY "import sys;sys.path.insert(0,'$REPO_ROOT/local-agent');from data import db,schema;t=schema.init_schema();print('labels' in t and 'label_requests' in t)")
assert_eq "T-L1 labels/label_requests 表存在" "$TABLES" "True"

# T-L2 规范标签集
SPECS=$(PY "from label import LabelAbility; print(len(LabelAbility.VALID_LABELS)>=20, 'in_progress' in LabelAbility.VALID_LABELS, 'p0_critical' in LabelAbility.VALID_LABELS)")
assert_eq "T-L2 规范标签集 20+ / 含 in_progress / p0_critical" "$SPECS" "True True True"

# T-L3 一线直接打标
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.apply_label('issue-51','in_progress'))")
assert_pass "T-L3 开发直接打标 in_progress" "$OUT"
OUT=$(PY "from roles.manager import ManagerRole; r=ManagerRole(); print(r.apply_label('issue-51','p1_high'))")
assert_pass "T-L3 经理直接打标 p1_high" "$OUT"

# T-L4 越权拦截
OUT=$(PY "from roles.market import SalesRole; r=SalesRole(); print(r.apply_label('issue-51','done'))")
assert_fail "T-L4 销售越权直接打标被拒" "$OUT"
OUT=$(PY "from roles.market import SalesRole; r=SalesRole(); print(r.apply_label('issue-51','not_a_real_label'))")
assert_fail "T-L4 非规范标签拦截" "$OUT"

# T-L5 全员提议 + 管理员审批
OUT=$(PY "from roles.market import SalesRole; r=SalesRole(); print(r.propose_label('issue-51','p0_critical','阻塞上线'))")
assert_pass "T-L5 销售提议 p0_critical" "$OUT"
REQ=$(PY "from label import LabelAbility; print(LabelAbility(owner='x').pending_requests()[0]['request_id'])")
OUT=$(PY "from roles.data_admin import DataAdminRole; r=DataAdminRole(); print(r.review_label_request('$REQ','approved'))")
assert_contains "T-L5 管理员审批通过自动落标" "$OUT" "approved"

# T-L6 事件驱动自动打标
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.auto_trigger('issue.open','issue-70'))")
assert_contains "T-L6 issue.open→open" "$OUT" "open"
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.auto_trigger('progress.advance','issue-70',10,6))")
assert_contains "T-L6 progress.advance→in_progress" "$OUT" "in_progress"
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.auto_trigger('pr.merged','issue-70'))")
assert_contains "T-L6 pr.merged→merged+done" "$OUT" "merged"
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.auto_trigger('review.need_fix','issue-70'))")
assert_contains "T-L6 review.need_fix→need_fix+blocked" "$OUT" "blocked"
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.auto_trigger('sentinel.alert','issue-70'))")
assert_contains "T-L6 sentinel.alert→stale" "$OUT" "stale"

# T-L7 进度百分比折算（人可读层）
OUT=$(PY "from label.auto import AutoLabelEngine; print(AutoLabelEngine.pct_from(10,4), AutoLabelEngine.pct_from(5,5), AutoLabelEngine.pct_estimate('in_progress'))")
assert_eq "T-L7 折算 40% / 100% / 估算40" "$OUT" "40 100 40"
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.auto_trigger('progress.advance','issue-80',20,12))")
assert_contains "T-L7 进度60%自动刷" "$OUT" "progress_pct:60%"

# T-L8 MCP 管线 CLI
OUT=$(cd local-agent && python3 -m label.cli auto --event progress.advance --entity issue-90 --goal-total 10 --current 3)
assert_contains "T-L8 CLI auto 自动打标" "$OUT" "progress_pct:30%"
OUT=$(cd local-agent && python3 -m label.cli status --entity issue-90)
assert_contains "T-L8 CLI status 程序化查状态" "$OUT" "in_progress"
OUT=$(cd local-agent && python3 -m label.cli apply --entity issue-91 --label done --operator 架构·评审)
assert_contains "T-L8 CLI apply 一线打标" "$OUT" "done"
OUT=$(cd local-agent && python3 -m label.cli propose --entity issue-92 --label p2_normal --operator 市场·销售 --reason 补充)
assert_contains "T-L8 CLI propose 全员提议" "$OUT" "pending"
OUT=$(cd local-agent && python3 -m label.cli apply --entity issue-93 --label done --operator 市场·销售)
assert_contains "T-L8 CLI 越权拦截" "$OUT" "NO_PERMISSION"

# T-L9 进度推手角色
OUT=$(PY "from label.progress_pusher import ProgressPusherRole; r=ProgressPusherRole(); print(r.push_progress('issue-100',goal_total=10,current=6))")
assert_contains "T-L9 进度推手 push_progress" "$OUT" "progress_pct:60%"
OUT=$(PY "from label.progress_pusher import ProgressPusherRole; r=ProgressPusherRole(); print(r.push_priority('issue-100','p1_high'))")
assert_contains "T-L9 进度推手 push_priority" "$OUT" "p1_high"
OUT=$(PY "from label.progress_pusher import ProgressPusherRole; r=ProgressPusherRole(); print(r.check_auto('issue-100'))")
assert_contains "T-L9 进度推手 check_auto 自动化触发" "$OUT" "actions"

# T-L10 BaseRole 全员挂载
OUT=$(PY "from roles.product import ProductRole; r=ProductRole(); print(r.label_ability is not None, callable(getattr(r,'query_progress',None)))")
assert_eq "T-L10 BaseRole 全员挂载 label_ability" "$OUT" "True True"

# T-L11 程序化进度查询（MCP，合并 goal_meters）
PY "import sys;sys.path.insert(0,'$REPO_ROOT/local-agent');from data import db,schema;from data import repository as repo;schema.init_schema();repo.apply_label('issue-120','in_progress','架构·开发')" >/dev/null 2>&1
OUT=$(PY "from roles.developer import DeveloperRole; r=DeveloperRole(); print(r.query_status('issue-120')['status'])")
assert_eq "T-L11 query_status 程序化" "$OUT" "in_progress"

# T-L12 AGENTS.md 固定规则 + 文档存在性
AGENTS=$(grep -c "架构·进度推手\|标签管理机制\|LabelAbility\|AutoLabelEngine" AGENTS.md)
[ "$AGENTS" -ge 1 ] && { PASS=$((PASS+1)); echo "  ✅ T-L12 AGENTS.md 标签机制固定规则"; } || { FAIL=$((FAIL+1)); FAILED_ITEMS+=("[T-L12] AGENTS.md 缺标签机制"); echo "  ❌ T-L12 AGENTS.md 缺标签机制"; }
DOC=$(ls docs/LABEL_AUTOMATION.md 2>/dev/null || echo MISSING)
assert_contains "T-L12 文档 LABEL_AUTOMATION.md" "$DOC" "LABEL_AUTOMATION"

rm -f "$DB_PATH" "$DB_PATH-wal" "$DB_PATH-shm"

echo "======================================================"
echo "通过: $PASS  失败: $FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf "失败项:\n"
  for i in "${FAILED_ITEMS[@]}"; do echo "  - $i"; done
  exit 1
fi
echo "✅ 标签自动化测试全部通过"
