#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# ============================================================
# ci-ensure-node —— 让 CI 具备「能跑 dsh-adapter TS 信号灯」的 node（Issue #175）
# ============================================================
# 为什么需要：dsh-adapter 的 TS 侧信号灯用 `node --experimental-strip-types`
# （Node >= 22.6；dsh-adapter/package.json engines 要求 ^22.19 || >=24）。
# 而 python:3.11 镜像默认无 node，`apt-get install nodejs` 给的是 v20.19 →
# 报 `node: bad option: --experimental-strip-types`，装了照样 3 项全红。
# 所以「有 node」不等于「node 能用」：**按能力判定，不按存在判定**。
#
# 策略（先便宜后贵，任一路成功即止）：
#   ① 已有可用 node（能认 --experimental-strip-types）→ 直接用；
#   ② 官方 tarball（nodejs.org）→ /usr/local（与镜像 glibc 兼容）；
#   ③ Debian/Ubuntu 发行版只用 NodeSource apt（不裸装 apt nodejs，那是 v20）。
# 最终仍不可用 → 非零退出（**不静默跳过**：跳过会变成"没跑也算过"的假绿）。
#
# 用法：bash scripts/ci-ensure-node.sh [--check-only]
#   --check-only  只核验不安装（本地/自测用）
# 退出码：0 = node 可用且支持 TS 剥离；1 = 装不上/不满足
# ============================================================
set -uo pipefail

NODE_MIN_MAJOR=22
NODE_MIN_MINOR=6
NODE_VERSION="${CI_NODE_VERSION:-v22.19.0}"
NODE_BASE_URL="${CI_NODE_BASE_URL:-https://nodejs.org/dist}"

# TS 剥离能力探测：老 node 不认该 flag（exit != 0 且 stderr 报 bad option）
node_supports_ts_strip() {
  local bin="${1:-node}"
  command -v "$bin" >/dev/null 2>&1 || return 1
  local out
  out="$("$bin" --experimental-strip-types --version 2>&1)" || return 1
  case "$out" in
    *"bad option"*|*"not recognized"*|*"Unknown"*) return 1 ;;
  esac
  return 0
}

node_version_ok() {
  command -v node >/dev/null 2>&1 || return 1
  node -e '
    const [maj, min] = process.versions.node.split(".").map(Number);
    process.exit(maj > 22 || (maj === 22 && min >= 6) ? 0 : 1);
  ' >/dev/null 2>&1 || return 1
  return 0
}

usable() {
  node_version_ok && node_supports_ts_strip && return 0
  return 1
}

report_ok() {
  echo "  ✅ node $(node --version)（$(command -v node)）· 支持 --experimental-strip-types"
}

if usable; then
  report_ok
  exit 0
fi

if [ "${1:-}" = "--check-only" ]; then
  echo "  ❌ node 不可用或不支持 --experimental-strip-types" >&2
  exit 1
fi

# ---- ② 官方 tarball ----
install_from_tarball() {
  local arch tarball tmpdir url
  arch="$(uname -m 2>/dev/null || echo unknown)"
  case "$arch" in
    x86_64|amd64) arch=x64 ;;
    aarch64|arm64) arch=arm64 ;;
    *) echo "  -- 未知架构 $arch，跳过官方 tarball" >&2; return 1 ;;
  esac
  tarball="node-${NODE_VERSION}-linux-${arch}.tar.xz"
  url="${NODE_BASE_URL}/${NODE_VERSION}/${tarball}"
  tmpdir="$(mktemp -d)"
  echo "  · 下载官方 node ${NODE_VERSION}（${arch}）"
  if curl -fsSL --retry 2 --connect-timeout 10 -o "$tmpdir/$tarball" "$url" 2>/dev/null \
     || curl -fsSL --retry 2 --connect-timeout 10 -o "$tmpdir/$tarball" "$url"; then :; else
    rm -rf "$tmpdir"; return 1
  fi
  if ! tar -xJf "$tmpdir/$tarball" -C "$tmpdir" 2>/dev/null; then
    rm -rf "$tmpdir"; return 1
  fi
  # 装到 /usr/local（优先于发行版 /usr/bin/node，不污染系统包）
  if cp -a "$tmpdir/node-${NODE_VERSION}-linux-${arch}/." /usr/local/ 2>/dev/null; then
    rm -rf "$tmpdir"
    hash -r 2>/dev/null || true
    return 0
  fi
  rm -rf "$tmpdir"; return 1
}

# ---- ③ NodeSource apt（发行版兜底，明确避开裸 apt nodejs 的 v20）----
install_from_nodesource() {
  command -v curl >/dev/null 2>&1 || return 1
  echo "  · 尝试 NodeSource apt 源（node 22.x）"
  ( curl -fsSL "https://deb.nodesource.com/setup_22.x" -o /tmp/nodesource_setup.sh \
    && bash /tmp/nodesource_setup.sh ) >/dev/null 2>&1 || return 1
  ( apt-get install -y -qq nodejs ) >/dev/null 2>&1 || return 1
  hash -r 2>/dev/null || true
  return 0
}

echo "==== [ci-ensure-node] 准备可用 node（需 >= ${NODE_MIN_MAJOR}.${NODE_MIN_MINOR}，支持 --experimental-strip-types） ===="
if command -v node >/dev/null 2>&1; then
  echo "  -- 现有 node $(node --version) 不可用（版本或缺 TS 剥离），升级中"
fi

install_from_tarball || true
usable && { report_ok; exit 0; }

install_from_nodesource || true
usable && { report_ok; exit 0; }

echo "  ❌ 无法获得可用 node（>= ${NODE_MIN_MAJOR}.${NODE_MIN_MINOR} + --experimental-strip-types）" >&2
if command -v node >/dev/null 2>&1; then
  echo "     现装版本: $(node --version)（$(command -v node)）" >&2
fi
echo "     → 不静默跳过：TS 侧信号灯没真跑就等于没做完，本作业应失败" >&2
exit 1
