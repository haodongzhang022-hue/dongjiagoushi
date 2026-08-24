# -*- coding: utf-8 -*-
"""
数据管理层（data）—— 本仓库数据架构升级核心
============================================
把原来「单文件接力卡 / 分片 JSON / 进程内 dict」的简单状态存储，升级为
**真正的关系型数据库承载**，支撑最大 **2500 个并发 agent** 的信息互通与持久化：

  - db         数据库连接层（sqlite 默认零依赖 / postgresql 可选，后端抽象）
  - schema     数据表结构（agents / messages / tasks / progress / archives / stats）
  - repository 仓储层（各表统一 CRUD，屏蔽后端差异）
  - admin      数据管理员职责（内容存档/进度统计/消息管线/任务存储 的统一执行）

使用：数据管理员角色（roles.d/data_admin.py）调用 admin.* 完成数据写入；
人类/总师通过 admin.progress_report() / task_overview() 俯瞰二级信息。

对齐现状（scale 层）：
  - 本层是 scale 的**数据底座**，替代 store.py 的 filesystem/memory 后端在
    大规模下的不足；store.py 保留为轻量单例兼容入口。
"""
from . import db, schema, repository, admin

__all__ = ["db", "schema", "repository", "admin"]
