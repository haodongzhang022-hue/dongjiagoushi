# 外部事件源接入 · 多终端协同 + 秘钥/IP白名单安全 + 本地上位机辅助

> 本文件描述本仓库的「**外部事件源接入层**」—— 把用户最新拍板的多终端协同落地：
> 首个外部源是**本地电脑**（云端 + 本地协同），手机 / 虚拟机 / 沙盒环境都可能作为
> 终端参与，**不能只支持一个源**；接入**以秘钥 key + IP 白名单**形式做安全认证，
> **webhook 更合理**；上位机部分未解决好，先**预设功能**、之后接入。
>
> 对应 ISSUE #26；可执行载体 `local-agent/dispatcher/`（security/webhook/sources/
> host_helper）+ `local-agent/tests/test_external_source.sh`。

---

## 一、需求来源（用户拍板原文摘要）

| 用户原话要点 | 本层落地 |
|--------------|----------|
| 「首个外部的源其实就是本地电脑，形成云端和本地的协同」 | **本地电脑作为主外部源**（local_pc），云端-本地协同 |
| 「手机作为终端也参与进来，包括虚拟机，还有沙盒环境」 | **多终端源预设**：phone / vm / sandbox / host_upper，不只一个源 |
| 「这些能接入，但安全性是个问题」 | **安全认证层**：秘钥 key + IP 白名单 |
| 「基于我们的开发，可以先以秘钥key+ip白名单形式，webhook似乎更合理」 | **Webhook 接收端** + key/IP 白名单双重校验 |
| 「上位机那部分还没解决好，你先预设功能，之后接入，或当本地上位机给他开发个功能辅助完成角色」 | **本地上位机辅助角色 host_helper**：预设功能，先可运行后接入真实上位机 |

---

## 二、总体设计（外部事件源接入拓扑）

```
  外部终端（本地电脑/手机/虚拟机/沙盒/上位机）
        │  POST /webhook/<source_name>   头: X-API-Key
        ▼
┌───────────────────────────────────────────────────────┐
│  ① security.py  安全认证（秘钥 key + IP 白名单）         │
│     源存在? 启用? key 匹配? IP 在白名单?  → deny-by-default│
│     认证成功/失败都留痕 external_auth（审计）             │
└────────────────────────┬──────────────────────────────┘
                         │ 通过
                         ▼
┌───────────────────────────────────────────────────────┐
│  ② webhook.py  多源 Webhook 接收端                       │
│     按源名路由 → 单事件 / 批量事件 → 规范化                │
└────────────────────────┬──────────────────────────────┘
                         │
                         ▼
┌───────────────────────────────────────────────────────┐
│  ③ sources.py  多源适配器注册（LocalHostAdapter 等）      │
│     本地电脑主动 poll / emit；多终端各自独立适配器          │
└────────────────────────┬──────────────────────────────┘
                         │
                         ▼
       复用 dispatcher 既有链路：normalize → rules → queue
       → guard（防无效）→ router（按 gid）→ webui（面板俯瞰）
```

### 新增模块清单

| 模块 | 职责 | 用户拍板落点 |
|------|------|--------------|
| `dispatcher/security.py` | 外部源登记表 + 秘钥认证 + IP 白名单 + 认证审计 | 秘钥 key + IP 白名单；多源独立授权 |
| `dispatcher/webhook.py` | 多源 Webhook 接收端（POST /webhook/<source>） | webhook 更合理；不只一个源 |
| `dispatcher/sources.py` | 多源适配器注册 + 本地电脑适配器 | 多终端协同（本地/手机/虚拟机/沙盒） |
| `dispatcher/host_helper.py` | 本地上位机辅助角色（预设功能，之后接入） | 上位机未解决好，先预设功能辅助角色 |

### 新增数据表（data/schema.py）

| 表 | 用途 |
|----|------|
| `external_sources` | 外部源登记：独立 key + IP 白名单 + 启停 + 类型 |
| `external_auth` | 认证审计：每次认证成功/失败留痕（源/IP/结果/原因/打码 key） |

---

## 三、安全机制（秘钥 key + IP 白名单）

用户拍板：**安全性是个问题**，先以秘钥 key + IP 白名单形式。

四道安全闸（**deny-by-default**，未登记即拒绝，不猜测放行）：

1. **源存在性**：`/webhook/<source_name>` 的源必须在 `external_sources` 表登记；
2. **启停开关**：源可停用（enabled=0），停用后一律拒绝；
3. **秘钥匹配**：请求头 `X-API-Key` 用**常数时间比较**（`hmac.compare_digest`）校验，
   防时序侧信道；每个源独立 key，多终端互不共享；
4. **IP 白名单**：来源 IP 必须在源绑定的白名单内（支持单 IP 与 CIDR 段；
   `0.0.0.0/0` 或 `*` 表示不限 IP，仅靠 key）。

