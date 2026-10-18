# -*- coding: utf-8 -*-
"""
角色名册 · 四个事实源归并为一张表（唯一事实源）
==============================================
本仓的角色其实分散在**四个事实源**里，各自服务不同消费者：

  | 事实源 | 消费者 | 内容 |
  |--------|--------|------|
  | `.cnb/settings.yml` | CNB 平台（云端 NPC） | 角色人设 prompt / defaultRole |
  | `local-agent/team.yaml` | 本地编排 / 管理台 | 角色 module / step / trigger_words |
  | `local-agent/roles/__init__.py:ROLE_REGISTRY` | 本地执行 | 角色类（能不能真跑） |
  | `local-agent/relay_card/__init__.py:ROLES` | 交接校验 | 接力卡 @ 时可用的角色名 |

四份之间**天然会漂移**（有人加了 settings 忘了加 registry，或反之）。
外部对端（管理-派单控制面）只想要一件事：**有哪些角色、ID 是什么、怎么触发**。
所以这里做的是「归并 + 显式标注缺口」，不是再造第五份清单：

  - 每个角色一条记录，带**稳定 ID**（`arch.secretary` 这种，跨版本不变）；
  - 缺口**不隐藏**：登记了但本地无实现 → `impl=false`；本地有实现但没登记 → 也列出来；
  - 有测试断言 `drift == 0`，漂移就会红，不给「看起来整齐」的假绿。

## ID 策略（跨仓对接的锚）

对端用 ID 派单，不用中文名——中文名会改名（`架构·数据管理员` vs `架构·数据管理`，
两个不同角色），ID 改名频率低得多，且天然适合写进 query / JSON key。

  `arch.secretary`   ← 命名空间(arch/mkt) + 稳定英文短名
  `role_id` 一旦发布不改；改名另开 ID 并保留 alias（见 `RENAMED_FROM`）。
"""
import os
import re

__all__ = [
    "ROLE_IDS", "RENAMED_FROM", "NAMESPACES", "ROLE_SPECS",
    "get_spec", "role_by_id", "role_by_name", "specs",
]

_LOCAL_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(_LOCAL_AGENT)

# 命名空间前缀 → 中文前缀（角色名以中文前缀开头）
NAMESPACES = {"arch": "架构·", "mkt": "市场·"}

# 规范角色全称 → 稳定 ID。**只增不改**：ID 是对外的锚，改名走 RENAMED_FROM。
ROLE_IDS = {
    # ---- 入口 / 需求 / 设计 ----
    "架构·秘书": "arch.secretary",
    "架构·产品": "arch.product",
    "架构·总师": "arch.architect",
    "架构·总师助理": "arch.chief_assistant",
    # ---- 调度 / 协同 ----
    "架构·经理": "arch.manager",
    "架构·小组长": "arch.team_lead",
    # ---- 实现 / 质量 ----
    "架构·开发": "arch.developer",
    "架构·评审": "arch.reviewer",
    "架构·测试": "arch.tester",
    "架构·对齐": "arch.aligner",
    "架构·找工具": "arch.tool_finder",
    "架构·交付": "arch.deliverer",
    "架构·版本管理": "arch.version_keeper",
    # ---- 底座 / 运维 ----
    "架构·数据管理员": "arch.data_admin",
    "架构·数据管理": "arch.data_manager",
    "架构·监控哨兵": "arch.sentinel",
    "架构·进度推手": "arch.progress_pusher",
    "架构·审核前置助手": "arch.review_precursor",
    "架构·运维": "arch.ops",
    # ---- 市场情报 / 获客 ----
    "市场·销售": "mkt.sales",
    "市场·客服": "mkt.support",
    "市场·数据": "mkt.data",
    "市场·渠道": "mkt.channel",
    "市场·工具": "mkt.tooling",
    "架构·找需求": "arch.demand_finder",
    "架构·价值确认": "arch.value_verifier",
    "架构·竞品分析": "arch.competitor",
    # ---- 能力底座 ----
    "架构·工具开发": "arch.tool_builder",
    "架构·优化": "arch.optimizer",
}

# 曾经用过、已不再出现的角色名 → 现名（改了名但 ID 不变时两种都认得）
RENAMED_FROM = {
    "架构·版本管理": "架构·对齐",
}

# 角色对外可见的**触发方式**（与 relay_card 的 @ 格式一致，ID 化后跨仓可用）
AT_TEMPLATE = "@{repo}({name})"
RELAY_TEMPLATE = "[触发:{name}]"


def _repo_slug():
    """动态解析当前仓库 slug（不写死 org/repo）。"""
    try:
        out = os.popen("git config --get remote.origin.url 2>/dev/null").read()
        m = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?\s*$", out)
        if m:
            return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return os.environ.get("CNB_REPO_SLUG", "") or "dongdongxiaozu/dongjiagoushi"


# ---------------------------------------------------------------------------
# 四个事实源读取（每个都可能失败：读不到就是缺口，不假装有）
# ---------------------------------------------------------------------------
def settings_roles():
    """云端定义的角色：.cnb/settings.yml 的 npc.roles[*].name（含 defaultRole）。

    只取 name/slogan，不取 prompt —— 名册是**索引**，正文留在事实源。
    """
    import yaml
    path = os.path.join(REPO_ROOT, ".cnb", "settings.yml")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    npc = data.get("npc") or {}
    out = {}
    for r in npc.get("roles") or []:
        name = (r.get("name") or "").strip()
        if name:
            out[name] = {"slogan": (r.get("slogan") or "").strip()}
    default = (npc.get("defaultRole") or "").strip()
    if default:
        out.setdefault(default, {"slogan": ""})
    return out


