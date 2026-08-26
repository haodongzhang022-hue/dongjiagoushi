# -*- coding: utf-8 -*-
"""
协作运作机制 · collab 包
========================
把 DATA_ARCHITECTURE 的原始六表数据层，升级为**有运作机制的协作引擎**。
对应 docs/COLLAB_ENGINE.md 的五个支柱：

  ① 实体解耦 + loc:// 位置寻址   （entities 注册表 + 灵活移交）
  ② 层级空间                     （spaces 父子树 + 共享空间）
  ③ 权限空间                     （acl 访问控制：谁可访问哪个位置）
  ④ 版本整合                     （versions 版本 + 冲突检测）
  ⑤ 小组提交                     （commits 小组统一向上整合交付）

由「架构·数据管理员」角色统一执行，遵循 DATA_ARCHITECTURE 五规则
（数据先行 / 统一口径 / 可回溯 / 可回放 / 唯一负责）。

同岗位多角色交互（peer collab）：
  - peer.py 补齐「同一岗位上多个 agent 面对同一个问题」的交互协议，
    对齐「默认单兵、按需补位、疑难才会诊」方向（非全员投票冗余）。

收尾闭环（peer collab closure，Issue #31 缺漏 G1~G4）：
  - decisions.py   决策落库 + 动作消费（会诊/前置/人类拍板持久化 + 驱动改道/补位/升级）
  - precursor.py   审核者前置助手引擎（L1 内部分支→L2 外部探索→L3 交人 + ⑤自决）
  - human_gate.py  结果前置·人类拍板（决策点叫人类 + CP 留痕，非事后背锅）
  - closure.py     收尾闭环统一编排（会诊未收敛 → 前置 → 人类 全自动多自动一环）

哨兵同岗收敛监控（sentinel.peer_guard）：对同岗协作组（cohort）量化收敛监控。

新模块（peer collab 收尾闭环）按需 import，避免破坏既有依赖：
  from collab import decisions, precursor, human_gate, closure
"""
