# ADR-0010：三宿主真实传输注册表 — 最常用闭环本地/网页两端也走真实机制（非 mock 假装）

- 状态：Accepted
- 决策日期：2026-09
- 相关：Issue #105（platform-adapter v0.6.0）、`docs/PLATFORM_ADAPTERS.md` 三.9、
  `local-agent/entries/host_transport.py`

## 背景
用户最常用闭环 = **本地 deepseek harness ⇄ 网页/gemini 工具桥 ⇄ cnb.cool 云端异步开发**。
v0.3.0~v0.5.0 把 cnb.cool 云端端做成**真实通道**（cnb_live，真实 cnb CLI 建 Issue/读状态/发回执，
ADR-0009「默认真实」），但闭环**另两端**——本地 deepseek harness、网页 gemini 工具桥——仍是
mock 假"投递到云端"，只能证明协议/状态机对，不能证明这两端真实宿主能达成配合。

## 决策
把闭环两端也升级为**真实宿主传输**，与云端端并列成**三宿主传输注册表**
（`entries/host_transport.py`），各实现同一 `{send, poll, ack}` 传输契约（可注入
`bridge.request_cloud_dev` / dashboard），**全程真实机制、不 mock 假装**：
- **cnb-live**（云端端）：真实 cnb CLI（复用 cnb_live）；
- **local-harness**（本地端）：真实 `relay` 接力卡——send 真实 `new_card`+落盘（relay.save）、
  poll 真实读卡状态、ack 真实写回执历史——本地云开发请求**可续跑、可回放**，不再是假"投到云端"；
- **web-bridge**（网页端）：真实 HTTP 通道——本仓 `run.py --serve` 的 `/api`+`/api/control`
  即网页桥可达端点，send/poll/ack 走真实 HTTP 请求（非 mock）；
- **未知宿主如实报错**，不静默回落到 mock。

## 为什么不是「继续 mock + 注入接口等真实宿主自接」
用户（ADR-0009 已点破）认为**模拟数据不可信**。三宿主若继续 mock，等于把「本地 harness /
网页桥能否真实达成配合」悬空到未来，无法核验。用**本仓已有的真实机制**（relay 接力卡本地真实、
--serve HTTP 通道网页真实、cnb CLI 云端真实）各接一版真实 transport，三端都可当下实测、可单测
核验结构、可续跑可回放——诚实暴露真实可达性（overview 三宿主矩阵），而不是假装三端都能通。

## 后续可能
- web-bridge 端把默认 --serve 端口探测做成可配置（PLATFORM_SERVE_PORT 已支持），并可在真实
  --serve 运行态下做一次真实 request/collect 的端到端实证。
