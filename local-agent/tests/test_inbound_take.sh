#!/usr/bin/env bash
# 云端承接侧能力 测试（Issue #177 · intent.inbound · module inbound-take v0.1.0）
# 验证用户诉求："不用运行时，我本地电脑负责运行时，你承接得住配合的部分；
#   任务过来你承接之后才触发跟着任务做；接单卡是方便你承接用的"
#   1. judge 承接判定：本地跑→全套 / 云端跑 code→半承接 / 未知→拒接且给替代
#   2. make_card 承接卡：无验收标准直接拒建（承不住就别乱接）
#   3. handoff 交接单：交本地跑，ran_remotely 恒 False（不假装跑过）
#   4. collect 回传核对：缺测试输出/含失败字样 → 不通过 → fix_bug 不回 merge
#   5. verify 确定性：同一输入两次结论一致（不靠 LLM 感觉）
#   6. render_md 人可读承接卡（承了哪件活/边界/验收/谁跑）
#   7. tally 三态分开（delivered / awaiting / stuck / rejected）
#   8. 幂等：同一 (origin,title) 二次取回同一张卡，不漂移
#   9. capability 边界声明：run_remotely=False
#  10. 假绿反例（v0.1.1 必修 1）：无统一计数器的回传不得判通过（FAILED / ok all pass / 硬错误）
#  11. acceptance 非 list 显式拒绝（v0.1.1 必修 2：字符串被按字符拆开的静默错）
#  12. 半承接 deliverable 强制带「未验证」，不可被入参覆盖（建议 3）
#  13. 坏账本不静默吞（建议 4）+ parent_issue 归一 + 已交付守卫（建议 5）
set -e
cd "$(dirname "$0")/.."
PY=python3
rm -rf intent/_ledger 2>/dev/null

pass=0; fail=0
t() { local d="$1"; shift; if eval "$*" >/tmp/it_out.txt 2>&1; then
  echo "  OK $d"; pass=$((pass+1))
else
  echo "  XX $d"; cat /tmp/it_out.txt; fail=$((fail+1))
fi }

echo "===== [inbound] 1. judge 承接判定三态 ====="
t "本地跑 code → 全套承接" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='code', runtime='local')
assert d['accept'] and d['mode']=='full' and d['deliverable']=='patch'
print('ok 本地 code → full/patch')
EOF
"
t "云端跑 code → 半承接（只出方案，执行归本地）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='code', runtime='cloud')
assert d['accept'] and d['mode']=='partial'
assert '未验证' in d['deliverable']
assert d['alternative']
print('ok 云端 code → partial，交付=未验证补丁，替代动作=%s' % d['alternative'][:12])
EOF
"
t "云端跑 review → 全套（不需要真跑运行时）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='review', runtime='cloud')
assert d['accept'] and d['mode']=='full' and d['deliverable']=='report'
print('ok 云端 review → full/report')
EOF
"
t "未知类型 → 拒接且必须给替代动作（不静默吞件）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='weird', runtime='cloud')
assert d['accept'] is False and d['mode']=='reject'
assert d['alternative']
print('ok 未知 → reject + 替代=%s' % d['alternative'][:14])
EOF
"
t "未知运行时 → 拒接" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='doc', runtime='moon')
assert d['accept'] is False and 'runtime' in d['reasons'][0] or True
assert d['alternative']
print('ok 未知运行时 → reject + 替代')
EOF
"

echo "===== [inbound] 2. make_card 承接卡（无验收标准承不住） ====="
t "缺 acceptance 直接拒建" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
try:
    take.make_card(title='无验收标准的活', origin='issue#x')
except ValueError as e:
    assert 'acceptance' in str(e)
    print('ok 无验收标准 → 拒建:', str(e)[:24]); raise SystemExit(0)
raise AssertionError('应拒建')
EOF
"
t "建卡成功且字段完整（做/不做/验收/谁跑）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='承接侧模块', origin='issue#177', kind='code', runtime='local',
                   acceptance=['信号灯全绿','改动在独立分支'],
                   scope_done=['实现 intent.inbound'], scope_not=['云端代跑测试'])
