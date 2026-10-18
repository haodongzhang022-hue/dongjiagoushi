# -*- coding: utf-8 -*-
"""
MCP 汇聚注册表（mcp_hub）
=========================
本仓已有 **4 个 MCP 面**（`dsh-adapter` 桥 / `dev_standard/host.py` /
`dispatcher/webhook.py` 的 roster / `label`、`relay_card` 的 CLI 管线），但**没有一张表
说清"这个端点提供哪些工具、从哪来、怎么起"**，也没有统一入口——对端要挨个翻文档。

本模块给的就是那个**专门存放的位置**：

    local-agent/mcp_hub/
      ├── specs.py      端点登记表（唯一事实源：id / 端口 / 前端 / 工具 / 转发方式）
      ├── dispatch.py   工具转发（自己不实现业务，未接就如实 `not_wired`）
      ├── server.py     统一入口，三前端一处语义（http / sse / jsonrpc）
      └── cli.py        catalog / serve / call / tools

对外四个函数：

    from mcp_hub import catalog, launch, call, tools

    catalog()                          # 有哪些端点、哪些工具、跑没跑起来（握手）
    launch(workspace, port=3092)       # **同一个请求**拉起服务 + 探活回执
    call("relay.check", {"text": ...}) # 不经网络直接调（CI/本地脚本用）
    tools()                            # 全量工具清单（MCP tools/list 形态）

三条硬约束（改之前先看 docs/MCP_HUB.md）：

  1. **工具清单留在模块内**，hub 只登记——否则又成一份会漂移的副本；
  2. **前端三形态不减项**：http / sse / jsonrpc 能力集合完全一致；
  3. **端口只做建议**：`specs` 里的 port 是「建议值」，真端口以启动参数为准（便于隔离
     多实例）；已在跑则复用，不重复起。
"""
from .specs import ENDPOINTS, FRONTS, endpoint_by_id, endpoint_for_tool, port_owners, tool_names
from .registry import catalog, launch, status
from .dispatch import call
from .server import tool_list as tools, serve

__all__ = [
    "ENDPOINTS", "FRONTS", "endpoint_by_id", "endpoint_for_tool", "port_owners",
    "tool_names", "catalog", "launch", "status", "call", "tools", "serve",
]
