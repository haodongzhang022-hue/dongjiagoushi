# -*- coding: utf-8 -*-
"""
有效性度量模型 · 确定性引擎（engine）
=====================================
把 Issue #100 决策 ⑤ 的"有效性度量细化分档"落成**可量化、可判定、可留痕**的
确定性引擎。核心是用户拍板的两个要点：

  1. **多维**：不只"解决率"，还含小八哥率 / 稳定性 / 通用性 / 跨场景一致性；
  2. **概率 × 程度分档**：不用单一均值，而是用 profile = 一组
     `(prob, degree)` 分布，如 "10% 概率 99% 解决；20% 概率 98% 解决"，
     规避"10 个问题有的 30% 有的 60% 算增加还是减少"的聚合歧义。

设计原则（对齐决策 ②④"以测试为准、可量化评估"）：
  - `profile()` 是确定性分类器：给定观测，必然产出归一化的分档分布；
  - `aggregate()` 归并多次观测，输出每维档位质量分布 + 总体有效度，不用歧义均值；
  - `judge()` 给出确定性达标/不达标判定（对照 spec.JUDGE_THRESHOLDS）；
  - `trace()` 把每次度量的观测与结果落库/留痕，供回溯与监控。

数据结构（观测观测物 observation）：
    {
      "target":      "issue/task/pr id（本次度量对象）",
      "kind":        "review_intervention | direct_fix | deliverable",
      "dims": {                      # 维度 → 概率×程度分布（prob 之和 ≤ 1）
        "resolution": [{"prob": .1, "degree": .99}, {"prob": .9, "degree": .3}],
        "bug_rate":   [{"prob": .8, "degree": .0}, {"prob": .2, "degree": .5}],
        "stability":  [{"prob": 1,  "degree": .98}],
        "generality": [{"prob": .7, "degree": .9}, {"prob": .3, "degree": .5}],
        "consistency":[{"prob": 1,  "degree": .95}],
      }
    }
  注：bug_rate 的 degree 是"引入缺陷概率"（越低越好），engine 会翻转为
  有效度 1-degree；其余维度 degree 本身"越高越好"。

对外接口：
  - normalize_profile(obs)             归一化观测（概率和 ≤1、degree∈[0,1]）
  - band_degree(dim, degree)           把某程度映射到档位（按 direction 翻转）
  - dim_result(obs_dim_profile, dim)   单维 → {mass_per_band, high_mass, weighted_degree}
  - aggregate(observations)            多维归并 → {per_dim, overall}
  - judge(result)                      确定性达标判定 → {verdicts, passed}
  - trace(observation, result)         留痕（写 state + 返回 trace_id）
"""
import json
import os
import threading
import time
import uuid

try:
    from data import admin
except Exception:  # noqa: BLE001
    admin = None

from . import spec

# ---------------- 兜底留痕（与 spec 同目录 state 文件） ----------------
_TRACE_LOCK = threading.Lock()
_TRACE = []
_TRACE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "review_metrics_trace.json",
)


