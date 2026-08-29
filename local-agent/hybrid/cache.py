# -*- coding: utf-8 -*-
"""
FingerprintCache · 测试指纹缓存（测试智能优化层 T3）
====================================================
解决「某模块代码自上次跑通后没有变化，结果却重新算一遍」的重复劳动浪费。

核心能力：
  - `fingerprint(script)`   计算某测试覆盖源码的指纹（git blob hash 摘要）
  - `is_hit(script)`        判定该测试本次是否可命中缓存（源码未变+上次通过）
  - `mark(script, result)`  写入/更新某测试的缓存结果
  - `filter_hits(scripts)`  批量过滤出「可缓存跳过」的测试清单

指纹口径（保守可靠）：
  - 取该测试在 TestRegistry 中 `covers` 的源码文件，用 `git hash-object` 逐文件
    计算 blob hash，再 SHA1 摘要这些 hash 作为该测试的指纹。
  - 源码文件一变 → 指纹必变 → 缓存失效；指纹不变 → 复用上次 PASS 结果，零 CPU。

缓存持久化：
  - 走 data 层新增 `test_cache` 表（可追溯可回溯），由数据管理员统一口径。
  - 支持环境变量 `HYBRID_CACHE=off` 关闭（供 CI / 强制全量用）。
"""
import hashlib
import os
import subprocess

# 数据层（可选导入；失败则退化到内存缓存，不崩）
try:
    from data import repository as _repo
except Exception:  # noqa
    _repo = None

from hybrid import registry as _registry


class FingerprintCache(object):
    """测试指纹缓存。"""

    def __init__(self, root_dir=None, fp_len=7):
        self.root_dir = root_dir or os.getcwd()
        self.fp_len = fp_len      # git hash-object 摘要长度（默认 7）

    # ---------- 开关 ----------
    def enabled(self):
        """缓存是否启用（HYBRID_CACHE=off 关闭）。"""
        return os.environ.get("HYBRID_CACHE", "on").lower() != "off"

    # ---------- 指纹计算 ----------
    def _git_hash(self, path):
        """对单个文件计算 git blob hash（短摘要）。"""
        cmd = ["git", "hash-object", path]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=self.root_dir, timeout=30)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    def fingerprint(self, script):
        """计算某测试覆盖源码的指纹。

        返回形如 `sha1:abcdef0` 的指纹字符串；无覆盖源码返回 None。
        """
        covers = _registry.covers(script) or []
        if not covers:
            return None
        hashes = []
        for c in covers:
            # covers 相对 local-agent/ 前缀（与 registry 约定一致），也兼容裸路径
            for cand in self._resolve_covered(c):
                h = self._git_hash(cand)
                if h:
                    hashes.append(h)
                else:
                    # 目录：展开成实际文件
                    files = self._expand_covered(cand)
                    for f in files:
                        hh = self._git_hash(f)
                        if hh:
                            hashes.append(hh)
        if not hashes:
            return None
        digest = hashlib.sha1("|".join(sorted(hashes)).encode()).hexdigest()
        return "sha1:" + digest[:self.fp_len]


    def _resolve_covered(self, covered):
        """把 covers 路径解析成实际候选路径（兼容 local-agent/ 前缀与裸路径）。"""
        candidates = []
        # 绝对路径
        if os.path.isabs(covered):
            candidates.append(covered)
        else:
            # 裸路径（registry 约定相对 local-agent/）
            candidates.append(os.path.join(self.root_dir, "local-agent", covered))
            candidates.append(os.path.join(self.root_dir, covered))
        return candidates

    def _expand_covered(self, covered):
        """把 covers 里的目录/前缀展开成实际文件清单。"""
        import glob
        path = os.path.join(self.root_dir, covered) if not os.path.isabs(covered) else covered
        # 如果是目录
        if os.path.isdir(path):
            return [os.path.join(path, f) for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
        # 可能是前缀/glob
        if "*" in covered:
            return glob.glob(os.path.join(self.root_dir, covered))
        return [path]

    # ---------- 命中判定 ----------
    def _row(self, script, fp):
        if _repo is None:
            return None
        try:
            return _repo.get_test_cache(script, fp)
        except Exception:  # noqa
            return None

    def is_hit(self, script):
        """判定某测试本次是否可命中缓存（源码未变 + 上次 PASS）。

        返回 (hit: bool, fp: str|None)。命中表示可直接跳过执行复用结果。
        """
        if not self.enabled():
            return (False, None)
        fp = self.fingerprint(script)
        if not fp:
            return (False, None)
        row = self._row(script, fp)
        if row and row.get("status") == "pass":
            return (True, fp)
        return (False, fp)

    def mark(self, script, result=None, status="pass"):
        """写入/更新某测试的缓存结果。返回是否成功写入。"""
        fp = self.fingerprint(script)
        if not fp:
            return False
        if _repo is None:
            return False
        try:
            _repo.upsert_test_cache(script, fp, result or {}, status)
            return True
        except Exception:  # noqa
            return False

    # ---------- 批量 ----------
    def filter_hits(self, scripts):
        """批量过滤：输入测试清单 → 返回 (hits, misses)。

        hits   = 可命中缓存直接跳过的测试（带缓存结果）
        misses = 需实际执行的测试（源码有变/无缓存/上次失败）
        """
        hits, misses = [], []
        for s in scripts:
            hit, fp = self.is_hit(s)
            if hit:
                row = self._row(s, fp)
                hits.append({"script": s, "fingerprint": fp,
                             "result": row.get("result", {}) if row else {}})
            else:
                misses.append(s)
        return hits, misses


# 便捷单例
default_cache = FingerprintCache()
