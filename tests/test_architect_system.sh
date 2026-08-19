#!/usr/bin/env bash
# ============================================================
# 架构师 Agent · 体系可核验产物完整性测试（testing 模块 v0.1.0）
# 仓库：dongjiagoushi
#
# 作用：把「没达成效果不能让通过」变成机器强制的信号灯。
#   本脚本对仓库内的架构师体系做静态断言，验证五项关键链路是否就绪。
#   任一断言失败即以非零码退出 → .cnb.yml 的 test 阶段 fail → 流水线红灯。
#
# 覆盖五类测试（对应 ISSUE #8 建议）：
#   T1 skill 触发链路      —— architect skill 可被 @ 触发并走八步（注入生效）
#   T2 八步产物完整性断言  —— 每个步骤都有可核验产物，缺一步即 fail
#   T3 CP 暂停点护栏       —— CP1/CP2/CP3 是否真的停等人确认
#   T4 流水线知识库入库    —— .cnb.yml 是否真的配了 knowledge:update 且可检索
#   T5 多角色接力          —— 接力卡上下文传递机制是否就绪
#
# 用法：
#   bash tests/test_architect_system.sh            # 本地运行
#   .cnb.yml 的 test 阶段调用：bash tests/test_architect_system.sh
# ============================================================

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

SKILL_FILE=".codebuddy/skills/architect/SKILL.md"
SETTINGS_FILE=".cnb/settings.yml"
PIPELINE_FILE=".cnb.yml"
AGENTS_FILE="AGENTS.md"
REPORT_TEMPLATE="docs/templates/architect-report.md"
ISSUE_TEMPLATE="docs/templates/issue-template.md"

# ------------------------------------------------------------
# 断言工具
# ------------------------------------------------------------
assert_contains() {
  # $1=测试名  $2=文件  $3=期望包含的文本
  local name="$1" file="$2" needle="$3"
  if [ ! -f "$file" ]; then
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 文件缺失: $file"); return
  fi
  if grep -qF -- "$needle" "$file"; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] $file 中缺少: $needle")
    echo "  ❌ $name"
  fi
}

echo "======================================================"
echo "架构师体系可核验产物完整性测试 (testing v0.1.0)"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# ------------------------------------------------------------
# T1 skill 触发链路
#   @CodeBuddy 提到 architect skill → 自动加载并走架构八步
# ------------------------------------------------------------
echo ""
echo "▶ T1 skill 触发链路"
assert_contains "T1 skill文件存在" "$SKILL_FILE" "name: architect"
assert_contains "T1 触发描述(描述含architect)" "$SKILL_FILE" "description:"
assert_contains "T1 化身架构师声明" "$SKILL_FILE" "架构师"
assert_contains "T1 零积分声明" "$SKILL_FILE" "零积分"
assert_contains "T1 铁律-完整不残次" "$SKILL_FILE" "完整不残次"
assert_contains "T1 铁律-诚实留痕" "$SKILL_FILE" "留痕"
assert_contains "T1 铁律-禁止假装执行" "$SKILL_FILE" "禁止假装执行"
assert_contains "T1 一库多角色(settings)" "$SETTINGS_FILE" "架构·总师"
assert_contains "T1 官方CodeBuddy化身" "$SETTINGS_FILE" "官方"
# 校验 skill 声明了触发词（架构八步/架构师/architect）
assert_contains "T1 触发词-架构八步" "$SKILL_FILE" "架构八步"

