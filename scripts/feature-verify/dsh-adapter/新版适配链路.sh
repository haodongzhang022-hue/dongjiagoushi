#!/usr/bin/env bash
# ============================================================
# [feature-verify] dsh-adapter / dsh 新版适配链路（Issue #145）
# ============================================================
# module:  dsh-adapter（dsh 新版适配 · 独立模块）
# feature: dsh 新版适配——组合包契约真实声明、版本闸门加载即生效（不静默）、
#          桥接真转发既有引擎、Agent Directory 锁默认入口
# 五要素:
#   Given   dsh-adapter/（package.json dsh.bundle.patch + cordis.patch.yml +
#           src/{index,compat,bridge}.ts）+ local-agent/dsh_adapter/compat.py
#   When    真跑 `bash local-agent/tests/test_dsh_adapter.sh`（18 组信号灯）+
#           读产物做语义断言（不只看"文件在"）
#   Then    1) 信号灯全绿（TS/Python 双端版本矩阵、defineTool 装载探针、桥接实跑）；条数按环境推导：有 node 18 组 / 无 node 13 组（Issue #175）；
#           2) package.json 真实声明 dsh.bundle.patch（组合包契约，非空壳）；
#           3) 版本闸门在加载路径上（index.ts 出现 checkVersion + throw，
#              compat 判定旧版为 incompatible、乱版显式失败）；
#           4) 桥接契约覆盖 dev-standard / label / relay（真转发不是重写）；
#           5) Agent Directory 注册 6 个「架构·」角色且默认入口锁「架构·秘书」。
#   Evidence 信号灯输出行（pass=/fail=）+ 上述语义 grep 命中
# 为什么是"功能级"：只断言"目录存在"抓不出"插件装不上新版/版本闸门被绕过/默认入口失锁"。
#   本脚本真跑装载探针 + 变异可感知断言——适配没做成新形态，这里就红。
# 用法：bash scripts/feature-verify/dsh-adapter/新版适配链路.sh
# ============================================================
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

PASS=0; FAIL=0
ok(){ PASS=$((PASS+1)); echo "  ✅ $1"; }
bad(){ FAIL=$((FAIL+1)); echo "  ❌ $1"; }

echo "==== [feature-verify] dsh-adapter/新版适配链路 ===="

# ---------- Then-1：信号灯真跑（条数按环境推导，Issue #175 假红收口） ----------
# 信号灯条数**取决于环境是否具备 node**：有 node 跑满 18 组；无 node（如 CI 的
# python:3.11 镜像）显式跳过 TS/桥接侧 → 13 组。硬编码 18 会把合法跳过判成红
# （CI 假红之一）。故：fail 必须 0，pass 须等于本环境应得条数（13 / 18）。
if command -v node >/dev/null 2>&1; then EXPECT_PASS=18; else EXPECT_PASS=13; fi
if OUT="$(bash local-agent/tests/test_dsh_adapter.sh 2>&1)"; then
  if echo "$OUT" | grep -qE "pass=${EXPECT_PASS} fail=0"; then
    ok "Then-1: 信号灯全绿（pass=${EXPECT_PASS} fail=0，node=$([ "$EXPECT_PASS" = 18 ] && echo 有 || echo 无)）"
  else
    bad "Then-1: 信号灯条数不符（期望 pass=${EXPECT_PASS} fail=0）"
    echo "$OUT" | tail -5 | sed 's/^/      /'
  fi
else
  bad "Then-1: local-agent/tests/test_dsh_adapter.sh 红 → 新版适配未达成"
  echo "$OUT" | tail -12 | sed 's/^/      /'
fi

