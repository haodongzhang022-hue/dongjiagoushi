#!/usr/bin/env bash
# ============================================================
# [feature-verify] manager / 经理节点真接线
# ============================================================
# module:   manager（经理真干活 · Issue #239 五轮）
# feature:  流水线（orchestrator）里的经理节点必须用**角色自己的引擎**跑**承上启下**，
#           而不是现造一个没 repo、没承接方、只有 execute_plan 的壳。
# 五要素:
#   Given    流水线跑到 架构·经理 节点
#   When     _run_role_engine 处理该节点
#   Then     ① 引擎带 repo（不再恒 dry_run、恒不建 Issue）；
#            ② 引擎带承接方注册表（启下"调人/借人/加派"不是空动作）；
#            ③ 走 carry（承上裁不可执行 + 多轮反馈），不是只 execute_plan；
#            ④ 输出不含"平台激活"这类把本地登记说成平台激活的旧措辞。
#   Evidence 节点输出文本 + engine.workers.roles() + res.upstream.dropped
#   为什么是"功能级": 单测直接调引擎，绕开了流水线这条路；于是"引擎及格、流水线里
#     的经理不及格"能长期共存。本脚本判的是"真实调用链上那个经理是不是同一个"。
# 用法：bash scripts/feature-verify/manager/经理节点真接线.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }
echo "==== [feature-verify] manager/经理节点真接线 ===="

OUT=$(DB_PATH=$(mktemp --suffix=_fv_wire.db) python3 - <<'EOF' 2>&1
import os, sys
sys.path.insert(0, "local-agent")
from data import admin, schema; admin.init(); schema.init_schema()
import orchestrator
from roles import get_role

role = get_role("架构·经理")
# 混一条没有承接线索的空话，用来验证"承上"真的在跑（裁掉 + 给替代路线）
plan = "1. 开发登录模块" + chr(10) + "2. 评审登录模块" + chr(10) + "3. 这件事你们看着办"
out = orchestrator._run_role_engine(role, plan, {"id": "plan", "role": "架构·经理"})
eng = role.manager_engine
print("WIRED", eng.repo != "", eng.workers is not None,
      len(eng.workers.roles()) if eng.workers else 0)
print("OUT_IS_CARRY", "承上启下" in out)
print("NO_FAKE_WORD", "平台激活" not in out)
print("DROPPED", "裁掉 1 条" in out)
EOF
)
echo "$OUT" | sed 's/^/      /'

echo "$OUT" | grep -qE "^WIRED True True ([1-9][0-9]*)$" \
  && ok "流水线里的经理带 repo + 带承接方（真能派、真能调人）" \
  || bad "流水线里的经理没 repo 或没承接方（启下全是空动作）"
echo "$OUT" | grep -q "^OUT_IS_CARRY True" \
  && ok "走承上启下入口（carry），不是只有 execute_plan" \
  || bad "仍走 execute_plan，承上/反馈两段没跑"
echo "$OUT" | grep -q "^NO_FAKE_WORD True" \
  && ok "输出不含「平台激活」旧措辞（口径不自证）" \
  || bad "输出仍把本地登记说成平台激活"
echo "$OUT" | grep -q "^DROPPED True" \
  && ok "承上真在跑：不可执行项被裁掉并给替代路线" \
  || bad "承上没跑（空话被原样下发）"

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "  ✅ [manager] 经理节点真接线 通过（功能完成）"; exit 0
fi
echo "  ❌ [feature-verify] manager/经理节点真接线 失败：PASS=$PASS FAIL=$FAIL"; exit 1
