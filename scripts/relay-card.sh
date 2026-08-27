#!/usr/bin/env bash
# 接力卡触发校验（防断链工具）CLI 封装
# 用法:
#   bash scripts/relay-card.sh check "<交付文本>" [--role 架构·评审]
#   bash scripts/relay-card.sh check --file payload.txt --role 架构·评审 --required
#   bash scripts/relay-card.sh gen --to 架构·评审
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/local-agent${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m relay_card "$@"
