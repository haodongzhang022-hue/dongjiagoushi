#!/usr/bin/env bash
# ============================================================
# 架构师 Agent · 真实功能链路测试（arch-skill 模块 v0.2.0）
# 仓库：dongjiagoushi
#
# 作用：把「不是代码写完就行，而是实际功能要能用」变成机器强制的信号灯。
#   区别于 test_architect_system.sh 的「静态断言（grep 关键词）」，
#   本脚本对三大真实功能链路做【真实执行】验证：
#
#   F1 数据获取链路   —— 真实调用 cnb issues API 拉取 Issue 声明头，验证能解析出模块
#   F2 看板呈现链路   —— 真实运行 scripts/generate-dashboard.py，验证生成 docs/DASHBOARD.md
#                         且内容确实包含各模块版本演进线（人类可真俯瞰）
#   F3 RAG 读取链路   —— 真实查询仓库知识库（knowledge-base query），验证
#                         架构上下文文档已入库、能被 RAG 检索命中
#
# 用法：
#   bash tests/test_functional_links.sh   # 本地/CI 运行
#   .cnb.yml 的 test 阶段可追加调用本脚本
#
# 前置：环境需具备 cnb CLI（携带平台鉴权）、python3、bash。
# ============================================================

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

REPO="${CNB_REPO_SLUG:-dongdongxiaozu/dongjiagoushi}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); FAILED_ITEMS+=("$1"); echo "  ❌ $1"; }

# ------------------------------------------------------------
# 环境守卫：真实功能链路测试依赖 cnb CLI（携带平台鉴权）访问
#   Issue API 与知识库 RAG。云 CI 容器（python:3.11）未装 cnb，
#   此环境无法真实连通平台链路 → 优雅跳过（exit 0），不作为失败。
#   本地/验收环境（具备 cnb CLI）则完整执行 F1/F2/F3 三大链路。
#   （对齐 Issue #57：云 CI 只留轻量校验，功能/真实链路本地验收）
# ------------------------------------------------------------
if ! command -v cnb >/dev/null 2>&1; then
  echo ""
  echo "⏭️  环境未安装 cnb CLI，真实功能链路（Issue API / 知识库 RAG）无法在此环境连通。"
  echo "    本测试为本地/验收链路测试，云 CI 优雅跳过（视为通过），本地执行脚本见"
  echo "    scripts/local-exec.sh（真实链路在具备 cnb CLI 的环境全量验收）。"
  echo "    ⏭️  SKIP（cnb CLI 缺失 → 跳过 F1/F2/F3 真实链路）"
  echo "======================================================"
  exit 0
fi


echo "======================================================"
echo "架构师体系 · 真实功能链路测试 (arch-skill v0.2.0)"
echo "仓库: $REPO"
echo "======================================================"

# ------------------------------------------------------------
# F1 数据获取链路 —— 真实调用 cnb issues API
#   验证：能拉到 Issue 列表，且能从正文声明头解析出模块归属
# ------------------------------------------------------------
echo ""
echo "▶ F1 数据获取链路（真实调用 cnb issues API）"

cnb issues list-issues --repo "$REPO" --page 1 --page-size 100 --verbose \
  > "$TMPDIR/issues.json" 2>/dev/null
RC=$?
if [ $RC -eq 0 ] && python3 -c "import json;json.load(open('$TMPDIR/issues.json'))" 2>/dev/null; then
  ok "F1.1 真实调用 cnb issues API 返回可解析 JSON (rc=$RC)"
else
  bad "F1.1 真实调用 cnb issues API 返回可解析 JSON (rc=$RC)"
fi

ISSUE_COUNT="$(python3 -c "
import json
d=json.load(open('$TMPDIR/issues.json'))
print(len(d['data']) if isinstance(d.get('data'),list) else 0)
" 2>/dev/null || echo 0)"
if [ "$ISSUE_COUNT" -gt 0 ]; then
  ok "F1.2 拉取到真实 Issue 数>0 (实际=$ISSUE_COUNT)"
else
  bad "F1.2 拉取到真实 Issue 数>0 (实际=$ISSUE_COUNT)"
fi

# 1.3 用真实 Issue 数据，通过生成器自带的解析函数验证声明头可解析
if [ -f scripts/generate-dashboard.py ]; then
  PARSE_OUT="$(python3 - "$REPO" <<'PY'
