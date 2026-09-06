#!/usr/bin/env bash
# ============================================================
# 变更范围感知测试选择器（Change-Aware Test Selector）
# ============================================================
# 作用：根据本次 git 变更的文件范围，只运行受影响的测试模块，
#       避免全量跑 35 个测试脚本造成 CPU 浪费。
#
# 用法：
#   bash scripts/change-aware-test.sh                 # 自动检测变更（PR/push 均适用）
#   bash scripts/change-aware-test.sh --all           # 强制全量跑
#   bash scripts/change-aware-test.sh --dry-run       # 只打印将运行的测试，不实际执行
#   bash scripts/change-aware-test.sh --dry-run --all # 只打印全量测试清单
#
# 环境变量：
#   CNB_PULL_REQUEST_TARGET_SHA                       # PR 目标分支 SHA（CNB 内置变量）
#   CNB_COMMIT                                        # 本次提交 SHA（CNB 内置变量）
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=false
FORCE_ALL=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --all) FORCE_ALL=true ;;
  esac
done

# ------------------------------------------------------------
# 1. 确定变更文件列表
# ------------------------------------------------------------
CHANGED_FILES=""
if [ "$FORCE_ALL" = "true" ]; then
  CHANGED_FILES="__ALL__"
elif [ -n "${CNB_PULL_REQUEST_TARGET_SHA:-}" ]; then
  # PR 事件：对比目标分支 SHA 与当前 HEAD
  CHANGED_FILES=$(git diff --name-only "$CNB_PULL_REQUEST_TARGET_SHA" "HEAD" 2>/dev/null)
elif [ -n "${CNB_COMMIT:-}" ]; then
  # push 事件：对比上一个 commit
  CHANGED_FILES=$(git diff --name-only "HEAD~1" "HEAD" 2>/dev/null)
else
  # 本地开发：对比 main（或首次提交时的空 diff）
  if git rev-parse --verify main >/dev/null 2>&1; then
    CHANGED_FILES=$(git diff --name-only "main...HEAD" 2>/dev/null)
  elif git rev-parse --verify HEAD~1 >/dev/null 2>&1; then
    CHANGED_FILES=$(git diff --name-only "HEAD~1" "HEAD" 2>/dev/null)
  else
    CHANGED_FILES="__ALL__"
  fi
fi

# 也包含未提交的工作区更改
WORKING_CHANGES=$(git diff --name-only 2>/dev/null || true)
if [ -n "$WORKING_CHANGES" ]; then
  if [ "$CHANGED_FILES" = "__ALL__" ]; then
    CHANGED_FILES="$WORKING_CHANGES"
  else
    CHANGED_FILES="$CHANGED_FILES
$WORKING_CHANGES"
  fi
fi

if [ -z "$CHANGED_FILES" ]; then
  # 没有变更文件 → 默认全量（新分支/首次推送等场景）
  CHANGED_FILES="__ALL__"
fi

echo "==== [change-aware] 变更范围感知测试选择 ===="
if [ "$CHANGED_FILES" = "__ALL__" ]; then
  echo "  模式: 全量（无法确定变更范围或强制 --all）"
else
  echo "  变更文件数: $(echo "$CHANGED_FILES" | grep -c . )"
  echo "  变更文件:"
  echo "$CHANGED_FILES" | sed 's/^/    /'
fi

