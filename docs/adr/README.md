# docs/adr/ — 架构决策记录（ADR 纪律）

> **定位**：把仓库的**架构取舍**沉淀为编号决策记录（借鉴 mattpocock/skills 的 ADR 纪律）。
> 每条一个 ADR，可短到一句话，记「做了 X 决策、为什么这么做」，防后来 agent「修正」掉刻意决策。
>
> **三条铁律（只在三者都满足时才写 ADR）**：
> 1. **难反转**（改了很难回头）；
> 2. **无上下文会困惑**（不记上下文未来会搞不懂为什么要这么干）；
> 3. **有真实权衡**（不是显然最优，有取舍）。

## 文件格式

`docs/adr/00NN-<短横线slug>.md`，编号递增，内容极简：

```
# ADR-00NN：标题

- 状态：Accepted（/ Proposed / Deprecated / Superseded by ADR-00xx）
- 决策日期：YYYY-MM-DD
- 相关：关联 Issue / 文档

## 背景
为什么做这个决策（难反转 / 会困惑 / 有取舍的语境）。

## 决策
做了什么、选哪条路。

## 后果（权衡）
选了它的代价 / 放弃的备选；何时需要重访。
```

## 现有 ADR 索引

| ADR | 决策 | 状态 |
|---|---|---|
| [0001-一库多角色](0001-monorepo-multirole.md) | 单一仓库承载多角色，非多库 | Accepted |
| [0002-架构师零积分不召NPC](0002-architect-zero-credit.md) | 官方 @CodeBuddy 化身，零积分 | Accepted |
| [0003-skill承载架构方法论](0003-skill-carries-architect.md) | 架构方法论走 .codebuddy/skills 而非 npc:go | Accepted |
| [0004-能力全员化而非加角色](0004-ability-generalize.md) | 把作业纪律沉淀为全员通用能力（Dispatch/Depth/Label/Handle/Standard…）| Accepted |
| [0005-一库多角色解耦与防冲突](0005-module-decoupling.md) | 功能模块解耦、独立PR base=main、防耦合冲突 | Accepted |
| [0006-三入口归一化](0006-one-repo-three-entry-adapt.md) | 网页/cnb/local 收敛一套仓库+多层适配+配置管差异，不拆3仓 | Accepted |
| [0007-桥接闭环体系内落地](0007-bridge-closed-loop-in-framework.md) | 本地⇄网页桥⇄cnb云端异步开发→本地测试先行，作为体系能力非独立产品 | Accepted |
| [0008-跨端聚合控制页](0008-dashboard-aggregate-control.md) | 每端一个面板的聚合控制面，不另立 web 服务/产品 | Accepted |
| [0009-默认真实传输](0009-live-transport-over-mock.md) | 默认走真实 cnb.cool 传输，mock 降为单测/兜底 | Accepted |
| [0010-三宿主真实传输](0010-three-host-real-transport.md) | 本地/网页/云端三宿主同契约真实机制，非 mock 假装 | Accepted |
| [0011-评审增量上下文+攒批异步](0011-review-incremental-coalesced-cycle.md) | 评审循环走增量上下文+攒批异步，不做同步乒乓逐轮复述/构建 | Accepted |
| [0012-阶段链门控](0012-stage-chain-gate.md) | 开发→评审→测试走阶段链门控，不让本该串行的环节并行/重复触发 | Accepted |
| [0013-写路径原子化+迁移下沉](0013-write-path-atomic-and-migration-sink.md) | 写路径事务包裹 + 冲突提案负数编号 + 迁移下沉建表入口 | Accepted |
| [0014-dsh适配作为独立模块](0014-dsh-adapter-new-version.md) | dsh 适配独立模块化 + 版本闸门前置（不静默放行），loader 只 import 构建产物 | Accepted |
| [0016-模型三档语义+降级显性](0016-model-fast-tier-and-explicit-degrade.md) | 模型按「档1 指定 / 档2 与其他角色一样 / 档3 兜底」配置，降级必须留痕可见（不静默换模型） | Accepted |

## 维护纪律

- 新决策若同时满足三条铁律 → 新建 `00NN` ADR 并登记到上表；
- 决策被推翻 → 不删除旧 ADR，改状态 `Superseded by ADR-00xx` 并新建新 ADR；
- ADR 收录到 docs/CAPABILITY_INDEX.md（能力域=文档），可被检索。
