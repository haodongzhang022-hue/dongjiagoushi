# -*- coding: utf-8 -*-
"""
宿主适配器抽象 + 三入口具体适配（entries.adapter · Issue #105）
===============================================================
核心设计（Issue #105 目标方案，收敛到 1 套仓库内）：

  1. 主入口锁死「架构·秘书」：三入口都是「把话送到秘书面前」的通道。
  2. 差异收口到「适配层 + 执行地」两维度，做配置不做硬编码：
     - 入口适配（web / cnb / local）各自实现最小宿主接口
       `trigger / read_card / run_dag / scale_swarm`；
     - 本地 vs 云端执行 → 走 `CLOUD_LOCAL_COOP.md` 分工边界（CPU 密集本地、
       LLM 强相关云端、成本/配额护栏），由 adapter 的 execution locus 配置承载，
       非逻辑硬编码。
  3. 结构性差异用「可插拔适配器 + 配置」承载，不用 if 塞：核心编排仅一份，
     本模块只做「入口 → 适配器 → 单份核心」的路由。

最小宿主接口（对应 PLATFORM_ADAPTERS.md 五）：
  trigger(role, task)       # 触发：把 任务 + 角色 交给团队
  read_card()/write(card)   # 接力卡读写（进度/回转/打断）
  run_dag(req)              # 跑 DAG 流水线到交付
  scale_swarm(tasks, n)     # 分形扩展到 n 个小组
"""
import json
import os


# ---------------------------------------------------------------------------
# 一、入口模板（entry）与执行地（locus）的配置映射
#    —— 差异是「配置」，不是代码分支。核心不感知入口。
# ---------------------------------------------------------------------------
# locus：执行地分工边界，对齐 docs/CLOUD_LOCAL_COOP.md——
#   cloud = 云端（cnb.cool NPC 原生、LLM 强相关）
#   local = 本地（harness/CLI、CPU 密集测试）
#   组合按工作类型，不做全局硬编码。
ENTRY_LOCI = {
    # entry -> (适配器标识, 默认执行地, 入口模板 profile, 说明)
    "web":  ("web",  "hybrid", "default", "网页对话：可驱动云端/本地，按工作类型 hybrid 分流"),
    "cnb":  ("cnb",  "cloud",  "default", "cnb.cool 云端 NPC：Issue/PR @CodeBuddy，接力卡=Issue 评论"),
    "local":("local","local",  "harness", "本地 AI（harness/CLI）：run.py/team.yaml DAG 直驱，接力卡落盘 state/"),
}


