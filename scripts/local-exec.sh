#!/usr/bin/env bash
# ============================================================
# 本地执行入口（scripts/local-exec.sh）
# ============================================================
# Issue #57「云原生构建-CPU 本地化开发」：
#   云端 CI 只保留 LLM 强相关操作，37 个 CPU 密集测试脚本本地执行。
#   本脚本是本地的统一入口：route 判定 → run 批量执行 → sync 同步留痕 → cost 报表。
#
# 用法：
#   bash scripts/local-exec.sh                # 完整链路（dry-run 演练）
#   bash scripts/local-exec.sh --real         # 真实执行（不演练，真跑测试）
#   bash scripts/local-exec.sh --only cost    # 只看成本报表
#   bash scripts/local-exec.sh --help
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"                # 保持在仓库根：worker 用相对路径 local-agent/tests/... 解析
if [ -n "${PYTHONPATH:-}" ]; then export PYTHONPATH="$ROOT/local-agent:$PYTHONPATH"; else export PYTHONPATH="$ROOT/local-agent"; fi   # hybrid 包在 local-agent 下

MODE=dry        # 默认演练（不真跑，避免 CI/本地误执行耗时测试）
ONLY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --real) MODE=real ;;
    --only) ONLY="$2"; shift ;;
    --help|-h)
      echo "用法: bash scripts/local-exec.sh [--real] [--only cost]"
      exit 0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done

# 演练标志：传给 cli
DRY_FLAG=""
[ "$MODE" = "real" ] || DRY_FLAG="--dry"

echo "==== 云原生构建-CPU 本地化 · 本地执行入口 ===="
echo "模式: $MODE | 工作根: $ROOT"

if [ "$ONLY" = "cost" ]; then
  echo "== 成本报表 =="
  python3 -m hybrid.cli cost
  exit 0
fi

echo "== 完整链路：route → run → sync → cost =="
python3 -m hybrid.cli all $DRY_FLAG --timeout 600

# -- batch 集成：本地测试跑完后，自动检查云端攒批队列 ----------
# 攒够 min_tasks 即 flush（一次唤醒云端处理多个任务，防频繁唤醒）；
# 未攒够则提示攒批进度，继续本地零成本积攒。
echo ""
echo "== 云端批量打包检查（CloudBatch） =="
python3 <<'PY'
import sys, os
sys.path.insert(0, os.environ.get("PYTHONPATH", os.path.join(os.getcwd(), "local-agent")))
try:
    from hybrid.batch import CloudBatch
    b = CloudBatch()
    st = b.status()
    if st["queued"] == 0:
        print("  攒批队列为空（无待提交云端任务）")
    elif st["ready"] or st["time_window_ready"]:
        r = b.flush(dry_run=False)
        # reuse/duplicate ≠ 提交成功：本批可能一条新任务都没提交（或保留队列待重试），
        # 一律按真实字段说话，不把"拿到一个编号"当成"提交成功"。
        if r.get("error"):
            print("  ⚠️ flush 未提交（队列保留 %s 条）：%s"
                  % (r.get("queued", "?"), r.get("error")))
        elif r.get("duplicate"):
            print("  ↺ 本批与云端既有 Issue #%s 内容一致（幂等命中，未重复提交）"
                  % r.get("number"))
        elif r.get("number") and r.get("submitted") is not None:
            print("  ✅ 攒批就绪 → 已提交 %s 条任务到云端 Issue #%s（一次唤醒）"
                  % (r.get("submitted"), r["number"]))
            print("     %s" % r.get("url", ""))
        elif r.get("number"):
            print("  ⚠️ flush 返回 Issue #%s 但未确认提交条数，请人工核对" % r["number"])
        else:
            print("  ⚠️ flush 失败: %s" % r.get("error", "未知"))
    else:
        print("  攒批进行中: %d/%d 个任务（本地零成本），继续攒批…" % (st["queued"], st["min_tasks"]))
except Exception as e:
    print("  batch 检查跳过（%s）" % e)
PY

# -- 配额护栏记账：本地化节省自动抵扣云端账本 ----------
echo ""
echo "== 云端核时配额护栏（QuotaGuard） =="
python3 -m hybrid.cli quota credit --amount 696 --note "local-exec 本地化抵扣(37测试)" 2>/dev/null || echo "  quota 不可用（跳过）"
python3 -m hybrid.cli quota status 2>/dev/null | head -8 || true

# -- 公交车式攒批调度：到点且队列非空才整批发车（Issue #90 收尾） ----------
echo ""
echo "== 公交车式批量测试调度（BusRunner·15min一班） =="
python3 -m hybrid.cli bus tick --real 2>/dev/null || echo "  bus 不可用（跳过）"
python3 -m hybrid.cli bus status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('  队列 %d 个待跑 / 下一班车 %d s 后' % (d['queued'], d['due_in_seconds']))" 2>/dev/null || true

echo ""
echo "==== 本地执行完成 ===="
echo "提示：云端 .cnb.yml 已移除这些 CPU 密集命令，结果已由 sync 同步留痕。"
echo "云端攒批：python3 -m hybrid.cli batch enqueue/status/flush"
