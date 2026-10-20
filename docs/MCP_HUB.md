# MCP 汇聚注册表（MCP_HUB）

> **定位**：给本仓已有的多个 MCP 面一个**专门存放位置**——一张说得清「哪个端点提供哪些
> 工具、从哪来、怎么起」的登记表，加一个统一入口。之前对端要挨个翻四份文档才拼得出全貌。
>
> **触发词**：MCP / mcp 收录 / MCP 注册表 / 端点清单 / 3092 / 统一入口 / mcp 服务 /
> 端口 / 前端形态 / jsonrpc / sse / 一把梭 MCP
>
> **唯一事实源**：`local-agent/mcp_hub/specs.py`（端点登记表）
>
> **接线点**：`local-agent/mcp_hub/cli.py`（`catalog/tools/call/serve/launch/status`）
> —— CLI 与库同一份实现，不是孤岛。

---

## 一、要解决的问题

本仓其实**已经有四个 MCP 面**，但它们是四个孤岛：

| 端点 | 形态 | 提供的能力 |
|---|---|---|
| `dsh-adapter/src/bridge.ts` | TypeScript 桥 | `dsh.compat` / `standard.*` / `label.*` / `relay.*`（7 个） |
| `dev_standard/host.py` | Python JSON host | `standard.*`（6 个） |
| `dispatcher/webhook.py` | HTTP webhook | `roster.*`（派单，走秘钥+IP 白名单） |
| `label/cli.py` + `relay_card` | CLI 管线 | `label.*`（12 个）/ `relay.*`（2 个） |

问题不是"能力不够"，是**没有一个地方能回答"我这儿一共有哪些 MCP 工具"**：
对端接一次要读四份文档、猜端口、自己判断哪个跑得起来。

所以 `mcp_hub` 做的是**登记 + 收口**，不是再造第五个实现。

---

## 二、存放位置的切分（为什么不是新目录约定）

| 固定位置 | 实质 | 谁维护 |
|---|---|---|
| `local-agent/mcp_hub/specs.py` | **汇聚注册表**（一行一个端点） | 本模块 |
| `local-agent/<模块>/mcp.py` | **单模块工具定义** | 各模块自己 |

工具清单**留在模块内**，hub 只登记——否则又变成一份会漂移的副本（这正是 roster 那轮
被评审打回的同类问题：事实源归并，不新增第五份清单）。

---

## 三、三个前端，一处语义

```bash
# 同一个服务，三个端点
GET  /health       # 三前端都可用，无副作用
POST /message      # 默认文本端点：{"tool","params","operator"}
GET  /sse          # 事件流：先推 endpoint 事件，客户端再 POST /message
POST /jsonrpc      # 规范线：JSON-RPC 2.0（initialize / tools/list / tools/call）
```

**能力集合完全一致**：三个前端最终都走 `mcp_hub.dispatch.call()`，不存在「http 能调、
sse 调不了」。信号灯里有一条专门比对两前端 `tools/list` 数量——分叉就红。

---

## 四、四个刻意取舍

**① 无状态优先（零握手也能用）**
`/message` 与 `/sse` 不强制 `initialize` 握手。MCP 规范里客户端应先 initialize，但现实中
"旧客户端只发 POST"很常见：服务要等握手就永远等不到。所以握手不设为闸门——`/jsonrpc`
端点仍按规范回 `initialize` 结果，两边都活。

**② 端口只做建议，不当契约**
`specs.py` 里的 `port` 是**建议值**，真端口以 `--port` 为准（方便多实例隔离、也方便测试）。
端口在库里只出现一次（`port_owners()` 有信号灯核验），避免"文档写一个、代码写另一个"。

**③ 未接线就如实说 `not_wired`，不代调**
- `roster.*` 走 `POST /webhook/<source>/roster`（真实鉴权 + IP 白名单），hub **不代调**，
  返回 `http_only` 并给出正确路径；
- `dsh.*` 由 dsh 插件装载时经子进程桥调用，hub 返回 `external_host`；
- `label.*` 写操作必须带 `operator`（白名单在 label 模块内校验），裸调返回
  `operator_required` —— 不回「看着成功」的假绿。

**④ 启动与探活是同一个请求**
`launch()` 一次调用就返回「起没起、复用没复用、在哪、有哪些工具」，不返回空壳：

```json
{"ok": true, "reused": false, "started": true, "port": 3092,
 "url": "http://127.0.0.1:3092", "tools": 32,
 "front_endpoints": {"http": ".../message", "sse": ".../sse", "jsonrpc": ".../jsonrpc"}}
```

端口被别的进程占着 → `ok=false + reason=port_in_use_by_other_process`；
子进程退出或探活超时 → `ok=false + reason=start_failed + 日志路径`。

---

## 五、用法

```bash
cd local-agent

python -m mcp_hub.cli catalog            # 端点/工具清单 + 可达状态
python -m mcp_hub.cli catalog --json     # 给对端/CI 吃
python -m mcp_hub.cli tools              # 一行一个工具名（grep 友好）
python -m mcp_hub.cli call relay.check '{"text":"@org/repo(架构·开发) [触发:架构·开发]"}'
python -m mcp_hub.cli call label.apply '{"entity":"issue-1","label":"p2"}' --operator 架构·开发
python -m mcp_hub.cli launch --port 3092 # 拉起 + 探活回执（同一请求）
python -m mcp_hub.cli status             # 只探活
```

```python
from mcp_hub import catalog, launch, call, tools

catalog()["tool_count"]                 # 32
launch()["front_endpoints"]["jsonrpc"]  # 直接拿去配客户端
call("relay.gen", {"to": "架构·评审"})   # 不经网络
```

---

## 六、信号灯

`local-agent/tests/test_mcp_hub.sh`（27 项）：

端点登记与真实模块对齐（登记的路径/文件必须真存在）· 五个 MCP 面全覆盖 ·
端口建议唯一 · 转发是真调（relay.check 能判合法/非法卡、standard.summary 拿真实规范数）·
拒判不假装（`unknown_tool` / `http_only` / `operator_required` / `external_host`）·
三前端一处语义（health 无副作用 / message / sse endpoint / sse POST / jsonrpc initialize /
jsonrpc tools/call / 两前端工具数一致）· 已在跑则复用 · 探活不假装（没起必须 alive=false，
停服后立刻为 false）。

红灯含义：**登记与真实模块漂移**，或**某个前端退化成空壳**。

---

## 七、索引

| 产物 | 位置 |
|---|---|
| 本说明 | `docs/MCP_HUB.md` |
| 端点登记表（唯一事实源） | `local-agent/mcp_hub/specs.py` |
| 工具转发 | `local-agent/mcp_hub/dispatch.py` |
| 三前端服务 | `local-agent/mcp_hub/server.py` |
| 握手/探活 | `local-agent/mcp_hub/registry.py` |
| CLI | `local-agent/mcp_hub/cli.py` |
| 信号灯 | `local-agent/tests/test_mcp_hub.sh` |
| 既有端点文档 | `docs/DSH_ADAPTER.md` · `docs/DEV_STANDARD.md`（M5）· `docs/ROSTER.md` · `docs/LABEL_AUTOMATION.md` |
| 多宿主适配总览 | `docs/PLATFORM_ADAPTERS.md` 四.3 |