# ------------------------------------------------------------
# T2 八步产物完整性断言
#   架构八步：调研/拓扑/可行性/工程方案/分工协作/进度对齐/索引/汇报复盘
# ------------------------------------------------------------
echo ""
echo "▶ T2 八步产物完整性断言（缺一步即 fail）"
assert_contains "T2 步骤1-调研" "$SKILL_FILE" "调研"
assert_contains "T2 步骤2-顶层架构拓扑" "$SKILL_FILE" "拓扑"
assert_contains "T2 步骤3-可行性验证" "$SKILL_FILE" "可行性"
assert_contains "T2 步骤4-工程实施方案" "$SKILL_FILE" "工程实施"
assert_contains "T2 步骤5-分工与协作规则" "$SKILL_FILE" "分工"
assert_contains "T2 步骤6-进度对齐" "$SKILL_FILE" "进度对齐"
assert_contains "T2 步骤7-索引建立" "$SKILL_FILE" "索引"
assert_contains "T2 步骤8-汇报与复盘" "$SKILL_FILE" "复盘"
# 八步产物模板存在且完整
assert_contains "T2 八步产物模板存在" "$REPORT_TEMPLATE" "调研报告"
assert_contains "T2 模板-拓扑" "$REPORT_TEMPLATE" "拓扑"
assert_contains "T2 模板-可行性矩阵" "$REPORT_TEMPLATE" "可行性矩阵"
assert_contains "T2 模板-工程实施方案" "$REPORT_TEMPLATE" "工程实施方案"
assert_contains "T2 模板-协作表" "$REPORT_TEMPLATE" "分工与协作规则"
assert_contains "T2 模板-里程碑" "$REPORT_TEMPLATE" "里程碑"
assert_contains "T2 模板-索引" "$REPORT_TEMPLATE" "索引"
assert_contains "T2 模板-汇报与复盘" "$REPORT_TEMPLATE" "汇报与复盘"
# 架构八步在 README / ROADMAP 中可核验
assert_contains "T2 ROADMAP记录里程碑" "docs/ROADMAP.md" "里程碑"

# ------------------------------------------------------------
# T3 CP 暂停点护栏测试
#   CP1/CP2/CP3 停等人确认；未确认不得放行；禁止代替确认
# ------------------------------------------------------------
echo ""
echo "▶ T3 CP 暂停点护栏测试"
assert_contains "T3 CP1 存在" "$SKILL_FILE" "CP1"
assert_contains "T3 CP2 存在" "$SKILL_FILE" "CP2"
assert_contains "T3 CP3 存在" "$SKILL_FILE" "CP3"
assert_contains "T3 禁止代替确认" "$SKILL_FILE" "禁止代替用户确认"
assert_contains "T3 AGENTS护栏表" "$AGENTS_FILE" "CP1"
assert_contains "T3 AGENTS-暂停点" "$AGENTS_FILE" "暂停点"
assert_contains "T3 AGENTS-禁止代替确认" "$AGENTS_FILE" "禁止代替用户确认"
assert_contains "T3 AGENTS-敏感信息红线" "$AGENTS_FILE" "Token"

# ------------------------------------------------------------
# T4 流水线知识库入库测试
#   .cnb.yml 配了 knowledge:update，入库触发 + embedding 模型 + 可检索
# ------------------------------------------------------------
echo ""
echo "▶ T4 流水线知识库入库测试"
assert_contains "T4 knowledge:update 配置" "$PIPELINE_FILE" "knowledge:update"
assert_contains "T4 入库触发(main push)" "$PIPELINE_FILE" "push"
assert_contains "T4 embedding模型" "$PIPELINE_FILE" "embeddingModel"
assert_contains "T4 include md文档" "$PIPELINE_FILE" "include"
assert_contains "T4 索引入口文档" "docs/KNOWLEDGE.md" "知识库"
assert_contains "T4 入库机制说明" "docs/KNOWLEDGE.md" "knowledge:update"

# ------------------------------------------------------------
# T5 多角色接力测试
#   接力卡上下文传递：settings 多角色 + 接力机制文档
# ------------------------------------------------------------
echo ""
echo "▶ T5 多角色接力测试"
assert_contains "T5 协作角色-架构·产品" "$SETTINGS_FILE" "架构·产品"
assert_contains "T5 协作角色-架构·开发" "$SETTINGS_FILE" "架构·开发"
assert_contains "T5 协作角色-架构·评审" "$SETTINGS_FILE" "架构·评审"
assert_contains "T5 协作角色-架构·测试" "$SETTINGS_FILE" "架构·测试"
assert_contains "T5 接力卡机制文档" "docs/ISSUE_MANAGEMENT.md" "接力卡"
assert_contains "T5 接力卡字段-任务书" "docs/ISSUE_MANAGEMENT.md" "任务书"
assert_contains "T5 接力卡字段-接手角色" "docs/ISSUE_MANAGEMENT.md" "接手角色"
assert_contains "T5 上下文传递(输入上下文)" "docs/ISSUE_MANAGEMENT.md" "输入上下文"

