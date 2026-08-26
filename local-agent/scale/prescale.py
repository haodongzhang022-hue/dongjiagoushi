# -*- coding: utf-8 -*-
"""
规模预设层（prescale）· 前期澄清阶段的体量预设
==============================================
用户诉求："秘书/产品/架构师/调研在需求澄清阶段先按体量预设 team_size + collab_plan
+ risk_level + 检索经验方案库，作为增减基准锚点；架构明确后由架构·经理按架构
做增量修正，不做从零规划。"

现状诊断（来自测试环节的关键发现 2）：此前只有 `spec.team_size` 的**用户/上层
CLI 声明**（用户自己喊 2500），不是"秘书/产品澄清阶段的体量预设"。二者不是一回事。

本模块补齐这条缺口：
  - `prescale(complexity, kind=...)` → 在**需求澄清阶段**给出
    { team_size, collab_plan, risk_level, rationale }
  - 作为「增减基准锚点」：架构明确后经理据此做**增量修正**，而非从零规划。
  - 提供「经验方案库（Pattern Lib）」检索：命中同体量/同类型历史成功/修正方案
    即复用，未命中才新建（呼应「熟悉方案的路径积累」）。
  - 提供「强制留痕」断言：**需求进入处理前必须先有预设记录**（配合测试红灯），
    让"到底预没预设"可被机器核验。

设计原则（对齐用户纠偏）：
  - **默认单兵**：绝大多数需求默认 1 人 + 低风险，不为了预设而预设（防无效堆砌）；
  - 只有复杂度/风险/多视角需求才抬升体量；
  - 预设值是**基准锚点**，不是终局——经理按架构做增量修正，可增可减。
"""
import json
import os
import threading
import time

# ---------------------------------------------------------------------------
# 预设结果持久化（留痕）：记录"这次需求有没有做过规模预设"
# ---------------------------------------------------------------------------
_PRESCALE_STORE = {}          # key = req_key → preset dict
_PRESCALE_LOCK = threading.Lock()
_PRESCALE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "state", "prescale_records.json",
)


