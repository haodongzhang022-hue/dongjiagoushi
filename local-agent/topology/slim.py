# -*- coding: utf-8 -*-
"""
复杂度递进式精简体系（Complexity-Slim · 角色子集精简 + 占比量化）
================================================================
用户 Issue #41 再设计纠偏（架构·总师迭代）：

  "小任务其实占比最高，这个才最适合体系承接，但需要简化的体系。
   复杂度最低的单点修改 → 只剩单名开发（甚至这种占比都不小）；
   复杂度低 → 基本就是敏捷开发（只剩下产品和开发）；
   中等复杂度 → 开始有架构师；
   复杂度高 → 公司结构拉满；
   再高 → 完整体系、公司规模最大、动态扩容，加水龙头蔓延、带蔓延回传合并。
   核心是缓存命中为主线，分工协作的架构是以能完成目标为准的。"

本模块与 `fusion.py` 的「规模金字塔→承接体系」互补（非重复）：
  - fusion 负责：按规模选档位（micro/small/medium/large/huge）+ 选承接体系
    （agile/architected/company/full）+ 选拓扑；
  - slim 负责：为每个档位给出**最小角色子集**（以能完成目标为准）+ **占比量化**
    （越小占比越高、越精简）+ 协作形态 + 缓存命中主线。

关键原则（对齐用户）：
  - **以能完成目标为准**：只建到能完成目标的角色，不为小任务拉满团队；
  - **越小占比越高越精简**：micro 40% / small 30% / medium 15% / large 10% / huge 5%，
    占比最高的最该优化精简；
  - **缓存命中为主线**：所有档位都以缓存命中为主线，只是聚合程度递增（见各档 cache）。

档位命名与 fusion.py 金字塔对齐：
  micro / small / medium / large / huge
"""
import json

# ---------------------------------------------------------------------------
# 每档最小角色子集（以能完成目标为准，从简到全）
# ---------------------------------------------------------------------------
ROLE_SUBSETS = {
    "micro":   ["架构·开发"],
    "small":   ["架构·产品", "架构·开发"],
    "medium":  ["架构·产品", "架构·总师", "架构·开发", "架构·评审"],
    "large":   ["架构·秘书", "架构·经理", "架构·产品", "架构·总师",
                "架构·小组长", "架构·开发", "架构·评审", "架构·测试"],
    "huge":    ["架构·秘书", "架构·经理", "架构·产品", "架构·总师",
                "架构·小组长", "架构·开发", "架构·评审", "架构·测试",
                "架构·监控哨兵", "架构·数据管理员"],   # 完整体系 + 动态扩容
}

# 各档在全部任务中的预期占比（越小占比越高 → 越精简越优化）
RATIO = {
    "micro": 0.40,   # 单点修改占比最高
    "small": 0.30,   # 低复杂敏捷次之
    "medium": 0.15,  # 中等架构
    "large": 0.10,   # 公司结构
    "huge": 0.05,    # 完整体系（最少但最大）
}

# 各档协作形态（一句话）
COLLAB = {
    "micro": "单名开发直做——单点修改/单文件改动，不建任何编队，改完即交付。",
    "small": "敏捷开发——产品+开发两角色，需求轻量澄清后直接开发，无架构/评审冗余。",
    "medium": "架构接力——产品→架构师→开发→评审，中等复杂度需架构设计把关。",
    "large": "公司式分工——秘书/经理/小组长/多部门，按功能域拆分并行，结构拉满。",
    "huge": "完整体系+动态扩容——规模最大，水龙头蔓延+带蔓延关系回传合并，动态扩缩容。",
}

# 各档缓存命中主线（贯穿所有规模，聚合程度递增）
CACHE = {
    "micro": (
        "【主线·缓存命中】单 agent 连续改同一处 → 复用同一上下文缓存，"
        "仅付增量差异 token，不重复构造完整 prompt（单点修改占比最高，省得最多）。"
    ),
    "small": (
        "【主线·缓存命中】产品+开发共享需求前缀，开发接手复用产品澄清前缀，"
        "命中缓存增量蔓延，敏捷迭代不重造上下文。"
    ),
    "medium": (
        "【主线·缓存命中】按 role 聚共享前缀（架构结论→开发复用），命中缓存增量蔓延；"
        "评审复用开发产出前缀。中等规模 token 复用充分。"
    ),
    "large": (
        "【主线·缓存命中】按功能域/小组聚合共享前缀为集群，同 role 节点只构造一次，"
        "后续节点命中缓存付增量 token；多部门天然并行，回传收口。"
    ),
    "huge": (
        "【主线·缓存命中】共享前缀聚合为集群（缓存命中为索引），水龙头蔓延只付增量差异 token；"
        "带蔓延关系的回传合并，动态扩容时新 agent 复用集群前缀。"
    ),
}


def slim_route(tier="micro"):
    """按金字塔档位返回精简体系（角色子集 + 占比 + 协作 + 缓存主线）。

    tier: micro / small / medium / large / huge（与 fusion.py 金字塔对齐）
    返回：{ tier, roles, collab, cache, ratio, reason }
    """
    tier = tier if tier in ROLE_SUBSETS else "micro"
    roles = ROLE_SUBSETS[tier]
    ratio = RATIO[tier]
    return {
        "tier": tier,
        "roles": roles,
        "collab": COLLAB[tier],
        "cache": CACHE[tier],
        "ratio": ratio,
        "reason": (
            f"档位「{tier}」：{COLLAB[tier]} 角色子集精简为 {len(roles)} 个（{roles}）。"
            f"缓存命中为主线贯穿该档。该档在全部任务中预期占比 {ratio:.0%}。"
        ),
    }


def overview():
    """全档俯视图（供人类俯瞰决策）。"""
    rows = []
    for tier in ["micro", "small", "medium", "large", "huge"]:
        rows.append({
            "tier": tier,
            "roles": ROLE_SUBSETS[tier],
            "collab": COLLAB[tier],
            "cache": CACHE[tier],
            "ratio": RATIO[tier],
        })
    return {
        "rule": "复杂度递进式精简体系（规模金字塔：越小占比越高、角色子集越精简）",
        "main_line": "缓存命中为主线（所有档位），分工协作以能完成目标为准，高复杂/大型才兼顾快速提速",
        "tiers": rows,
    }


if __name__ == "__main__":
    import sys
    if "--overview" in sys.argv:
        print(json.dumps(overview(), ensure_ascii=False, indent=2))
    else:
        for t in ["micro", "small", "medium", "large", "huge"]:
            r = slim_route(t)
            print(f"{t:8} roles={len(r['roles'])}个  ratio={r['ratio']:.0%}  {r['collab'][:30]}...")
