# -*- coding: utf-8 -*-
"""
角色名册与派单接入（roster · 对外稳定接口面）
==============================================
外部对端（管理-派单控制面 / 本地中控 / Agent 网关）接进本仓，只需要三个函数：

    from roster import catalog, resolve, intake

    catalog()                  # 你这边有哪些角色、ID、能不能跑（握手）
    resolve("架构·开发")        # 中文名/别名/@串 → role_id（派单前对一次）
    intake({"target": "arch.developer", "task": "..."})   # 派单入场（走标准链路）

设计取舍（为什么不是"再写一份角色清单"）：

  1. **归并而非新增事实源**：角色散在 settings.yml / team.yaml / ROLE_REGISTRY /
     relay_card 四处，本模块只把它们合成一张带 ID 的表，缺口如实暴露（见 specs.py）。
  2. **对端只依赖 ID**：中文名会改名，ID 不会（真改名才在 `ROLED_ALIASES` 登记旧名）。
  3. **不另起派发**：派单翻译成 dispatcher 的标准事件，走既有
     `rules → queue → guard → router` 链路，留痕、去重、护栏全部复用。
  4. **跑不了就拒派**：`ROLE_REGISTRY` 里没有实现类 → `ok=false` + `role_not_implemented`，
     不写 dispatch、不占 dedup。`ok=true` 只代表"真派出去了"。
  5. **不是孤岛**：已接进 `dispatcher.webhook`（`POST /webhook/<source>/roster`），
     对端不必 import 本仓任何模块。

CLI：
    python -m roster catalog [--json]
    python -m roster resolve 架构·开发
    python -m roster verify  --their roles.json
    python -m roster intake  --target arch.developer --task "补 token 刷新" [--dry-run]

HTTP（对端不 import 任意模块）：
    POST /webhook/<source_name>/roster   {"target": "arch.developer", "task": "..."}
"""
from .payload import CONTRACT, catalog, resolve, verify
from .intake import intake, intake_batch, ENTRY_ROLE_ID
from . import specs

__all__ = ["CONTRACT", "catalog", "resolve", "verify",
           "intake", "intake_batch", "ENTRY_ROLE_ID", "specs"]
