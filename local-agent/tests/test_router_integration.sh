#!/usr/bin/env bash
# ============================================================
# 融合路由接线层集成测试（test_router_integration）
# ============================================================
# 验证 Issue #41「打通架构意图→真实执行断点」：
#   run_pipeline 不再硬编码走 team.yaml dag，而是按 fusion.route()
#   选出的拓扑（agile/dag/prefix/scatter）动态执行。
#   1. router 按需求规模选拓扑 + 拿到可执行节点集
#   2. 各档位节点集均能被 DagEngine 校验（可真实执行）
#   3. run_pipeline 端到端：micro→agile(4节点) 不再硬编码 11 节点 dag
#   4. run_pipeline 端到端：大型→prefix(17节点)
#   5. --no-fusion 回退老行为（team.yaml 11 节点 dag，无 fusion 字段）
#   6. --topo 显式指定拓扑（绕过规模评估）
# ============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

check() { # desc, actual, expect
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (got='$2' expect='$3')"; fi
}

# 前置：初始化数据层（gid_registry 等表 + 数据管理员档案），避免 fractal/data 依赖崩
PRE="import sys,os;sys.path.insert(0,'$ROOT');from data import admin;admin.init();"

echo "== 融合路由接线层（规模→拓扑→可执行节点集，run_pipeline 动态执行）=="

# 1. router 按需求规模选拓扑 + 节点集
#    "改 bug" → micro → agile（4 节点）
R=$(python3 -c "$PRE from topology import router;r=router.route_pipeline('帮我改一下登录接口的 bug');print(r['tier']+'|'+r['system']+'|'+r['selected']+'|'+str(len(r['nodes'])))")
check "micro 需求→agile(4节点)" "$R" "micro|agile|agile|4"

#    "2500并发大型系统" → huge → prefix（17 节点）
R=$(python3 -c "$PRE from topology import router;r=router.route_pipeline('设计一个支持2500并发的企业级分布式系统架构，包含多部门协作');print(r['tier']+'|'+r['system']+'|'+r['selected']+'|'+str(len(r['nodes'])))")
check "huge 需求→prefix(17节点)" "$R" "huge|full|prefix|17"

#    force 显式指定拓扑（绕过规模评估）
R=$(python3 -c "$PRE from topology import router;r=router.route_pipeline('xx',force='scatter');print(r['selected']+'|'+str(len(r['nodes'])))")
check "force=scatter→scatter(15节点)" "$R" "scatter|15"

# 2. 各档位节点集均能被 DagEngine 校验（可真实执行）
R=$(python3 -c "
import sys,os;sys.path.insert(0,'$ROOT')
from data import admin;admin.init()
from topology import router
from graph import DagEngine
res=[]
for t in ['micro','small','medium','large','huge']:
    r=router.route_for_tier(t)
    dag=DagEngine(name=t,description='t',nodes=r['nodes'])
    ok,err=dag.validate()
    res.append(t+':'+r['selected']+':'+('ok' if ok else 'ERR'))
print(';'.join(res))
")
check "5 档节点集全部通过 DagEngine 校验" "$R" "micro:agile:ok;small:agile:ok;medium:dag:ok;large:scatter:ok;huge:prefix:ok"

# 3. run_pipeline 端到端：micro→agile 实际执行 4 节点（不再硬编码 11 节点 dag）
R=$(cd "$ROOT" && timeout 60 python3 -c "
import sys,os,io,contextlib;sys.path.insert(0,'.')
from data import admin;admin.init()
import orchestrator
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    r=orchestrator.run_pipeline('帮我改一下登录接口的 bug', backend='cli_fallback', use_fusion=True)
f=r.get('fusion',{})
print(f.get('selected','')+'|'+f.get('tier','')+'|'+str(len(r.get('steps',[]))))")
check "run_pipeline micro→agile(4步)" "$R" "agile|micro|4"

# 4. run_pipeline 端到端：大型→prefix 实际执行 17 节点
R=$(cd "$ROOT" && timeout 60 python3 -c "
import sys,os,io,contextlib;sys.path.insert(0,'.')
from data import admin;admin.init()
import orchestrator
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    r=orchestrator.run_pipeline('设计一个支持2500并发的企业级分布式系统架构，包含多部门协作，含缓存、消息队列、监控、安全', backend='cli_fallback', use_fusion=True)
f=r.get('fusion',{})
print(f.get('selected','')+'|'+f.get('tier','')+'|'+str(len(r.get('steps',[]))))")
check "run_pipeline huge→prefix(17步)" "$R" "prefix|huge|17"

# 5. --no-fusion 回退老行为（不 consult 融合路由，无 fusion 字段，11 节点 dag）
R=$(cd "$ROOT" && timeout 60 python3 -c "
import sys,os,io,contextlib;sys.path.insert(0,'.')
from data import admin;admin.init()
import orchestrator
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    r=orchestrator.run_pipeline('帮我改一下登录接口的 bug', backend='cli_fallback', use_fusion=False)
print(('yes' if 'fusion' not in r else 'no')+'|'+str(len(r.get('steps',[]))))")
check "--no-fusion 回退(无fusion,11步)" "$R" "yes|11"

# 6. --topo 显式指定拓扑（绕过规模评估）
R=$(cd "$ROOT" && timeout 60 python3 -c "
import sys,os,io,contextlib;sys.path.insert(0,'.')
from data import admin;admin.init()
import orchestrator
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    r=orchestrator.run_pipeline('xx', backend='cli_fallback', use_fusion=True, force_topology='scatter')
f=r.get('fusion',{})
print(f.get('selected','')+'|'+str(len(r.get('steps',[]))))")
check "--topo scatter 显式指定(15步)" "$R" "scatter|15"

echo ""
echo "=============================="
echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ] || exit 1