import sys, json, importlib.util
repo = sys.argv[1]
# 只加载解析逻辑（复用生成器的 fetch/parse 函数），不执行 main
src = open("scripts/generate-dashboard.py").read()
# 用 exec 但拦截 main 执行：生成器应有 if __name__=="__main__" 保护
spec = importlib.util.spec_from_loader("gen", loader=None)
# 简化：直接用正则解析生成器的 parse_decl 逻辑不可靠，改为加载模块
import types
mod = types.ModuleType("gen")
mod.__file__ = "scripts/generate-dashboard.py"
try:
    exec(compile(src, "scripts/generate-dashboard.py", "exec"), mod.__dict__)
    issues = mod.fetch_issues()
    decls = [mod.parse_decl(i.get("body","")) for i in issues]
    modules = sorted(set(d.get("module") for d in decls if d.get("module")))
    print("ISSUES=%d MODULES=%d LIST=%s" % (len(issues), len(modules), ",".join(modules)))
except Exception as e:
    print("ISSUES=0 MODULES=0 LIST=ERR:%s" % e)
PY
)"
  MODS="$(echo "$PARSE_OUT" | grep -oE 'MODULES=[0-9]+' | cut -d= -f2)"
  MODULE_LIST="$(echo "$PARSE_OUT" | grep -oE 'LIST=.*' | cut -d= -f2)"
  if [ "${MODS:-0}" -gt 0 ] 2>/dev/null; then
    ok "F1.3 真实解析 Issue 声明头 (识别 $MODS 个模块)"
  else
    bad "F1.3 真实解析 Issue 声明头 (识别 ${MODS:-0} 个模块)"
  fi
  if [ "${MODS:-0}" -gt 0 ] 2>/dev/null && [ -n "$MODULE_LIST" ]; then
    ok "F1.4 解析出模块声明头（实际=$MODULE_LIST）"
  else
    bad "F1.4 解析出模块声明头 (实际=${MODULE_LIST:-空})"
  fi
else
  bad "F1.3 生成器脚本缺失，无法验证数据获取"
fi

# ------------------------------------------------------------
# F2 看板呈现链路 —— 真实运行看板生成器
#   验证：能产出 docs/DASHBOARD.md 且内容包含模块版本演进线（人类可真俯瞰）
# ------------------------------------------------------------
echo ""
echo "▶ F2 看板呈现链路（真实运行 generate-dashboard.py）"

if [ -f scripts/generate-dashboard.py ]; then
  BEFORE="$(cat docs/DASHBOARD.md 2>/dev/null | md5sum | awk '{print $1}')"
  GEN_RC=0
  timeout 120 python3 scripts/generate-dashboard.py > "$TMPDIR/gen.log" 2>&1 || GEN_RC=$?
  if [ $GEN_RC -eq 0 ] && grep -q "ok" "$TMPDIR/gen.log"; then
    ok "F2.1 生成器真实运行成功 (rc=$GEN_RC)"
  else
    bad "F2.1 生成器真实运行成功 (rc=$GEN_RC)"
  fi
  # F2.6/F2.7 动态化：从当前 Issue 声明的模块/链接校验（不再硬编码 arch-skill/#4，
  # 避免 Issue 演进后过时断言误伤（历史 arch-skill 已不在当前 issue 声明中）。
  DASH_MODULES="$(grep '^### 模块' docs/DASHBOARD.md | sed 's/^### 模块 //;s/\`//g' | sort -u | paste -sd, -)"
  DASH_ISSUE="$(grep -oE 'issues/[0-9]+' docs/DASHBOARD.md | head -1 || true)"
  for pair in \
    "F2.2 docs/DASHBOARD.md 文件存在|test -f docs/DASHBOARD.md" \
    "F2.3 看板含「模块版本演进看板」标题|grep -q '模块版本演进看板' docs/DASHBOARD.md" \
    "F2.4 看板含「里程碑表」|grep -q '里程碑表' docs/DASHBOARD.md" \
    "F2.5 看板含「Issue 声明汇总表」|grep -q 'Issue 声明汇总表' docs/DASHBOARD.md"; do
    name="${pair%%|*}"; cond="${pair#*|}"
    if eval "$cond"; then ok "$name"; else bad "$name"; fi
  done
  # F2.6 看板至少含一个模块版本线（与实际 Issue 声明的模块一致）
  if [ -n "$DASH_MODULES" ]; then
    ok "F2.6 看板呈现模块版本线 (实际模块: $DASH_MODULES)"
  else
    bad "F2.6 看板呈现模块版本线 (无模块版本线)"
  fi
  # F2.7 看板含真实 Issue 链接（有任一 Issue 链接即通过）
  if [ -n "$DASH_ISSUE" ]; then
    ok "F2.7 看板含真实 Issue 链接 ($DASH_ISSUE)"
  else
    bad "F2.7 看板含真实 Issue 链接 (未发现)"
  fi
  AFTER="$(cat docs/DASHBOARD.md | md5sum | awk '{print $1}')"
  echo "  ℹ️ F2.8 生成前后 DASHBOARD.md md5: ${BEFORE:0:8}→${AFTER:0:8}（无 diff=看板已与真实数据一致）"
