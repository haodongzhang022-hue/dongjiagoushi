#!/usr/bin/env bash
# ============================================================
# 架构师 Agent · 真实功能链路测试（v0.2.0）
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
echo "架构师体系 · 真实功能链路测试 (v0.2.0)"
echo "仓库: $REPO"
echo "======================================================"

# cnb CLI 可用性检查：CI 环境可能未安装 cnb，此时跳过真实 API 调用段（F1/F3）
if command -v cnb >/dev/null 2>&1; then
  CNB_AVAILABLE=1
  echo "  ℹ️ cnb CLI 可用，将执行真实 API 调用测试"
else
  CNB_AVAILABLE=0
  echo "  ⚠️ cnb CLI 不可用（rc=127），跳过依赖 API 的 F1/F3 段"
fi

# ------------------------------------------------------------
# F1 数据获取链路 —— 真实调用 cnb issues API
#   验证：能拉到 Issue 列表，且能从正文声明头解析出模块归属
# ------------------------------------------------------------
echo ""
echo "▶ F1 数据获取链路（真实调用 cnb issues API）"

if [ "${CNB_AVAILABLE:-0}" = "1" ]; then

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

# F1.3 / F1.4 拆成两件事，不再混为一谈：
#   F1.3 解析能力（确定性，不受线上 Issue 现状影响）：声明头样本必须解析出模块；
#        无声明头样本必须解析为空。抓的是「解析器把声明头丢了」这类真 bug。
#   F1.4 线上覆盖率（信息项，不判红）：统计当前线上有多少 Issue 带声明头。归零通常意味着
#        open Issue 全是收尾/探针单，是台账真实状态、不是解析链路坏了。此前写成硬断言，
#        每次收尾清零就必然红一条，长期挂在「pre-existing 红」里被当噪音忽略，反而掩盖真信号。
if [ -f scripts/generate-dashboard.py ]; then
  PARSE_OUT="$(python3 - <<'PY'
import types
src = open("scripts/generate-dashboard.py").read()
mod = types.ModuleType("gen")
mod.__file__ = "scripts/generate-dashboard.py"
exec(compile(src, "scripts/generate-dashboard.py", "exec"), mod.__dict__)

d1 = mod.parse_decl("module: hybrid\nmodule_version: v2.0.0\ntype: update\n")
d2 = mod.parse_decl("协助管理这俩issue和5个pr\n")
ok_decl = 1 if (d1.get("module") == "hybrid" and d1.get("module_version") == "v2.0.0") else 0
ok_plain = 1 if not d2.get("module") else 0

issues = mod.fetch_issues() or []
with_decl, mods = 0, set()
for i in issues:
    d = mod.parse_decl(i.get("body", "") or "")
    if d.get("module"):
        with_decl += 1
        mods.add(d["module"])
print("PARSE_DECL=%d PARSE_PLAIN=%d ISSUES=%d WITH_DECL=%d MODULES=%s"
      % (ok_decl, ok_plain, len(issues), with_decl, ",".join(sorted(mods))))
PY
)"
  PARSED="$(echo "$PARSE_OUT" | grep -oE 'PARSE_DECL=[0-9]+' | cut -d= -f2)"
  PLAIN="$(echo "$PARSE_OUT" | grep -oE 'PARSE_PLAIN=[0-9]+' | cut -d= -f2)"
  TOTAL_ISSUES="$(echo "$PARSE_OUT" | grep -oE 'ISSUES=[0-9]+' | cut -d= -f2)"
  WITH_DECL="$(echo "$PARSE_OUT" | grep -oE 'WITH_DECL=[0-9]+' | cut -d= -f2)"
  MODULE_LIST="$(echo "$PARSE_OUT" | grep -oE 'MODULES=.*' | cut -d= -f2-)"

  if [ "${PARSED:-0}" = "1" ] && [ "${PLAIN:-0}" = "1" ]; then
    ok "F1.3 声明头解析器可解析（有声明→出模块，无声明→解析为空）"
  else
    bad "F1.3 声明头解析器异常 (PARSE_DECL=${PARSED:-0} PARSE_PLAIN=${PLAIN:-0} 原始=$PARSE_OUT)"
  fi

  echo "  i  F1.4 线上 Issue 声明头覆盖：${WITH_DECL:-0}/${TOTAL_ISSUES:-0} 条带声明头（模块=${MODULE_LIST:-无}）"
  echo "     —— 归零意味着当前 open Issue 都是无声明头的收尾/探针单，不是解析链路故障"
else
  bad "F1.3 生成器脚本缺失，无法验证数据获取"
fi

fi  # F1 cnb 可用

# ------------------------------------------------------------
# F2 看板呈现链路 —— 真实运行看板生成器
#   验证：能产出 docs/DASHBOARD.md 且内容包含模块版本演进线（人类可真俯瞰）
# ------------------------------------------------------------
echo ""
echo "▶ F2 看板呈现链路（真实运行 generate-dashboard.py）"

