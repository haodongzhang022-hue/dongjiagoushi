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

# 6. CLI route（registry 登记的全部脚本都要被判 local/cloud 且不重不漏）
#    ⚠️ 断言口径不写死数字：脚本集从 registry.json 派生，新增测试不会让信号灯假红
EXPECT=$(cd "$ROOT" && python3 -c "import sys;sys.path.insert(0,'local-agent');from hybrid import registry;print(len([t for t in registry.all_tests() if (registry.get(t) or {}).get('kind') != 'light']))")
R=$(cd "$ROOT" && python3 -m hybrid.cli route | python3 -c "import sys,json;d=json.load(sys.stdin);print(str(d['total'])+'|'+str(d['local'])+'|'+str(d['cloud']))")
echo "  cli route: $R (expect total=$EXPECT)"
if [ "$(echo "$R" | cut -d'|' -f1)" = "$EXPECT" ] && [ $(( $(echo "$R" | cut -d'|' -f2) + $(echo "$R" | cut -d'|' -f3) )) = "$EXPECT" ]; then
  ok "CLI route 覆盖 $EXPECT 个登记脚本（local+cloud 不重不漏）"
else
  bad "CLI route 数量不符: $R (expect total=$EXPECT)"
fi

# 7. CLI all（dry-run 完整链路）
R=$(cd "$ROOT" && python3 -m hybrid.cli all --dry --timeout 5 | python3 -c "import sys,json;d=json.load(sys.stdin);print(str(d['run']['pass'])+'/'+str(d['run']['total'])+'|'+str(d['sync']['synced']))")
echo "  cli all: $R"
if [ "$(echo "$R" | cut -d'|' -f1)" = "$EXPECT/$EXPECT" ] && [ "$(echo "$R" | cut -d'|' -f2)" = "True" ]; then
  ok "CLI all 完整链路 $EXPECT 全通过 + 同步成功"
else
  bad "CLI all 失败: $R"
fi

# 8. scripts/local-exec.sh 本地执行入口（only cost）
R=$(cd "$(dirname "$ROOT")" && bash scripts/local-exec.sh --only cost | python3 -c "import sys,json,re;txt=sys.stdin.read();d=json.loads(txt[txt.index('{'):]);print(d['net_save'])")
if [ -n "$R" ] && [ "$R" != "0.0" ]; then ok "local-exec.sh 成本报表正常 net_save=$R"; else bad "local-exec.sh 成本报表异常: $R"; fi

# 9. .cnb.yml 云端只保留 registry 标记 kind=light 的测试（纯 CPU 密集脚本必须本地跑）
#    ⚠️ 不写死"必须为 0"：dsh 装载验证这类 kind=light 的脚本按设计留在云端。
STRAY=$(cd "$(dirname "$ROOT")" && python3 -c "
import re,sys
sys.path.insert(0,'local-agent')
from hybrid import registry
txt=open('.cnb.yml',encoding='utf-8').read()
bad=[]
for m in re.finditer(r'bash\s+((?:local-agent/)?tests/test_[\w.]+\\.sh)', txt):
    t=m.group(1)
    kind=(registry.get(t) or {}).get('kind')
    if kind != 'light':
        bad.append(t)
print(len(bad), ','.join(sorted(set(bad))))
")
CNB=$(echo "$STRAY" | cut -d' ' -f1)
NAMES=$(echo "$STRAY" | cut -d' ' -f2-)
if [ "$CNB" = "0" ]; then
  ok ".cnb.yml 云端无 CPU 密集测试命令（仅保留 kind=light）"
else
  bad ".cnb.yml 仍含 $CNB 条 CPU 密集命令: $NAMES"
fi

# 10. 公开接口 __init__ 可导入
R=$(python3 -c "import sys;sys.path.insert(0,'$ROOT');import hybrid;print(hasattr(hybrid,'HybridResourceRouter') and hasattr(hybrid,'LocalWorker') and hasattr(hybrid,'ResultSync') and hasattr(hybrid,'CostMonitor'))")
check "hybrid __init__ 公开接口齐全" "$R" "True"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
