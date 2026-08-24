# -*- coding: utf-8 -*-
"""
规模伸缩层 · 团队规模声明（spec）
================================
用户诉求："允许跟 AI 交互，声明要的团队大小、分工层级。尤其比较大规模的协作
比如上百个，上千个，是否还能正常协作？"

本模块让用户/上层 harness **声明团队拓扑**，而非由代码写死。声明要素：

  - `team_size`     团队大小（并发 agent 数），如 10 / 100 / 2500
  - `levels`        分工层级（扁平 / 三层 / 五层），决定嵌套分组深度
  - `concurrency`   并发度（默认取 team_size，可单独指定）
  - `mode`          协作模式：team（团队）/ company（公司多部门）/ harness（deepseek 模式）
  - `profile`       前置流程模板（见 profile.py）
  - `roles`         需要的角色子集（与角色插件层配合，灵活增减）

通过 `--spec '{"team_size": 2500, "levels": 3, ...}'` 传入，
或从环境变量 `TEAM_SPEC` 读取（deepseek harness 注入）。

核心能力：
  - 校验声明合法性（不能负数、levels 有上限防爆栈）；
  - 根据 levels 生成**分组拓扑**（小组 → 子小组 → 叶子 agent）；
  - 估算「消息总线 / 状态分片 / 并发池」所需资源配置建议；
  - 判定「当前运行后端能否承载该规模」（关键：2500 级需分布式后端）。
"""
import json
import os
import threading

DEFAULT_SPEC = {
    "team_size": 4,
    "levels": 2,
    "concurrency": None,   # None → 取 team_size
    "mode": "team",
    "profile": "default",
    "roles": [],           # 空 → 用 profile 默认角色集
}

# 单机后端可承载的合理上限（超出需分布式）
LOCAL_CAP = int(os.environ.get("LOCAL_CAP", "64"))

# 层级上限（防止嵌套分组爆栈）
MAX_LEVELS = 6

_spec_lock = threading.Lock()
_current = None


def parse(spec):
    """解析并规范化规模声明。spec 可为 dict 或 JSON 字符串。"""
    if isinstance(spec, str):
        spec = json.loads(spec)
    merged = {**DEFAULT_SPEC, **(spec or {})}
    return normalize(merged)


def normalize(s):
    s["team_size"] = max(1, int(s.get("team_size", 4)))
    s["levels"] = min(MAX_LEVELS, max(1, int(s.get("levels", 2))))
    if not s.get("concurrency"):
        s["concurrency"] = s["team_size"]
    s["concurrency"] = max(1, int(s["concurrency"]))
    s.setdefault("mode", "team")
    s.setdefault("profile", "default")
    s.setdefault("roles", [])
    return s


def set_spec(spec):
    """全局设置当前规模声明。"""
    global _current
    with _spec_lock:
        _current = normalize(spec)
    return _current


def get_spec():
    """获取当前规模声明（默认 DEFAULT_SPEC 副本）。"""
    global _current
    with _spec_lock:
        if _current is None:
            _current = dict(DEFAULT_SPEC)
        return dict(_current)


def build_topology(spec):
    """根据 levels 生成分组拓扑。

    返回树：root 下按 fanout 逐层展开，叶子是 agent。
    例：team_size=12, levels=2 → 根组下分 4 组，每 3 个叶子。
    """
    spec = normalize(spec)
    size = spec["team_size"]
    levels = spec["levels"]

    def _branch(count, depth):
        if depth <= 1 or count <= 1:
            return [{"type": "agent", "id": f"a{i}"} for i in range(count)]
        # 尽量均匀分叉
        fan = max(2, int(count ** (1 / (depth - 1))))
        groups = []
        remain = count
        idx = 0
        while remain > 0:
            gsz = min(remain, max(1, (count + fan - 1) // fan))
            groups.append(
                {
                    "type": "group",
                    "id": f"g{idx}",
                    "children": _branch(gsz, depth - 1),
                }
            )
            remain -= gsz
            idx += 1
        return groups

    return {
        "spec": spec,
        "root": {
            "type": "group",
            "id": "root",
            "children": _branch(size, levels),
        },
    }


def leaf_count(topology):
    """统计拓扑中叶子 agent 数。"""
    def _count(node):
        if node["type"] == "agent":
            return 1
        return sum(_count(c) for c in node["children"])
    return _count(topology["root"])


def resource_estimate(spec):
    """估算运行该规模所需的资源，并给出后端建议。"""
    spec = normalize(spec)
    size = spec["team_size"]
    est = {
        "team_size": size,
        "levels": spec["levels"],
        "concurrency": spec["concurrency"],
        "messages_per_round": size * 2,       # 每轮每个 agent 至少 2 条消息
        "state_cards": size,                   # 状态分片数
        "suggested_backend": "filesystem" if size <= LOCAL_CAP else "redis+distributed",
        "fits_local": size <= LOCAL_CAP,
        "warning": (
            None
            if size <= LOCAL_CAP
            else f"team_size={size} 超过单机上限 {LOCAL_CAP}，需分布式消息总线 + 状态后端"
        ),
    }
    return est


def to_json(spec):
    return json.dumps(normalize(spec), ensure_ascii=False, indent=2)
