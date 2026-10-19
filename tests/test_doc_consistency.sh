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
# 测试隔离：评审效率运行时核验会真发一班车 → 队列/账本落临时目录，不污染工作区共享状态
TMPDIR_DC="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_DC"' EXIT
export BUS_QUEUE_FILE="$TMPDIR_DC/bus_queue.json"
export QUOTA_LEDGER_FILE="$TMPDIR_DC/quota_ledger.json"

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

absent() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" != *"$needle"* ]]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 不应再含: $needle")
    echo "  ❌ $name（不应再含: $needle）"
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
# 五、统一审查处置标签：文档与实现一致性
# ============================================================
echo ""
echo "▶ 五、统一审查处置标签（Review Disposition）一致性"

file_exists "REVIEW_DISPOSITION.md 存在" "docs/REVIEW_DISPOSITION.md"
contains "AGENTS.md 含统一审查处置标签规则" "$(cat AGENTS.md)" "统一审查处置标签"

# 引擎（唯一规范来源）应存在，且 spec 覆盖八种标签
OUT=$($PY -c "import sys; sys.path.insert(0,'local-agent'); from collab import disposition; print(','.join(disposition.spec()['labels']))" 2>/dev/null)
check "disposition.spec 八种标签" "merge,proceed,fix_bug,research,human,consult,vote,blocked" "$OUT"

# 评审输出契约强制绑定 disposition
contains "评审输出契约含 disposition" "$(cat local-agent/roles/reviewer.py)" "disposition"
contains "评审提示声明缺标签即评审未完成" "$(cat local-agent/roles/reviewer.py)" "缺标签即评审未完成"

# 文档标签表与引擎 spec 一致（每行含规范标签名）
contains "文档含 merge 标签" "$(cat docs/REVIEW_DISPOSITION.md)" "merge"
contains "文档含 vote 标签" "$(cat docs/REVIEW_DISPOSITION.md)" "vote"
contains "文档含 consult 标签" "$(cat docs/REVIEW_DISPOSITION.md)" "consult"

# 测试护栏存在
file_exists "disposition 测试脚本存在" "local-agent/tests/test_disposition.sh"

# ============================================================
# 六、Issue #98 领域文档 + 追踪问题纪律（P0/P1）一致性
# ============================================================
echo ""
echo "▶ 六、Issue #98 领域文档 + 追踪问题纪律一致性"

# P0-1 单一规范能力/功能索引
file_exists "CAPABILITY_INDEX.md 存在（唯一事实源）" "docs/CAPABILITY_INDEX.md"
contains "AGENTS.md 含领域文档追踪纪律规则" "$(cat AGENTS.md)" "领域文档 + 追踪问题纪律"
contains "CAPABILITY_INDEX 含能力/机制索引" "$(cat docs/CAPABILITY_INDEX.md)" "能力/机制总索引"
contains "CAPABILITY_INDEX 含 ask-matt 式路由速查" "$(cat docs/CAPABILITY_INDEX.md)" "ask-matt 式路由速查"

# P0-2 领域术语表 CONTEXT.md（root 共享语言）
file_exists "root CONTEXT.md 存在（术语表）" "CONTEXT.md"
contains "CONTEXT.md 为纯 glossary 铁律" "$(cat CONTEXT.md)" "纯 glossary"
contains "CONTEXT.md 含 _Avoid_ 弃用词纪律" "$(cat CONTEXT.md)" "_Avoid_"
contains "AGENTS.md 引用 CONTEXT.md 为领域术语表" "$(cat AGENTS.md)" "CONTEXT.md"

# P0-3 决策记录 ADR
file_exists "docs/adr/README.md 存在（ADR 纪律）" "docs/adr/README.md"
contains "ADR 目录含 ADR-0001" "$(ls docs/adr/)" "0001-monorepo-multirole.md"
contains "ADR README 声明三条铁律" "$(cat docs/adr/README.md)" "难反转"
contains "CAPABILITY_INDEX 登记 ADR 能力域" "$(cat docs/CAPABILITY_INDEX.md)" "docs/adr/"

