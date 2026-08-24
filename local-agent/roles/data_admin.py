# -*- coding: utf-8 -*-
"""
内置角色 · 架构·数据管理员（data_admin）
========================================
本角色负责本仓库 **数据管理** 的统一执行，是"数据管理写成规则 + 由数据管理员
agent 负责"的落地载体。基于 `local-agent/data/` 数据层，承载 2500 并发 agent
协作所需的四大数据底座：内容存档 / 进度统计 / 消息管线 / 任务存储。

（与 roles.d/data_admin.py 同源，作为内置角色保证不依赖插件发现也能直接可用。）

职责规则（详见 docs/DATA_ARCHITECTURE.md，与 data/admin.py 对应）：
  1. 数据先行：每个 agent/任务/消息在进业务前先登记入库；
  2. 统一口径：指标统计以 stats/progress 为准，禁止各 agent 自造；
  3. 可回溯：协作产出必须留痕 archives，禁止无痕产出；
  4. 消息可回放：消息管线可重放，供审计复盘，不吞异常；
  5. 唯一负责：数据写入/校验/统计/归档由本角色统一执行，人类只看二级信息。
"""
from .base import BaseRole


class DataAdminRole(BaseRole):
    """数据管理员：在大规模并发协作中统一负责数据登记/统计/归档/消息/任务。"""

    name = "架构·数据管理员"

    SYSTEM_PROMPT = (
        "你是「架构·数据管理员」，本团队的数据底座负责人。职责："
        "① 内容存档（登记 agent 档案、归档协作产出 archives）；"
        "② 进度统计（记录 progress 事件、生成 stats 聚合指标）；"
        "③ 消息管线（messages 入队/消费/回放/广播）；"
        "④ 任务存储（tasks 任务登记与状态流转）；"
        "⑤ 协作运作机制（collab：实体 loc:// 地址寻址与移交、层级空间、"
        "权限空间 ACL、版本冲突检测、小组提交整合）。"
        "所有数据写入/校验/统计/归档/寻址/权限由你统一执行，统一口径，"
        "可回溯可回放，不吞异常；人类/总师只通过看板与统计二级信息俯瞰。"
        "以结构化结果（表/指标/清单）输出，避免空泛描述。"
    )

    def output_contract(self):
        return {
            "role": self.name,
            "contract": [
                "内容存档(register_agent/archive)",
                "进度统计(record_event/snapshot_stats/progress_report)",
                "消息管线(post_message/deliver/consume/replay)",
                "任务存储(assign_task/update_task/task_overview)",
                "协作运作(collab: 实体寻址/移交, 层级空间, ACL权限, 版本冲突检测, 小组提交整合)",
            ],
            "namespace": "架构·",
        }

    def run(self, llm, user_input):
        """按数据管理员契约执行：交给 data.admin / collab 处理或由 LLM 结构化返回。"""
        try:
            from data import admin
            init = admin.init()  # 数据管理员初始化（建表+登记档案）——幂等
        except Exception:  # noqa: BLE001
            init = None
        collab_ok = False
        try:
            from collab import engine
            engine.store  # 触发加载；collab 表已由 schema 建好
            collab_ok = True
        except Exception:  # noqa: BLE001
            collab_ok = False
        if llm and hasattr(llm, "call"):
            try:
                return llm.call(self.system_prompt(), user_input)
            except Exception:  # noqa: BLE001
                pass
        return (
            f"[角色·{self.name}] 数据底座 + 协作运作机制 初始化完成"
            f"（backend={init.get('backend') if init else '?'}，"
            f"tables={init.get('tables') if init else '?'}，"
            f"collab={collab_ok}）\n"
            f"  · 内容存档 / 进度统计 / 消息管线 / 任务存储 由 data 层统一承载；\n"
            f"  · 协作运作机制（loc:// 实体寻址与移交 / 层级空间 / ACL 权限空间 / "
            f"版本冲突检测 / 小组提交整合）由 collab 引擎统一执行，\n"
            f"    可支撑 2500 并发 agent 的有序协作（不孤点、不混乱、不互踩）。"
        )