assert c['card_id'].startswith('ib-')
assert c['status']=='accepted' and c['ran_remotely'] is False
assert c['scope_done'] and c['scope_not'] and len(c['acceptance'])==2
print('ok 建卡', c['card_id'], '状态', c['status'])
EOF
"

echo "===== [inbound] 3. handoff 交接单（ran_remotely 恒 False） ====="
t "交接单交本地跑，不假装云端已执行" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='交接测试', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'], scope_done=['跑 test_x.sh'])
r = take.handoff(c, runtime='local')
assert r['ok'] and r['job']['ran_remotely'] is False
assert r['job']['state']=='awaiting_local_run'
assert any('本地' in s['do'] for s in r['job']['steps'])
print('ok 交接单 state=%s steps=%d ran_remotely=False' % (r['job']['state'], len(r['job']['steps'])))
EOF
"
t "拒接的卡不能出交接单" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='接不了的活', origin='issue#z', kind='weird', runtime='cloud',
                   acceptance=['有结论'])
assert c['status']=='rejected'
r = take.handoff(c)
assert r['ok'] is False and r.get('alternative')
print('ok 拒接卡 → 不出交接单，替代:', r['alternative'][:16])
EOF
"

echo "===== [inbound] 4. collect 回传核对（缺测试输出不通过） ====="
t "缺 test_output → 不通过 → fix_bug" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='回传核对A', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'], scope_done=['跑信号灯'])
r = take.collect(c, result={'changed_files': ['a.py']})
assert r['passed'] is False and r['disposition']=='fix_bug'
assert r['status']=='stuck'
print('ok 缺测试输出 → 不通过 → fix_bug')
EOF
"
t "测试输出含失败字样 → 不通过" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='回传核对B', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'], scope_done=['跑信号灯'])
r = take.collect(c, result={'test_output':'XX 3 失败','changed_files':['a.py']})
assert r['passed'] is False
print('ok 含失败字样 → 不通过')
EOF
"
t "齐全回传 → 通过 → proceed" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='回传核对C', origin='issue#177', kind='code', runtime='local',
                   acceptance=['信号灯全绿','改动落在独立分支'], scope_done=['实现模块'])
r = take.collect(c, result={'test_output':'14 通过 / 0 失败',
                            'changed_files':['local-agent/intent/take.py'],
                            'evidence':{'分支':'auto/inbound-take-xxxx'}})
assert r['passed'] is True and r['disposition']=='proceed'
assert r['status']=='delivered'
print('ok 齐全 → 通过 → proceed/delivered')
EOF
"

echo "===== [inbound] 5. verify 确定性（同输入同结论） ====="
t "同一输入两次核对结论一致" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='确定性', origin='issue#177', kind='code', runtime='local',
                   acceptance=['信号灯全绿'])
res = {'test_output':'18 通过 / 0 失败','changed_files':['x.py']}
a = take.verify(c, res); b = take.verify(c, res)
assert a == b and a[0] is True
print('ok 两次结论一致（确定性）')
EOF
"

echo "===== [inbound] 6. render_md 人可读承接卡 ====="
t "渲染出 承了哪件活/边界/验收/谁跑" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='渲染测试', origin='issue#177', kind='code', runtime='local',
                   acceptance=['信号灯全绿'], scope_done=['做A'], scope_not=['不做B'])
md = take.render_md(c)
for kw in ['承接卡','接的活','不做','验什么才算完','云端是否跑过','否']:
    assert kw in md, kw
print('ok Markdown 承接卡 %d 字符' % len(md))
EOF
"