# ------------------------------------------------------------
# 2. 模块 → 测试脚本 映射表
# ------------------------------------------------------------
# 每个条目: "路径模式|测试脚本1,测试脚本2,..."
declare -a MODULE_MAP=(
  # ---- 核心架构体系（改到根级文件时兜底核心测试）----
  "AGENTS.md|tests/test_architect_system.sh,tests/test_doc_consistency.sh,tests/test_mini_e2e.sh"
  ".cnb.yml|tests/test_architect_system.sh,tests/test_doc_consistency.sh"
  "README.md|tests/test_architect_system.sh,tests/test_doc_consistency.sh"

  # ---- 顶层文档 → 文档一致性 ----
  "docs/|tests/test_doc_consistency.sh,tests/test_architect_system.sh"

  # ---- 源码内存/工具链 ----
  "src/memory/|tests/test_memory_store.sh"
  "src/|tests/test_memory_store.sh,tests/test_architect_system.sh"

  # ---- local-agent 核心运行时 ----
  "local-agent/run.py|local-agent/tests/test_local_agent.sh"
  "local-agent/orchestrator.py|local-agent/tests/test_local_agent.sh,local-agent/tests/test_engine.sh"
  "local-agent/relay.py|local-agent/tests/test_local_agent.sh,tests/test_relay_workflow.sh"
  "local-agent/graph.py|local-agent/tests/test_local_agent.sh,local-agent/tests/test_engine.sh"
  "local-agent/fractal.py|local-agent/tests/test_local_agent.sh,local-agent/tests/test_ops_sim.sh"

  # ---- 规模伸缩层 ----
  "local-agent/scale/|local-agent/tests/test_scale.sh,local-agent/tests/test_prescale_entry.sh"

  # ---- 秘书感知 ----
  "local-agent/roles/secretary|local-agent/tests/test_secretary_sense.sh,local-agent/tests/test_scale.sh"

  # ---- 自适应@定位 ----
  "local-agent/handle/|tests/test_handle_ability.sh"

  # ---- 数据管理层 ----
  "local-agent/data/|local-agent/tests/test_data_layer.sh,local-agent/tests/test_collab.sh"

  # ---- 协作运作 ----
  "local-agent/collab/|local-agent/tests/test_collab.sh,local-agent/tests/test_peer_collab.sh,local-agent/tests/test_peer_closure.sh"

  # ---- 审查处置标签 ----
  "local-agent/collab/disposition|local-agent/tests/test_disposition.sh"

  # ---- 七层深度引擎 ----
  "local-agent/depth/|local-agent/tests/test_depth_engine.sh"

  # ---- 派发能力/分发引擎 ----
  "local-agent/dispatch/|local-agent/tests/test_dispatch_ability.sh,local-agent/tests/test_dispatch_engine.sh"
  "local-agent/dispatch_engine.py|local-agent/tests/test_dispatch_engine.sh"

  # ---- 调度中枢 ----
  "local-agent/dispatcher/|local-agent/tests/test_dispatcher.sh,local-agent/tests/test_probe.sh"

  # ---- 监控哨兵 ----
  "local-agent/sentinel/|local-agent/tests/test_sentinel.sh,local-agent/tests/test_ops_sim.sh"

  # ---- 标签自动化 ----
  "local-agent/label/|local-agent/tests/test_label_automation.sh"

  # ---- 拓扑/融合/路由/前缀缓存 ----
  "local-agent/topology/|local-agent/tests/test_topology_fusion.sh,local-agent/tests/test_topology_slim.sh,local-agent/tests/test_router_integration.sh,local-agent/tests/test_prefix_cache.sh"
  "local-agent/topology/prefix_cache.py|local-agent/tests/test_prefix_cache.sh"
  "local-agent/topology/runner.py|local-agent/tests/test_topology_comparison.sh,local-agent/tests/test_benchmark_ab.sh,local-agent/tests/test_topology_hybrid.sh"

  # ---- 高尔顿板 ----
  "local-agent/galton/|local-agent/tests/test_galton.sh"

  # ---- 上位机引擎/外部事件源 ----
  "local-agent/engine/|local-agent/tests/test_engine.sh,local-agent/tests/test_external_source.sh"

  # ---- 池/并发 ----
  "local-agent/pool/|local-agent/tests/test_scale.sh"

  # ---- 任务转交闭环 ----
  "local-agent/roles/|local-agent/tests/test_review_tester_handoff.sh,local-agent/tests/test_dual_axis_review.sh"

  # ---- 全局 gid/ops ----
  "local-agent/gid.py|local-agent/tests/test_ops_sim.sh"
  "local-agent/ops.py|local-agent/tests/test_ops_sim.sh"

  # ---- 测试脚本自身变更 → 兜底核心测试 ----
  "tests/|tests/test_architect_system.sh,tests/test_doc_consistency.sh,tests/test_mini_e2e.sh"
  "local-agent/tests/|local-agent/tests/test_local_agent.sh,tests/test_architect_system.sh"
)

# ------------------------------------------------------------
# 3. 匹配变更文件 → 选测试
# ------------------------------------------------------------
SELECTED_TESTS=""
declare -A SEEN=()

select_test() {
  local test="$1"
  if [ -z "${SEEN[$test]:-}" ]; then
    SEEN[$test]=1
    if [ -n "$SELECTED_TESTS" ]; then
      SELECTED_TESTS="$SELECTED_TESTS $test"
    else
      SELECTED_TESTS="$test"
    fi
  fi
}

if [ "$CHANGED_FILES" = "__ALL__" ]; then
  echo "  选定: ALL（全量模式）"
  exit 0
fi

for file in $CHANGED_FILES; do
  # 跳过空行和删除的文件（/dev/null）
  [ -z "$file" ] && continue
  for entry in "${MODULE_MAP[@]}"; do
    pattern="${entry%%|*}"
    tests="${entry#*|}"
    if [[ "$file" == *"$pattern"* ]]; then
      IFS=',' read -ra test_arr <<< "$tests"
      for t in "${test_arr[@]}"; do
        select_test "$t"
      done
    fi
  done
done

# 如果没有任何测试被选中，跑核心冒烟测试作为兜底
if [ -z "$SELECTED_TESTS" ]; then
  echo "  未匹配到任何模块，跑核心冒烟测试兜底"
  SELECTED_TESTS="tests/test_architect_system.sh"
fi

echo "  选定的测试($(echo $SELECTED_TESTS | wc -w)个):"
for t in $SELECTED_TESTS; do
  echo "    bash $t"
done

# ------------------------------------------------------------
# 4. 执行测试（--dry-run 只打印）
# ------------------------------------------------------------
if [ "$DRY_RUN" = "true" ]; then
  exit 0
fi

echo ""
FAILED=0
for t in $SELECTED_TESTS; do
  echo ""
  echo "==== 运行测试: $t ===="
  if bash "$t"; then
    echo "  ✅ $t 通过"
  else
    echo "  ❌ $t 失败"
    FAILED=1
  fi
done

echo ""
if [ "$FAILED" = "0" ]; then
  echo "==== [change-aware] 所有选定测试通过 ===="
else
  echo "==== [change-aware] 存在失败测试 ===="
fi
exit $FAILED
