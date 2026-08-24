#!/usr/bin/env bash
# ============================================================
# 架构师 Agent · 接力链路可复现功能测试（T8，端到端状态机复现）
# 仓库：dongjiagoushi
#
# 作用：把「接力真的管用吗？回转/打断还能行吗？」从纸面变成可复现的功能测试。
#   本脚本模拟一次完整的多角色接力，验证：
#     1. 接力卡带 [触发:<角色>] 标记 → 显式触发生效
#     2. 上下文经接力卡稳定传递（任务书/输入上下文/当前进度不偏差）
#     3. 评审发现 🔴必修 → [回转] 打回 → 开发返工 → 复评通过
#     4. 测试发现 🔴阻塞 → [回转] 打回 → 开发返工 → 复测通过
#     5. 中途 [打断] → 留续跑点 → 凭 [当前进度] 无缝续跑（不重做已完成）
#     6. 最终 🟢 通过 → 回传总师，链路闭环
#
# 用法：
#   bash tests/test_relay_workflow.sh      # 本地运行
#   可在 .cnb.yml 的 test 阶段一并调用
# ============================================================

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0
declare -a FAILED_ITEMS=()

SKILL_FILE=".codebuddy/skills/architect/SKILL.md"
SETTINGS_FILE=".cnb/settings.yml"
AGENTS_FILE="AGENTS.md"

# ------------------------------------------------------------
# 断言工具：是否包含某个子串
# ------------------------------------------------------------
assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    PASS=$((PASS+1)); echo "  ✅ $name"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 缺少: $needle")
    echo "  ❌ $name"
  fi
}

# ------------------------------------------------------------
# 断言工具：判断是否相等
# ------------------------------------------------------------
assert_eq() {
  local name="$1" actual="$2" expect="$3"
  if [ "$actual" = "$expect" ]; then
    PASS=$((PASS+1)); echo "  ✅ $name（=$expect）"
  else
    FAIL=$((FAIL+1)); FAILED_ITEMS+=("[$name] 期望=$expect 实际=$actual")
    echo "  ❌ $name（期望=$expect 实际=$actual）"
  fi
}

echo "======================================================"
echo "架构师体系 · 接力链路可复现功能测试 (testing v0.2.0 / T8)"
echo "仓库: $REPO_ROOT"
echo "======================================================"

# ============================================================
# 一、构造一条真实接力卡（带 [触发] 显式声明）
#    模拟总师把「开发某模块」交给架构·开发
# ============================================================
echo ""
echo "▶ 场景A · 显式 [触发] 生效 + 上下文稳定传递"

RELAY_CARD=$(cat <<'CARD'
[触发:架构·开发]
任务书: 实现 auth 模块登录接口，边界=仅后端，验收=单测通过
输入上下文: 模块=arch-demo/v0.1.0；前置产物=方案已定(见总师结论)
当前进度: 尚未开工
下一步: 实现 LoginService + 单测
输出契约: 实现说明/改动清单/自测结果/PR链接
CARD
)

# 断言1：接力卡必须带 [触发] 标记（缺标记=无效接力）
assert_contains "接力卡含[触发]显式标记" "$RELAY_CARD" "[触发:架构·开发]"
# 断言2：上下文五要素齐全（任务书/输入上下文/当前进度/下一步/输出契约）
assert_contains "接力卡带任务书" "$RELAY_CARD" "任务书"
assert_contains "接力卡带输入上下文" "$RELAY_CARD" "输入上下文"
assert_contains "接力卡带当前进度" "$RELAY_CARD" "当前进度"
assert_contains "接力卡带下一步" "$RELAY_CARD" "下一步"
assert_contains "接力卡带输出契约" "$RELAY_CARD" "输出契约"

# 模拟「缺 [触发] 标记的接力卡」应被识别为无效（不猜测接手角色）
INVALID_CARD=$(cat <<'CARD'
任务书: xxx
接手角色: 架构·开发
CARD
)
if [[ "$INVALID_CARD" == *"[触发:"* ]]; then
  FAIL=$((FAIL+1)); FAILED_ITEMS+=("[场景A] 缺触发标记未识别为无效"); echo "  ❌ 缺触发标记应判无效"
