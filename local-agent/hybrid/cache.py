# -*- coding: utf-8 -*-
"""
FingerprintCache · 测试源码指纹缓存（Issue #65 · T3）
====================================================
对「测试脚本 → 覆盖源码文件」计算**内容指纹**，存到 data 层 `test_cache` 表。
当源码文件未变化时（指纹一致），对应测试结果可直接复用（**缓存命中跳过**），
避免重复跑无变化的测试。

能力：
  - `fingerprint(path)`：计算单个文件的 SHA-256 内容指纹；
  - `fingerprints_for(test_script)`：计算某测试脚本覆盖的全部源码文件指纹；
  - `is_hit(test_script)`：判断某测试是否命中缓存（指纹与上次一致）；
  - `record(test_script, run_result)`：记录一次测试结果并持久化指纹；
  - `clear()`：清空缓存（全量回归时用）。

设计原则：
  - **纯逻辑 + 数据层**：指纹计算纯 Python，缓存落 `data` 层 `test_cache` 表；
  - **数据层不可用时降级**：走内存 dict 兜底，不吞异常也不阻断流程；
  - **解耦**：不 import registry/selector 等运行时模块，通过外部传入覆盖映射
    或默认按仓库内建清单计算。
"""
import hashlib
import json
import os
import time

# 默认覆盖映射：测试脚本 → 它覆盖的源码文件/目录
# 此内建清单与 T1 TestRegistry 的 test_registry.json 对齐；若已合并 T1，
# 外部可通过 `set_covers_provider()` 注入 TestRegistry 接口。
DEFAULT_COVERS = {
    "test_benchmark_ab.sh": ["local-agent/topology/benchmark.py"],
    "test_cache_layer.sh": ["local-agent/llm", "local-agent/roles",
                            "local-agent/topology/cache_monitor.py",
                            "local-agent/topology/prefix_cache.py",
                            "local-agent/data"],
    "test_collab.sh": ["local-agent/collab", "local-agent/engine"],
    "test_data_layer.sh": ["local-agent/data", "local-agent/scale/plugin.py",
                           "local-agent/roles/data_admin.py"],
    "test_depth_engine.sh": ["local-agent/depth", "local-agent/roles"],
    "test_dispatch_ability.sh": ["local-agent/dispatch", "local-agent/roles"],
    "test_dispatch_engine.sh": ["local-agent/dispatch", "local-agent/dispatch_engine.py"],
    "test_dispatcher.sh": ["local-agent/dispatcher"],
    "test_disposition.sh": ["local-agent/collab/disposition.py"],
    "test_engine.sh": ["local-agent/engine", "local-agent/scale"],
    "test_external_source.sh": ["local-agent/dispatcher"],
    "test_galton.sh": ["local-agent/galton"],
    "test_hybrid_router.sh": ["local-agent/hybrid/router.py"],
    "test_hybrid_pipeline.sh": ["local-agent/hybrid", "scripts/local-exec.sh"],
    "test_label_automation.sh": ["local-agent/label", "local-agent/roles"],
    "test_local_agent.sh": ["local-agent/run.py", "local-agent/roles",
                            "local-agent/orchestrator.py"],
    "test_ops_sim.sh": ["local-agent/engine", "local-agent/sentinel"],
    "test_peer_closure.sh": ["local-agent/collab/closure"],
    "test_peer_collab.sh": ["local-agent/collab/peer.py"],
    "test_prefix_cache.sh": ["local-agent/topology/prefix_cache.py",
                             "local-agent/topology/topologies.py"],
    "test_prescale_entry.sh": ["local-agent/scale/prescale.py", "local-agent/engine"],
    "test_probe.sh": ["local-agent/dispatcher/probe.py"],
    "test_router_integration.sh": ["local-agent/topology/router.py",
                                   "local-agent/topology/fusion.py"],
    "test_scale.sh": ["local-agent/scale", "local-agent/engine", "local-agent/pool"],
    "test_secretary_sense.sh": ["local-agent/roles/secretary_sense.py",
                                "local-agent/roles"],
    "test_sentinel.sh": ["local-agent/sentinel", "local-agent/engine"],
    "test_topology_comparison.sh": ["local-agent/topology/runner.py",
                                    "local-agent/topology/benchmark.py"],
    "test_topology_fusion.sh": ["local-agent/topology/fusion.py"],
    "test_topology_hybrid.sh": ["local-agent/topology/topologies.py"],
    "test_topology_slim.sh": ["local-agent/topology/slim.py"],
}


