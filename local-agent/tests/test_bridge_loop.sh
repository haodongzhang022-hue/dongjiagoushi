#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 本地⇄云端桥接闭环 测试（Issue #105 最常用链路深化 · entries.bridge）
# 验证用户最常用闭环链路能力：
#   1. request_cloud_dev：本地/web 发卡 → 云端异步开发（拿到跨对话/跨PR句柄）
#   2. 同 req_key 二次触发取回同一 handle（gid 稳定寻址不漂移）
#   3. collect_cloud_result：云端产出(merged/done/need_fix + PR)跨 PR 归集收集
#   4. align_local：云端产出回写本地 relay/data 双向对齐
#   5. local_test_first：云端 CPU 密集测试下放本地（降云端建环境成本，用户点名成本点）
#   6. run.py --bridge CLI 全链可调
set -e
cd "$(dirname "$0")/.."
PY=python3
# 每次清空桥状态保证确定性
rm -f entries/_bridge_state/cloud_dev_handles.json 2>/dev/null

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/bridge_out.txt 2>&1; then
  echo "  ✅ $d"; pass=$((pass+1))
else
  echo "  ❌ $d"; cat /tmp/bridge_out.txt; fail=$((fail+1))
fi }

echo "===== [bridge-loop] 1. request_cloud_dev 发起云端异步开发（拿句柄）====="
t "web 工具桥 → 发云开发请求，返回跨对话句柄" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('补齐本地测试先行门', entry='web')
assert h['handle_id'].startswith('tk-'), '句柄应为 gid tk- 前缀'
assert h['status'] in ('pending','in_cloud_dev')
assert h['entry'] == 'web'
print('句柄:', h['handle_id'], '| status:', h['status'], '| 发起入口:', h['entry'])
EOF
"

t "同 req_key 二次触发取回同一 handle（gid 稳定寻址不漂移）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
a = bridge.request_cloud_dev('对齐登录模块PR产出', entry='local')
b = bridge.request_cloud_dev('对齐登录模块PR产出', entry='local')
assert a['handle_id'] == b['handle_id'], '同任务二次触发应同一句柄(不漂移)'
print('稳定寻址 ok:', a['handle_id'])
EOF
"

echo "===== [bridge-loop] 2. collect_cloud_result 云端产出跨 PR 收集====="
t "云端 merged + 多 PR 跨 PR 归集" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('跨仓库开发PR产物归集', entry='cnb')
hid = h['handle_id']
col = bridge.collect_cloud_result(hid, cloud_state='merged',
                                  pr_ids=['PR#301','PR#302'])
assert col['ok'] is True
assert col['handle']['status'] == 'collected'
cr = col['handle']['cloud_result']
assert cr['state'] == 'merged'
assert cr['pr_ids'] == ['PR#301','PR#302']
print('跨PR收集 ok: state=', cr['state'], 'prs=', cr['pr_ids'])
EOF
"

t "need_fix 状态(评审打回)也被如实记录，可续跑" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('评审发现缺陷需改', entry='cnb')
col = bridge.collect_cloud_result(h['handle_id'], cloud_state='need_fix')
assert col['ok'] is True
assert col['handle']['cloud_result']['state'] == 'need_fix'
# need_fix 状态不吞，明确暴露供续跑/回转
print('need_fix 记录 ok（供续跑，非吞异常）')
EOF
"

echo "===== [bridge-loop] 3. align_local 云端产出回写本地（双向对齐）====="
t "align 把 collected 句柄写回 relay + data 归档 + messages" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('对齐数据到本地', entry='local')
bridge.collect_cloud_result(h['handle_id'], cloud_state='done', pr_ids=['PR#401'])
al = bridge.align_local(h['handle_id'])
assert al['ok'] is True
assert al['relay_aligned'] is True
assert al['data_archived'] is True
# relay 接力卡里已写入 cloud_bridge 对齐块
import relay
card = relay.load()
assert card.get('cloud_bridge',{}).get('handle_id') == h['handle_id']
print('本地对齐 ok: relay+data 均落痕')
EOF
"

t "未 collected 的句柄不可对齐（防错序）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('还在云端开发不应对齐', entry='web')
# 未 collect 直接 align → 拒绝
al = bridge.align_local(h['handle_id'])
assert al['ok'] is False, '未收集产出不应提前对齐'
print('错序对齐被拦截 ok')
EOF
"

echo "===== [bridge-loop] 4. local_test_first 云端CPU密集测试下放本地====="
t "CPU 密集/长耗时测试路由本地，跳过云端重复建环境" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('本地测试先行门', entry='web')
plan = bridge.local_test_first(h['handle_id'])
assert plan['ok'] is True
assert plan['skipped_cloud_build'] is True
assert len(plan['routed_local']) >= 1
assert '建环境' in plan['cost_note']
print('本地测试先行 ok: 下放=', plan['routed_local'])
print('  cost_note:', plan['cost_note'])
EOF
"

echo "===== [bridge-loop] 5. 闭环俯瞰 + run.py CLI ====="
t "loop_overview 提供闭环状态俯瞰" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from entries import bridge
ov = bridge.loop_overview()
assert ov['handles_total'] >= 1
assert 'handles_by_status' in ov
assert len(ov['close_loop_steps']) == 4
print('闭环俯瞰: 句柄数=', ov['handles_total'], '步骤=', len(ov['close_loop_steps']))
EOF
"

t "run.py --bridge overview 可调用" "python3 run.py --bridge overview"

echo ""
echo "===== 本地⇄云端桥接闭环 测试结果：$pass 通过 / $fail 失败 ====="
[ "$fail" = "0" ] || exit 1
