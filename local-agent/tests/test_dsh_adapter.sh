#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# dsh 适配 新版兼容 测试（Issue #145 · module dsh-adapter v0.1.0）
# 验证用户诉求："dsh 已经有新版的了，适配一下最新版本……完成适配新版"
#   1. Python 侧版本矩阵/API 面判定（dsh_adapter.compat）
#   2. TS 侧兼容层（Node 原生 TS 剥离，无 dsh 依赖）
#   3. 组合包契约（package.json dsh.bundle.patch + cordis.patch.yml）
#   4. 插件 API 面（Cordis apply + inject + defineTool）与工具注册
#   5. Agent Directory 注册 6 角色 + 默认入口锁秘书
#   6. 旧版→新版判据（0.1.2 判 incompatible，targetVersion 判 ok）
#   7. **真实包**装载面（Issue #202）：output.render 必调钩子 —— 离线桩不校验它，
#      只有真实 @deepseek-ai/dsh-tools 才能暴露"注册成功但一调用就 TypeError"的静默失效
set -e
cd "$(dirname "$0")/.."
# 失败落点显式化（Issue #175）：CI 上 `t()` 把每项输出重定向到临时文件，若脚本因
# `set -e` 在项外提前退出，失败证据就进不了日志 → 只看到 pass=N fail=1 无法定位。
# 这里在退出时打印落点，并把最近一项的输出回显（不吞错误原文）。
_last_item=""
trap 'rc=$?; if [ "$rc" -ne 0 ]; then echo "[dsh-adapter] 异常退出 rc=$rc（最后执行项: ${_last_item:-无}）"; fi' EXIT
PY=python3
ROOT="$(pwd)"
DSH_DIR="$ROOT/../dsh-adapter"
[ -d "$DSH_DIR" ] || DSH_DIR="$ROOT/dsh-adapter"

pass=0; fail=0
t() { local d="$1"; shift; _last_item="$d"; if eval "$*" >/tmp/dshad_out.txt 2>&1; then
  # t() 把整项输出重定向到 /tmp/dshad_out.txt（保持信号灯干净），但"没真跑"
  # 的证据就在被吞掉的输出里（SKIP 首行 + pass=0）——绿项也回显它，否则
  # 一眼看去是绿的、实际一条真实包断言都没跑（假绿）。这里把 SKIP/pass=0
  # 的首行一并回显；正常项的收尾行（pass=N fail=0）不刷屏，跳过。
  echo "  OK $d"; pass=$((pass+1))
  grep -q 'SKIP\|pass=0 ' /tmp/dshad_out.txt 2>/dev/null && sed -n '1,2p' /tmp/dshad_out.txt || true
else
  echo "  XX $d"; cat /tmp/dshad_out.txt; fail=$((fail+1))
fi }

echo "===== [dsh-adapter] 1. Python 侧版本矩阵 ====="
t "check targetVersion → ok" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from dsh_adapter import compat
r = compat.check_version(compat.DSH_COMPAT['target_version'])
assert r['state'] == 'ok', r
assert 'defineTool' in r['faces'] and 'cordis-all-plugin' in r['faces']
# 真实 dsh-tools 0.0.1-rc.1 实测出的必调渲染面必须在面表里
assert 'output-render' in r['faces'], r['faces']
print('ok 新版兼容', r['state'])
EOF
"
t "check 0.1.2-rc.1 → incompatible（旧版缺 cordis/defineTool）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from dsh_adapter import compat
r = compat.check_version('0.1.2-rc.1')
assert r['state'] == 'incompatible', r
assert 'cordis-all-plugin' in r['missing_faces']
print('ok 旧版判不兼容')
EOF
"
t "check 乱版 → incompatible（显式暴露不静默）" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from dsh_adapter import compat
r = compat.check_version('garbage')
assert r['state'] == 'incompatible' and '无法解析' in r['message'], r
print('ok 乱版显式不兼容')
EOF
"
t "matrix 覆盖新版+旧版档位" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from dsh_adapter import compat
m = compat.compat_matrix()
assert m['matrix'][m['target_version']] == 'ok', m['target_version']
assert m['matrix']['0.1.2-rc.1'] == 'incompatible'
# 0.1.5.x 是 API 面齐但未用真实包实测的一代 → degrade（不谎报 ok）
assert m['matrix']['0.1.5-rc.2'] == 'degrade', m['matrix']['0.1.5-rc.2']
assert len(m['api_faces']) >= 5
print('ok 矩阵 target=%s 档位=%d' % (m['target_version'], len(m['matrix'])))
EOF
"
t "CLI: python -m dsh_adapter.compat check 退出码正确" \
  "cd '$ROOT' && $PY -m dsh_adapter.compat check 0.2.1-rc.2 >/dev/null && $PY -m dsh_adapter.compat matrix >/dev/null"