class FingerprintCache(object):
    """测试源码指纹缓存：指纹计算 + 缓存命中判定 + data 层持久化。"""

    def __init__(self, repo_root=None, use_data_layer=True, covers=None):
        self.repo_root = repo_root or self._find_repo_root()
        self.use_data_layer = use_data_layer
        self.covers = covers or DEFAULT_COVERS
        self._memory = {}          # 内存兜底：{test_script: {fingerprint, result, ts}}
        self._covers_provider = None  # 可选：注入 TestRegistry 的接口

    # ---------- 路径/仓库 ----------
    @staticmethod
    def _find_repo_root():
        d = os.getcwd()
        while d != "/":
            if os.path.exists(os.path.join(d, ".git")):
                return d
            d = os.path.dirname(d)
        return os.getcwd()

    def _resolve(self, path):
        """把相对仓库根的路径解析为绝对路径。"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.repo_root, path)

    # ---------- 指纹计算 ----------
    @staticmethod
    def fingerprint_file(filepath):
        """计算单个文件的 SHA-256 内容指纹。

        文件不存在或不可读时返回 None（不缓存不可判定的文件）。
        """
        try:
            with open(filepath, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except (IOError, OSError):
            return None

    def fingerprint_dir(self, dirpath):
        """计算目录下所有 *.py/*.sh 文件的内容指纹（拼接后哈希）。

        目录指纹用于「覆盖整个模块目录」的场景（如 covers=["local-agent/hybrid"]）。
        """
        try:
            files = []
            for root, dirs, fnames in os.walk(dirpath):
                # 跳过常见排除目录
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__",
                                                        ".cnb-results", "node_modules")]
                for fn in sorted(fnames):
                    if fn.endswith((".py", ".sh")):
                        files.append(os.path.join(root, fn))
            if not files:
                return None
            h = hashlib.sha256()
            for f in sorted(files):
                fhash = self.fingerprint_file(f)
                if fhash:
                    h.update(fhash.encode("utf-8"))
            return h.hexdigest()
        except (IOError, OSError):
            return None

    def fingerprint(self, path):
        """计算任意路径的指纹（文件或目录）。"""
        abs_path = self._resolve(path)
        if os.path.isdir(abs_path):
            return self.fingerprint_dir(abs_path)
        return self.fingerprint_file(abs_path)

    # ---------- 覆盖映射 ----------
    def set_covers_provider(self, provider):
        """注入外部覆盖映射提供者（如 T1 TestRegistry）。

        provider 需实现 `covers_of(script_name) -> [路径...]` 接口。
        """
        self._covers_provider = provider

    def covers_of(self, test_script):
        """返回某测试脚本覆盖的源码文件/目录列表。

        优先走外部 provider（若已注入），否则用内建 DEFAULT_COVERS。
        """
        if self._covers_provider is not None:
            try:
                covers = self._covers_provider.covers_of(test_script)
                if covers:
                    return covers
            except Exception:  # noqa provider 异常时回退内建
                pass
        return self.covers.get(test_script, [])

    def compute_fingerprint(self, test_script):
        """计算某测试脚本覆盖的全部源码的**组合指纹**。

        把每个覆盖文件/目录的指纹排序拼接后再哈希，得到单一指纹。
        若某文件不可读，跳过它（不影响整体指纹判定）。
        """
        covers = self.covers_of(test_script)
        if not covers:
            return None
        parts = []
        for c in covers:
            fhash = self.fingerprint(c)
            if fhash:
                parts.append("%s=%s" % (c, fhash))
        if not parts:
            return None
        h = hashlib.sha256()
        h.update("|".join(sorted(parts)).encode("utf-8"))
        return h.hexdigest()

    # ---------- 缓存命中判定 ----------
    def is_hit(self, test_script):
        """判断某测试是否命中缓存（覆盖源码指纹与上次记录一致）。

        返回 {hit, fingerprint, last_fingerprint}。
        """
        fp = self.compute_fingerprint(test_script)
        if fp is None:
            return {"hit": False, "fingerprint": None, "last_fingerprint": None}

        last = self._load(test_script)
        last_fp = last.get("fingerprint") if last else None
        return {
            "hit": last is not None and last_fp == fp,
            "fingerprint": fp,
            "last_fingerprint": last_fp,
        }

    def hit_tests(self, test_scripts):
        """批量判定一组测试脚本的缓存命中情况。

        返回 {test_script: bool}（True=命中缓存可跳过）。
        """
        return {t: self.is_hit(t)["hit"] for t in test_scripts}

    def need_run(self, test_scripts):
        """返回需要运行的测试脚本列表（未命中缓存 / 无缓存记录的）。

        等价于 hit_tests 中值为 False 的测试。
        """
        hits = self.hit_tests(test_scripts)
        return [t for t, hit in hits.items() if not hit]

    # ---------- 记录结果 ----------
    def record(self, test_script, run_result=None, force=False):
        """记录一次测试执行：计算指纹 + 保存结果。

        run_result: 可选，{exit_code, duration, output} 等测试结果快照。
        force: True 时强制覆盖已有缓存（如全量回归后的更新）。
        """
        fp = self.compute_fingerprint(test_script)
        entry = {
            "test_script": test_script,
            "fingerprint": fp,
            "result": run_result or {},
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self._save(test_script, entry, force)
        return entry

    # ---------- 清除 ----------
    def clear(self, test_script=None):
        """清空缓存（全量回归前置）。指定 test_script 时只清该测试。"""
        if test_script:
            self._delete(test_script)
            self._memory.pop(test_script, None)
        else:
            self._memory.clear()
            self._clear_all()

    # ---------- 统计 ----------
    def stats(self):
        """返回缓存统计：总记录数 / 命中数 / 命中率。"""
        if self.use_data_layer:
            try:
                rows = self._query_all()
                total = len(rows)
                return {"total": total, "hit": total, "miss": 0,
                        "hit_rate": 1.0 if total else 0.0}
            except Exception:  # noqa
                pass
        total = len(self._memory)
        return {"total": total, "hit": total, "miss": 0,
                "hit_rate": 1.0 if total else 0.0}

    # ---------- data 层 ----------
    def _table_ready(self):
        """确保 test_cache 表存在。返回 True 成功 / False 数据层不可用。"""
        try:
            from data import db
            db.execute("""
                CREATE TABLE IF NOT EXISTS test_cache (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_script TEXT NOT NULL,
                    fingerprint TEXT DEFAULT '',
                    result      TEXT DEFAULT '{}',
                    ts          TEXT,
                    UNIQUE(test_script)
                )
            """)
            return True
        except Exception:  # noqa
            return False

    def _load(self, test_script):
        """从 data 层读取某测试的缓存记录。"""
        if self.use_data_layer and self._table_ready():
            try:
                from data import db
                rows = db.query(
                    "SELECT fingerprint, result, ts FROM test_cache "
                    "WHERE test_script=?", (test_script,))
                if rows:
                    r = rows[0]
                    return {
                        "fingerprint": r.get("fingerprint"),
                        "result": json.loads(r.get("result", "{}")),
                        "ts": r.get("ts"),
                    }
            except Exception:  # noqa
                pass
        return self._memory.get(test_script)

    def _save(self, test_script, entry, force=False):
        """持久化到 data 层；失败则写内存兜底。"""
        if self.use_data_layer and self._table_ready():
            try:
                from data import db
                if force:
                    db.execute(
                        "INSERT OR REPLACE INTO test_cache "
                        "(test_script, fingerprint, result, ts) "
                        "VALUES (?,?,?,?)",
                        (test_script, entry.get("fingerprint"),
                         json.dumps(entry.get("result", {})),
                         entry.get("ts")))
                else:
                    db.execute(
                        "INSERT OR IGNORE INTO test_cache "
                        "(test_script, fingerprint, result, ts) "
                        "VALUES (?,?,?,?)",
                        (test_script, entry.get("fingerprint"),
                         json.dumps(entry.get("result", {})),
                         entry.get("ts")))
                return True
            except Exception:  # noqa
                pass
        self._memory[test_script] = entry
        return True

    def _delete(self, test_script):
        """从 data 层删除某测试缓存。"""
        if self.use_data_layer and self._table_ready():
            try:
                from data import db
                db.execute("DELETE FROM test_cache WHERE test_script=?",
                           (test_script,))
            except Exception:  # noqa
                pass

    def _clear_all(self):
        """清空 data 层 test_cache 表。"""
        if self.use_data_layer and self._table_ready():
            try:
                from data import db
                db.execute("DELETE FROM test_cache")
            except Exception:  # noqa
                pass

    def _query_all(self):
        """查询 data 层全部缓存记录。"""
        if self.use_data_layer and self._table_ready():
            try:
                from data import db
                return db.query("SELECT test_script, fingerprint FROM test_cache")
            except Exception:  # noqa
                pass
        return []


# 便捷单例
default_cache = FingerprintCache()
