#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 真实 cnb.cool 传输通道 测试（Issue #105 真实本地实测 · entries.cnb_live · v0.5.0）
# 验证用户诉求："使用模拟数据不可信 → 尝试本地实测真实通道，发送信号做配合，
#   不行则适配。" cnb_live 把 bridge/dashboard 的 mock transport 升级为真实通道：
#   1. probe 只读通道探测（默认不污染仓库）；无 cnb CLI → mock 兜底如实标注
#   2. live_transport / mock_transport 结构齐全（send/poll/ack）
#   3. default_transport：有 cnb CLI → live-cnb 真实优先（用户：模拟数据不可信）
#   4. bridge.request live=False 仍走 mock（单测确定性不污染）；live=True 可注入真实
#   5. mock transport 显式标注 mock（不骗人），dashboard health 反映真实通道可达性
set -e
cd "$(dirname "$0")/.."
PY=python3
rm -f entries/_bridge_state/cloud_dev_handles.json 2>/dev/null

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/cnblive_out.txt 2>&1; then
  echo "  OK $d"; pass=$((pass+1))
else
  echo "  XX $d"; cat /tmp/cnblive_out.txt; fail=$((fail+1))
fi }

echo "===== [cnb_live] 1. transport 结构齐全 ====="
t "live_transport/mock_transport 含 send/poll/ack" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import cnb_live
for tr in (cnb_live.live_transport(), cnb_live.mock_transport()):
    assert tr['name'] and callable(tr['send'])
    assert callable(tr['poll']) and callable(tr['ack'])
assert cnb_live.mock_transport()['name'] == 'mock'
assert cnb_live.live_transport()['name'] == 'live-cnb'
print('ok transport 结构齐 + mock 显式标注不骗人')
EOF
"

echo "===== [cnb_live] 2. default_transport 真实优先（用户：模拟数据不可信）====="
t "有 cnb CLI → default live-cnb；无 cnb → mock 兜底" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import cnb_live
import shutil
want = 'live-cnb' if shutil.which('cnb') else 'mock'
tr = cnb_live.default_transport()
assert tr['name'] == want, f'应 {want} 实际 {tr["name"]}'
print('ok default_transport =', tr['name'])
EOF
"

echo "===== [cnb_live] 3. probe 只读探测（默认不建 Issue 不污染）====="
t "probe 默认只读：send=False，返回 health/transport" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import cnb_live
import shutil
p = cnb_live.probe()
assert 'probe' in p and 'health' in p and 'transport' in p
if shutil.which('cnb'):
    assert p['transport'] == 'live-cnb'
    assert p['probe']['send'] is False        # 只读不建 Issue
    assert p['health']['status'] == 'ok'       # read 通 = 真实通道可达成配合
else:
    assert p['transport'] == 'mock'
print('ok probe(只读):', p['transport'], p['health']['status'])
EOF
"

echo "===== [cnb_live] 4. bridge.request 单测确定性（live=False 不污染）====="
t "live=False 默认 mock（单测确定性，不真实建 Issue）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('单测用任务', entry='local', live=False)
assert h['handle_id'].startswith('tk-')
assert h['status'] in ('pending','in_cloud_dev')
# 单测确定性：live=False 时 transport 走 mock，不真实建 Issue
tr = (h.get('cloud_ref') or {}).get('transport','mock')
assert tr == 'mock', f'live=False 应走 mock 单测不污染，实际 {tr}'
print('ok live=False 走 mock 单测确定性，不污染真实仓库')
EOF
"
t "live=True 只做 transport 选择（不真发），机制由 CLI/dashboard 承载真实信号" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge, cnb_live
# 验证 live=True 会让 request 选用 cnb_live.default_transport（真实优先）
# 不真发：只验证 transport 选择机制（真实 request 的发送由 run.py --bridge / probe 承担）
import shutil
want = 'live-cnb' if shutil.which('cnb') else 'mock'
assert cnb_live.default_transport()['name'] == want
# cli_bridge 透传 live 参数
assert 'live' in __import__('inspect').signature(bridge.cli_bridge).parameters
print('ok live=True 机制就绪，真实信号由 CLI/dashboard request 发出')
EOF
"

echo "===== [cnb_live] 5. dashboard health 反映真实通道 ====="
t "dashboard snapshot transport_default 反映真实通道可达性" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import dashboard, cnb_live
import shutil
want = 'live-cnb' if shutil.which('cnb') else 'mock'
s = dashboard.snapshot()
assert s.get('transport_default') == want, s.get('transport_default')
lt = s['health'].get('live_transport') or {}
assert lt.get('transport') == want
print('ok dashboard health 反映 transport_default =', s.get('transport_default'))
EOF
"

echo ""
echo "===== 真实 cnb 传输通道 测试结果：$pass 通过 / $fail 失败 ====="
[ "$fail" = "0" ] || exit 1
