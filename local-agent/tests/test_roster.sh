#!/usr/bin/env bash
# 角色名册与派单接入信号灯（roster · 对外稳定接口面）
# 覆盖：握手清单 / ID 稳定 / 解析不猜 / 派生入口 / 派单入场 / 留痕 / 缺口如实
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/local-agent${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT/local-agent"

PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✅ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ❌ $1"; }

py() { python3 -c "$1" 2>&1; }

echo "== roster 信号灯 =="
# 去重键是「实体:roster:角色」持久化的，跨次运行会撞 → 每轮用唯一后缀
RUN="$(date +%s)-$$"; export RUN


# 1. 握手：catalog 带契约版本 + 角色数 + 主入口
R1=$(py "from roster import catalog; c=catalog(); print(c['contract'], c['count']>0, c['entry_role_id'])")
case "$R1" in
  "dongjiagoushi.roster/v1 True arch.secretary") ok "catalog 契约版本/角色数/主入口齐备";;
  *) bad "catalog 握手不全: $R1";;
esac

# 2. ID 稳定：同一中文名多次解析 → 同一 ID（不漂移）
R2=$(py "
from roster import resolve
a=resolve('架构·开发'); b=resolve('arch.developer'); c=resolve('开发')
print(a['role_id']==b['role_id']==c['role_id']=='arch.developer')")
[ "$R2" = "True" ] && ok "中文名/ID/别名解析到同一 role_id（不漂移）" || bad "ID 漂移: $R2"

# 3. @串 与 [触发] 标记都能解析（跨仓派单常见形态）
R3=$(py "
from roster import resolve
print(resolve('@dongdongxiaozu/dongjiagoushi(架构·评审)')['role_id'],
      resolve('[触发:架构·测试]')['role_id'])")
[ "$R3" = "arch.reviewer arch.tester" ] && ok "@串/[触发] 标记解析正确" || bad "标记解析错: $R3"

# 4. 认不出不猜：未知目标返回失败+候选，绝不返回一个"最像的"
R4=$(py "
from roster import resolve
r=resolve('火星执行者'); print(r['ok'], r.get('reason'))")
[ "$R4" = "False unknown_role" ] && ok "未知角色不猜（ok=False + reason）" || bad "未知角色被猜了: $R4"

# 5. 空目标派单 → 落到秘书主入口（默认入口规则）
R5=$(py "
from roster import intake
r=intake({'task':'没说派给谁'}, dispatch=False)
print(r['role_id'], r['role_id']=='arch.secretary')")
[ "$R5" = "arch.secretary True" ] && ok "未指定目标 → 秘书主入口（不绕过默认入口）" || bad "默认入口错: $R5"

# 6. 无 task 拒收（下游无法开工，必须显式失败）
R6=$(py "
from roster import intake
r=intake({'target':'arch.developer'}, dispatch=False); print(r['ok'], r.get('reason'))")
[ "$R6" = "False empty_task" ] && ok "空 task 被拒（不静默接受）" || bad "空 task 未拒: $R6"

# 7. 派单入场：走标准 dispatcher 链路并返回 event_id（可回查）
R7=$(py "
from roster import intake
r=intake({'target':'arch.developer','task':'补 token 刷新','entity':'issue-42-'+__import__('os').environ['RUN']})
print(r['ok'], r['status'], bool(r.get('event_id')), r['role_id'])")
case "$R7" in
  "True dispatched True arch.developer") ok "派单入场走 dispatcher 并留痕 event_id";;
  *) bad "派单入场异常: $R7";;
esac

# 8. 留痕可回查：事件落 dispatch 表
R8=$(py "
from roster import intake
from data import db, schema
schema.init_schema()
r=intake({'target':'arch.reviewer','task':'复评 PR','entity':'pr-9-'+__import__('os').environ['RUN']})
row=db.query('SELECT * FROM dispatch WHERE event_id=?',(r['event_id'],))
print(len(row), row[0]['target_role'] if row else '')")
[ "$R8" = "1 架构·评审" ] && ok "派单落 dispatch 表可回查（target_role 正确）" || bad "留痕缺失: $R8"

# 9. 不可跑角色：直接拒派（ok=False，不返回 event_id、不写 dispatch、不占 dedup）
R9=$(py "
from roster import intake
from data import db, schema
schema.init_schema()
e='amb-'+__import__('os').environ['RUN']
r=intake({'target':'架构·审核前置助手','task':'二选一拿不准','entity':e})
row=db.query('SELECT * FROM dispatch WHERE entity=?',(e,))
print(r['ok'], r.get('reason'), bool(r.get('event_id')), len(row))")
[ "$R9" = "False role_not_implemented False 0" ] && ok "无实现角色拒派（不假绿/不落库）" || bad "无实现角色未被拒: $R9"

# 10. 缺口如实：漂移只有两类，且每条都带 kind/sources
R10=$(py "
from roster import specs
d=specs.drift()
print(len(d)>0,
      all(x['kind'] in ('missing_in_source','no_implementation') and x['sources'] for x in d),
      any(x['kind']=='no_implementation' for x in d))")
[ "$R10" = "True True True" ] && ok "缺口分两类如实暴露（每条带 kind+sources）" || bad "缺口口径不对: $R10"

# 10b. 漂移口径以 registry 为基准：relay 子集不报假问题、真缺的必须报
R10b=$(py "
from roster import specs
d={x['role_id']: (x['kind'], x['sources']) for x in specs.drift()}
fake = [k for k,(kind,srcs) in d.items() if kind=='missing_in_source' and set(srcs) <= {'relay'}]
real = d.get('arch.deliverer', ('',''))[1], d.get('arch.data_admin', ('',''))[1]
print(len(fake), 'team' in real[0], 'team' in real[1])")
[ "$R10b" = "0 True True" ] && ok "漂移口径正确（relay 子集不误报 / team 真缺报出来）" || bad "漂移口径仍错: $R10b"

# 11. verify：对端清单 ⇄ 本仓名册 双向差集
R11=$(py "
from roster import verify
r=verify(['arch.developer','架构·评审','火星角色'])
print(bool(r['only_theirs']), bool(r['only_ours']), r['count']['theirs'])")
case "$R11" in
  "True True 3") ok "verify 双向差集（多出来的对端角色被点名）";;
  *) bad "verify 差集异常: $R11";;
esac

# 12. verify 对齐时 ok=True（全对上不误报）
R12=$(py "
from roster import verify, catalog
r=verify(catalog()['roles']); print(r['ok'], r['only_theirs'], r['only_ours'])")
[ "$R12" = "True [] []" ] && ok "verify 全对齐时不误报" || bad "verify 误报: $R12"

# 13. 只解析不派发：dry_run 不写库
R13=$(py "
from roster import intake
from data import db, schema
schema.init_schema()
r=intake({'target':'arch.tester','task':'跑 E2E','entity':'pr-77-'+__import__('os').environ['RUN']}, dispatch=False)
row=db.query('SELECT * FROM dispatch WHERE entity=?',('pr-77-'+__import__('os').environ['RUN'],))
print(r['dry_run'], len(row))")
[ "$R13" = "True 0" ] && ok "dry-run 只解析不落库（可先预演再派）" || bad "dry-run 落库了: $R13"

# 14. 批量派单：单条失败不中断整批
R14=$(py "
from roster import intake_batch
import os; u=os.environ['RUN']
r=intake_batch([{'target':'arch.developer','task':'A','entity':'b1-'+u},
                {'target':'火星人','task':'B','entity':'b2-'+u},
                {'target':'arch.tester','task':'C','entity':'b3-'+u}])
print(r['total'], r['accepted'], r['rejected'])")
[ "$R14" = "3 2 1" ] && ok "批量派单逐条记账，单条失败不中断" || bad "批量派单异常: $R14"

# 15. 去重护栏复用：同一实体同一角色二次派单 → 被 dedup 拦截（不重复派活）
R15=$(py "
from roster import intake
e='dup-'+__import__('os').environ['RUN']
a=intake({'target':'arch.developer','task':'干活','entity':e})
b=intake({'target':'arch.developer','task':'干活','entity':e})
print(a['status'], b['status'], b.get('ok'))")
case "$R15" in
  "dispatched rejected False") ok "同实体同角色二次派单被 dedup 拦截（护栏复用）";;
  *) bad "去重护栏失效: $R15";;
esac

# 16. 不存在曾用名：解析器与 catalog 必须自一致（认得出的必是名册里真有的角色）
R16=$(py "
from roster import resolve, catalog, specs
ids={r['role_id'] for r in catalog()['roles']}
ghost=resolve('架构·版本管理')
print(ghost['ok'], ghost.get('reason'), resolve('arch.developer')['role_id'] in ids)")
[ "$R16" = "False unknown_role True" ] && ok "幽灵角色名不被解析（resolve ⇄ catalog 自一致）" || bad "幽灵角色可解析: $R16"

# 17. 名册不造第五份清单：每个 role_id 都必须来自某个事实源
R17=$(py "
from roster import catalog
c=catalog()
print(all(r['name'] for r in c['roles']), all(r['role_id'] and not r['role_id'].startswith('unregistered.') for r in c['roles']))")
[ "$R17" = "True True" ] && ok "名册全部来自事实源（无临时编造条目）" || bad "名册含造出来的条目: $R17"

# 18. 文档承诺兑现：webhook 有 roster 派单入口，且 intake 真有调用方（不再是死代码）
R18=$(bash -c "cd \"$ROOT\" && grep -q 'roster' local-agent/dispatcher/webhook.py && grep -rq 'roster' --include=*.py local-agent/dispatcher/ && echo wired")
[ "$R18" = "wired" ] && ok "webhook 接真实入口（intake 非孤岛）" || bad "webhook 未接 roster: $R18"

# 19. 真实 HTTP 端到端：鉴权 → intake → 200/400 语义正确（不 mock）
R19=$(py "
import sys, json, threading, time, urllib.request, urllib.error, os
sys.path.insert(0, os.path.dirname(os.path.abspath('.')))
from data import schema; schema.init_schema()
from dispatcher import security, webhook
from http.server import HTTPServer
src=security.get_source('local_pc') or security.register_source('local_pc', ip_whitelist=['127.0.0.1','::1'])
key=src['api_key']
srv=HTTPServer(('127.0.0.1',0), webhook._WebhookHandler)
port=srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start(); time.sleep(0.2)
def post(path, body, k=key):
    req=urllib.request.Request('http://127.0.0.1:%d%s'%(port,path),
        data=json.dumps(body).encode(),
        headers={'X-API-Key':k,'Content-Type':'application/json'})
    try:
        r=urllib.request.urlopen(req); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())
u=os.environ['RUN']
c1,b1=post('/webhook/local_pc/roster',{'target':'arch.developer','task':'补token','entity':'wh-ok-'+u})
c2,b2=post('/webhook/local_pc/roster',{'target':'架构·审核前置助手','task':'x','entity':'wh-ni-'+u})
c3,b3=post('/webhook/local_pc/roster',{'target':'arch.developer','task':'x'}, k='wrong')
srv.shutdown()
print(c1, b1['ok'], bool(b1.get('event_id')), c2, b2['reason'], c3)")
[ "$R19" = "200 True True 400 role_not_implemented 401" ] && ok "真实 HTTP 端到端（派单/拒派/鉴权语义正确）" || bad "HTTP 端到端异常: $R19"

# 20. CLI 真能跑：`python -m roster.cli intake` 不因同名函数遮蔽子模块而崩
R20=$(py "
import subprocess, os, sys, json
env=dict(os.environ); env['PYTHONPATH']='.'
r=subprocess.run([sys.executable,'-m','roster.cli','intake','--target','arch.developer',
                  '--task','补 token','--dry-run'],capture_output=True,text=True,env=env)
out=json.loads(r.stdout) if r.stdout.strip().startswith('{') else {}
print(r.returncode, out.get('dry_run'), out.get('role_id'))")
[ "$R20" = "0 True arch.developer" ] && ok "CLI intake 可运行（不崩、dry-run 生效）" || bad "CLI intake 崩了: $R20"

echo "结果: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" = "0" ]