def _ensure_dir():
    d = os.path.dirname(_PRESCALE_FILE)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _load_records():
    _ensure_dir()
    if not os.path.exists(_PRESCALE_FILE):
        return {}
    try:
        with open(_PRESCALE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_records(records):
    _ensure_dir()
    try:
        with open(_PRESCALE_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 留痕为尽力而为，不阻断主流程


def req_key(req, kind="default"):
    """生成需求预设记录的唯一 key（稳定寻址，同需求二次触发取回同一记录）。"""
    # 对需求文本做规范化摘要，过长截断避免 key 爆炸
    text = (req or "").strip()
    if len(text) > 120:
        text = text[:120]
    return f"{kind}::{text}"


def clear_prescale_records():
    """清空预设记录（测试/续跑前清理用）。"""
    global _PRESCALE_STORE
    with _PRESCALE_LOCK:
        _PRESCALE_STORE = {}
        _ensure_dir()
        if os.path.exists(_PRESCALE_FILE):
            try:
                os.remove(_PRESCALE_FILE)
            except Exception:
                pass


def prescale_records():
    """返回全部预设记录（供测试/俯瞰核验'到底预没预设'）。"""
    with _PRESCALE_LOCK:
        return dict(_PRESCALE_STORE)


def has_prescale(req, kind="default"):
    """断言：需求进入处理前是否已有预设记录（红灯判据）。"""
    return req_key(req, kind) in prescale_records()


def record_prescale(req, preset, kind="default"):
    """写入一条预设留痕记录（含时间戳）。"""
    key = req_key(req, kind)
    rec = {
        "req_key": key,
        "kind": kind,
        "preset": preset,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with _PRESCALE_LOCK:
        _PRESCALE_STORE[key] = rec
    # 落盘持久化
    records = _load_records()
    records[key] = rec
    _save_records(records)
    return rec


# ---------------------------------------------------------------------------
# 经验方案库（Pattern Library）· 熟悉方案的路径积累
# ---------------------------------------------------------------------------
# 沉淀三类高价值经验：
#   1. 成功路径：哪种体量 + 哪种协作方案跑得顺 → 直接复用
#   2. 失误修正：踩过坑后的修正版 → 下次避开（从"事后拦截"升为"事前规避"）
#   3. 加量经验：从 N 扩到 N' 的迁移经验 → 提升初始正确性
# 与 src/memory/ 经验记忆库同源（此处先内置一组种子模式，后续可接云端 RAG）。
PATTERN_LIB = {
    # 体量级: (kind, complexity_band) → 方案模板
    ("default", "simple"): {
        "team_size": 1,
        "collab_plan": "single",
        "risk_level": "low",
        "pattern": "单兵直做——个人/内部简单需求，默认单兵，不建编队（防无效堆砌）。",
        "pattern_type": "success",
    },
    ("default", "medium"): {
        "team_size": 3,
        "collab_plan": "single_plus_relay",
        "risk_level": "medium",
        "pattern": "单兵主战 + 接力深化——产品→总师→经理→开发→评审→测试，跨岗位接力；同岗位按需补位，不无条件组队。",
        "pattern_type": "success",
    },
    ("default", "complex"): {
        "team_size": 5,
        "collab_plan": "differentiated_cohort",
        "risk_level": "high",
        "pattern": "差异化编队 + 触发补位——默认单兵，卡点/专长缺口/高风险触发差异化 agent 补位；疑难走专家会诊；会诊仍无解走审核者前置助手（L1内部分支→L2外部探索→L3交人）。",
        "pattern_type": "success",
    },
    ("company", "complex"): {
        "team_size": 8,
        "collab_plan": "company_multi_dept",
        "risk_level": "high",
        "pattern": "公司多部门协同——秘书→销售/客服建联→产品→架构→部门协同，部门/小组与岗位编队并存。",
        "pattern_type": "success",
    },
}


def search_pattern(kind, complexity_band):
    """检索经验方案库：命中同体量/同类型历史方案 → 返回；未命中 → None。"""
    p = PATTERN_LIB.get((kind, complexity_band))
    if p:
        return dict(p)
    # 未命中精确档 → 回退到 default 同复杂度档（兜底复用，不空手）
    fallback = PATTERN_LIB.get(("default", complexity_band))
    if fallback:
        f = dict(fallback)
        f["fallback_kind"] = True
        return f
    return None


# ---------------------------------------------------------------------------
# 复杂度判定 → 预设
# ---------------------------------------------------------------------------
def _estimate_complexity(req, hint=None):
    """从需求文本/外部 hint 估复杂度带。返回 simple / medium / complex。"""
    if hint in ("simple", "medium", "complex"):
        return hint
    text = (req or "").lower()
    # 关键词加权粗判
    complexity_markers = ["集群", "2500", "并发", "上千", "多部门", "公司化",
                          "架构升级", "全链路", "分布式", "大规模", "多岗位",
                          "复杂", "高风险", "平台级", "对外获客"]
    weight = sum(1 for m in complexity_markers if m in text)
    if weight >= 4:
        return "complex"
    if weight >= 2:
        return "medium"
    return "simple"


def prescale(req, kind="default", complexity_hint=None, force=False):
    """澄清阶段规模预设。

    参数:
      req: 需求文本（必填）
      kind: 前置流程模板（default/company/harness/acquisition/support）
      complexity_hint: 可显式指定复杂度带（simple/medium/complex），否则自动判定
      force: 强制覆盖已有记录
    返回:
      dict { team_size, collab_plan, risk_level, rationale, pattern, ... }
    """
    key = req_key(req, kind)
    # 稳定寻址：同一需求二次预设取回同一结果（不做漂移变更）
    existing = prescale_records().get(key)
    if existing and not force:
        return existing["preset"]

    band = _estimate_complexity(req, complexity_hint)
    pattern = search_pattern(kind, band)
    if pattern is None:
        # 完全没有可复用方案 → 全新规划（保守基准：单兵低风险起步，可增）
        preset = {
            "team_size": 1,
            "collab_plan": "single",
            "risk_level": "low",
            "complexity_band": band,
            "kind": kind,
            "source": "new_plan",       # 未命中方案库 → 全新规划
            "rationale": "未命中经验方案库，按保守基准起步（默认单兵低风险），架构明确后由经理增量调整。",
            "adjustable": True,          # 基准锚点：经理可按架构增量修正
        }
    else:
        preset = {
            "team_size": pattern["team_size"],
            "collab_plan": pattern["collab_plan"],
            "risk_level": pattern["risk_level"],
            "complexity_band": band,
            "kind": kind,
            "source": "pattern_lib",     # 命中经验方案库 → 复用常规路径
            "pattern": pattern["pattern"],
            "pattern_type": pattern["pattern_type"],
            "rationale": f"命中经验方案库（{band} 复杂度 / {kind} 位置）常规路径，"
                         f"作为增减基准锚点，架构明确后由经理做增量修正。",
            "adjustable": True,
        }

    record_prescale(req, preset, kind)
    return preset


def adjust_by_architect(preset, arch_factors):
    """架构明确后，经理按架构做**增量修正**（不做从零规划）。

    参数:
      preset: 澄清阶段预设结果
      arch_factors: dict { scale_factor: float, risk_override: str|None }
    返回:
      增量修正后的预设（仍保留 adjustable 语义）
    """
    if not preset:
        return preset
    import math
    new = dict(preset)
    f = arch_factors.get("scale_factor", 1.0)
    new["team_size"] = max(1, int(round(preset["team_size"] * f)))
    if arch_factors.get("risk_override"):
        new["risk_level"] = arch_factors["risk_override"]
    new["adjusted_by_architect"] = True
    new["rationale"] = (
        f"基于澄清预设（team_size={preset['team_size']}, "
        f"{preset['collab_plan']}）按架构增量修正 "
        f"scale_factor={f} → team_size={new['team_size']}，不做从零规划。"
    )
    return new


def to_json(preset):
    return json.dumps(preset, ensure_ascii=False, indent=2, default=str)