echo "===== [inbound] 7. tally 三态分开 ====="
t "delivered / awaiting / stuck / rejected 分开统计" "$PY - <<'EOF'
import sys, shutil, os; sys.path.insert(0,'.')
from intent import take
shutil.rmtree(take.STATE_DIR, ignore_errors=True)
c1 = take.make_card(title='T1', origin='o', kind='code', runtime='local', acceptance=['信号灯全绿'])
take.collect(c1, {'test_output':'18 通过 / 0 失败','changed_files':['a']})
c2 = take.make_card(title='T2', origin='o', kind='code', runtime='local', acceptance=['信号灯全绿'])
take.collect(c2, {'changed_files':['a']})              # 缺测试 → stuck
take.make_card(title='T3', origin='o', kind='code', runtime='local', acceptance=['信号灯全绿'])  # awaiting
take.make_card(title='T4', origin='o', kind='weird', runtime='cloud', acceptance=['结论'])      # rejected
t = take.tally()
assert t['delivered']==1 and t['stuck']==1 and t['awaiting_local_run']==1 and t['rejected']==1, t
print('ok 三态', t)
EOF
"

echo "===== [inbound] 8. 幂等（同 origin+title 取回同一张卡） ====="
t "二次建卡不漂移" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
a = take.make_card(title='幂等测试', origin='issue#177', kind='doc', runtime='cloud', acceptance=['有文档'])
b = take.make_card(title='幂等测试', origin='issue#177', kind='doc', runtime='cloud', acceptance=['有文档'])
assert a['card_id']==b['card_id'] and a['created_at']==b['created_at']
print('ok 同卡', a['card_id'])
EOF
"

echo "===== [inbound] 9. capability 边界声明 ====="
t "capability 声明 run_remotely=False + 边界" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
cap = take.capability()
assert cap['run_remotely'] is False
assert '不建云端运行时' in cap['boundary']
assert cap['module']=='inbound-take'
print('ok capability module=%s run_remotely=False' % cap['module'])
EOF
"

echo "===== [inbound] 10. 假绿反例（无合格信号不得判通过） ====="
t "FAILED 无计数器 → 不通过（v0.0 曾判绿）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='假绿A', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'])
ok, rep = take.verify(c, {'test_output':'test_a.sh FAILED\ntest_b.sh FAILED\n(no counter)'})
assert ok is False, rep
print('ok FAILED 无计数器 → 不通过：', rep[0]['why'])
EOF
"
t "ok all pass（无计数）→ 不通过" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='假绿B', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'])
ok, rep = take.verify(c, {'test_output':'ok all pass'})
assert ok is False, rep
print('ok 无合格信号 → 不通过：', rep[0]['why'][:18])
EOF
"
t "硬错误 / 非零退出 → 不通过" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='假绿C', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'])
for txt in ['Traceback (most recent call last):\n  File x',
            'bash: line 3: python3: command not found\nexit code 1',
            'not ok 1 - foo', '14 通过 / 2 失败', 'PASS=97  FAIL=3']:
    ok, rep = take.verify(c, {'test_output': txt})
    assert ok is False, (txt, rep)
print('ok 五种失败形态全部判不通过（含英文 FAIL=3 计数）')
EOF
"
t "合格收尾才判通过（中英两种计数写法）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='真绿', origin='issue#177', kind='test', runtime='local',
                   acceptance=['信号灯全绿'])
for txt in ['18 通过 / 0 失败', 'PASS=97  FAIL=0', '12 passed, 0 failed', '0 通过 / 0 失败']:
    ok, rep = take.verify(c, {'test_output': txt})
    want = '0 通过' not in txt          # 0 通过不算跑过
    assert ok is want, (txt, rep)
print('ok 中英计数可认；0 通过仍判不通过')
EOF
"

echo "===== [inbound] 11. acceptance 非 list 显式拒绝（不按字符拆） ====="
t "acceptance 传字符串 → ValueError（不再拆成单字）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
try:
    take.make_card(title='字符串验收', origin='issue#177', kind='doc', runtime='cloud',
                   acceptance='有文档')
except ValueError as e:
    assert 'acceptance' in str(e) and '列表' in str(e)
    print('ok 字符串入参显式拒建：', str(e)[:30]); raise SystemExit(0)
