#!/usr/bin/env bash
# ============================================================
# Hybrid 管线测试（test_hybrid_pipeline）
# ============================================================
# 验证 Issue #57「云原生构建-CPU 本地化」完整链路：
#   1. LocalWorker 本地批量执行（dry-run + 真实）
#   2. ResultSync 结果同步留痕（数据层 archives/messages）
#   3. CostMonitor 成本报表（net_save/ratio）
#   4. CLI 入口（classify/route/run/sync/cost/all）
#   5. scripts/local-exec.sh 本地执行入口
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }
check(){ if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi; }

echo "== Hybrid 管线：worker → sync → cost → cli → local-exec =="

# 1. LocalWorker dry-run（不真跑）
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.worker import LocalWorker;w=LocalWorker(root_dir='$ROOT',dry_run=True);print(w.run(['test_unit.sh','test_bench.sh'])['summary'])")
echo "  dry-run: $R"
if echo "$R" | grep -q "'fail': 0"; then ok "LocalWorker dry-run 全部通过"; else bad "dry-run 失败: $R"; fi

# 2. LocalWorker 真实执行一个轻量脚本（验证子进程执行）
cat > /tmp/_hybrid_sample.sh << 'S'
#!/usr/bin/env bash
echo "hybrid sample ok"
S
chmod +x /tmp/_hybrid_sample.sh
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');from hybrid.worker import LocalWorker;w=LocalWorker(root_dir='/tmp');print(w.run_one('/tmp/_hybrid_sample.sh'))")
if echo "$R" | grep -q "'exit_code': 0"; then ok "LocalWorker 真实执行脚本通过"; else bad "真实执行失败: $R"; fi

# 3. ResultSync 同步留痕到数据层
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT')
from hybrid.sync import ResultSync
s=ResultSync()
out=s.sync({'results':[{'script':'test_unit.sh','exit_code':0,'duration':1.2}],'summary':{'total':1,'pass':1,'fail':0}},'test-batch')
print(str(out['synced'])+'|'+out['target']+'|'+str(out['fallback']))
")
check "ResultSync 同步到数据层" "$R" "True|data_layer|False"

# 4. CostMonitor 成本报表
R=$(python3 -c "
import sys;sys.path.insert(0,'$ROOT')
from hybrid.router import HybridResourceRouter
from hybrid.cost import CostMonitor
r=HybridResourceRouter()
tasks=[('test_unit_cpu.sh',5,20),('test_scale.sh',10,30),('llm_knowledge_update',5,15)]
res=r.route_many(tasks)
rep=CostMonitor().report(res)
print(str(rep['localized_cpu'])+'|'+str(rep['cloud_remain'])+'|'+str(rep['net_save']))
")
check "CostMonitor 报表（localized=50 cloud_remain=15）" "$R" "50.0|15.0|50.0"

# 5. CLI classify
R=$(cd "$ROOT" && python3 -m hybrid.cli classify test_unit_cpu.sh llm_knowledge_update | tr '\n' ';')
echo "  cli classify: $R"
if echo "$R" | grep -q "test_unit_cpu.sh → local"; then ok "CLI classify 纯CPU→local"; else bad "CLI classify local 失败: $R"; fi
if echo "$R" | grep -q "llm_knowledge_update → cloud"; then ok "CLI classify LLM→cloud"; else bad "CLI classify cloud 失败: $R"; fi

# 6. CLI route（37 脚本全部判 local 或 cloud，总数为 37）
R=$(cd "$ROOT" && python3 -m hybrid.cli route | python3 -c "import sys,json;d=json.load(sys.stdin);print(str(d['total'])+'|'+str(d['local'])+'|'+str(d['cloud']))")
echo "  cli route: $R"
if [ "$(echo "$R" | cut -d'|' -f1)" = "37" ]; then ok "CLI route 覆盖37个脚本"; else bad "CLI route 数量不符: $R"; fi

# 7. CLI all（dry-run 完整链路）
R=$(cd "$ROOT" && python3 -m hybrid.cli all --dry --timeout 5 | python3 -c "import sys,json;d=json.load(sys.stdin);print(str(d['run']['pass'])+'/'+str(d['run']['total'])+'|'+str(d['sync']['synced']))")
echo "  cli all: $R"
if [ "$(echo "$R" | cut -d'|' -f1)" = "37/37" ] && [ "$(echo "$R" | cut -d'|' -f2)" = "True" ]; then
  ok "CLI all 完整链路 37 全通过 + 同步成功"
else
  bad "CLI all 失败: $R"
fi

# 8. scripts/local-exec.sh 本地执行入口（only cost）
R=$(cd "$(dirname "$ROOT")" && bash scripts/local-exec.sh --only cost | python3 -c "import sys,json,re;txt=sys.stdin.read();d=json.loads(txt[txt.index('{'):]);print(d['net_save'])")
if [ -n "$R" ] && [ "$R" != "0.0" ]; then ok "local-exec.sh 成本报表正常 net_save=$R"; else bad "local-exec.sh 成本报表异常: $R"; fi

# 9. .cnb.yml 云端已移除 CPU 密集测试命令（纯 CPU 命令不再在云端执行）
CNB=$(cd "$(dirname "$ROOT")" && grep -cE "bash (local-agent/)?tests/test_" .cnb.yml || true)
if [ "$CNB" = "0" ]; then ok ".cnb.yml 已移除 CPU 密集测试命令(0条)"; else bad ".cnb.yml 仍含 $CNB 条 CPU 密集命令"; fi

# 10. 公开接口 __init__ 可导入
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');import hybrid;print(hasattr(hybrid,'HybridResourceRouter') and hasattr(hybrid,'LocalWorker') and hasattr(hybrid,'ResultSync') and hasattr(hybrid,'CostMonitor'))")
check "hybrid __init__ 公开接口齐全" "$R" "True"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