# P0-4 追踪问题 agent-ready brief 链路
file_exists "ISSUE_TRACKING.md 存在（追踪问题链路）" "docs/ISSUE_TRACKING.md"
contains "ISSUE_TRACKING 含 agent-ready brief" "$(cat docs/ISSUE_TRACKING.md)" "agent-ready brief"
contains "ISSUE_TRACKING 含 .out-of-scope 记被否需求" "$(cat docs/ISSUE_TRACKING.md)" ".out-of-scope"
contains "ISSUE_TRACKING 含 wontfix 分诊态" "$(cat docs/ISSUE_TRACKING.md)" "wontfix"
contains ".out-of-scope 目录存在" "$(ls -d .out-of-scope 2>/dev/null)" ".out-of-scope"

# P1-1 code-review 双轴（标准∥spec）
#   修复 Issue #98 遗留（评审机制不全）：双轴不再是"就绪可调能力"，而是评审必走闸门——
#   评审主流程 do_review 强制先产出双轴、机器核验 axes_complete、缺任一轴即评审不完整禁止放行。
contains "评审角色含双轴评审（Standards）" "$(cat local-agent/roles/reviewer.py 2>/dev/null)" "Standards"
contains "评审角色含双轴评审（Spec）" "$(cat local-agent/roles/reviewer.py 2>/dev/null)" "Spec"
contains "评审主流程入口 do_review（双轴强制）" "$(cat local-agent/roles/reviewer.py 2>/dev/null)" "def do_review"
contains "双轴完整性机器核验 axes_complete" "$(cat local-agent/roles/reviewer.py 2>/dev/null)" "axes_complete"
contains "双轴缺轴即不完整禁止放行" "$(cat local-agent/roles/reviewer.py 2>/dev/null)" "双轴必走"
contains "REVIEW_DUAL_AXIS 文档登记必走闸门" "$(cat docs/REVIEW_DUAL_AXIS.md 2>/dev/null)" "必走闸门"
contains "AGENTS.md 登记双轴必走固定规则" "$(cat AGENTS.md 2>/dev/null)" "双轴必走"
# 运行时核验：do_review 缺任一轴 → review_complete=False + disposition=fix_bug（禁止放行）
$PY - >/dev/null 2>&1 <<'PYINNER'
import sys
sys.path.insert(0, "local-agent")
try:
    from data import admin
    admin.init()
    from roles import get_role
    r = get_role("架构·评审")
    rep = r.do_review("缺轴校验", source="PR #x", spec_ref="Issue #x",
                      standards_axis={"🔴": [], "note": "ok"}, spec_axis={})
    assert rep["axes_complete"] is False, "缺轴应不完整"
    assert rep["review_complete"] is False, "缺轴评审不完整"
    assert rep["disposition"] == "fix_bug", "缺轴禁止放行应 fix_bug"
except Exception as e:
    print("ERR", e); sys.exit(1)
PYINNER
if [ $? -eq 0 ]; then
  PASS=$((PASS+1)); echo "  ✅ 运行时核验：do_review 缺轴 → review_complete=False + fix_bug（禁止放行）"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[双轴强制运行时核验] 缺轴未正确判不完整/禁止放行")
  echo "  ❌ 运行时核验：do_review 缺轴未正确判不完整/禁止放行"
fi
# ============================================================
# 七、Issue #150 评审效率（减 CPU 损耗）文档-实现一致性
# ============================================================
echo ""
echo "▶ 七、评审效率·减 CPU 损耗（Issue #150）一致性"

file_exists "REVIEW_EFFICIENCY.md 存在" "docs/REVIEW_EFFICIENCY.md"
contains "AGENTS.md 登记评审效率固定规则" "$(cat AGENTS.md 2>/dev/null)" "评审效率·减 CPU 损耗"
contains "CAPABILITY_INDEX 登记评审增量上下文" "$(cat docs/CAPABILITY_INDEX.md)" "review-context"
contains "CAPABILITY_INDEX 登记评审段调度器" "$(cat docs/CAPABILITY_INDEX.md)" "review-cycle"
file_exists "ADR-0011 存在（评审效率决策）" "docs/adr/0011-review-incremental-coalesced-cycle.md"
file_exists "ADR-0012 存在（阶段链门控决策）" "docs/adr/0012-stage-chain-gate.md"
contains "CAPABILITY_INDEX 登记阶段链门控" "$(cat docs/CAPABILITY_INDEX.md)" "stage-gate"
# 八、写时状态中介（写路径原子化 + 迁移下沉 · ADR-0013）文档-实现一致性
echo ""
echo "▶ 八、写时状态中介（写路径原子化）一致性"
file_exists "ADR-0013 存在（写路径原子化决策）" "docs/adr/0013-write-path-atomic-and-migration-sink.md"
# 九、ADR 编号唯一性（PR #175 修复：合并后曾出现两个 ADR-0009 重号）
echo ""
echo "▶ 九、ADR 编号唯一性 / dsh 适配决策登记"
ADR_DUP="$(ls docs/adr/ | grep -oE '^[0-9]{4}' | sort | uniq -d)"
if [ -z "$ADR_DUP" ]; then
  PASS=$((PASS+1)); echo "  ✅ ADR 编号无重号（全仓 00NN 唯一）"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[ADR] 存在重号编号: $ADR_DUP")
  echo "  ❌ ADR 编号重号: $ADR_DUP"
