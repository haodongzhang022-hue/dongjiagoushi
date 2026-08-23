#!/usr/bin/env bash
# 本地 Agent · 可复现测试（信号灯）
# 验证：CLI 入口 / 单角色触发 / 团队流水线编排 / 接力卡 / 回转 / 打断续跑 / 角色清单
set -e
cd "$(dirname "$0")/.."

RUN="python3 run.py"
pass=0; fail=0

t() { # t <desc> <cmd>
  local desc="$1"; shift
  if eval "$*" >/tmp/la_out.txt 2>&1; then
    echo "  ✅ $desc"; pass=$((pass+1))
  else
    echo "  ❌ $desc"; cat /tmp/la_out.txt; fail=$((fail+1))
  fi
}

echo "==== 本地 Agent 测试（信号灯）===="

t "列表角色" "$RUN --list-roles"
t "清空接力卡" "$RUN --clear"

t "单角色触发：架构·总师" "$RUN --role 架构·总师 --req '对XX做架构设计' --backend cli_fallback"
t "单角色触发：架构·产品" "$RUN --role 架构·产品 --req '我要做一个系统' --backend cli_fallback"
t "单角色触发：架构·经理" "$RUN --role 架构·经理 --req '把架构方案拆解分配调度给各执行角色' --backend cli_fallback"
t "单角色触发：架构·测试" "$RUN --role 架构·测试 --req '验收交付' --backend cli_fallback"

# 完整团队流水线（占位模式，验证骨架编排可跑通）
t "团队流水线 full（占位）" "$RUN --pipeline full --req '做一个订单系统' --backend cli_fallback"

# 接力卡已生成
if [ -f state/relay_card.json ]; then
  echo "  ✅ 接力卡已持久化"; pass=$((pass+1))
else
  echo "  ❌ 接力卡未生成"; fail=$((fail+1))
fi

# 续跑
t "从接力卡续跑 --resume" "$RUN --resume --backend cli_fallback"

# 校验角色注册表完整性（9 个角色：新增 架构·经理 分配调度核心）
count=$(python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; print(len(list_roles()))")
if [ "$count" = "9" ]; then
  echo "  ✅ 角色注册表 9 个角色齐全（含 架构·经理 分配调度核心）"; pass=$((pass+1))
else
  echo "  ❌ 角色数量异常: $count"; fail=$((fail+1))
fi

# 校验 架构·经理 已注册且承担分配调度核心
grep -q '架构·经理' <(python3 -c "import sys; sys.path.insert(0,'local-agent'); from roles import list_roles; print(list_roles())")
if [ $? = 0 ]; then
  echo "  ✅ 分配调度核心 架构·经理 已注册"; pass=$((pass+1))
else
  echo "  ❌ 架构·经理 未注册"; fail=$((fail+1))
fi

echo ""
echo "结果：$pass 通过 / $fail 失败"
[ "$fail" = "0" ] || exit 1