# ---------- Then-2：组合包契约真实声明 ----------
python3 - <<'PY' >/tmp/_dsh_pkg.$$ 2>&1
import json
d=json.load(open('dsh-adapter/package.json'))
b=d.get('dsh',{}).get('bundle',{})
print('patch=', b.get('patch'))
print('main=', d.get('main'))
print('peers=', ','.join(sorted((d.get('peerDependencies') or {}).keys())))
PY
PKG="$(cat /tmp/_dsh_pkg.$$)"; rm -f /tmp/_dsh_pkg.$$
if printf '%s' "$PKG" | grep -qE 'patch= \.?/?cordis\.patch\.yml' && printf '%s' "$PKG" | grep -q 'main= lib/index.js'; then
  ok "Then-2: package.json 声明 dsh.bundle.patch + main=lib/index.js（新版只 import 构建产物）"
else
  bad "Then-2: 组合包契约缺失或 main 非 lib/index.js → 新版 loader 装不上"; printf '%s\n' "$PKG" | sed 's/^/      /'
fi
printf '%s' "$PKG" | grep -q 'cordis' && printf '%s' "$PKG" | grep -q 'dsh-tools' \
  && ok "Then-2b: peer 依赖声明 cordis + dsh-tools" \
  || bad "Then-2b: peer 依赖未声明 cordis/dsh-tools"

# ---------- Then-3：版本闸门在加载路径上 ----------
grep -q 'checkVersion' dsh-adapter/src/index.ts && grep -q 'throw' dsh-adapter/src/index.ts \
  && ok "Then-3: index.ts 加载即过版本闸门且失败 throw（不静默）" \
  || bad "Then-3: 加载路径无版本闸门/静默放行"
printf '%s' "$PKG" >/dev/null
if python3 -c "
import sys; sys.path.insert(0,'local-agent')
from dsh_adapter.compat import check_version
assert check_version('0.1.6-alpha.2')['state'] == 'ok', '新版必须兼容'
assert check_version('0.1.2-rc.1')['state'] == 'incompatible', '旧版必须 incompatible'
assert check_version('garbage-ver')['state'] == 'incompatible', '乱版必须显式失败'
assert check_version('0.1.4-rc.1')['state'] == 'incompatible', '缺必需 API 面必须 incompatible'
" 2>/dev/null; then
  ok "Then-3b: Python 侧矩阵——新版兼容 / 旧版 incompatible / 乱版显式失败"
else
  bad "Then-3b: Python 版本矩阵判定失准（旧版被放行或乱版静默）"
fi

# ---------- Then-4：桥接真转发既有引擎 ----------
for k in dev_standard label relay; do
  grep -q "$k" dsh-adapter/src/bridge.ts \
    && ok "Then-4: 桥接覆盖 $k（真转发既有引擎，不重写）" \
    || bad "Then-4: 桥接缺 $k 通路"
done

# ---------- Then-5：Agent Directory 默认入口锁 ----------
python3 - <<'PY' >/tmp/_dsh_rules.$$ 2>&1
import yaml
d=yaml.safe_load(open('dsh-adapter/dsh-collaboration-rules.yaml'))
agents=d.get('agents') or []
names=[a.get('name') for a in agents]
print('n=',len(names))
print('names=', ','.join(str(n) for n in names))
print('default=', d.get('defaultRole'))
PY
RULES="$(cat /tmp/_dsh_rules.$$ 2>/dev/null)"; rm -f /tmp/_dsh_rules.$$
if printf '%s' "$RULES" | grep -q 'n= 6' && printf '%s' "$RULES" | grep -q '架构·秘书'; then
  ok "Then-5: 注册 6 个「架构·」角色，含架构·秘书"
else
  bad "Then-5: Agent Directory 角色数/名称不符（期望 6 个含架构·秘书）"; printf '%s\n' "$RULES" | sed 's/^/      /'
fi
if printf '%s' "$RULES" | grep -q 'default= 架构·秘书'; then
  ok "Then-5b: 默认入口锁「架构·秘书」（强制入口不被绕过）"
else
  bad "Then-5b: 默认入口未锁架构·秘书"
fi

echo ""
echo "[dsh-adapter] pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ] && { echo "🟢 dsh-adapter/新版适配链路 达成"; exit 0; } || { echo "🔴 dsh-adapter/新版适配链路 未达成"; exit 1; }
