#!/usr/bin/env bash
# ============================================================
# npc-model.sh · NPC 模型选择 CLI（module npc-model v0.1.0）
# 唯一事实源：.cnb/npc-models.yml
# ------------------------------------------------------------
# 用法（流水线里只用 resolve）：
#   bash scripts/npc-model.sh resolve          # 解析 → 导出 NPC_MODEL / NPC_USE_DEFAULT
#   bash scripts/npc-model.sh resolve --json   # 机器可读
#   bash scripts/npc-model.sh info             # 人可读策略快照（含当前会选谁）
#   bash scripts/npc-model.sh learn --log-file f  # 从 npc:go 失败日志认出被拒模型
#
# 为什么不在 .cnb.yml 里直接写 model：
#   model 必须是「当前组织可选模型列表」里的 ID，列表会漂移。写死任意 ID 都有
#   再次静默失效的风险，且故障只出现在 stage 层，表现为「评论 @角色 → 3 秒挂」。
# 本脚本的做法：大参数优先 → 兜底不写 model（平台默认）→ 换模型只改 yml。
# ============================================================
set -eu

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/local-agent:${PYTHONPATH:-}"

CMD="${1:-info}"; shift || true

case "$CMD" in
  resolve|info|learn)
    python3 - "$CMD" "$ROOT" "$@" <<'PY'
import json
import os
import sys

sys.path.insert(0, os.path.join(sys.argv[2], "local-agent"))
from npc_model import ModelSpec, select_model, resolve, learn_from_error  # noqa: E402

cmd = sys.argv[1]
root = sys.argv[2]
args = sys.argv[3:]

config_path = os.path.join(root, ".cnb", "npc-models.yml")
if "--config" in args:
    config_path = args[args.index("--config") + 1]

if cmd == "resolve":
    result = resolve(config_path=config_path)
    want_json = "--json" in args
    if want_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        # 人可读日志（进 CI 日志，便于事后复盘「这次为什么用这个模型」）
        print("[npc-model] 策略源: .cnb/npc-models.yml")
        print("[npc-model] 选择来源: %s" % result["source"])
        print("[npc-model] 原因: %s" % result["reason"])
        if result["use_platform_default"]:
            print("[npc-model] 结果: 不写 model，走平台默认模型（兜底路径）")
        else:
            print("[npc-model] 结果: model=%s" % result["model"])
    # set-output 导出给后续 stage（空模型用 NPC_USE_DEFAULT=1 表达，绝不写 model: ''）
    model = result["model"] or ""
    print("##[set-output npc_model=%s]" % model)
    print("##[set-output npc_use_default=%s]" % ("1" if result["use_platform_default"] else "0"))

elif cmd == "info":
    spec = ModelSpec.load(config_path)
    policy = select_model(spec)
    print("[npc-model] 配置: %s" % config_path)
    print("[npc-model] prefer(大参数优先): %s" % " -> ".join(spec.prefer))
    print("[npc-model] 可用候选: %s" % (", ".join(spec.usable) or "（无）"))
    print("[npc-model] 黑名单缓存: %s" % (", ".join(spec.unavailable) or "（空）"))
    print("[npc-model] 兜底: %s（= 不写 model，走平台默认模型）" % spec.fallback)
    print("[npc-model] 覆盖键: %s" % spec.override_env)
    print("[npc-model] 当前会选: %s ← %s" % (
        policy.model or "平台默认模型", policy.reason))
    if spec.history:
        print("[npc-model] 变更留痕:")
        for h in spec.history:
            print("  - %s" % h)

elif cmd == "learn":
    text = ""
    if "--log-file" in args:
        with open(args[args.index("--log-file") + 1], "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    if "--log-text" in args:
        text = args[args.index("--log-text") + 1]
    hit = learn_from_error(text, ModelSpec.load(config_path))
    if not hit:
        print("[npc-model] 日志里没有认出「模型不在可选列表」的报错")
        print("[npc-model] 若本次失败是别的原因，按实际报错处理；不是模型问题时无需改配置")
    else:
        print("[npc-model] 被拒模型: %s（已在黑名单: %s）" % (hit["model"], hit["known"]))
        print("[npc-model] 建议: %s" % hit["hint"])
PY
    ;;
  *)
    echo "用法: bash scripts/npc-model.sh {resolve|info|learn} [--json|--config PATH|--log-file PATH]" >&2
    exit 2
    ;;
esac