**认证审计**：每次认证成功/失败都写入 `external_auth` 表，key 只落**打码**形式
（不落明文，安全红线），供 Web 面板俯瞰「谁在何时从哪个 IP 打哪个 key、拦了多少」。

### 预设默认多终端源

`webhook.py` / `host_helper.py` 启动时预设 5 个多终端源（每个独立 key + 白名单）：

| 源名 | 定位 | 默认 IP 白名单 |
|------|------|----------------|
| `local_pc` | 本地电脑（云端-本地协同主源） | `127.0.0.1` / `::1` / `0.0.0.0/0` |
| `phone` | 手机终端 | 空（待配置，deny-all） |
| `vm` | 虚拟机 | 空（待配置） |
| `sandbox` | 沙盒环境 | 空（待配置） |
| `host_upper` | 上位机（部分未解决好，先预设） | 空（待配置） |

> ⚠️ 预设仅生成骨架（功能预设）。除 `local_pc`（本地回环开放）外，其余源默认
> **deny-all**，需你按真实终端 IP 配置白名单后才能真正接入——这是安全兜底。

---

## 四、Webhook 接收端（webhook 更合理）

`webhook.py` 提供统一多源入口 `POST /webhook/<source_name>`：

- 请求头带 `X-API-Key`（该源秘钥）；
- Body 为事件 JSON：单事件 `{"event_type":"requirement","entity":"..."}` 或批量
  `{"events":[...]}`；
- 认证不通过返回 401（审计留痕）；通过后事件注入 dispatcher 同一链路。

```
curl -X POST http://127.0.0.1:8081/webhook/local_pc \
  -H "X-API-Key: sk-xxxx" \
  -d '{"event_type":"requirement","entity":"本地新需求","detail":{"gid":"tk-1"}}'
```

也可复用 Web 面板同一端口（`webui.py` 已挂 `/webhook/*`），便于一处管理。

---

## 五、本地上位机辅助角色（host_helper）

用户拍板：**上位机那部分还没解决好，先预设功能，之后接入；或当本地的上位机，
给他开发个功能去辅助完成这个角色**。

`host_helper.py` 把「本地电脑」视为本体系的上位机主控，预设以下辅助功能
（都可独立演进、先可运行后接真实上位机逻辑）：

| 功能 | 说明 |
|------|------|
| `host_start()` | 启动上位机辅助：预设多源 + 起 Webhook 接收端 |
| `host_report()` | 本地电脑向云端上报事件（经本地 emit 或 webhook） |
| `host_pull_actions()` | 上位机拉取云端派发给本地的动作/任务 |
| `host_ack()` | 上位机确认/驳回一条派发（配合人工闸门） |
| `host_overview()` | 上位机俯瞰本地外部源/认证审计/队列/驳回 |

真实上位机接口未定时，这里提供**可运行的预设实现 + 契约**，后续按真实上位机
仓库/接口填实即可（替换 `local_provider` 或对接 webhook）。

---

## 六、CLI 用法

```bash
# 登记外部源（生成独立 key + 绑定 IP 白名单）
python -m local-agent.dispatcher.cli ext add local_pc --ip 127.0.0.1

# 列出外部源（key 明文仅 CLI 展示，保存后不再显示）
python -m local-agent.dispatcher.cli ext list

# 轮换秘钥（旧 key 立即失效）
python -m local-agent.dispatcher.cli ext rotate local_pc

# 认证审计（安全拦截俯瞰）
python -m local-agent.dispatcher.cli ext audit

# 起多源 Webhook 接收端（本地电脑/手机/虚拟机/沙盒/上位机统一入口）
python -m local-agent.dispatcher.cli webhook --port 8081

# 本地上位机辅助
python -m local-agent.dispatcher.cli host overview
python -m local-agent.dispatcher.cli host report --type requirement --entity "本地需求"
python -m local-agent.dispatcher.cli host pull
python -m local-agent.dispatcher.cli host ack --event-id <ev>
```

---

## 七、Web 面板俯瞰

`webui.py` 新增「🔌 外部事件源」板块，人类可俯瞰：

- 多终端源列表（源名 / 类型 / IP 白名单 / 秘钥打码）；
- 认证审计（✅通过 / ⛔拦截，含来源 IP、拦截原因、时间）；
- 认证统计（allow / deny 计数）。

秘钥**只以打码形式**展示，面板不落明文（安全红线）。

---

## 八、验收与测试

`local-agent/tests/test_external_source.sh` 5 组功能测试（纳入 local-agent 测试信号灯）：

1. **多终端独立授权**：预设 5 源、独立 key、deny-by-default；
2. **秘钥 + IP 白名单认证**：key 匹配 / CIDR 段 / 错误 key / 非白名单 / 停用源 / 审计打码；
3. **Webhook 接收端**：无 key 401、错误 key 401、正确 key 200、单事件 + 批量注入；
4. **本地上位机辅助**：本地上报 / 俯瞰 / 拉取动作；
5. **CLI 命令**：ext add/list/audit、host overview。

回归：既有 dispatcher 测试全绿。
