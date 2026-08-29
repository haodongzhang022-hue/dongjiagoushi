# -*- coding: utf-8 -*-
"""
PolicyEngine · 策略引擎（测试智能优化层 T5）
============================================
把「incremental（增量）/ cache（缓存）/ parallel（并行）/ full（全量）」
各开关的决策规则配置化，根据 CI 上下文决定本次「跑哪些 + 怎么跑」。

核心能力：
  - `decide(...)`   给定配置 + 变更信息 → 返回执行策略（测试清单 + 并行度 + 模式）
  - 全量回归周期策略：默认每 7 天强制一次全量回归（防增量/缓存漏测累积）
  - 各开关可配：incremental/cache/parallel/full 独立开关

依赖关系（架构方案）：
  - Registry + Selector（T1/T2）：增量选择受影响测试
  - Cache（T3）：缓存命中跳过
  - Parallel（T4）：并行执行
  - CostReporter（T6）：成本报表（策略执行后消费）
"""
import os
import time


DEFAULT_FULL_REGRESSION_DAYS = 7    # 默认全量回归周期（天）


class PolicyEngine(object):
    """策略引擎。"""

    def __init__(self, full_regression_days=DEFAULT_FULL_REGRESSION_DAYS):
        self.full_regression_days = full_regression_days

    # ---------- 配置 ----------
    def config(self, incremental=True, cache=True, parallel=True, full=True):
        """返回策略配置快照（供 decide 消费）。"""
        return {
            "incremental": incremental,   # 增量选择（只跑受变更影响的测试）
            "cache": cache,               # 缓存命中跳过（源码未变复用上次结果）
            "parallel": parallel,         # 并行执行（-P）
            "full": full,                 # 全量回归开关（周期强制）
        }

    def _env_cfg(self, overrides=None):
        """从环境变量 + overrides 合并出最终配置。

        环境变量：HYBRID_INCREMENTAL / HYBRID_CACHE / HYBRID_PARALLEL / HYBRID_FULL
        （'0'/'false'/'off' 视为关闭）
        """
        cfg = self.config()
        for key, var in [("incremental", "HYBRID_INCREMENTAL"),
                         ("cache", "HYBRID_CACHE"),
                         ("parallel", "HYBRID_PARALLEL"),
                         ("full", "HYBRID_FULL")]:
            val = os.environ.get(var)
            if val is not None:
                cfg[key] = str(val).lower() not in ("0", "false", "off", "no")
        if overrides:
            cfg.update({k: v for k, v in overrides.items() if k in cfg})
        return cfg

    # ---------- 全量回归周期判定 ----------
    def full_regression_due(self, last_full_ts=None):
        """判定全量回归是否到期（默认每 7 天一次）。

        last_full_ts：上次全量回归时间戳（epoch 秒 / ISO 字符串 / None）。
        返回 True=需要全量回归。
        """
        if not self.full_regression_days or self.full_regression_days <= 0:
            return True
        if not last_full_ts:
            return True
        # 解析时间戳
        if isinstance(last_full_ts, (int, float)):
            last = float(last_full_ts)
        else:
            try:
                # 兼容 ISO 字符串
                last = time.mktime(time.strptime(last_full_ts, "%Y-%m-%dT%H:%M:%S"))
            except Exception:  # noqa
                try:
                    # 兼容 epoch 秒字符串
                    last = float(last_full_ts)
                except (TypeError, ValueError):  # noqa
                    return True
        elapsed_days = (time.time() - last) / 86400.0
        return elapsed_days >= self.full_regression_days

    # ---------- 决策 ----------
    def decide(self, changed_files=None, cache=None, selector=None,
               full_suite=None, last_full_ts=None, overrides=None):
        """核心决策：给定变更 + 可选组件 → 返回执行策略。

        changed_files: git diff 变更文件清单（增量输入）
        cache:         FingerprintCache 实例（T3，可选）
        selector:      IncrementalSelector 实例（T2，可选）
        full_suite:    全量测试清单 callable/列表
        last_full_ts:  上次全量回归时间戳
        overrides:     配置覆盖（incremental/cache/parallel/full 布尔）

        返回策略 dict：
          {
            mode:      'incremental' | 'full'（本次走增量还是全量）
            tests:     需执行的测试清单（已剔除缓存命中）
            cache_hits:缓存命中跳过的测试（复用结果，零 CPU）
            parallel:  并行度（parallel 开关）
            switches:  本次各开关生效状态
            reason:    决策说明
          }
        """
        cfg = self._env_cfg(overrides)

        # 全量回归强制（优先级最高）
        if cfg["full"] and self.full_regression_due(last_full_ts):
            suite = full_suite
            if callable(suite):
                suite = suite()
            tests = list(suite or []) if suite else []
            cache_hits = []
            parallel = 4 if cfg["parallel"] else 1
            return {
                "mode": "full", "tests": tests, "cache_hits": cache_hits,
                "parallel": parallel, "switches": cfg,
                "reason": "全量回归周期到期（%s 天）" % self.full_regression_days,
            }

        # 增量选择
        tests = []
        if cfg["incremental"] and changed_files and selector is not None:
            tests = selector.select(changed_files)
            mode = "incremental"
            reason = "增量选择：%d 个变更文件 → %d 个受影响测试" % (
                len(changed_files), len(tests))
        else:
            # 无增量信息/开关关 → 走全量兜底
            suite = full_suite
            if callable(suite):
                suite = suite()
            tests = list(suite or []) if suite else []
            mode = "full"
            reason = "增量未启用/无变更信息，全量兜底"

        # 缓存命中剔除
        cache_hits = []
        if cfg["cache"] and cache is not None and tests:
            cache_hits, tests = cache.filter_hits(tests)
            if cache_hits:
                reason += "；缓存命中跳过 %d 个" % len(cache_hits)

        parallel = 4 if cfg["parallel"] else 1
        return {
            "mode": mode, "tests": tests, "cache_hits": cache_hits,
            "parallel": parallel, "switches": cfg, "reason": reason,
        }


# 便捷单例
default_policy = PolicyEngine()
