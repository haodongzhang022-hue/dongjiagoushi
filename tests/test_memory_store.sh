#!/usr/bin/env bash
# ============================================================
# 架构师 Agent · 经验记忆库 + 语义向量触发 功能测试（T9，memory）
# 仓库：dongjiagoushi
#
# 作用：验证「语义向量触发真正落地 + 双后端兼容（LanceDB/云端同格式）」
#   已从"纸面/prompt 关键词"升级为"真实向量检索 + 持久化记忆库"。
#   本脚本端到端验证：
#     1. 语义向量触发（无显式 [触发] 也能按职责语义命中正确角色）
#     2. 显式 [触发] 优先级最高
#     3. 本地 LanceDB 后端：写入/检索/计数/持久化
#     4. 云端后端（同格式）：写入/检索/导出 Markdown+JSONL
#     5. 双兼容（dual 双写）：本地与云端同格式同时写入
#     6. 经验积累：写入协作交互记录，可被检索回溯（持续积累经验）
#     7. 统一格式：MemoryRecord schema 两端一致、Markdown 可往返解析
#
# 用法：
#   bash tests/test_memory_store.sh      # 本地运行（需 python3 + lancedb）
#   可在 .cnb.yml 的 test 阶段一并调用
# ============================================================

set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

# 临时目录
TMP_DIR=$(mktemp -d /tmp/memtest_XXXXXX)
trap 'rm -rf "$TMP_DIR"' EXIT

PY="python3"
export PYTHONPATH="$REPO_ROOT/src"

echo "======================================================"
echo "架构师体系 · 经验记忆库 + 语义向量触发 (memory / T9)"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# 检查 lancedb 可用
if ! $PY -c "import lancedb" 2>/dev/null; then
  echo "❌ 未安装 lancedb，请先: pip install -r src/memory/requirements.txt"
  echo "   (语义触发引擎部分仍可测试，LanceDB 后端部分将被跳过)"
  HAS_LANCEDB=0
else
  HAS_LANCEDB=1
fi

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
    echo "  ❌ $name"
  fi
}

# ============================================================
# 一、语义向量触发（不依赖显式 [触发]，按职责语义命中角色）
# ============================================================
echo ""
echo "▶ 场景A · 语义向量触发（真实向量检索 → 角色）"

OUT=$($PY - <<PYEOF
from memory import SemanticTriggerEngine
eng = SemanticTriggerEngine()
cases = {
  "写一个登录接口": "架构·开发",
  "实现auth模块": "架构·开发",
  "提交PR": "架构·开发",
  "帮我评审这段代码有没有bug": "架构·评审",
  "拆解需求": "架构·产品",
  "跑测试看能不能通过": "架构·测试",
}
for text, expect in cases.items():
    r = eng.trigger(text)
    print(f"{text}|{r['method']}|{r['role']}|{expect}")
PYEOF
)
while IFS='|' read -r text method role expect; do
  [ -z "$text" ] && continue
  check "语义触发: $text → $expect (method=$method)" "$expect" "$role"
done <<< "$OUT"

# ============================================================
# 二、显式 [触发] 优先级最高
# ============================================================
echo ""
echo "▶ 场景B · 显式 [触发] 优先级最高"

OUT=$($PY - <<PYEOF
from memory import SemanticTriggerEngine
r = SemanticTriggerEngine().trigger("[触发:架构·评审] 顺便帮我看看这段代码")
print(r['method'] + "|" + r['role'])
PYEOF
)
check "显式[触发]优先 → method=explicit role=架构·评审" "explicit|架构·评审" "$OUT"

# ============================================================
# 三、本地 LanceDB 后端（写入/检索/计数/持久化）
# ============================================================
echo ""
if [ "$HAS_LANCEDB" = "1" ]; then
  echo "▶ 场景C · 本地 LanceDB 后端"

  OUT=$($PY - <<PYEOF
from memory import MemoryStore, MemoryRecord
from memory.schema import hash_embedding, now_iso
store = MemoryStore(backend="lancedb", path="$TMP_DIR/lance")
store.add([
  MemoryRecord(id="r1", role="架构·开发", category="experience", text="实现 auth 登录接口，边界仅后端", vector=hash_embedding("实现 auth 登录接口"), meta={"status":"done"}, created_at=now_iso()),
  MemoryRecord(id="r2", role="架构·评审", category="experience", text="评审发现空指针 bug，打回修复", vector=hash_embedding("评审空指针 bug"), meta={}, created_at=now_iso()),
])
c = store.count()
res = store.search(hash_embedding("实现登录功能"), top_k=1)
hits = res[0][0].text if res else ""
score = round(res[0][1], 3) if res else 0.0
print(f"{c}|{hits}|{score}")
store.close()
PYEOF
  )
  IFS='|' read -r c hits score <<< "$OUT"
  check "LanceDB 写入后计数=2" "2" "$c"
  contains "LanceDB 向量检索命中 auth 登录实现" "$hits" "auth 登录接口"
  echo "  （检索相似度: $score）"

  # 持久化验证：重开连接仍能读到
  OUT=$($PY - <<PYEOF
from memory import MemoryStore
s = MemoryStore(backend="lancedb", path="$TMP_DIR/lance")
print(s.count())
s.close()
PYEOF
  )
  check "LanceDB 持久化：重开连接计数仍=2" "2" "$OUT"
else
  echo "  ⏭️ 跳过 LanceDB 后端测试（未安装 lancedb）"
fi

# ============================================================
# 四、云端后端（同格式）+ 统一格式往返
# ============================================================
echo ""
echo "▶ 场景D · 云端后端（CNB 知识库同格式适配）"