# ---------------------------------------------------------------------------
# 二、宿主无关的适配器抽象（最小宿主接口契约）
# ---------------------------------------------------------------------------
class HostAdapter:
    """宿主适配器抽象基类。

    任何宿主只需实现 / 默认承载以下最小接口即可接入同一套核心编排：
      trigger / read_card / write / run_dag / scale_swarm
    核心编排（角色/接力卡/DAG/触发协议）不感知入口——由本层做适配。

    子类应声明:
      key    适配器标识（web / cnb / local）
      locus  默认执行地（cloud / local / hybrid）
      profile 对应入口模板（default / harness / ...）
    """

    key = "base"
    locus = "local"
    profile = "default"
    name = "宿主适配器（抽象）"

    # ---- 接口 1：触发（把 任务 + 角色 交给团队）----
    def trigger(self, role, task):
        """触发单角色执行。返回结构化触发结果（含是否经秘书主入口）。"""
        return {
            "ok": True,
            "entry": self.key,
            "role": role,
            "task": task,
            "message": f"[{self.key} 适配器] 已触发 {role} 处理任务：{task[:50]}",
        }

    # ---- 接口 2：接力卡读写（进度/回转/打断）----
    def read_card(self):
        """读取接力卡。默认委托本地 relay（跨入口共享同一接力卡协议）。"""
        return self._relay_load()

    def write(self, card):
        """写接力卡。默认委托本地 relay。"""
        return self._relay_save(card)

    def _relay_load(self):
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import relay
            return relay.load()
        except Exception as e:  # noqa: BLE001
            return {"error": f"relay 读取失败: {e}"}

    def _relay_save(self, card):
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import relay
            relay.save(card)
            return {"ok": True, "saved": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # ---- 接口 3：跑 DAG 流水线到交付（走单份核心编排）----
    def run_dag(self, req, **kw):
        """执行核心流水线。默认委托 orchestrator.run_pipeline（核心仅一份）。"""
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import orchestrator
        return orchestrator.run_pipeline(req, **kw)

    # ---- 接口 4：分形扩展（多小组并行）----
    def scale_swarm(self, tasks, n=2):
        """分形扩展到 n 个小组。返回分形计划（走单份分形引擎）。"""
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import fractal
        # 每个小组固定配 n 个开发实例（默认 2），任务均分到各小组
        return fractal.build_fractal_plan(list(tasks), devs_per_team=n)

    def describe(self):
        return {
            "key": self.key,
            "name": self.name,
            "locus": self.locus,
            "profile": self.profile,
            "interfaces": ["trigger", "read_card", "write", "run_dag", "scale_swarm"],
        }


# ---------------------------------------------------------------------------
# 三、三入口具体适配器（cnb.cool 原生 / 本地 harness / 网页对话）
# ---------------------------------------------------------------------------
class CnbAdapter(HostAdapter):
    """cnb.cool 云端 NPC 适配器。

    现状 = 零成本（本仓原生）：Issue/PR 评论 `@CodeBuddy` 触发；
    接力卡 = Issue 评论内嵌结构化卡片；`[触发]/[回转]/[打断]` = 评论标记。
    """
    key = "cnb"
    locus = "cloud"
    profile = "default"
    name = "cnb.cool 云端 NPC（原生）"


class LocalAdapter(HostAdapter):
    """本地 harness / CLI 适配器。

    run.py 为入口脚本；team.yaml DAG + 角色库被 harness 逐节点调度；
    接力卡落到 state/relay_card.json；支持 --resume 续跑（对应 [打断]）、
    --role 单角色触发（对应 [触发]）。
    """
    key = "local"
    locus = "local"
    profile = "harness"
    name = "本地 harness / CLI"


class WebAdapter(HostAdapter):
    """网页对话适配器（用户在公司/获客等网页对话框里说话）。

    入口 UI + 上下文来源不同；默认走 default profile 的秘书主入口，
    执行地按工作类型 hybrid 分流（CPU 密集本地、LLM 强相关云端）。
    """
    key = "web"
    locus = "hybrid"
    profile = "default"
    name = "网页对话"


ADAPTERS = {
    "cnb":   CnbAdapter,
    "local": LocalAdapter,
    "web":   WebAdapter,
}


# ---------------------------------------------------------------------------
# 四、配置驱动的适配器注册 / 路由（不做硬编码 if 分支）
# ---------------------------------------------------------------------------
def get_adapter(entry):
    """按入口标识取适配器实例；未知入口回退 local（保守本地）。"""
    cls = ADAPTERS.get(entry, LocalAdapter)
    return cls()


def list_adapters():
    """列出全部可用适配器（含配置映射：入口/执行地/profile）。"""
    out = []
    for entry in ("web", "cnb", "local"):
        a = get_adapter(entry)
        locus = ENTRY_LOCI[entry][1]
        profile = ENTRY_LOCI[entry][2]
        out.append({
            "entry": entry,
            "adapter": a.key,
            "name": a.name,
            "locus": locus,
            "profile": profile,
            "interfaces": a.describe()["interfaces"],
        })
    return out


def overview():
    """二级信息俯瞰：三入口归一化矩阵（供人类/经理决策）。"""
    rows = list_adapters()
    return {
        "module": "platform-adapter",
        "issue": "Issue #105",
        "main_entry": "架构·秘书",   # 主入口锁死秘书，三入口只是触达通道
        "entries": rows,
        "core": "单份核心编排（角色/接力卡/DAG/触发协议 宿主无关）",
    }
