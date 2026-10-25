#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 桥接句柄自足 + 脑区判定 测试（Issue #232 · entries.bridge v0.3.1）
# 场景来源（用户实测）：本地发起的云开发请求，云端只有「桥接句柄」，
# 且本地服务没开 —— 此时云端是不是完全没法操作？该不该交付就带全信息？
# 断言口径：
#   1. 只给一个 id，也能渲染出「无场外信息即可承接」的自足卡（目的/验收/不做/在哪/脑区）
#   2. 自足卡自带合规接力卡标记（能被 relay_card.check 机器校验，不是靠自觉）
#   3. 残卡（只贴 id）被 verify 判不达标，并逐项列缺
#   4. 脑区判定：云端能做开发/评审/CI；本地测试与对齐必须本地；合并卡人类
#   5. 本地不可达 = 证据缺口明确暴露（不再 mock ok=True 假绿灯），真跑 rc 非 0 如实 False
#   6. 未知动作宁拦不放；relaunch 后脑区与证据翻正
set -e
cd "$(dirname "$0")/.."
PY=python3
rm -rf entries/_bridge_state

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/selfc_out.txt 2>&1; then
  echo "  ✅ $d"; pass=$((pass+1))
else
  echo "  ❌ $d"; cat /tmp/selfc_out.txt; fail=$((fail+1))
fi }

echo "===== [selfcontained] 1. 一个 id 重建全部上下文 ====="
t "仅凭 handle_id 渲染自足卡：目的/验收/不做/在哪/脑区齐备" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('云端只有句柄时能否承接', entry='local')
r = bridge.render_handle_card(h['handle_id'], to_role='架构·开发')
assert r['ok'], r
card = r['card']
for k in ('目的','验收','不做','在哪','脑区'):
    assert k in card, '卡缺关键区块: ' + k
assert h['handle_id'] in card, '卡内必须带句柄 id'
assert 'target_repo=' in card, '缺所在仓库 → 云端不知去哪干活'
print('自足卡区块齐备，长度', len(card))
PY
"

t "自足卡自带合规接力卡标记，能被 relay_card 机器校验通过" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
from relay_card import check
h = bridge.request_cloud_dev('核查卡片合规标记', entry='web')
r = bridge.render_handle_card(h['handle_id'], to_role='架构·评审')
assert r['relay_ok'] is True, r['relay_reasons']
ok, reasons = check(r['card'], role='架构·评审')
assert ok, reasons
print('relay_card 校验通过（@完整 + [触发] 都在卡里）')
PY
"

echo "===== [selfcontained] 2. 残卡拦截（只贴 id 的原始症状）====="
t "只贴 handle_id 的卡 → verify 判不自足并逐项列缺" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('残卡拦截', entry='local')
bad = 'handle=%s 你看下改改' % h['handle_id']
v = bridge.verify_handle_card(bad, handle_id=h['handle_id'])
assert v['ok'] is False
joined = ' '.join(v['missing'])
for k in ('目的','验收','不做','所在仓库'):
    assert k in joined, '未暴露缺项: ' + k
print('残卡缺项:', len(v['missing']), '项')
PY
"

t "完整自足卡 → verify 通过" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('完整卡通过', entry='local')
card = bridge.render_handle_card(h['handle_id'], to_role='架构·开发')['card']
v = bridge.verify_handle_card(card, handle_id=h['handle_id'], to_role='架构·开发')
assert v['ok'] is True, v['missing']
print('自足核验通过')
PY
"

echo "===== [selfcontained] 3. 脑区判定（不是能不能，是在哪能做）====="
t "云端可做开发/评审/CI；本地测试与对齐必须本地；合并卡人类" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
a = bridge.analyze_locus(local_reachable=False)
assert 'write_code' in a['cloud_can'] and 'review' in a['cloud_can']
assert 'local_test' in a['must_local'] and 'align_local' in a['must_local']
assert 'merge_gate' in a['must_human']
assert a['evidence_available'] is False, '本地不可达必须暴露证据缺口'
print('云端可做=', a['cloud_can'], '| 必须本地=', a['must_local'])
PY
"

t "未知动作宁拦不放（进 blocked 而非静默放行）" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
a = bridge.analyze_locus(['write_code','偷偷增发token'])
assert any('偷偷增发token' == b['action'] for b in a['blocked'])
print('未知动作已拦截登记')
PY
"

t "relaunch 后脑区与证据翻正" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('本地可达后翻正', entry='local')
assert bridge.analyze_locus(local_reachable=bool(h['relaunch']))['evidence_available'] is False
bridge.mark_relaunch(h['handle_id'])
h2 = bridge.get_handle(h['handle_id'])
a = bridge.analyze_locus(local_reachable=bool(h2['relaunch']))
assert a['evidence_available'] is True
assert a['blocked'] == []
print('本地可达后证据可得、无缺口登记')
PY
"

echo "===== [selfcontained] 4. 本地不可达不给假绿灯 ====="
t "未真跑 / 本地不可达：ok 不谎报，cost_note 明说无证据" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('不谎报绿灯', entry='local')
plan = bridge.local_test_first(h['handle_id'])
assert plan['executed'] is False
assert '无本地测试证据' in plan['cost_note']
print('未真跑如实标注: executed=False')
PY
"

t "真跑：rc 非 0 如实 ok=False（脚本不存在不再被当通过）" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('真跑如实报rc', entry='local')
bridge.mark_relaunch(h['handle_id'])
plan = bridge.local_test_first(h['handle_id'], run=True,
                              test_scripts=['__definitely_missing__.sh'])
assert plan['executed'] is True
assert plan['ok'] is False, 'rc 非 0 / 脚本不存在必须报不通过'
print('rc 如实:', plan['results'][0])
PY
"

t "真跑一个真实通过的信号灯脚本 → ok=True" "$PY - <<'PY'
import sys; sys.path.insert(0,'.')
from entries import bridge
h = bridge.request_cloud_dev('真跑真实脚本', entry='local')
bridge.mark_relaunch(h['handle_id'])
plan = bridge.local_test_first(h['handle_id'], run=True,
                              test_scripts=['test_bridge_loop.sh'])
r = plan['results'][0]
assert r['returncode'] == 0 and r['ok'] is True, r
print('真实脚本真跑通过 rc=0')
PY
"

echo ""
echo "===== 句柄自足 + 脑区判定 测试结果：$pass 通过 / $fail 失败 ====="
[ "$fail" = "0" ] || exit 1