# ------------------------------------------------------------
# T6 触发强制化测试
#   协作角色不是纸面说明，而是三层触发机制硬约束：
#   显式[触发] / 语义触发 / rules固定触发；缺触发标记视为无效接力
# ------------------------------------------------------------
echo ""
echo "▶ T6 触发强制化测试（显式[触发]/语义/rules固定，非纸面说明）"
assert_contains "T6 显式触发标记[触发]" "$SKILL_FILE" "[触发:"
assert_contains "T6 缺触发标记=无效接力" "$SKILL_FILE" "无效接力"
assert_contains "T6 语义向量触发" "$SKILL_FILE" "语义向量触发"
assert_contains "T6 语义命中切角色" "$SKILL_FILE" "语义信号"
assert_contains "T6 rules固定触发" "$SKILL_FILE" "rules 固定触发"
assert_contains "T6 触发写在铁律" "$SKILL_FILE" "触发强制化"
assert_contains "T6 AGENTS rules固定触发" "$AGENTS_FILE" "触发强制化"
assert_contains "T6 AGENTS 显性触发优先" "$AGENTS_FILE" "显性声明触发（最高优先）"
assert_contains "T6 AGENTS 语义向量触发" "$AGENTS_FILE" "语义向量触发"
assert_contains "T6 AGENTS rules兜底" "$AGENTS_FILE" "rules 固定触发（兜底）"
assert_contains "T6 settings 产品触发" "$SETTINGS_FILE" "[触发:架构·产品]"
assert_contains "T6 settings 开发触发" "$SETTINGS_FILE" "[触发:架构·开发]"
assert_contains "T6 settings 评审触发" "$SETTINGS_FILE" "[触发:架构·评审]"
assert_contains "T6 settings 测试触发" "$SETTINGS_FILE" "[触发:架构·测试]"

# ------------------------------------------------------------
# T7 回转（打回）/打断（中断续跑）协议测试
#   接力不是单向直线，必须能打回重做、中断续跑
# ------------------------------------------------------------
echo ""
echo "▶ T7 回转/打断协议测试（打回重做 + 中断续跑）"
assert_contains "T7 回转协议" "$SKILL_FILE" "[回转]"
assert_contains "T7 回转打回主动" "$SKILL_FILE" "主动打回"
assert_contains "T7 回转退回到角色" "$SKILL_FILE" "退回:"
assert_contains "T7 回转最多3次" "$SKILL_FILE" "最多 3 次"
assert_contains "T7 打断协议" "$SKILL_FILE" "[打断]"
assert_contains "T7 续跑点" "$SKILL_FILE" "续跑点"
assert_contains "T7 不重做已完成" "$SKILL_FILE" "不重做已完成部分"
assert_contains "T7 状态机供复现" "$SKILL_FILE" "状态机"
assert_contains "T7 AGENTS 回转" "$AGENTS_FILE" "[回转]"
assert_contains "T7 AGENTS 打断" "$AGENTS_FILE" "[打断]"
assert_contains "T7 settings 评审打回" "$SETTINGS_FILE" "[回转] 退回:架构·开发"
assert_contains "T7 settings 测试打回" "$SETTINGS_FILE" "🔴阻塞 必须打回"

# ------------------------------------------------------------
# 汇总（信号灯）
# ------------------------------------------------------------
echo ""
echo "======================================================"
echo "测试汇总：PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "❌ 信号灯：🔴 阻塞（存在未达成的核验项，不允许放行）"
  echo "失败项："
  for item in "${FAILED_ITEMS[@]}"; do
    echo "  - $item"
  done
  exit 1
else
  echo "✅ 信号灯：🟢 通过（五项关键链路核验全部达成）"
  exit 0
fi