fi
file_exists "ADR-0014 存在（dsh 适配独立模块决策）" "docs/adr/0014-dsh-adapter-new-version.md"
contains "ADR README 登记 ADR-0014" "$(cat docs/adr/README.md)" "0014-dsh-adapter-new-version"
contains "CAPABILITY_INDEX 登记 dsh 适配 ADR-0014" "$(cat docs/CAPABILITY_INDEX.md)" "ADR-0014-dsh"
# 索引行编号须与文件编号一致（防"文件改名了、索引行没改"）
contains "ADR README 索引行编号与文件编号一致" "$(grep 'dsh-adapter-new-version' docs/adr/README.md)" "| [0014-dsh"

contains "ADR README 登记 ADR-0013" "$(cat docs/adr/README.md)" "0013-write-path-atomic"
contains "CAPABILITY_INDEX 登记写时状态中介" "$(cat docs/CAPABILITY_INDEX.md)" "写时状态中介"
contains "AGENTS.md 登记写路径原子化规则" "$(cat AGENTS.md)" "写路径原子化"
contains "COLLAB_ENGINE 记录唯一键含 branch" "$(cat docs/COLLAB_ENGINE.md)" "UNIQUE(entity_loc, branch, vno)"
contains "COLLAB_ENGINE 记录负数冲突编号语义" "$(cat docs/COLLAB_ENGINE.md)" "冲突提案用负数编号"
file_exists "迁移模块存在" "local-agent/data/migrate.py"
file_exists "写时状态中介 feature-verify 存在" "scripts/feature-verify/collab/写时状态中介.sh"
# 复评返工：远程写路径显式收口（fail-loud）+ 假绿收口 + PG 闭环跟踪项
contains "ADR-0013 记录 PG 写路径闭环为跟踪项" "$(cat docs/adr/0013-write-path-atomic-and-migration-sink.md)" "跟踪项"
contains "db.py 修正无缝切换表述（写路径闭环为跟踪项）" "$(cat local-agent/data/db.py)" "跟踪项"
contains "db.py 远程事务内 db.execute fail-loud" "$(cat local-agent/data/db.py)" "远程后端的事务内不支持 db.execute()"
contains "DATA_ARCHITECTURE 暴露 PG 写路径未闭环" "$(cat docs/DATA_ARCHITECTURE.md)" "PG 写路径端到端尚未闭环"
contains "test_data_layer 组10 假绿收口为适配层冒烟" "$(cat local-agent/tests/test_data_layer.sh)" "适配层冒烟（sqlite 方言"
# CI 依赖接线防静默退化：feature-verify Then-6 依赖 sqlalchemy；若 CI 不装，该信号灯
# 在云端变空转（跳过）→ 与本地不一致。锁死「依赖声明在 requirements + CI 显式安装」。
contains "requirements 声明 sqlalchemy 依赖项（非注释，Then-6 依赖）" "$(grep -E '^sqlalchemy' local-agent/requirements.txt)" "sqlalchemy"
contains "CI feature-verify 作业显式安装依赖（不静默跳过）" "$(cat .cnb.yml)" 'python3 -c "import sqlalchemy'
contains "feature-verify Then-6 带环境守卫（无 sqlalchemy 优雅跳过）" "$(cat scripts/feature-verify/collab/写时状态中介.sh)" "Then-6 跳过：未装 sqlalchemy"
# 🟡 收口：「无缝迁移/切换」残留清零——文档不得再给「零成本切 PG」的假象
# （db.py / DATA_ARCHITECTURE 已改口，AGENTS.md:616 与 schema.py:18 两处残留一并收）。
absent "AGENTS.md 不再称「同一套表结构与接口无缝迁移」" "$(cat AGENTS.md)" "同一套表结构与接口无缝迁移"
absent "schema.py 不再称「同一套 schema 在不同后端无缝切换」" "$(cat local-agent/data/schema.py)" "在不同后端无缝切换"
contains "AGENTS.md 暴露 PG 写路径未闭环（勿按无缝预期）" "$(cat AGENTS.md)" "但 PG 写路径端到端尚未闭环"
contains "schema.py 暴露 PG 写路径未闭环（勿按无缝预期）" "$(cat local-agent/data/schema.py)" "但 PG 写路径端到端尚未闭环"
contains "AGENTS.md 登记阶段链门控规则" "$(cat AGENTS.md)" "阶段链门控"
file_exists "阶段链门控引擎存在" "local-agent/review_cycle/gate.py"
file_exists "阶段链唯一事实源存在" "local-agent/review_cycle/stage_spec.py"
file_exists "review_context 引擎存在" "local-agent/review_context/engine.py"
file_exists "review_cycle 引擎存在" "local-agent/review_cycle/cycle.py"
file_exists "评审效率测试存在" "local-agent/tests/test_review_efficiency.sh"