def team_roles():
    """本地编排定义的角色：team.yaml 的 roles[*]（module/step/trigger_words）。"""
    import yaml
    path = os.path.join(_LOCAL_AGENT, "team.yaml")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out = {}
    for r in data.get("roles") or []:
        name = (r.get("name") or "").strip()
        if name:
            out[name] = {
                "module": (r.get("module") or "").strip(),
                "step": (r.get("step") or "").strip(),
                "trigger_words": list(r.get("trigger_words") or []),
                "slogan": (r.get("slogan") or "").strip(),
            }
    return out


def registry_roles():
    """本地可实例化的角色：roles.ROLE_REGISTRY 的键（= 真能跑的）。"""
    import sys
    if _LOCAL_AGENT not in sys.path:
        sys.path.insert(0, _LOCAL_AGENT)
    try:
        from roles import ROLE_REGISTRY
        return set(ROLE_REGISTRY.keys())
    except Exception:  # noqa: BLE001 导入失败 = 一个都不可跑（缺口如实反映）
        return set()


def relay_roles():
    """接力卡校验认得的角色名：relay_card.ROLES（+ 别名可归一化的）。"""
    import sys
    if _LOCAL_AGENT not in sys.path:
        sys.path.insert(0, _LOCAL_AGENT)
    try:
        from relay_card import ROLES
        return set(ROLES)
    except Exception:  # noqa: BLE001
        return set()


def pipeline_nodes():
    """team.yaml pipeline 里出现的角色 → 节点/依赖（供对端判断派单落点）。"""
    import yaml
    path = os.path.join(_LOCAL_AGENT, "team.yaml")
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out = {}
    for node in ((data.get("pipeline") or {}).get("dag") or {}).get("nodes") or []:
        role = (node.get("role") or "").strip()
        if role:
            out.setdefault(role, []).append(
                {"node": node.get("id", ""), "depends_on": list(node.get("depends_on") or [])}
            )
    return out


# ---------------------------------------------------------------------------
# 归并（缓存在进程内：名册是构建产物，不是运行态）
# ---------------------------------------------------------------------------
_CACHE = {}


def _build():
    s = settings_roles()
    t = team_roles()
    reg = registry_roles()
    relay = relay_roles()
    nodes = pipeline_nodes()
    repo = _repo_slug()

    names = list(dict.fromkeys(list(s) + list(t) + list(reg) + list(relay)))

    specs, missing_ids, drift = {}, [], []
    for name in names:
        rid = ROLE_IDS.get(name)
        canonical = RENAMED_FROM.get(name, name)
        if rid is None:
            rid = ROLE_IDS.get(canonical)
        if rid is None:
            missing_ids.append(name)      # 新角色没登记 ID：显式缺口，不临时编
            rid = "unregistered." + re.sub(r"[^\w]+", "_", name).strip("_")

        in_settings, in_team = name in s, name in t
        in_registry, in_relay = name in reg, name in relay

        # 「缺哪一侧」必须分别记：settings 有、本地没有 = 云端能 @ 但跑不起来
        gaps = []
        if not in_settings:
            gaps.append("settings")
        if not in_team:
            gaps.append("team")
        if not in_registry:
            gaps.append("registry")
        if not in_relay:
            gaps.append("relay")

        spec = {
            "role_id": rid,
            "name": name,
            "namespace": name.split("·", 1)[0] if "·" in name else "",
            "slogan": (t.get(name, {}).get("slogan") or s.get(name, {}).get("slogan") or ""),
            "module": t.get(name, {}).get("module", ""),
            "step": t.get(name, {}).get("step", ""),
            "trigger_words": list(t.get(name, {}).get("trigger_words") or []),
            "in_settings": in_settings,
            "in_team": in_team,
            "in_registry": in_registry,
            "in_relay": in_relay,
            "pipeline": nodes.get(name, []),
            "gaps": gaps,
            # 能不能真跑：本地有实现类才算。云端有登记不算。
            "impl": in_registry,
            "at": AT_TEMPLATE.format(repo=repo, name=name),
            "relay": RELAY_TEMPLATE.format(name=name),
        }
        if name in RENAMED_FROM:
            spec["renamed_from"] = name
            spec["name"] = RENAMED_FROM[name]
        specs[rid] = spec

        if not in_settings or not in_registry:
            drift.append({"role_id": rid, "name": name, "gaps": gaps})

    _CACHE.update({"specs": specs, "missing_ids": missing_ids,
                   "drift": drift, "repo": repo})
    return _CACHE


def specs():
    """全部角色记录（首次调用构建并缓存）。"""
    return _build()["specs"] if not _CACHE else _CACHE["specs"]


def get_spec(role_id):
    return specs().get(role_id)


def role_by_id(role_id):
    spec = specs().get(role_id)
    return spec["name"] if spec else None


def role_by_name(name):
    """中文名/别名 → 稳定 ID（含「别名归一化」与「改名映射」）。"""
    if not name:
        return None
    name = name.strip()
    canonical = RENAMED_FROM.get(name, name)
    for rid, spec in specs().items():
        if spec["name"] == canonical:
            return rid
    # 别名：无「架构·」前缀但核心名能匹配
    if "·" not in name:
        for rid, spec in specs().items():
            if spec["name"].split("·", 1)[-1] == name and "·" in spec["name"]:
                return rid
    return None


def drift():
    """缺口明细：settings 有/本地没有，或本地有/settings 没有。"""
    return (_CACHE or _build())["drift"]


def missing_ids():
    """没有稳定 ID 的角色名（新增角色忘了登记 ID 时暴露出来）。"""
    return (_CACHE or _build())["missing_ids"]


def repo():
    return (_CACHE or _build())["repo"]
