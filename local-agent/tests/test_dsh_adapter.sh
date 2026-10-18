#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# dsh 适配 新版兼容 测试（Issue #145 · module dsh-adapter v0.1.0）
# 验证用户诉求："dsh 已经有新版的了，适配一下最新版本……完成适配新版"
#   1. Python 侧版本矩阵/API 面判定（dsh_adapter.compat）
#   2. TS 侧兼容层（Node 原生 TS 剥离，无 dsh 依赖）
#   3. 组合包契约（package.json dsh.bundle.patch + cordis.patch.yml）
#   4. 插件 API 面（Cordis apply + inject + defineTool）与工具注册
#   5. Agent Directory 注册 6 角色 + 默认入口锁秘书
#   6. 旧版→新版判据（0.1.2 判 incompatible，0.1.6-alpha.2 判 ok）
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
  echo "  OK $d"; pass=$((pass+1))
else
  echo "  XX $d"; cat /tmp/dshad_out.txt; fail=$((fail+1))
fi }

echo "===== [dsh-adapter] 1. Python 侧版本矩阵 ====="
t "check 0.1.6-alpha.2 → ok" "$PY - <<'EOF'
import sys; sys.path.insert(0,'.')
from dsh_adapter import compat
r = compat.check_version('0.1.6-alpha.2')
assert r['state'] == 'ok', r
assert 'defineTool' in r['faces'] and 'cordis-all-plugin' in r['faces']
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
assert m['target_version'] == '0.1.6-alpha.2', m['target_version']
assert m['matrix']['0.1.6-alpha.2'] == 'ok'
assert m['matrix']['0.1.2-rc.1'] == 'incompatible'
assert len(m['api_faces']) >= 5
print('ok 矩阵 target=%s 档位=%d' % (m['target_version'], len(m['matrix'])))
EOF
"
t "CLI: python -m dsh_adapter.compat check 退出码正确" \
  "cd '$ROOT' && $PY -m dsh_adapter.compat check 0.1.6-alpha.2 >/dev/null && $PY -m dsh_adapter.compat matrix >/dev/null"

echo "===== [dsh-adapter] 2. TS 侧兼容层（Node 原生 TS 剥离） ====="
if command -v node >/dev/null 2>&1; then
  # node 由 .cnb.yml 在 CI 上显式安装并前置核验（缺则作业直接失败，不静默跳过）；
  # 本脚本仍保留本地/离线可跑：无 node 时下面整段跳过并显式打印，不假装验过。
  t "TS compat 测试 15 项全绿" "node --experimental-strip-types '$DSH_DIR/tests/compat.test.mjs' | tail -1 | grep -q 'fail=0'"
  t "组合包契约测试 15 项全绿" "node '$DSH_DIR/tests/bundle.test.mjs' | tail -1 | grep -q 'fail=0'"
  t "插件加载测试 9 项全绿" "node --experimental-strip-types '$DSH_DIR/tests/plugin.test.mjs' | tail -1 | grep -q 'fail=0'"
else
  echo "  -- 无 node，跳过 TS 侧（CI 环境将安装）"
fi

echo "===== [dsh-adapter] 2b. 桥接实际调用（真实 Python 引擎） ====="
# 三态门控（Issue #175）：① 有 node + 已链接真实 dsh → 真跑桥接 + 真装载探针；
#   ② 有 node 但未链接 dsh → 只跑桥接实跑（Python 引擎可达）；
#   ③ **无 node → 显式跳过**（曾漏判：else 分支自称"桥接实跑仍验证"却直接调 node，
#     上游 python:3.11 镜像无 node → `node: command not found` 被记红，CI 假红）。
if ! command -v node >/dev/null 2>&1; then
  echo "  -- 无 node，跳过桥接实跑与真实装载探针（TS/桥接侧未在本环境验证）"
elif [ -e "$DSH_DIR/node_modules/@deepseek-ai/dsh-tools" ]; then
  t "桥接实际调用（dsh_adapter/dev_standard/relay 真跑）" "node --experimental-strip-types '$DSH_DIR/tests/bridge.live.test.mjs' | tail -1 | grep -q 'fail=0'"
  t "真实 defineTool 装载探针（7 工具注册）" "node --experimental-strip-types '$DSH_DIR/tests/real-load.probe.mjs' | tail -1 | grep -q 'REAL-LOAD-OK'"
elif command -v node >/dev/null 2>&1; then
  echo "  -- 未链接真实 dsh，跳过真实装载探针；桥接实跑仍验证"
  t "桥接实际调用（Python 引擎可达）" "cd '$DSH_DIR' && node --experimental-strip-types tests/bridge.live.test.mjs | tail -1 | grep -q 'fail=0'"
else
  # 无 node：显式跳过并打印（.cnb.yml 会在 CI 上装 node，本分支只服务离线/精简环境）。
  # 不把"环境缺能力"记成"功能有缺陷"，也不假装验过——TS 侧到底跑没跑，日志里看得见。
  echo "  -- 无 node，跳过桥接实跑（TS 侧未在本环境验证；CI 由 .cnb.yml 装 node 后真跑）"
fi

echo "===== [dsh-adapter] 3. 组合包契约文件 ====="
t "package.json 声明 dsh.bundle.patch" "grep -q '\"bundle\"' '$DSH_DIR/package.json' && grep -q 'cordis.patch.yml' '$DSH_DIR/package.json'"
t "cordis.patch.yml 是 insert 定向 patch" "grep -q 'insert:' '$DSH_DIR/cordis.patch.yml' && grep -q 'dongjiagoushi-dsh-adapter' '$DSH_DIR/cordis.patch.yml'"
t "peer 依赖声明 dsh-tools + cordis" "grep -q '@deepseek-ai/dsh-tools' '$DSH_DIR/package.json' && grep -q '@deepseek-ai/cordis' '$DSH_DIR/package.json'"

echo "===== [dsh-adapter] 4. 插件新版 API 面 ====="
t "src/index.ts 用 Cordis apply + inject + defineTool" "grep -q 'export function apply(ctx' '$DSH_DIR/src/index.ts' && grep -q \"inject = \\['tools'\\]\" '$DSH_DIR/src/index.ts' && grep -q 'defineTool(' '$DSH_DIR/src/index.ts'"
t "加载即版本闸门（checkVersion + throw）" "grep -q 'checkVersion(' '$DSH_DIR/src/index.ts' && grep -q 'throw new Error' '$DSH_DIR/src/index.ts'"
t "桥接契约表 BRIDGE_MAP 覆盖 dev-standard/label/relay" "grep -q 'dev_standard.host' '$DSH_DIR/src/bridge.ts' && grep -q 'label.cli' '$DSH_DIR/src/bridge.ts' && grep -q 'relay_card' '$DSH_DIR/src/bridge.ts'"

echo "===== [dsh-adapter] 5. Agent Directory ====="
t "注册 6 个架构角色（架构·前缀）" "test \$(grep -c 'name: 架构·' '$DSH_DIR/dsh-collaboration-rules.yaml') -eq 6"
t "默认入口锁「架构·秘书」" "grep -q 'defaultRole: 架构·秘书' '$DSH_DIR/dsh-collaboration-rules.yaml'"

echo ""
echo "[dsh-adapter] pass=$pass fail=$fail"
[ "$fail" -eq 0 ] || exit 1