# 运行时核验：评审角色主流程内接线（增量上下文 + 攒批）真实生效
$PY - >/dev/null 2>&1 <<'PYINNER2'
import sys
sys.path.insert(0, "local-agent")
try:
    from data import admin
    admin.init()
    from roles import get_role
    from review_cycle.gate import StageGate
    import tempfile
    r = get_role("架构·评审")
    assert hasattr(r, "build_review_context"), "评审应具备 build_review_context"
    assert hasattr(r, "prepare_review_batch"), "评审应具备 prepare_review_batch"
    # 阶段链门控（Issue #150 打断补齐）：先让上游收口，评审才允许触发
    g = StageGate(state_file=tempfile.mktemp(suffix=".json"))
    g.mark_done("效率核验", "development"); g.mark_done("效率核验", "testing")
    rep = r.do_review("效率核验", source="PR #150", spec_ref="Issue #150",
                      standards_axis={"🔴": [], "note": "ok"},
                      spec_axis={"faithful": True},
                      stable_parts={"goal": "G" * 300},
                      volatile_parts={"diff_summary": "d"},
                      extra_tests=["local-agent/tests/test_a.sh"],
                      gate=g, auto_route=False)
    assert rep["context_pack"] is not None, "do_review 应产出增量上下文包"
    assert rep["batch"] is not None, "do_review 应产出攒批结果"
except Exception as e:
    print("ERR", e); sys.exit(1)
PYINNER2
if [ $? -eq 0 ]; then
  PASS=$((PASS+1)); echo "  ✅ 运行时核验：do_review 内接线 增量上下文 + 攒批"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[评审效率接线] do_review 未接增量上下文/攒批")
  echo "  ❌ 运行时核验：do_review 未接增量上下文/攒批"
fi

# 运行时核验：阶段链门控真的拦抢跑（缺轴/阶段门任一不完整即不允许放行）
$PY - >/dev/null 2>&1 <<'PYINNER3'
import sys, tempfile
sys.path.insert(0, "local-agent")
try:
    from review_cycle.gate import StageGate
    from review_cycle import stage_spec
    # N1 校正：仓库权威链条 = 开发 → 评审 → 测试（评审通过才转交测试）
    assert stage_spec.STAGE_ORDER == ("development", "review", "testing"), stage_spec.STAGE_ORDER
    assert stage_spec.UPSTREAM == {"review": "development", "testing": "review"}
    g = StageGate(state_file=tempfile.mktemp(suffix=".json"))
    g.mark_active("T", "development")
    v = g.should_trigger("T", "review")
    assert v["allow"] is False and v["decision"] == "blocked_upstream", v
    v2 = g.should_trigger("T", "development")
    assert v2["decision"] == "blocked_active", v2
    # 链式推进：开发收口 → 评审放行 → 评审收口 → 测试放行
    g.mark_done("T", "development")
    assert g.should_trigger("T", "review")["allow"] is True
    g.mark_active("T", "review")
    g.mark_done("T", "review")
    assert g.should_trigger("T", "testing")["allow"] is True
except Exception as e:
    print("ERR", e); sys.exit(1)
PYINNER3
if [ $? -eq 0 ]; then
  PASS=$((PASS+1)); echo "  ✅ 运行时核验：阶段链门控拦抢跑/重复触发（allow=False）"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[阶段链门控] 抢跑/重复触发未被拦下")
  echo "  ❌ 运行时核验：阶段链门控未拦下抢跑/重复触发"