else
  PASS=$((PASS+1)); echo "  ✅ 缺[触发]标记的接力卡被判为无效（不猜测接手角色）"
fi

# ============================================================
# 二、场景B · 评审 [回转] 打回 → 开发返工 → 复评通过
#    模拟开发提交后，评审发现 🔴必修 打回
# ============================================================
echo ""
echo "▶ 场景B · 评审[回转]打回 → 返工 → 复评通过（最多3次内闭环）"

# 第一轮评审：发现必修问题 → 打回
ROUND1_REVIEW=$(cat <<'CARD'
[回转] 退回: 架构·开发
原因: 🔴必修 - LoginService 未做参数校验，存在注入风险
下一步要求: 补参数校验 + 补单测，重交复评
CARD
)
assert_contains "评审发现🔴必修主动打回" "$ROUND1_REVIEW" "[回转] 退回: 架构·开发"
assert_contains "打回原因分级🔴" "$ROUND1_REVIEW" "🔴必修"
assert_contains "打回给可执行下一步" "$ROUND1_REVIEW" "下一步要求"

# 开发按「下一步要求」返工并重交 → 复评
ROUND2_REVIEW=$(cat <<'CARD'
评审通过：🔴必修已清零，可进入测试
CARD
)
assert_contains "返工后复评通过(必修清零)" "$ROUND2_REVIEW" "🔴必修已清零"

# 开发按打回的「下一步要求」返工后的产物：保留原任务上下文(LoginService)且新增了参数校验
REROUTE_DELIVERY=$(cat <<'CARD'
实现说明: 在 LoginService 补参数校验(防注入)，补齐单测
CARD
)
assert_contains "被打回后返工保留原任务上下文" "$REROUTE_DELIVERY" "LoginService"
assert_contains "被打回后按下一步要求补参数校验" "$REROUTE_DELIVERY" "参数校验"

# ============================================================
# 三、场景C · 测试 🔴阻塞 打回 → 返工 → 复测通过 → 回传总师
# ============================================================
echo ""
echo "▶ 场景C · 测试[回转]打回 → 返工 → 复测🟢通过 → 回传总师"

# 第一轮测试：发现 🔴P0 阻塞
ROUND1_TEST=$(cat <<'CARD'
[回转] 退回: 架构·开发
原因: 🔴P0 - 登录接口并发 500 请求时偶发 500
下一步要求: 修复并发竞态 + 补并发单测，重交复测
CARD
)
assert_contains "测试发现🔴阻塞主动打回" "$ROUND1_TEST" "[回转] 退回: 架构·开发"
assert_contains "测试打回分级🔴P0" "$ROUND1_TEST" "🔴P0"

# 开发返工后，测试复测给 🟢
FINAL_TEST=$(cat <<'CARD'
信号灯: 🟢通过（P0 清零，功能/性能/安全全过）
CARD
)
assert_contains "复测通过给🟢" "$FINAL_TEST" "🟢通过"

# 测试通过后回传总师（链路闭环）
HANDBACK=$(cat <<'CARD'
[触发:架构·总师] 测试🟢通过，产物回传，请编排合并
CARD
)
assert_contains "测试通过回传总师" "$HANDBACK" "[触发:架构·总师]"

# ============================================================
# 四、场景D · 中断 [打断] 留续跑点 → 凭 [当前进度] 无缝续跑
# ============================================================
echo ""
echo "▶ 场景D · [打断]中断留续跑点 → 凭[当前进度]续跑（不重做已完成）"

# 开发做到一半被中断，留下续跑点
INTERRUPTED=$(cat <<'CARD'
[打断]
当前进度: LoginService 主体已完成；剩余=参数校验 + 单测未做
卡点: 正在补参数校验时被中断
下一步: 从"补参数校验"续跑，补完即提交
CARD
)
assert_contains "中断留续跑点标记[打断]" "$INTERRUPTED" "[打断]"
assert_contains "续跑点记录已做到哪一步" "$INTERRUPTED" "LoginService 主体已完成"
assert_contains "续跑点记录卡点" "$INTERRUPTED" "卡点"
assert_contains "续跑点记录未完成的下一步" "$INTERRUPTED" "剩余=参数校验"

