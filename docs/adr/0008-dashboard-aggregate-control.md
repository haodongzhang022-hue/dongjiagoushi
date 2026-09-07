# ADR-0008：跨端聚合控制页作为 platform-adapter 能力落地（每端一个面板），不另立 web 服务/产品

- 状态：Accepted
- 决策日期：2026-09
- 相关：Issue #105（platform-adapter v0.4.0）、`docs/PLATFORM_ADAPTERS.md` 三.7、`local-agent/entries/dashboard.py`

## 背景
用户在 Issue #105 评论区（2026-09-07，PR #112 通过后）追加诉求：
> 「目前可以本地连接 cnb.cool 不用处理 api 的事情，不过如果有更加聚合的方便控制的能力，可以做一个
> 方便控制的聚合，类似于 fastapi 聚合页包括状态显示，然后每个端我都尝试建立一个，这样跨端交互的
> 就会更加顺畅。」

用户点明：**跨端交互（本地 deepseek harness ⇄ 网页/gemini 工具桥 ⇄ cnb.cool 云端）需要一块
聚合控制面**——像 FastAPI /docs 那样一个地址看到各端状态 + 可触发的一键动作，且**每端（web/cnb/
local）都建一个**，便于顺畅跨端。

## 决策
「跨端聚合控制页」**作为 platform-adapter 体系内的聚合控制能力落地**（`entries/dashboard.py`），
**不开独立 FastAPI web 服务、不另立产品、不散点维护各端状态**：
- **宿主无关聚合（single source）**：`snapshot()` 从三端适配器矩阵 + 本地⇄云端桥接句柄 + 接力卡 +
  成本模型聚合出一张控制台，任何端读同一份聚合，杜绝散点状态。
- **每端一个面板（per-end panel）**：`panel(entry)` 同一聚合器按端过滤出「本端视角」（本端适配器 +
  本端发起句柄 + 本端可用动作）；`all_panels()` 三端并列。延续「一套核心 + 每端适配层」，不另起炉灶。
- **状态显示 + 一键控制**：健康状态灯（🟢/🔴）+ FastAPI 风格路由键（health/overview/entry/{e}/
  handles/relay/control/{action}）；`control()` 动作**回写真实桥接/接力状态机**（request/collect/
  align/localtest），控制台不只是看板、能真操作。
- **人可读 HTML 聚合页**：`html_page()` 输出可嵌入网页桥的 HTML（状态灯 + 表 + 一键动作表单）。
- **真实 API 传输暂不处理**：用户明确「本地可连 cnb.cool、不用处理 API 的事」——真实 cnb.cool API /
  web 工具桥经 transport 抽象注入，本层给协议与状态机（同 ADR-0007），不在此轮硬造 3rd 服务。

## 后果（权衡）
- 好处：跨端交互被「一块控制台」收敛，人类/网页桥/harness 一个地址看到各端状态并一键控制；
  每端一个面板延续每端适配器思路，跨端顺畅、状态不散点；确定性可本地单测（12 项信号灯）。
- 代价：HTML 聚合页目前为**命令/脚本可读**的人读形态，非常驻 HTTP 服务——需真正跑在浏览器
  常驻监听时，由宿主（网页桥/local）把 `html_page` 挂到 FastAPI/静态页即可，核心聚合逻辑不重写。
  难反转，记 ADR。