fi


# ============================================================
# ADR-0013 口径锁（Issue #165 项4 · 复评 🔴2 返工）
# ------------------------------------------------------------
# ADR-0013 原文锁的对象是 `feature-verify \`collab/写时状态中介\``（Then-1~N），
# 证据脚本是 scripts/feature-verify/collab/写时状态中介.sh —— **不是 selector**。
# 原版口径锁取的是 selector/映射全覆盖.sh 的最大 Then（11），与 ADR 那句话无关：
# 锁本身永远绿（抓不住漂移），并且把 ADR 从「Then-1~5（少报）」放成「Then-1~11（多报）」。
# 本版三件事一起做，缺一不成：
#   ① 证据脚本指向 collab/写时状态中介.sh，grep 口径取全文 Then-N[a-z]（该脚本多数
#      断言写在 ok()/bad() 的字符串里，只 grep `^# -+ Then-` 会漏到 6 以下）；
#   ② ADR 的 Then-1~N 改成脚本**实际最大序号**；
#   ③ 牙齿自证：把 ADR 临时改成错值，锁必须转红（否则又是"永远绿"的假牙）。
# ============================================================
echo ""
echo "▶ ADR-0013 Then 覆盖区间口径锁（证据=collab/写时状态中介）"
ADR_FILE="docs/adr/0013-write-path-atomic-and-migration-sink.md"
EVID_SH="scripts/feature-verify/collab/写时状态中介.sh"

# max_then <file>：脚本内实际最大 Then 主序号（Then-1b / Then-5b 归主序号）
max_then() {
  grep -oE 'Then-[0-9]+[a-z]?' "$1" 2>/dev/null | grep -oE '[0-9]+' | sort -n | tail -1
}
# adr_then <file>：ADR 声明的 Then-1~N 的 N
adr_then() {
  grep -oE 'Then-1~[0-9]+' "$1" 2>/dev/null | grep -oE '[0-9]+$' | head -1
}

if [ -f "$ADR_FILE" ] && [ -f "$EVID_SH" ]; then
  EVID_MAX="$(max_then "$EVID_SH")"
  ADR_N="$(adr_then "$ADR_FILE")"
  check "ADR-0013 声明的 Then-1~N 与 collab 证据脚本实际最大 Then 一致" "$EVID_MAX" "$ADR_N"
  contains "ADR-0013 口径引用指向 collab/写时状态中介证据" "$(cat "$ADR_FILE")" 'collab/写时状态中介'
  # 牙齿自证：ADR 改成错值（实际+1）必须被判红 → 证明上面的 check 不是恒真
  ADR_MUT="$(mktemp)"
  sed -E "s/Then-1~[0-9]+/Then-1~$((EVID_MAX + 1))/" "$ADR_FILE" > "$ADR_MUT"
  if [ "$(adr_then "$ADR_MUT")" != "$(max_then "$EVID_SH")" ]; then
    PASS=$((PASS+1)); echo "  ✅ ADR-0013 口径锁有牙：ADR 写成 Then-1~$((EVID_MAX + 1)) 时锁判不一致（非恒真）"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[ADR-0013 口径锁牙齿] ADR 写错值仍判一致 → 锁是空牙")
    echo "  ❌ ADR-0013 口径锁牙齿：ADR 写错值仍判一致 → 锁是空牙"
  fi
  # 反向自证：证据脚本换成 selector（原版的错对象）时数值应当不同，
  # 说明「指向哪个脚本」真的决定结果，不是两处恰好同值造成的假一致
  SEL_SH="scripts/feature-verify/selector/映射全覆盖.sh"
  if [ -f "$SEL_SH" ] && [ "$(max_then "$SEL_SH")" != "$EVID_MAX" ]; then
    PASS=$((PASS+1)); echo "  ✅ ADR-0013 口径锁对象正确：selector 最大 Then=$(max_then "$SEL_SH") ≠ collab 证据 $EVID_MAX（原版锁错对象）"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[ADR-0013 口径锁对象] selector 与 collab 证据最大 Then 相同，无法证明锁错对象")
    echo "  ❌ ADR-0013 口径锁对象：两脚本最大 Then 相同，锁对象是否正确的判据不成立"
  fi
  rm -f "$ADR_MUT"
else
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[ADR-0013 口径锁] 文件缺失：$ADR_FILE 或 $EVID_SH")
  echo "  ❌ ADR-0013 口径锁：文件缺失"
fi

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