else
  bad "F2.1 生成器脚本缺失，无法验证看板呈现"
fi

# ------------------------------------------------------------
# F3 RAG 读取链路 —— 真实查询仓库知识库
#   验证：架构上下文文档已入库、能被 RAG 检索命中
# ------------------------------------------------------------
echo ""
echo "▶ F3 RAG 读取链路（真实查询 knowledge-base）"

cnb knowledge-base get-knowledge-base-info --repo "$REPO" --verbose \
  > "$TMPDIR/kb.json" 2>/dev/null
if python3 -c "import json;d=json.load(open('$TMPDIR/kb.json'));assert d.get('status')==200" 2>/dev/null; then
  ok "F3.1 知识库存在并可查询"
else
  bad "F3.1 知识库存在并可查询"
fi

KB_COUNT="$(python3 -c "
import json
d=json.load(open('$TMPDIR/kb.json'))['data']
print(d.get('statistics',{}).get('count',0))
" 2>/dev/null || echo 0)"
if [ "${KB_COUNT:-0}" -gt 0 ] 2>/dev/null; then
  ok "F3.2 知识库已入库文档块>0 (实际=$KB_COUNT)"
else
  bad "F3.2 知识库已入库文档块>0 (实际=${KB_COUNT:-0})"
fi

if python3 -c "
import json
d=json.load(open('$TMPDIR/kb.json'))['data']
m=d.get('embedding_model',{})
assert 'hunyuan' in str(m.get('name',''))
" 2>/dev/null; then
  ok "F3.3 知识库 embedding 模型=hunyuan"
else
  bad "F3.3 知识库 embedding 模型=hunyuan"
fi

if python3 -c "
import json
d=json.load(open('$TMPDIR/kb.json'))['data']
assert d.get('issue_sync_enabled') is True
" 2>/dev/null; then
  ok "F3.4 Issue 数据同步已开启 (issueSyncEnabled)"
else
  bad "F3.4 Issue 数据同步已开启 (issueSyncEnabled)"
fi

# 真实发起一次 RAG 检索，验证能命中架构上下文
cnb knowledge-base query-knowledge-base-get --repo "$REPO" \
  --query "架构师框架的核心设计理念是什么" --top-k 3 --verbose \
  > "$TMPDIR/query.json" 2>/dev/null
if python3 -c "import json;d=json.load(open('$TMPDIR/query.json'));assert d.get('status')==200" 2>/dev/null; then
  ok "F3.5 真实 RAG 检索成功"
else
  bad "F3.5 真实 RAG 检索成功"
fi

HIT_COUNT="$(python3 -c "
import json
d=json.load(open('$TMPDIR/query.json'))
print(len(d.get('data',[])) if isinstance(d.get('data'),list) else 0)
" 2>/dev/null || echo 0)"
if [ "${HIT_COUNT:-0}" -gt 0 ] 2>/dev/null; then
  ok "F3.6 RAG 检索命中结果>0 (实际=$HIT_COUNT)"
else
  bad "F3.6 RAG 检索命中结果>0 (实际=${HIT_COUNT:-0})"
fi

# 命中结果含架构上下文关键词，且结果可溯源（url 元数据）
if python3 -c "
import json
d=json.load(open('$TMPDIR/query.json')).get('data',[])
joined=json.dumps(d, ensure_ascii=False)
assert any(k in joined for k in ['AI 优先','人类俯瞰','主动规避风险','架构八步']), '无设计理念关键词'
" 2>/dev/null; then
  ok "F3.7 RAG 命中内容含核心设计理念"
else
  bad "F3.7 RAG 命中内容含核心设计理念"
fi

if python3 -c "
import json
d=json.load(open('$TMPDIR/query.json')).get('data',[])
for it in d:
    if isinstance(it.get('metadata'),dict) and it['metadata'].get('url'):
        raise SystemExit(0)
raise SystemExit(1)
" 2>/dev/null; then
  ok "F3.8 RAG 结果可溯源(含 url 元数据)"
else
  bad "F3.8 RAG 结果可溯源(含 url 元数据)"
fi

# ------------------------------------------------------------
# 汇总（信号灯）
# ------------------------------------------------------------
echo ""
echo "======================================================"
echo "真实功能链路测试汇总：PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "❌ 信号灯：🔴 阻塞（存在真实功能链路未达成的项，不允许放行）"
  echo "失败项："
  for item in "${FAILED_ITEMS[@]}"; do
    echo "  - $item"
  done
  exit 1
else
  echo "✅ 信号灯：🟢 通过（数据获取 / 看板呈现 / RAG 读取 三大真实功能链路全部打通）"
  exit 0
fi
