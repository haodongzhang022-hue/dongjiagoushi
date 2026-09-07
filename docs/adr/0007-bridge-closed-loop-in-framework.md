# ADR-0007：最常用链路（本地⇄网页桥⇄cnb云端异步开发→本地测试先行）作为体系内能力落地，不另立产品/仓库

- 状态：Accepted
- 决策日期：2026-09
- 相关：Issue #105（platform-adapter v0.3.0）、`docs/PLATFORM_ADAPTERS.md` 三.6、`local-agent/entries/bridge.py`

## 背景
用户在 Issue #105 评论区（2026-09-07）补充最常用链路诉求：
> 「最常用的应该会是本地 deepseek harness 然后发送消息给网页的。比如 gemini，它是网页对话
> 的形式，然后让它调用工具发送消息到本地的 deepseek harness 的桥。接收信息，结合本地管理
> 能力和测试能力，发送消息给 cnb.cool 这样进行开发，然后把结果返回到本地完成闭环。……
> 本地测试可以减少云端构建环境这种问题…… 然后这应该是我们常规的形式…… 一套架构式框架是
> 本地 deepseek harness 也会使用的。优先优化这一条链路下的场景。」

## 决策
「本地⇄网页(gemini)工具桥⇄cnb.cool 云端异步开发 → 云端产出回传本地对齐 → 本地测试先行」这条
最常用链路，**作为 platform-adapter 体系内的一条闭环能力落地**（`entries/bridge.py`），**不另立
产品、不开 3rd 仓库、不为"桥"单独造协议**：
- 复用「本地 ⇄ 云端桥」既有通道：cnb.cool=原生 `[触发]` 接力卡 / Issue 评论；web/gemini 工具桥=
  经本地 harness 同一套桥协议发卡（`CLOUD_LOCAL_COOP` / CloudBatch 攒批一致）。
- 一次云开发请求 = **一个桥接句柄（CloudDevHandle，带 gid）**——解决用户点名「长时开发、跨很多
  对话/PR、可能跨仓库」的上下文连续性（句柄二次触发取回同一 gid，不漂移、不丢）。
- **本地测试先行门**内建为能力：识别 CPU 密集/长耗时测试下放本地（skipped_cloud_build），云端只
  保留 LLM 强相关 + 评审——直击用户点名「云端测试建一次环境成本大」的主要成本点。
- 对齐层把云端产出（merged/done/need_fix + PR）回写本地 relay/data，本地 harness 与网页桥读同一份
  「本地对齐后状态」。

## 后果（权衡）
- 好处：最常用链路在**同一套框架**里可执行、可单测（确定性 mock 传输 + 真实 cnb/web 桥经 transport
  注入）；不拆仓库即避免对齐地狱（延续 ADR-0006）；云端建环境成本通过本地测试先行显著下降。
- 代价：默认传输是本地模拟，真实 cnb.cool API / web 工具桥需宿主注入 transport（本仓给到协议与
  全链状态机，宿主只接通道）；桥接句柄需维护（但复用 gid 体系，成本低）。难反转，记 ADR。