# F2 静态检查（不依赖 cnb，检查已提交的 docs/DASHBOARD.md）
for pair in \
  "F2.2 docs/DASHBOARD.md 文件存在|test -f docs/DASHBOARD.md" \
  "F2.3 看板含「模块版本演进看板」标题|grep -q '模块版本演进看板' docs/DASHBOARD.md" \
  "F2.4 看板含「里程碑表」|grep -q '里程碑表' docs/DASHBOARD.md" \
  "F2.5 看板含「Issue 声明汇总表」|grep -q 'Issue 声明汇总表' docs/DASHBOARD.md" \
  "F2.6 看板呈现模块版本演进线|grep -q '模块 \`' docs/DASHBOARD.md" \
  "F2.7 看板含真实 Issue 链接|grep -qE 'issues/[0-9]+' docs/DASHBOARD.md"; do
  name="${pair%%|*}"; cond="${pair#*|}"
  if eval "$cond"; then ok "$name"; else bad "$name"; fi
done

if [ "${CNB_AVAILABLE:-0}" = "1" ]; then

if [ -f scripts/generate-dashboard.py ]; then
  # ★ 写临时文件而非仓库内 docs/DASHBOARD.md：校验「生成器能跑通并产出完整看板」，
  #   但不允许测试改脏工作区（此前直接覆写仓库文件，会让 `git status` 出现假改并掩盖真实 diff）。
  BEFORE="$(cat docs/DASHBOARD.md 2>/dev/null | md5sum | awk '{print $1}')"
  GEN_RC=0
  timeout 120 python3 scripts/generate-dashboard.py --out "$TMPDIR/DASHBOARD.md" > "$TMPDIR/gen.log" 2>&1 || GEN_RC=$?
  if [ $GEN_RC -eq 0 ] && grep -q "ok" "$TMPDIR/gen.log"; then
    ok "F2.1 生成器真实运行成功 (rc=$GEN_RC)"
  else
    bad "F2.1 生成器真实运行成功 (rc=$GEN_RC)"
  fi
  # 结构断言 + 「声明头→看板」链路真实可用性。
  # 不拿「线上此刻是否恰好有带声明头的 Issue」当断言（与 F1.4 同理，那取决于台账现状）：
  # 归零时用一条已知带声明头的样本**自证**渲染链路没断，线上有数据时再用线上数据复核。
  if [ -s "$TMPDIR/DASHBOARD.md" ] && grep -q '模块版本演进看板' "$TMPDIR/DASHBOARD.md"; then
    ok "F2.1b 生成产物含看板结构"
  else
    bad "F2.1b 生成产物缺失看板结构"
  fi
  if [ "${WITH_DECL:-0}" -gt 0 ] 2>/dev/null; then
    if grep -q '模块 `' "$TMPDIR/DASHBOARD.md" && grep -qE 'issues/[0-9]+' "$TMPDIR/DASHBOARD.md"; then
      ok "F2.1c 线上声明头已渲染为模块行+Issue 链接（${WITH_DECL} 条）"
    else
      bad "F2.1c 线上有 ${WITH_DECL} 条声明头，但看板无模块行/Issue 链接"
    fi
  else
    SELF_RC=0
    python3 - <<'PY' > "$TMPDIR/selfcheck.log" 2>&1 || SELF_RC=$?
import types
src = open("scripts/generate-dashboard.py").read()
mod = types.ModuleType("gen")
mod.__file__ = "scripts/generate-dashboard.py"
exec(compile(src, "scripts/generate-dashboard.py", "exec"), mod.__dict__)
fake = [{"number": "1", "state": "open", "title": "自证样本",
         "body": "module: selfcheck-sample\nmodule_version: v0.0.1\ntype: init\n"}]
mod.fetch_issues = lambda: fake
content, _issues, _by_module = mod.render()
ok = ("模块 `selfcheck-sample`" in content) and ("issues/1" in content)
print("SELF_RENDER_OK" if ok else "SELF_RENDER_FAIL")
raise SystemExit(0 if ok else 1)
PY
    if [ $SELF_RC -eq 0 ]; then
      ok "F2.1c 声明头→看板链路自证通过（线上暂无带声明头 Issue，用样本证明渲染链路未断）"
    else
      bad "F2.1c 声明头→看板链路自证失败（见 $TMPDIR/selfcheck.log）"
      cat "$TMPDIR/selfcheck.log" 2>/dev/null | head -5
    fi
  fi
  AFTER="$(cat docs/DASHBOARD.md | md5sum | awk '{print $1}')"
  if [ "$BEFORE" = "$AFTER" ]; then
    ok "F2.8 测试未改动仓库内 DASHBOARD.md"
  else
    bad "F2.8 测试污染了仓库内 DASHBOARD.md"
  fi
else
  bad "F2.1 生成器脚本缺失，无法验证看板呈现"
fi

fi  # F2 cnb 可用

# ------------------------------------------------------------
# F3 RAG 读取链路 —— 真实查询仓库知识库
#   验证：架构上下文文档已入库、能被 RAG 检索命中
# ------------------------------------------------------------
echo ""
echo "▶ F3 RAG 读取链路（真实查询 knowledge-base）"

if [ "${CNB_AVAILABLE:-0}" = "1" ]; then

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

fi  # F3 cnb 可用

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
