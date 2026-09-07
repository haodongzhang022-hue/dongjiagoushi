#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 跨端聚合控制页 测试（Issue #105 最常用链路深化 · entries.dashboard · v0.4.0）
# 验证用户诉求："做一个方便控制的聚合，类似于 fastapi 聚合页包括状态显示，
#   然后每个端我都尝试建立一个，这样跨端交互的就会更加顺畅"
#   1. snapshot 全端聚合大盘（三端适配器矩阵 + 句柄 + 接力卡 + 成本）
#   2. panel 每端一个面板（web/cnb/local），本端视角过滤 + 本端可用动作
#   3. FastAPI 风格路由键 + 健康状态灯（health/overview/handles/relay）
#   4. 控制动作回写真实状态机（request/collect/align/localtest 非假状态）
#   5. 人可读 HTML 聚合页（全端大盘 + 每端面板）
#   6. run.py --dashboard / --dashboard-html CLI 全链可调
set -e
cd "$(dirname "$0")/.."
PY=python3
rm -f entries/_bridge_state/cloud_dev_handles.json 2>/dev/null

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/dash_out.txt 2>&1; then
  echo "  OK $d"; pass=$((pass+1))
else
  echo "  XX $d"; cat /tmp/dash_out.txt; fail=$((fail+1))
fi }

echo "===== [dashboard] 1. snapshot 全端聚合大盘 ====="
t "snapshot 聚合三端矩阵+句柄+接力卡+成本，健康反映真实通道" "$PY - <<'EOF'
import sys, shutil; sys.path.insert(0,'.')
from entries import dashboard
d = dashboard.snapshot()
assert d['module'] == 'platform-adapter'
# health 反映真实通道（无 cnb CLI 环境=degraded，有 cnb=ok；核心三件 adapters/handles/relay 恒健康）
lt = d['health'].get('live_transport') or {}
assert lt.get('transport') == ('live-cnb' if shutil.which('cnb') else 'mock')
assert d['health']['adapters'] and d['health']['handles'] and d['health']['relay']
assert len(d['entries']) == 3
assert {e['entry'] for e in d['entries']} == {'web','cnb','local'}
assert 'handles' in d and 'relay' in d and 'cost' in d
assert d['main_entry'] == '架构·秘书'
assert len(d['endpoints']) >= 9
print('ok 聚合大盘 三端=%s 路由=%d live=%s' % (','.join(e['entry'] for e in d['entries']), len(d['endpoints']), lt.get('transport')))
EOF
"

echo "===== [dashboard] 2. panel 每端一个面板 ====="
t "每端面板：本端视角过滤句柄 + 本端可用动作" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard, bridge
bridge.request_cloud_dev('本地发起的开发', entry='local')
bridge.request_cloud_dev('云端发起的开发', entry='cnb')
for e in ('web','cnb','local'):
    p = dashboard.panel(e)
    assert p['ok'] and p['panel']['title'].startswith(e)
    assert p['panel']['this_adapter']['entry'] == e
    assert p['panel']['actions']
lp = dashboard.panel('local')
myids = [h['handle_id'] for h in lp['panel']['my_handles']]
assert len(myids) >= 1
acts = {a['action'] for a in lp['panel']['actions']}
assert 'localtest' in acts and 'align' in acts
print('ok 每端面板 local端句柄=%d 动作=%s' % (len(myids), ','.join(a['action'] for a in lp['panel']['actions'])))
EOF
"
t "all_panels 三端并列（每端都建一个）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard
ap = dashboard.all_panels()
for e in ('web','cnb','local'):
    assert e in ap and ap[e]['ok']
print('ok all_panels 三端并列')
EOF
"

echo "===== [dashboard] 3. FastAPI 风格控制动作（回写真实状态机）====="
t "health/overview/handles/relay 结构化快照" "$PY - <<'EOF'
import sys, shutil; sys.path.insert(0,'.')
from entries import dashboard
# health 状态反映真实通道（有 cnb=ok，无 cnb=degraded）；overview/handles/relay 恒定可用
h = dashboard.control('health')['data']['health']
lt = h.get('live_transport') or {}
assert h['status'] in ('ok','degraded')
assert h['status'] == 'ok' if shutil.which('cnb') else h['status'] in ('degraded','ok')
assert lt.get('transport') == ('live-cnb' if shutil.which('cnb') else 'mock')
assert dashboard.control('overview')['ok']
assert dashboard.control('handles')['ok']
assert dashboard.control('relay')['ok']
print('ok health=%s/%s' % (h['status'], lt.get('transport')))
EOF
"
t "request collect merged+多PR align localtest 一键闭环" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard
import os
f='entries/_bridge_state/cloud_dev_handles.json'
if os.path.exists(f): os.remove(f)
rq = dashboard.control('request', req='聚合页控制动作演示', entry='web')
assert rq['ok']
hid = rq['data']['handle_id']
co = dashboard.control('collect', handle_id=hid, collect_state='merged', pr_ids='PR#1,PR#2')
assert co['ok'] and co['data']['handle']['cloud_result']['state']=='merged'
assert co['data']['handle']['cloud_result']['pr_ids']==['PR#1','PR#2']
assert dashboard.control('align', handle_id=hid)['data']['ok'] is True
lt = dashboard.control('localtest', handle_id=hid)
assert lt['ok'] and lt['data']['skipped_cloud_build'] is True
print('ok 控制动作闭环 merged+2PR align localtest')
EOF
"
t "未知动作/缺参数返回错误不静默" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard
bad = dashboard.control('nonsense')
assert bad['ok'] is False and 'available' in bad
assert dashboard.control('align')['ok'] is False
print('ok 未知动作/缺参拦截')
EOF
"

echo "===== [dashboard] 4. 人可读 HTML 聚合页 ====="
t "html 全端大盘（状态灯+表+一键控制）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard
html = dashboard.html_page(None)
for n in ('<!DOCTYPE html>','跨端交互聚合控制台','一键控制动作','桥接句柄状态'):
    assert n in html, '缺 '+n
print('ok html 大盘页 len=', len(html))
EOF
"
t "html 每端面板（web/cnb/local）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard
for e in ('web','cnb','local'):
    html = dashboard.html_page(e)
    assert e + ' 端' in html and '一键控制动作' in html
print('ok html 每端面板')
EOF
"

echo "===== [dashboard] 5. run.py --dashboard CLI ====="
t "--dashboard overview 聚合大盘可读" "$PY run.py --dashboard overview 2>&1 | grep -q '跨端聚合控制台'"
t "--dashboard panel local 本端面板可读" "$PY run.py --dashboard panel --entry local 2>&1 | grep -q 'local 端'"
t "--dashboard-html 输出 HTML 聚合页" "$PY run.py --dashboard-html 2>&1 | grep -q '<!DOCTYPE html>'"
t "--dashboard request 经控制台发起云开发" "$PY run.py --dashboard request --req 'CLI控制台发起' 2>&1 | grep -q 'handle='"

echo ""
echo "===== [dashboard] 结果: $pass 通过 / $fail 失败 ====="
[ "$fail" -eq 0 ] || exit 1