echo "===== [dsh-adapter] 2. TS 侧兼容层（Node 原生 TS 剥离） ====="
# 门控按**真实能力**判定，不按「有没有 node」（Issue #175）：CI 镜像装到的可能是
# 发行版 node v20，存在但不支持 `--experimental-strip-types` → 直接 `bad option`。
# 那种情况要让日志说清"是环境能力不够"，而不是让它冒充"适配没做成"。
NODE_TS_READY=0
NODE_NOTE=""
if ! command -v node >/dev/null 2>&1; then
  NODE_NOTE="无 node"
elif ! node --experimental-strip-types -e '' >/dev/null 2>&1; then
  NODE_NOTE="node $(node --version) 不支持 --experimental-strip-types（需 ≥22.6）"
else
  NODE_TS_READY=1
fi
if [ "$NODE_TS_READY" = "1" ]; then
  t "TS compat 测试 15 项全绿" "node --experimental-strip-types '$DSH_DIR/tests/compat.test.mjs' | tail -1 | grep -q 'fail=0'"
  t "组合包契约测试 15 项全绿" "node '$DSH_DIR/tests/bundle.test.mjs' | tail -1 | grep -q 'fail=0'"
  t "插件加载测试全绿（含 output.render 契约）" "node --experimental-strip-types '$DSH_DIR/tests/plugin.test.mjs' | tail -1 | grep -q 'fail=0'"
else
  echo "  -- 跳过 TS 侧：${NODE_NOTE}（CI 由 scripts/ci-ensure-node.sh 保证可用）"
fi

echo "===== [dsh-adapter] 2b. 桥接实际调用（真实 Python 引擎） ====="
# 三态门控（Issue #175）：① node 能力就绪 + 已链接真实 dsh → 真跑桥接 + 真装载探针；
#   ② 能力就绪但未链接 dsh → 只跑桥接实跑（Python 引擎可达）；
#   ③ node 缺失/太旧 → 显式跳过并打印原因（曾漏判：else 分支自称"桥接实跑仍验证"
#     却直接调 node → `command not found` / `bad option` 被记成功能缺陷 = CI 假红）。
if [ "$NODE_TS_READY" != "1" ]; then
  echo "  -- 跳过桥接实跑与真实装载探针：${NODE_NOTE}（TS/桥接侧未验证）"
