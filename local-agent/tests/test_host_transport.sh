#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 三宿主真实传输注册表 测试（Issue #105 最常用链路 · entries.host_transport · v0.6.0）
# 补齐最常用闭环「本地 deepseek harness ⇄ 网页/gemini ⇄ cnb.cool」真实宿主传输两端：
#   1. hosts()/resolve_host 别名归一（网页/gemini→web-bridge；本地/deepseek→local-harness；cnb→cnb-live）
#   2. host_transport 三宿主结构齐全（send/poll/ack），非 mock 假装
#   3. local-harness 真实落 relay（真实接力卡，非 mock）→ relay 卡可读可续
#   4. bridge_via 经指定真实宿主发起云开发（得到真实句柄）
#   5. dashboard snapshot 纳入三宿主可达矩阵
#   6. run.py --bridge via-overview / via 真实宿主 CLI 可调
set -e
cd "$(dirname "$0")/.."
PY=python3
rm -f entries/_bridge_state/cloud_dev_handles.json 2>/dev/null

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/hosttr_out.txt 2>&1; then
  echo "  OK $d"; pass=$((pass+1))
else
  echo "  XX $d"; cat /tmp/hosttr_out.txt; fail=$((fail+1))
fi }

echo "===== [host_transport] 1. 三宿主注册表 + 别名归一 ====="
t "hosts() 返回三宿主（cnb-live/local-harness/web-bridge）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import host_transport as ht
ks = {h['name'] for h in ht.hosts()}
assert ks == {'cnb-live','local-harness','web-bridge'}, ks
assert all(h['real'] for h in ht.hosts())   # 三宿主都标真实，不 mock 假装
print('ok 三宿主注册表:', sorted(ks))
EOF
"
t "resolve_host 别名归一（网页/gemini/web/web-bridge→web-bridge；本地/deepseek/harness→local-harness；cnb/云端→cnb-live）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import host_transport as ht
for a in ('web','gemini','网页','web-bridge'):
    assert ht.resolve_host(a)=='web-bridge', a
for a in ('local','deepseek','harness','dsh','本地','local-harness'):
    assert ht.resolve_host(a)=='local-harness', a
for a in ('cnb','cloud','云端','cnb-live'):
    assert ht.resolve_host(a)=='cnb-live', a
print('ok 别名归一到三端之一')
EOF
"

echo "===== [host_transport] 2. host_transport 三宿主结构齐全（send/poll/ack）====="
t "host_transport 三宿主都含 name/send/poll/ack" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import host_transport as ht
for name in ('cnb-live','local-harness','web-bridge'):
    tr = ht.host_transport(name)
    assert tr['name'], name                       # transport 有真实名（cnb-live 内部名 live-cnb 亦可）
    assert callable(tr['send']) and callable(tr['poll']) and callable(tr['ack'])
print('ok 三宿主 transport 结构齐')
EOF
"

echo "===== [host_transport] 3. local-harness 真实落 relay（非 mock 假装）====="
t "local-harness send 真实写 relay 接力卡 + poll 读真实状态" "$PY - <<'EOF'
import sys, os; sys.path.insert(0,'.')
from entries import host_transport as ht
import relay
relay.clear()
tr = ht.host_transport('local-harness')
h = {'req':'host_transport 真实 relay 投递测试','handle_id':'tk-test','issue_id':'','entry':'local'}
s = tr['send'](h)
assert s['ok'] and s['cloud_ref']['transport']=='local-harness'
assert relay.load() is not None            # 真实 relay 卡已落盘
assert relay.load().get('status')=='in_progress'
p = tr['poll'](h)
assert p['ok'] and p['transport']=='local-harness'
a = tr['ack'](h)
assert a['ok']
# 真实机制：有 relay 历史留痕可回放，非 mock
assert len(relay.load().get('history', [])) >= 2
relay.clear()
print('ok local-harness 真实 relay 落盘/读/回执（可续跑可回放）')
EOF
"

echo "===== [host_transport] 4. bridge_via 经指定真实宿主发起云开发 ====="
t "bridge_via local-harness 得到真实句柄（status in_cloud_dev）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import host_transport as ht
import relay
relay.clear()
bv = ht.bridge_via('host_transport via 实测', via='local-harness')
assert bv['via']=='local-harness'
assert bv['handle']['handle_id'].startswith('tk-')
assert bv['handle']['status'] in ('pending','in_cloud_dev')
assert 'hosts' in bv
relay.clear()
print('ok bridge_via local-harness 真实句柄:', bv['handle']['handle_id'])
EOF
"
t "bridge_via 别名（deepseek→local-harness）归一" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import host_transport as ht
bv = ht.bridge_via('别名 deepseek 实测', via='deepseek')
assert bv['via']=='local-harness'
print('ok 别名 deepseek 归一 →', bv['via'])
EOF
"

echo "===== [host_transport] 5. dashboard snapshot 纳入三宿主可达矩阵 ====="
t "dashboard snapshot 含 hosts 三宿主矩阵（v0.6.0）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard
snap = dashboard.snapshot()
assert 'hosts' in snap
hosts = snap['hosts'].get('hosts', [])
assert {h['key'] for h in hosts} == {'cnb-live','local-harness','web-bridge'}
assert all('reachable' in h and 'health' in h for h in hosts)
print('ok dashboard hosts 矩阵三宿主齐')
EOF
"

echo "===== [host_transport] 6. run.py --bridge via 真实宿主 CLI ====="
t "run.py --bridge via-overview 可输出三宿主矩阵" "$PY run.py --bridge via-overview >/dev/null 2>&1 && grep -q 'local-harness' <(python3 run.py --bridge via-overview)"
t "run.py --bridge request --bridge-via local-harness 可调" "$PY run.py --bridge request --req 'CLI via 实测' --bridge-via local-harness >/dev/null 2>&1 && echo ok"
t "run.py --bridge-via unknown 如实报错不静默 mock" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import host_transport as ht
# ① host_transport.send 直接报错
tr = ht.host_transport('no-such-host')
r = tr['send']({'req':'x'})
assert r.get('ok') is False and '未知宿主' in r.get('error','')
# ② bridge_via 完整路径 handle 标 blocked + 带 send_error（不假成功 in_cloud_dev）
bv = ht.bridge_via('x', via='no-such-host')
assert bv['handle']['status'] == 'blocked', bv['handle']['status']
assert '未知宿主' in bv['handle'].get('send_error','')
print('ok 未知宿主如实报错不静默 mock（send + bridge_via 双路径）')
EOF
"

echo ""
echo "===== 三宿主真实传输 测试结果：$pass 通过 / $fail 失败 ====="
[ "$fail" = "0" ] || exit 1