OUT=$($PY - <<PYEOF
from memory import MemoryStore, MemoryRecord
from memory.schema import hash_embedding, now_iso, MemoryRecord as R
store = MemoryStore(backend="cloud", export_dir="$TMP_DIR/cloud")
rec = MemoryRecord(id="c1", role="架构·开发", category="experience", text="修复 token 过期逻辑", vector=hash_embedding("修复 token 过期"), meta={"source":"relay"}, created_at=now_iso())
store.add([rec])
c = store.count()
res = store.search(hash_embedding("token 过期怎么修"), top_k=1)
hit = res[0][0].text if res else ""
# 统一格式往返：markdown -> record
roundtrip = R.from_markdown(rec.to_markdown())
print(f"{c}|{hit}|{roundtrip.id}|{roundtrip.role}")
store.close()
PYEOF
)
IFS='|' read -r c hit rid rrole <<< "$OUT"
check "云端后端 计数=1" "1" "$c"
contains "云端后端 同格式检索命中 token 修复" "$hit" "token 过期"
check "统一格式 Markdown 往返解析 id=c1" "c1" "$rid"
check "统一格式 Markdown 往返解析 role=架构·开发" "架构·开发" "$rrole"

# 云端导出文件存在性
if [ -f "$TMP_DIR/cloud/memory_records.md" ]; then
  PASS=$((PASS+1)); echo "  ✅ 云端导出 memory_records.md 存在"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[云端导出] memory_records.md 不存在")
  echo "  ❌ 云端导出 memory_records.md 不存在"
fi
if [ -f "$TMP_DIR/cloud/memory_records.jsonl" ]; then
  PASS=$((PASS+1)); echo "  ✅ 云端导出 memory_records.jsonl 存在"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[云端导出] memory_records.jsonl 不存在")
  echo "  ❌ 云端导出 memory_records.jsonl 不存在"
fi

# ============================================================
# 五、双兼容（dual 双写：本地 + 云端同格式）
# ============================================================
echo ""
echo "▶ 场景E · 双兼容（LanceDB + 云端同格式双写）"

if [ "$HAS_LANCEDB" = "1" ]; then
  OUT=$($PY - <<PYEOF
from memory import MemoryStore, MemoryRecord
from memory.schema import hash_embedding, now_iso
store = MemoryStore(backend="dual", path="$TMP_DIR/dual_lance", export_dir="$TMP_DIR/dual_cloud")
store.add([MemoryRecord(id="d1", role="架构·测试", category="experience", text="测试矩阵 3 项全绿", vector=hash_embedding("测试矩阵全绿"), meta={}, created_at=now_iso())])
lc = store.count()
store.close()
# 云端独立读取
import os
cloud_has_md = os.path.exists("$TMP_DIR/dual_cloud/memory_records.md")
cloud_has_jl = os.path.exists("$TMP_DIR/dual_cloud/memory_records.jsonl")
print(f"{lc}|{cloud_has_md}|{cloud_has_jl}")
PYEOF
  )
  IFS='|' read -r lc cm cj <<< "$OUT"
  check "dual 本地计数=1" "1" "$lc"
  check "dual 云端导出 md 存在" "True" "$cm"
  check "dual 云端导出 jsonl 存在" "True" "$cj"
else
  echo "  ⏭️ 跳过双兼容测试（未安装 lancedb）"
fi

# ============================================================
# 六、经验积累（持续积累：多次交互写入 → 可检索回溯）
# ============================================================
echo ""
echo "▶ 场景F · 持续积累经验（多次写入 → 可检索回溯）"

if [ "$HAS_LANCEDB" = "1" ]; then
  OUT=$($PY - <<PYEOF
from memory import MemoryStore, MemoryRecord, SemanticTriggerEngine
from memory.schema import hash_embedding, now_iso
store = MemoryStore(backend="lancedb", path="$TMP_DIR/accum")
# 模拟多次协作交互积累
interactions = [
  ("架构·开发", "实现 auth 登录接口"),
  ("架构·开发", "修复 token 过期"),
  ("架构·评审", "发现空指针，打回开发"),
  ("架构·测试", "信号灯全绿通过"),
]
for i, (role, text) in enumerate(interactions):
    store.add([MemoryRecord(id=f"a{i}", role=role, category="experience", text=text, vector=hash_embedding(text), meta={}, created_at=now_iso())])
c = store.count()
# 用语义触发引擎结合记忆库做二次确认
eng = SemanticTriggerEngine()
res = eng.trigger_with_memory("实现登录接口", store, top_k=2)
role = res.get("role")
mhits = len(res.get("memory_hits", []))
print(f"{c}|{role}|{mhits}")
store.close()
PYEOF
  )
  IFS='|' read -r c role mhits <<< "$OUT"
  check "经验积累 4 条已写入" "4" "$c"
  check "经验积累 语义触发命中 架构·开发" "架构·开发" "$role"
  if [ "$mhits" -gt 0 ]; then
    PASS=$((PASS+1)); echo "  ✅ 语义触发结合记忆库二次确认（$mhits 条相关经验）"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[经验积累] 无相关记忆命中")
    echo "  ❌ 语义触发结合记忆库二次确认（0 条相关经验）"
  fi
else
  echo "  ⏭️ 跳过经验积累测试（未安装 lancedb）"
fi

# ============================================================
# 汇总
# ============================================================
echo ""
echo "======================================================"
echo "结果: PASS=$PASS FAIL=$FAIL"
echo "======================================================"
if [ "$FAIL" -gt 0 ]; then
  echo "失败项:"
  for item in "${FAILED_ITEMS[@]}"; do echo "  - $item"; done
  exit 1
fi
echo "✅ 全部通过"
exit 0