elif [ -e "$DSH_DIR/node_modules/@deepseek-ai/dsh-tools" ]; then
  t "桥接实际调用（dsh_adapter/dev_standard/relay 真跑）" "node --experimental-strip-types '$DSH_DIR/tests/bridge.live.test.mjs' | tail -1 | grep -q 'fail=0'"
  t "真实 defineTool 装载探针（7 工具注册）" "node --experimental-strip-types '$DSH_DIR/tests/real-load.probe.mjs' | tail -1 | grep -q 'REAL-LOAD-OK'"
  # 判据：收尾行 pass=/fail= 且 fail=0。**未装真实包时该测试自体 SKIP
  # （pass=0 fail=0 + 首行 SKIP 标记），此处据此亮灯但显式喊出"没真跑"**，
  # 不把「跳过」当「失败」（CI 未装 dsh-tools 时曾经全红），也不把跳过当
  # 「真实包装载通过」——真跑证据由首行 SKIP 缺席给出。
  t "真实包装载测试（output.render 必调面；未装真实包则 SKIP ·非红且不冒充通过）" \
    "node --experimental-strip-types '$DSH_DIR/tests/real-package.test.mjs' > /tmp/dshad_realpkg.txt 2>&1 || { cat /tmp/dshad_realpkg.txt; false; }; if grep -q 'SKIP' /tmp/dshad_realpkg.txt; then sed -n '1,2p' /tmp/dshad_realpkg.txt; else grep 'fail=0' /tmp/dshad_realpkg.txt; fi"
else
  echo "  -- 未链接真实 dsh，跳过真实装载探针；桥接实跑仍验证"
  echo "  !! 注意：离线桩不校验 output.render，真实 dsh 一调用即 TypeError（Issue #202）。" 
  echo "     本条绿≠真实包装得上，装机前务必 npm i -D @deepseek-ai/dsh-tools 跑 real-package 测试。"
  t "桥接实际调用（Python 引擎可达）" "cd '$DSH_DIR' && node --experimental-strip-types tests/bridge.live.test.mjs | tail -1 | grep -q 'fail=0'"
fi

echo "===== [dsh-adapter] 3. 组合包契约文件 ====="
t "package.json 声明 dsh.bundle.patch" "grep -q '\"bundle\"' '$DSH_DIR/package.json' && grep -q 'cordis.patch.yml' '$DSH_DIR/package.json'"
t "cordis.patch.yml 是 insert 定向 patch" "grep -q 'insert:' '$DSH_DIR/cordis.patch.yml' && grep -q 'dongjiagoushi-dsh-adapter' '$DSH_DIR/cordis.patch.yml'"
t "peer 依赖声明 dsh-tools + cordis" "grep -q '@deepseek-ai/dsh-tools' '$DSH_DIR/package.json' && grep -q '@deepseek-ai/cordis' '$DSH_DIR/package.json'"

echo "===== [dsh-adapter] 4. 插件新版 API 面 ====="
t "src/index.ts 用 Cordis apply + inject + defineTool" "grep -q 'export function apply(ctx' '$DSH_DIR/src/index.ts' && grep -q \"inject = \\['tools'\\]\" '$DSH_DIR/src/index.ts' && grep -q 'defineTool(' '$DSH_DIR/src/index.ts'"
t "加载即版本闸门（checkVersion + throw）" "grep -q 'checkVersion(' '$DSH_DIR/src/index.ts' && grep -q 'throw new Error' '$DSH_DIR/src/index.ts'"
t "每个工具都带 output.render（真实 dsh ≥0.2 必调，缺则一调用就崩）" "test \$(grep -c 'render: renderValueContent' '$DSH_DIR/src/index.ts') -ge 2"
t "桥接契约表 BRIDGE_MAP 覆盖 dev-standard/label/relay" "grep -q 'dev_standard.host' '$DSH_DIR/src/bridge.ts' && grep -q 'label.cli' '$DSH_DIR/src/bridge.ts' && grep -q 'relay_card' '$DSH_DIR/src/bridge.ts'"

echo "===== [dsh-adapter] 5. Agent Directory ====="
t "注册 6 个架构角色（架构·前缀）" "test \$(grep -c 'name: 架构·' '$DSH_DIR/dsh-collaboration-rules.yaml') -eq 6"
t "默认入口锁「架构·秘书」" "grep -q 'defaultRole: 架构·秘书' '$DSH_DIR/dsh-collaboration-rules.yaml'"

echo ""
echo "[dsh-adapter] pass=$pass fail=$fail"
[ "$fail" -eq 0 ] || exit 1
