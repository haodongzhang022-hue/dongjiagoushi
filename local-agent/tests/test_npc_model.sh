#!/usr/bin/env bash
# ============================================================
# npc-model 模型策略 信号灯（module npc-model v0.1.0）
# 验证用户诉求："不写死模型 / 只有架构师吃大参数 / 其余走默认 / 兜底保证一直能通 /
#               模型有更新能换"
#   1. 首选大参数（prefer 顺序优先，黑名单命中即顺延）+ ★角色闸门分层
#   2. 真实配置 .cnb/npc-models.yml 可解析且选出的模型可用
#   3. 兜底 = platform_default（不写 model），绝不产出 model: ''
#   4. 环境变量覆盖最高优先（临时换模型不改仓库）
#   5. 非法配置确定性失败（fallback 不许写成具体模型 ID）
#   6. 失败日志闭环学习：认出被拒模型 + 给出「该改哪一行」
#   7. CLI 输出可被流水线消费（set-output 格式）
#   8. 流水线接线：走解析结果 + failStages 兜底，且不再写死模型 ID
#   9. 文档与能力索引接线
# 用法：bash local-agent/tests/test_npc_model.sh
# ============================================================
set -e
cd "$(dirname "$0")/../.."
PY=python3
CASES="$PY local-agent/tests/npc_model_cases.py"

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/npcm_out.txt 2>&1; then
  echo "  OK $d"; pass=$((pass+1))
else
  echo "  XX $d"; sed -n '1,12p' /tmp/npcm_out.txt; fail=$((fail+1))
fi }

echo "===== [npc-model] 1. 首选大参数（prefer 顺序优先） ====="
t "黑名单命中即顺延到下一个大参数候选" "$CASES prefer_order"
t "真实配置可解析且选出的模型不在黑名单" "$CASES real_config"

echo "===== [npc-model] 1'. 角色闸门（只有架构师吃大模型） ====="
t "架构·总师→大参数 / 其余角色→默认档（含未识别角色）" "$CASES role_gate"
t "真实配置：大模型角色仅架构·总师、默认档=deepseek-v4.1-flash" "$CASES role_config"

echo "===== [npc-model] 2. 兜底 = 平台默认（不写 model） ====="
t "候选全不可用 → platform_default 且 npc_options 为空" "$CASES fallback_platform_default"

echo "===== [npc-model] 3. 环境变量覆盖（不改仓库换模型） ====="
t "NPC_MODEL_OVERRIDE 优先于 prefer，且黑名单覆盖带风险提示" "$CASES override"

echo "===== [npc-model] 4. 非法配置确定性失败 ====="
t "fallback 写成模型 ID / 空串 → 报错" "$CASES reject_bad_fallback"
t "prefer 为空 → 报错" "$CASES reject_empty_prefer"

echo "===== [npc-model] 5. 失败日志闭环学习 ====="
t "从 npc:go 报错（中英文）认出被拒模型 + 整改建议" "$CASES learn"

echo "===== [npc-model] 6. CLI 输出可被流水线消费 ====="
t "resolve 导出 NPC_MODEL / NPC_USE_DEFAULT（架构师身份）" "
out=\$(bash scripts/npc-model.sh resolve --role '架构·总师')
echo \"\$out\" | grep -q '##\\[set-output npc_model='
echo \"\$out\" | grep -q '##\\[set-output npc_use_default=0\\]'
echo \"\$out\" | grep -q '选择来源: prefer'
"
t "resolve 读平台注入的 CNB_NPC_NAME（真实 @角色 触发路径）" "
out=\$(CNB_NPC_NAME='架构·总师' bash scripts/npc-model.sh resolve)
echo \"\$out\" | grep -q '##\\[set-output npc_model=hy4\\]'
out2=\$(CNB_NPC_NAME='架构·评审' bash scripts/npc-model.sh resolve)
echo \"\$out2\" | grep -q '##\\[set-output npc_model=deepseek-v4.1-flash\\]'
"
t "--role 让非架构师也能临时走大参数（人工试跑）" "
out=\$(bash scripts/npc-model.sh resolve --role '架构·总师')
echo \"\$out\" | grep -q '##\[set-output npc_model=hy4\]'
echo \"\$out\" | grep -q '选择来源: prefer'
"
t "非架构师角色经 CLI 走默认档" "
out=\$(bash scripts/npc-model.sh resolve --role '架构·开发')
echo \"\$out\" | grep -q '##\[set-output npc_model=deepseek-v4.1-flash\]'
echo \"\$out\" | grep -q '选择来源: role_default'
"
t "override 经 CLI 生效（不出现平台默认）" "
out=\$(NPC_MODEL_OVERRIDE=hy4 bash scripts/npc-model.sh resolve)
echo \"\$out\" | grep -q '##\\[set-output npc_model=hy4\\]'
echo \"\$out\" | grep -q '选择来源: override'
"
t "info 打印策略快照（prefer/黑名单/兜底/当前选谁）" "
out=\$(bash scripts/npc-model.sh info)
echo \"\$out\" | grep -q 'prefer(大参数优先)'
echo \"\$out\" | grep -q '黑名单缓存'
echo \"\$out\" | grep -q '兜底: platform_default'
echo \"\$out\" | grep -q '当前会选:'
"

echo "===== [npc-model] 7. 流水线接线（.cnb.yml） ====="
t ".cnb.yml 走解析结果 + 角色闸门 + failStages 兜底 + 无写死模型" "$CASES pipeline_wiring"

echo "===== [npc-model] 8. 文档与索引接线 ====="
t "docs/NPC_MODEL.md 存在且写清兜底策略" "grep -q 'platform_default' docs/NPC_MODEL.md"
t "CAPABILITY_INDEX 收录 npc-model" "grep -q 'npc-model' docs/CAPABILITY_INDEX.md"

echo ""
echo "===== [npc-model] 结果：$pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ] || exit 1