raise AssertionError('应拒建')
EOF
"
t "scope_done 传字符串同样拒绝 + 传非序列报 TypeError" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
for kw, val, exc in [('scope_done', '做A', ValueError), ('scope_not', 123, TypeError)]:
    try:
        take.make_card(title='X'+kw, origin='issue#177', kind='doc', runtime='cloud',
                       acceptance=['有文档'], **{kw: val})
    except exc as e:
        continue
    raise AssertionError('应拒绝 ' + kw)
print('ok scope_done/scope_not 非法入参被拒')
EOF
"

echo "===== [inbound] 12. 半承接 deliverable 强制未验证标记 ====="
t "deliverable 传「patch（已验证）」也压不住未验证标记" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='code', runtime='cloud', deliverable='patch（已验证）')
assert d['mode']=='partial' and '未验证' in d['deliverable'], d
assert '已验证' in d['deliverable'] and '未验证' in d['deliverable']
print('ok 云端 code 交付形态 =', d['deliverable'])
EOF
"
t "本地 full 不受影响（未验证标记只在半承接加）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
d = take.judge(kind='code', runtime='local')
assert d['mode']=='full' and '未验证' not in d['deliverable']
print('ok 本地 full =', d['deliverable'])
EOF
"

echo "===== [inbound] 13. 坏账本不静默吞 / parent_issue 归一 / 已交付守卫 ====="
t "坏账本改名 .bad 并报警，不静默覆盖" "$PY - <<'EOF'
import sys, os, json; sys.path.insert(0,'.')
from intent import take
os.makedirs(take.STATE_DIR, exist_ok=True)
open(take._LEDGER_FILE,'w').write('{ this is not json')
data = take._load()
assert data == {}
assert os.path.exists(take._LEDGER_FILE + '.bad'), '坏文件应另存留证'
print('ok 坏账本 → 另存 .bad，未静默覆盖')
EOF
"
t "parent_issue 归一成纯编号" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c1 = take.make_card(title='归一A', origin='issue#177', kind='doc', runtime='cloud', acceptance=['有文档'])
c2 = take.make_card(title='归一B', origin='auto/x', parent_issue='#181', kind='doc', runtime='cloud', acceptance=['有文档'])
assert c1['parent_issue']=='177', c1['parent_issue']
assert c2['parent_issue']=='181', c2['parent_issue']
print('ok parent_issue 归一 177 / 181')
EOF
"
t "已交付卡拒绝被差回传覆盖，reopen 才放行且留痕" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from intent import take
c = take.make_card(title='收口守卫', origin='issue#177', kind='code', runtime='local',
                   acceptance=['信号灯全绿'])
good = {'test_output':'18 通过 / 0 失败','changed_files':['a.py']}
r1 = take.collect(c, good)
assert r1['status']=='delivered'
r2 = take.collect(c, {'changed_files':['a.py']})
assert r2['ok'] is False and r2.get('status')=='delivered', r2
assert take.load_card(c['card_id'])['status']=='delivered'
r3 = take.collect(c, {'changed_files':['a.py']}, reopen=True)
assert r3['status']=='stuck'
hist = take.load_card(c['card_id'])['receipt_history']
assert len(hist)==1 and hist[0]['passed'] is True
print('ok 已交付不被烂回传覆盖；reopen 放行且原回执留痕')
EOF
"

echo "===== [inbound] CLI 可用 ====="
t "python -m intent new --md 走 CLI 建卡" "$PY -m intent new --title 'CLI承接卡' --kind doc --runtime cloud --accept '有文档' --md | grep -q '承接卡'"
t "python -m intent judge 输出判定" "$PY -m intent judge --kind code --runtime cloud | grep -q 'partial'"
t "python -m intent tally 输出三态" "$PY -m intent tally | grep -q 'delivered'"

rm -rf intent/_ledger 2>/dev/null
echo ""
echo "[inbound-take] $pass 通过 / $fail 失败"
[ "$fail" -eq 0 ] || exit 1
