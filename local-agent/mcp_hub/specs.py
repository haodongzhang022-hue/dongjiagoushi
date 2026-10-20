# -*- coding: utf-8 -*-
"""
MCP 汇聚注册表 · 规格层（唯一事实源）
====================================
「专门存放的位置」不是一个新目录约定，而是**两个固定位置 + 三层职责**：

  | 固定位置 | 实质 | 谁在用 |
  |---|---|---|
  | `local-agent/mcp_hub/` | **汇聚注册表**（这个文件） | 所有 MCP 端点的登记处，缺登记即不对外 |
  | `local-agent/<模块>/mcp.py` | **单模块工具定义** | 各模块自己维护工具清单，不被搬走 |

刻意如此切分：
  - 工具清单**留在模块内**（`dev_standard/mcp.py` 已经在用），不搬进 hub，否则又成一份会漂移的副本；
  - hub 只记「这个端点提供哪些工具、从哪来、怎么起」，一行一个，可核验；
  - `local-agent/dispatcher/webhook.py` 是**那一个入网口**，hub 不另起鉴权实现。

对齐 AGENTS.md「一域一事实源」：条目变更先改本文件，再刷 `docs/MCP_HUB.md` 与 CAPABILITY_INDEX。
"""

# 前端三形态：同一个 MCP 服务对外只差一层皮，不减任何一项
#   http   —— 默认文本端点（够用、可 curl、无状态）
#   sse    —— 事件流端点（长连接场景，GET /sse）
#   jsonrpc—— MCP 规范线（Content-Type: application/json，JSON-RPC 2.0）
FRONTS = ["http", "sse", "jsonrpc"]

# 端点登记表。加一个 MCP 端点 = 这里加一行 + 模块内暴露 TOOL_SPECS。
#   id      稳定标识，跨版本不改（对端据此寻址，不靠中文名）
#   port    **建议**端口（占位即冲突源，只许建议）
#   source  tools/call 的转发实现：模块内 call_mcp(tool, params, operator)
#   scope   standard.* 类工具名的规范前缀（None = 不限定）
ENDPOINTS = [
    {
        "id": "dsh-adapter",
        "name": "dsh 适配桥",
        "kind": "bridge",
        "port": None,
        "fronts": ["http"],
        "module": "dsh-adapter/src/bridge.ts",
        "call_via": "node <repo>/dsh-adapter/lib/index.js（构建产物）",
        "tools": ["dsh.compat", "standard.summary", "standard.enforced",
                  "label.progress", "label.apply", "relay.check", "relay.gen"],
        "material": True,
        "note": "经子进程桥转 Python，本 hub 不代调：避免与插件装载流程两套语义",
    },
    {
        "id": "dev-standard",
        "name": "开发规范宿主",
        "kind": "in-process",
        "port": 8701,
        "fronts": ["http", "sse", "jsonrpc"],
        "module": "dev_standard/host.py",
        "call_via": "dev_standard.mcp.call_mcp",
        "tools": ["standard.list", "standard.get", "standard.enforced",
                  "standard.check", "standard.report", "standard.summary"],
        "material": False,
        "note": "既有 JSON host（POST /rpc），本 hub 只做登记与统一入口",
    },
    {
        "id": "roster",
        "name": "角色名册派单",
        "kind": "webhook",
        "port": None,
        "fronts": ["http"],
        "module": "dispatcher/webhook.py",
        "call_via": "POST /webhook/<source>/roster（X-API-Key + IP 白名单）",
        "tools": ["roster.catalog", "roster.resolve", "roster.verify",
                  "roster.intake", "roster.drift"],
        "material": False,
        "note": "HTTP 形态，经真实鉴权；hub 的 http 前端复用同一套 message 语义",
    },
    {
        "id": "label",
        "name": "标签 MCP 管线",
        "kind": "cli",
        "port": None,
        "fronts": ["http"],
        "module": "label/cli.py",
        "call_via": "label.LabelAbility",
        "tools": ["label.progress", "label.status", "label.labels", "label.apply",
                  "label.remove", "label.propose", "label.review", "label.auto",
                  "label.depends", "label.next", "label.priority", "label.node"],
        "material": True,
        "note": "查询工具已可转发；写操作需 --operator 白名单：裸调一律拒（不回假绿）",
    },
    {
        "id": "relay-card",
        "name": "接力卡校验",
        "kind": "cli",
        "port": None,
        "fronts": ["http"],
        "module": "relay_card/__main__.py",
        "call_via": "relay_card.check / gen",
        "tools": ["relay.check", "relay.gen"],
        "material": True,
        "note": "纯函数型，可直接转发",
    },
]

# 转发隔离：tools/call 在子进程里跑，一个工具崩不拖垮 hub
CALL_TIMEOUT_SECONDS = 30


def endpoint_by_id(endpoint_id):
    for e in ENDPOINTS:
        if e["id"] == endpoint_id:
            return e
    return None


def endpoint_for_tool(tool_name):
    """工具名 → 端点。同名工具被多个端点声明时取第一个（登记顺序即优先级）。"""
    for e in ENDPOINTS:
        if tool_name in e["tools"]:
            return e
    return None


def tool_names():
    names = []
    for e in ENDPOINTS:
        for t in e["tools"]:
            if t not in names:
                names.append(t)
    return names


def port_owners():
    """建议端口 → 端点列表。用于端口冲突核对（只提示，不阻断）。"""
    owners = {}
    for e in ENDPOINTS:
        port = e.get("port")
        if port:
            owners.setdefault(port, []).append(e["id"])
    return owners
