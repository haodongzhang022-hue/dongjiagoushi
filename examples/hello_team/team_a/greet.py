# -*- coding: utf-8 -*-
"""
hello_team · 小组A 交付模块 — greet.py
=========================================
由「分形小组A」开发：
  角色分工：架构·开发（实现）→ 架构·测试（单组自测）
职责：核心问候能力。
数据互通：本模块调用「分形小组B」交付的 meta.py，读取团队调度元数据，
          证明跨小组数据能互通、能被正确消费。
"""
from typing import Optional


def greet(name: str, meta_loader: Optional[callable] = None) -> str:
    """生成一条问候消息。

    参数：
      name:        被问候者姓名。
      meta_loader: 可选的元数据加载器（默认导入小组B的 meta.load_team_meta）。
                   用于跨小组数据互通：把小组B的元数据拼进问候语。
    返回：
      形如「你好，{name}！来自小组B的团队标识：{team_id}」
    """
    team_id = _fetch_team_id(meta_loader)
    return f"你好，{name}！团队标识：{team_id}"


def _fetch_team_id(meta_loader: Optional[callable] = None) -> str:
    """从小组B的元数据模块读取 team_id，演示跨组数据互通。"""
    if meta_loader is not None:
        return meta_loader()
    try:
        # 依赖小组B的交付：meta.load_team_meta()
        from team_b.meta import load_team_meta
        meta = load_team_meta()
        return meta["teams"][1]["team_id"]  # team_b
    except (ImportError, KeyError, IndexError):
        return "unknown-team"
