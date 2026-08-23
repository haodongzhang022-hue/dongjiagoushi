#!/usr/bin/env bash
# ============================================================
# 架构师 Agent · 文档-实现一致性测试（T10，doc-consistency）
# 仓库：dongjiagoushi
#
# 作用：防止"文档声明"与"实际实现"漂移。
#   现有测试多验证"产物存在性 / 链路可跑通"，本脚本补上"文档说了什么 vs 代码/配置
#   实际是什么"的一致性断言，作为框架自升级的护栏之一（见 docs/FRAMEWORK_UPGRADE.md）。
#
# 覆盖四类一致性：
#   1. memory 模块：文档声明的文件/能力/embedding 提供方 与 实际代码一致
#   2. embedding 可插拔：get_embedder 支持 hash + sentence，维度一致，可无缝替换
#   3. 框架自升级：FRAMEWORK_UPGRADE.md 存在且与 issue-template 的 upgrade 类型互相呼应
#   4. 看板：generate-dashboard.py 实际生成了"框架健康度"维度
#
# 用法：
#   bash tests/test_doc_consistency.sh
#   .cnb.yml 的 test 阶段调用：bash tests/test_doc_consistency.sh
# ============================================================

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

PY="python3"
export PYTHONPATH="$REPO_ROOT/src"

echo "======================================================"
echo "文档-实现一致性测试 (T10 / doc-consistency)"
echo "仓库: $REPO_ROOT"
echo "======================================================"

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 期望=$expected 实际=$actual")
    echo "  ❌ $name（期望=$expected 实际=$actual）"
  fi
}

contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 缺少: $needle")
    echo "  ❌ $name（缺少: $needle）"
  fi
}

file_exists() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 文件缺失: $file")
    echo "  ❌ $name（文件缺失: $file）"
  fi
}

# ============================================================
# 一、memory 模块：文档声明的文件与能力 与 实际实现一致
# ============================================================
echo ""
echo "▶ 一、memory 模块文档-实现一致性"

# MEMORY.md 声明的文件应实际存在
for f in src/memory/schema.py src/memory/store.py src/memory/triggers.py \
         src/memory/cli.py src/memory/backends/embedding.py \
         src/memory/backends/sentence_embedding.py \
         src/memory/backends/lancedb_backend.py src/memory/backends/cloud_backend.py; do
  file_exists "memory 文档声明文件存在: $f" "$f"
done

# 文档声明了"真实语义 embedding"能力 → 代码里应有 SentenceEmbedding 与 get_embedder('sentence')
contains "MEMORY.md 声明真实 embedding" "$(cat docs/MEMORY.md)" "sentence-transformers"
contains "代码实现 SentenceEmbedding" "$(cat src/memory/backends/sentence_embedding.py)" "class SentenceEmbedding"
contains "get_embedder 支持 sentence" "$(cat src/memory/backends/embedding.py)" '"sentence"'

# 文档声明的统一维度应与代码一致（EMBEDDING_DIM=256）
OUT=$($PY -c "from memory.schema import EMBEDDING_DIM; print(EMBEDDING_DIM)")
check "EMBEDDING_DIM 与文档一致=256" "256" "$OUT"

# ============================================================
# 二、embedding 可插拔：hash 与 sentence 维度一致、可无缝替换
# ============================================================
echo ""
echo "▶ 二、embedding 可插拔一致性"

# get_embedder 默认 hash；sentence 未装模型时回退 hash，维度都=256
OUT=$($PY - <<'PYEOF'
from memory.backends.embedding import get_embedder
h = get_embedder("hash")
s = get_embedder("sentence")
print(f"{len(h.embed('测试'))}|{len(s.embed('测试'))}|{s.name}")
PYEOF
)
check "hash 与 sentence 维度一致(=256|256)" "256|256|sentence" "$OUT"

# schema 提供 hash_embedding 且触发引擎默认走 hash（CI 可复现）
contains "triggers 默认 hash 向量化" "$(cat src/memory/triggers.py)" 'embed_kind: str = "hash"'

# ============================================================
# 三、框架自升级闭环：文档与模板互相呼应
# ============================================================
echo ""
echo "▶ 三、框架自升级闭环一致性"

file_exists "FRAMEWORK_UPGRADE.md 存在" "docs/FRAMEWORK_UPGRADE.md"
contains "FRAMEWORK 声明 upgrade 类型" "$(cat docs/FRAMEWORK_UPGRADE.md)" "type=upgrade"
contains "FRAMEWORK 声明 framework 模块版本线" "$(cat docs/FRAMEWORK_UPGRADE.md)" "framework 模块版本线"
contains "issue-template 声明 upgrade 类型" "$(cat docs/templates/issue-template.md)" "upgrade"
contains "issue-template 引用 FRAMEWORK_UPGRADE" "$(cat docs/templates/issue-template.md)" "FRAMEWORK_UPGRADE.md"
contains "ISSUE_MANAGEMENT 声明 framework 模块" "$(cat docs/ISSUE_MANAGEMENT.md)" "framework"
contains "ISSUE_MANAGEMENT 声明 upgrade 类型" "$(cat docs/ISSUE_MANAGEMENT.md)" "upgrade"

# ============================================================
# 四、看板：generate-dashboard.py 实际支持"框架健康度"维度
# ============================================================
echo ""
echo "▶ 四、看板框架健康度一致性"

contains "generate-dashboard 支持框架健康度" "$(cat scripts/generate-dashboard.py)" "框架健康度"
contains "DASHBOARD 已含框架健康度章节" "$(cat docs/DASHBOARD.md)" "框架健康度"

# ============================================================
# 汇总（信号灯）
# ============================================================
echo ""
echo "======================================================"
echo "测试汇总：PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "❌ 信号灯：🔴 阻塞（存在文档-实现漂移，不允许放行）"
  echo "失败项："
  for item in "${FAILED_ITEMS[@]}"; do
    echo "  - $item"
  done
  exit 1
else
  echo "✅ 信号灯：🟢 通过（文档与实现一致）"
  exit 0
fi