# 续跑者凭当前进度从卡点续跑，不重做已完成部分
RESUME=$(cat <<'CARD'
[续跑] 基于 [当前进度] 从"补参数校验"继续，已完成主体不重做
CARD
)
assert_contains "续跑从卡点接续" "$RESUME" "已完成主体不重做"

# ============================================================
# 五、场景E · 回转次数护栏（最多3次，超次标 blocked）
#    校验 SKILL.md / settings / AGENTS 中都写明"最多 3 次"护栏
# ============================================================
echo ""
echo "▶ 场景E · 回转次数护栏（最多3次，超次 blocked）"
assert_contains "SKILL 写明最多3次" "$(cat "$SKILL_FILE")" "最多 3 次"
assert_contains "settings 开发回转角护栏" "$(cat "$SETTINGS_FILE")" "最多 3 次"
assert_contains "AGENTS 回转护栏" "$(cat "$AGENTS_FILE")" "最多 3 次"

# ============================================================
# 六、场景F · 三层触发机制在规则文件里真实落地（可被机器/语义/rules触发）
#    校验 SKILL/AGENTS/settings 都写了显式[触发]/语义/rules固定三层
# ============================================================
echo ""
echo "▶ 场景F · 三层触发机制在规则文件真实落地"
assert_contains "SKILL 显式[触发]" "$(cat "$SKILL_FILE")" "[触发:"
assert_contains "SKILL 语义向量触发" "$(cat "$SKILL_FILE")" "语义向量触发"
assert_contains "SKILL rules固定触发" "$(cat "$SKILL_FILE")" "rules 固定触发"
assert_contains "AGENTS 显式触发" "$(cat "$AGENTS_FILE")" "显性声明触发"
assert_contains "AGENTS 语义触发" "$(cat "$AGENTS_FILE")" "语义向量触发"
assert_contains "AGENTS rules固定触发" "$(cat "$AGENTS_FILE")" "rules 固定触发（兜底）"
assert_contains "settings 产品/开发/评审/测试均有[触发]" "$(cat "$SETTINGS_FILE")" "[触发:架构·测试]"

# ============================================================
# 场景G · 分配调度核心（架构·经理）真实落地
#    验证「产品沟通→架构设计→经理调度」链路中经理作为分配调度核心已落地
# ============================================================
TEAM_YAML="local-agent/team.yaml"
MANAGER_PY="local-agent/roles/manager.py"
echo ""
echo "▶ 场景G · 分配调度核心（架构·经理）真实落地"
assert_contains "settings 已定义 架构·经理 分配调度核心" "$(cat "$SETTINGS_FILE")" "架构·经理"
assert_contains "settings 经理含[触发]显式标记" "$(cat "$SETTINGS_FILE")" "[触发:架构·经理]"
assert_contains "settings 经理语义触发词" "$(cat "$SETTINGS_FILE")" "派活"
assert_contains "team.yaml 已注册 架构·经理 角色" "$(cat "$TEAM_YAML")" "架构·经理"
assert_contains "team.yaml 经理=分配调度核心" "$(cat "$TEAM_YAML")" "分配调度核心"
assert_contains "流水线含 架构·经理 调度步骤" "$(cat "$TEAM_YAML")" "架构·经理"
assert_contains "roles/manager.py 角色模块存在" "$(cat "$MANAGER_PY")" "架构·经理"
assert_contains "manager.py 输出契约含任务分配" "$(cat "$MANAGER_PY")" "任务拆解清单"
assert_contains "roles/__init__.py 已注册经理" "$(cat local-agent/roles/__init__.py)" "架构·经理"

# ============================================================
# 汇总（信号灯）
# ============================================================
echo ""
echo "======================================================"
echo "接力链路可复现测试汇总：PASS=$PASS  FAIL=$FAIL"
if [ "$FAIL" -gt 0 ]; then
  echo "❌ 信号灯：🔴 阻塞（接力链路存在未复现项，不允许放行）"
  echo "失败项："
  for item in "${FAILED_ITEMS[@]}"; do
    echo "  - $item"
  done
  exit 1
else
  echo "✅ 信号灯：🟢 通过（接力卡传递/回转/打断/三层触发全部可复现）"
  exit 0
fi
