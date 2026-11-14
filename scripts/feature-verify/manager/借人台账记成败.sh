#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 借人台账记成败
# ============================================================
# module:   manager（经理真干活 · Issue #239 收尾轮）
# feature:  跨岗借人"按需 + 记结果 + 失败换人"：借谁由任务语义派生；
#           每次借人（成败）都进 borrow_ledger；借败过的人下轮自动跳过、换下一个。
# 五要素:
#   Given    一条"需要评审"的任务，本岗（架构·开发）接不住
#   When     经理走启下手段借人（多轮）
#   Then     ① 借的对象按任务语义派生（评审任务先借评审），不写死；
#            ② 每轮借人结果都落台账（role/lane/handle/ok/reason 齐）；
#            ③ 借败的人不再出现在下轮候选里，实际借的是没败过的人；
#            ④ 候选全借光 → 显式提示"该换手段"，不原地循环。
#   Evidence borrow_ledger 表行 + borrow_overview() 的 stuck 清单
#   为什么是"功能级": 单测只证明"调用了 borrow_role"。写死不记结果也照样能绿；
#     本脚本判的是"结果有没有被记住、记住之后有没有改变下一轮的选择"。
# 用法：bash scripts/feature-verify/manager/借人台账记成败.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/借人台账记成败 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_ledger.db) python3 - <<'EOF' 2>&1
import sys
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()
from manager import ManagerEngine, borrow as borrow_mod

# —— 有通路的场景：借到人要落台账 ——
m = ManagerEngine(repo="dongdongxiaozu/dongjiagoushi", dry_run=True)
b = m.borrow_role("", task_key="fv-ok", task="需要评审复评", exclude=["架构·开发"])
rows = borrow_mod.history(task_key="fv-ok")
print("OK_PICK", b["role"], b["ok"])
print("OK_ROW", rows[0]["role"], rows[0]["lane"], bool(rows[0]["handle"]), rows[0]["ok"])

# —— 无通路的场景：借不到要记失败，且下轮换人 ——
m2 = ManagerEngine(repo="", dry_run=True)
r1 = m2.borrow_role("", task_key="fv-fail", task="需要评审复评", attempts=2)
round1 = [t["role"] for t in r1["tried"]]
failed = list(r1["failed_roles"])
r2 = m2.borrow_role("", task_key="fv-fail", task="需要评审复评", attempts=2)
round2 = [t["role"] for t in r2["tried"]]
repeat = sorted(set(round1) & set(round2))
print("FAIL_R1", ",".join(round1))
print("FAIL_R2", ",".join(round2))
print("REPEAT", ",".join(repeat))
print("FAIL_ROLES", ",".join(failed))
print("OVERVIEW_STUCK", len(m2.borrow_overview("fv-fail")["stuck"]))
m2.borrow_role("", task_key="fv-fail", task="需要评审复评", attempts=99)
allgone = m2.borrow_role("", task_key="fv-fail", task="需要评审复评")
print("EXHAUSTED", "换手段" in (allgone.get("next") or ""))
EOF
)
echo "$OUT" | sed 's/^/      /'

if echo "$OUT" | grep -qE "^OK_PICK 架构·评审 True"; then
  ok "按需借人：评审任务借到评审（不是写死开发）"
else
  bad "借的对象没按任务语义派生"
fi
if echo "$OUT" | grep -qE "^OK_ROW 架构·评审 [a-z_]+ True 1"; then
  ok "借到人落台账：role/lane/handle/ok 齐全可回溯"
else
  bad "借人结果没落台账"
fi
if echo "$OUT" | grep -qE "^FAIL_ROLES [^,]+" && ! echo "$OUT" | grep -qE "^FAIL_ROLES $"; then
  ok "借不到也记：失败进台账，能被 failed_roles 查出来"
else
  bad "借失败没留痕（下轮还会重复找同一个人）"
fi
if echo "$OUT" | grep -qE "^REPEAT $"; then
  ok "失败换人：下轮试的不含上一轮借败过的人"
else
  bad "下轮又借了失败过的人（重复找不到人用）"
fi
if echo "$OUT" | grep -qE "^EXHAUSTED True"; then
  ok "候选全败 → 显式提示该换手段，不原地循环"
else
  bad "候选借光后没给出'该换手段'的结论"
fi

echo ""
if [ "$FAIL" -gt 0 ]; then
  echo "🔴 manager/借人台账记成败 未达成 → 功能没做完"
  exit 1
else
  echo "🟢 manager/借人台账记成败 通过"
  exit 0
fi
