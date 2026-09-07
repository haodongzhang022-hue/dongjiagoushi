# ADR-0009：默认真实 cnb.cool 传输通道，mock 降为单测/无 cnb 兜底（模拟数据不可信）

- 状态：Accepted
- 决策日期：2026-09
- 相关：Issue #105（platform-adapter v0.5.0）、`docs/PLATFORM_ADAPTERS.md` 三.8、
  `local-agent/entries/cnb_live.py`

## 背景
用户在 Issue #105 评论区（2026-09-07，PR #113 合并后）明确点破 mock 的局限：
> 「使用**模拟数据的我们一般认为是不可信的**，所以你开发完成这一部分之后，下一步就要尝试去用
> **本地实测**了。**发送信号尝试做配合**，看看能不能达成好的效果，不行的话，然后去做适配。」

v0.3.0 bridge / v0.4.0 dashboard 默认走**本地模拟传输（mock transport）**——只能证明「协议 /
状态机对」，不能证明「真实跨端配合能达成好效果」。用户要求：**本地实测真实通道，发真实信号，
不行再适配**。

## 决策
把传输通道默认从 mock 升级为**真实 cnb.cool 通道**（`entries/cnb_live.py`，cnb CLI / git remote
驱动），mock 降为「单测确定性 / 无 cnb CLI 兜底」，且显式标注 mock 不骗人：
- **默认真实**：`default_transport()` 有真实 cnb CLI → live-cnb（真实优先）；无 cnb → mock 兜底。
  真实使用入口（run.py `--bridge request`、dashboard `control('request')`）默认走真实。
- **单测保留 mock**：`bridge.request_cloud_dev(live=False)`（函数默认）走 mock，保单测确定性、
  不污染真实仓库；`test_cnb_live.sh` 信号灯用 mock 跑确定性断言。
- **真实信号配合**：`send` 真实在目标仓库建云开发请求 Issue 作 cloud_ref 锚；`poll` 真实读云端
  Issue 状态（不臆造 PR）；`ack` collect 后真实回执；`probe` 通道探测（默认只读不污染）。
- **健康反映真实**：dashboard `snapshot()` health 含 `live_transport` 真实可达性探测，health 红灯
  即真实通道不可达——诚实暴露，不假装成功。
- **`--serve` 常驻 HTTP**：把聚合页挂可常驻服务（标准库 http.server），浏览器直接开。

## 为什么不是「保留 mock 做默认 + 可选真实」
用户点破 mock 不可信——mock 无法证明真实跨端配合能达成。默认真实 + mock 兜底，才能让每次真实
使用都在真实通道上核验（发送真实信号、看能否达成，不行就适配），而不是停留在「看起来通的假状态」。

## 后续可能
- 若某宿主无 cnb CLI / 网络受限：probe 如实降级暴露（mock 兜底），并把受限显式反馈（不假装成功）。
- web/gemini 工具桥的真实宿主传输仍经 transport 抽象注入，协议与状态机与此一致。
