#!/usr/bin/env bash
# relay_card 防断链工具信号灯测试
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/local-agent${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

run() { python3 -m relay_card "$@" 2>&1; }
status() { python3 -m relay_card "$@" >/dev/null 2>&1; echo $?; }

echo "== relay_card 信号灯 =="

# 1. gen 生成合规模板
G="$(run gen --to 架构·评审)"
case "$G" in
  *"@dongdongxiaozu/dongjiagoushi(架构·评审)"*"[触发:架构·评审]"*) ok "gen 生成含完整 @org/repo(角色)+[触发] 模板";;
  *) bad "gen 输出不合规: $G";;
esac

# 2. gen 别名归一化
G2="$(run gen --to 评审)"
case "$G2" in
  *"(架构·评审)"*"[触发:架构·评审]"*) ok "gen 别名『评审』归一化为『架构·评审』";;
  *) bad "gen 别名未归一化: $G2";;
esac

# 3. check 合规文本 → 通过
C="$(run check --role 架构·评审 "@dongdongxiaozu/dongjiagoushi(架构·评审) [触发:架构·评审]")"
case "$C" in *RELAY_VALID*) ok "check 合规文本通过";; *) bad "check 合规文本误判: $C";; esac

# 4. check 缺 [触发] 标记 → 拦截
R4="$(status check --role 架构·评审 "@dongdongxiaozu/dongjiagoushi(架构·评审)")"
if [ "$R4" = "1" ]; then ok "check 缺 [触发] 标记被拦截"; else bad "缺 [触发] 未拦截(code=$R4)"; fi

# 5. check 用 @CodeBuddy 缺完整 @ → 拦截
R5="$(status check --role 架构·评审 "@CodeBuddy 开始评审")"
if [ "$R5" = "1" ]; then ok "check @CodeBuddy 缺完整 @org/repo 被拦截"; else bad "@CodeBuddy 断链未拦截(code=$R5)"; fi

# 6. check --required 缺标记 exit 1
R6="$(status check --required --role 架构·开发 "@CodeBuddy 开发完成")"
if [ "$R6" = "1" ]; then ok "check --required 缺标记 exit 1"; else bad "--required 未强制拦截(code=$R6)"; fi

# 7. check 目标角色未命中 → 拦截
R7="$(status check --role 架构·测试 "@dongdongxiaozu/dongjiagoushi(架构·评审) [触发:架构·评审]")"
if [ "$R7" = "1" ]; then ok "check 目标角色(@测试)未命中评审 被拦截"; else bad "目标角色未命中未拦截(code=$R7)"; fi

# 8. 空文本 → 拦截
R8="$(status check "")"
if [ "$R8" = "1" ]; then ok "check 空文本被拦截"; else bad "空文本未拦截(code=$R8)"; fi

# 9. 漏写 @ 的角色提及（Issue #169 真实故障）→ 必须拦截
#    用户实际写法 dongdongxiaozu/dongjiagoushi(架构·评审) 少了 @，平台不识别为 NPC 提及
R9="$(status check --role 架构·评审 "dongdongxiaozu/dongjiagoushi(架构·评审) [触发:架构·评审] 这里唤醒会出错")"
if [ "$R9" = "1" ]; then ok "check 漏写 @ 的角色提及被拦截（Issue #169）"; else bad "漏写 @ 未拦截(code=$R9)"; fi

# 10. 漏写 @ + @CodeBuddy 兜底（Issue #169 原文形态）→ 必须拦截
R10="$(status check --role 架构·评审 "dongdongxiaozu/dongjiagoushi(架构·评审) 这里唤醒会出错，是哪里出bug了吗 @CodeBuddy")"
if [ "$R10" = "1" ]; then ok "check 原文形态(漏@ + @CodeBuddy) 被拦截"; else bad "原文形态未拦截(code=$R10)"; fi

# 11. AGENTS.md 已固化 @ 召唤硬约束（防再犯）
if grep -q '[@] 召唤必须带' AGENTS.md && grep -q '漏写 `@`' AGENTS.md; then
  ok "AGENTS.md 固化 @ 召唤必须带 @ 规则"
else
  bad "AGENTS.md 缺少 @ 召唤硬约束"
fi

echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