def _persist():
    try:
        os.makedirs(os.path.dirname(_TRACE_FILE), exist_ok=True)
        with open(_TRACE_FILE, "w", encoding="utf-8") as f:
            json.dump(_TRACE, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


# ======================================================================
# ① 归一化观测
# ======================================================================
def normalize_profile(obs):
    """归一化观测：把 dims 里每维的 prob 归一化和≤1、degree 夹到 [0,1]。
    返回统一结构的 dict，未知维度报错（防自造指标）。"""
    if not obs:
        raise ValueError("observation is empty")
    dims_in = obs.get("dims", {})
    out_dims = {}
    for dim, bins in dims_in.items():
        spec.dim_spec(dim)               # 校验规范维度，未知抛 KeyError
        norm = []
        total = 0.0
        for b in bins:
            p = max(0.0, min(1.0, float(b.get("prob", 0.0))))
            d = max(0.0, min(1.0, float(b.get("degree", 0.0))))
            norm.append({"prob": p, "degree": d})
            total += p
        # prob 和 > 1 → 等比例缩到 1（归一）
        if total > 1.0 and norm:
            k = 1.0 / total
            norm = [{"prob": b["prob"] * k, "degree": b["degree"]} for b in norm]
        # 未覆盖的剩余概率质量 → 补一个中性档（degree=0.5，防"缺数据直接满分/零分"）
        remain = 1.0 - sum(b["prob"] for b in norm)
        if remain > 1e-9:
            norm.append({"prob": round(remain, 6), "degree": 0.5})
        out_dims[dim] = norm
    return {"target": obs.get("target", "?"),
            "kind": obs.get("kind", "observation"),
            "dims": out_dims}


# ======================================================================
# ② 档位映射（按方向翻转后分档）
# ======================================================================
def _eff_degree(dim, degree):
    """把原始 degree 折算成"越高越好"的有效度 degree。
    方向 -1 的维度（bug_rate）翻转：有效度 = 1 - 引入缺陷概率。"""
    meta = spec.dim_spec(dim)
    return 1.0 - degree if meta["direction"] == -1 else degree


def band_degree(dim, degree):
    """把某程度映射到档位名（low/mid/high/full）。用翻转后的有效度判断。"""
    d = _eff_degree(dim, degree)
    for lo, hi, grade, _ in spec.band_edges(dim):
        if lo <= d < hi:
            return grade
    return spec.band_edges(dim)[-1][2]  # 落到满档


def _band_names(dim):
    return [g for _, _, g, _ in spec.band_edges(dim)]


# ======================================================================
# ③ 单维归并 → 档位质量分布 + 达标质量占比 + 加权程度
# ======================================================================
def dim_result(obs_dims, dim):
    """给定归一化后的单维 profile（bins 列表），归并出该维结果。"""
    meta = spec.dim_spec(dim)
    mass = {g: 0.0 for g in _band_names(dim)}
    wdeg = 0.0
    total = 0.0
    for b in obs_dims:
        p = b["prob"]
        d = _eff_degree(dim, b["degree"])     # 翻转后有效度
        grade = band_degree(dim, b["degree"])
        mass[grade] += p
        wdeg += p * d
        total += p
    # 高档(high)+满档(full) 质量占比 = 达标质量（方向无关，已统一"越高越好"）
    high_mass = mass.get("high", 0.0) + mass.get("full", 0.0)
    weighted_degree = wdeg / total if total > 0 else 0.0
    return {
        "dim": dim,
        "name": meta["name"],
        "direction": meta["direction"],
        "mass_per_band": {k: round(v, 4) for k, v in mass.items()},
        "high_mass": round(high_mass, 4),
        "weighted_degree": round(weighted_degree, 4),
    }


# ======================================================================
# ④ 多维归并 → 总体有效度（加权，不用歧义均值）
# ======================================================================
def aggregate(observations):
    """归并多次观测：每维独立归并，再按 spec 权重做总体加权。
    输入：observations = [obs, ...]，每个 obs 可含多维或部分维。"""
    if not observations:
        raise ValueError("no observations to aggregate")
    # 收集每维的全部 bin
    per_dim_bins = {dim: [] for dim in spec.valid_dims()}
    observed_dims = set()
    for obs in observations:
        n = normalize_profile(obs)
        for dim, bins in n["dims"].items():
            per_dim_bins[dim].extend(bins)
            observed_dims.add(dim)
    per_dim = {d: dim_result(per_dim_bins[d], d) for d in spec.valid_dims()}

    w = spec.weights()
    # 总体：对已观测维度按权重归一化后加权（规避缺失维度拖低总分）
    tot_w = sum(w[d] for d in observed_dims)
    overall = 0.0
    for d in observed_dims:
        overall += w[d] * per_dim[d]["high_mass"]
    overall = overall / tot_w if tot_w > 0 else 0.0
    return {
        "n": len(observations),
        "per_dim": per_dim,
        "overall": round(overall, 4),
        "observed_dims": sorted(observed_dims),
    }


# ======================================================================
# ⑤ 确定性判定（对照 spec.JUDGE_THRESHOLDS）
# ======================================================================
def judge(result):
    """按各维 high_mass 对照阈值，给出确定性达标判定。"""
    verdicts = {}
    for dim, r in result["per_dim"].items():
        thr = spec.judge_threshold(dim)
        verdicts[dim] = {
            "passed": r["high_mass"] >= thr,
            "high_mass": r["high_mass"],
            "threshold": thr,
        }
    # 总体达标 = 已观测维全部达标
    passed_dims = [d for d, v in verdicts.items() if v["passed"]]
    all_passed = result["observed_dims"] and len(passed_dims) == len(result["observed_dims"])
    return {
        "verdicts": verdicts,
        "overall_high_mass": result["overall"],
        "all_passed": all_passed,
    }


# ======================================================================
# ⑥ 留痕
# ======================================================================
def trace(observation, result=None, meta=None):
    """把一次度量观测+归并结果留痕，返回 trace_id。"""
    trace_id = "rvm-" + uuid.uuid4().hex[:10]
    entry = {
        "trace_id": trace_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "observation": observation,
        "result": result,
        "meta": meta or {},
    }
    with _TRACE_LOCK:
        _TRACE.append(entry)
        _persist()
    # 同时尽量落 data/ archives（可回溯，与数据底座打通）
    if admin is not None:
        try:
            admin.archive(trace_id, "review_metrics", "评审有效性度量",
                          json.dumps(entry, ensure_ascii=False), "review_metrics")
        except Exception:  # noqa: BLE001
            pass
    return trace_id


def trace_recent(limit=20):
    """返回最近留痕（供监控/看板俯瞰）。"""
    return _TRACE[-limit:]
