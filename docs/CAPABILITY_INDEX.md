# 能力/功能索引 · CAPABILITY_INDEX（唯一事实源）

> **定位**：本仓库能力的**单一规范索引**（借鉴 mattpocock/skills 顶层 README + bucket README
> + `ask-matt` 路由）。任何 agent / 人类想知道「我这种情况该用哪个机制/能力、找谁、触发词是什么、
> 唯一事实源在哪、版本线到哪」，先查这一张表。
>
> **铁律**：本表是**入口与事实源索引**，不是规则正文。每行的「唯一事实源」才承载正文；
> 若正文有变，先改正文再回来刷本表（防索引漂移）。

## 一、能力/机制总索引（按能力域分组）

| 能力域 | 能力/机制 | 触发词 | 唯一事实源 | 文档位置 | 演进版本线 |
|---|---|---|---|---|---|
| **入口** | 架构·秘书（强制入口+路由）| 秘书/入口/接待/先看看 | `.cnb/settings.yml` + `AGENTS.md·默认入口协议` | docs/SECRETARY_SENSE.md | module_version 声明头 |
| **入口** | 三入口归一化（platform-adapter）| 三入口/入口归一化/网页对话/cnb/local/多宿主/谁当入口 | `local-agent/entries/` | docs/PLATFORM_ADAPTERS.md | Issue #105 · module platform-adapter v0.2.0 |
| **桥接闭环** | 本地⇄云端桥接闭环（entries.bridge）| 最常用链路/本地deepseek harness/网页gemini工具桥/云开发请求/异步句柄/跨对话/跨PR/跨仓库/本地数据对齐/本地测试先行/云端建环境贵 | `local-agent/entries/bridge.py` | docs/PLATFORM_ADAPTERS.md 三.6 | Issue #105 · module platform-adapter v0.3.0 |
| **模型** | 模型路由（统一配置文件 + 多级降级链 + 真实接线）| 模型/统一配置/配置文件/角色指定(默认不启用定制)/主模型/备用模型/多级备选/降级/渠道不通/配置生效/非单次有效/按角色/v4.1 flash/codebuddy/glm | `local-agent/model_routing/models.yml`（唯一配置文件）| docs/MODEL_ROUTING.md | Issue #147 · module model-routing v0.3.0-update |
| **聚合控制页** | 跨端聚合控制页（entries.dashboard）| 聚合控制/fastapi聚合页/状态显示/每端面板/跨端交互/控制台/健康灯/一键控制/overview/panel | `local-agent/entries/dashboard.py` | docs/PLATFORM_ADAPTERS.md 三.7 | Issue #105 · module platform-adapter v0.5.0 |
| **真实通道** | 真实 cnb.cool 传输（entries.cnb_live）| 模拟数据不可信/本地实测/真实传输/发信号配合/通道探测/默认真实/mock仅单测兜底/真实闭环 | `local-agent/entries/cnb_live.py` | docs/PLATFORM_ADAPTERS.md 三.8 | Issue #105 · module platform-adapter v0.5.0 |
| **宿主传输** | 三宿主真实传输注册表（entries.host_transport）| 三宿主/真实宿主传输/本地deepseek harness/网页gemini工具桥/local-harness真实relay/web-bridge真实HTTP/别名归一/bridge via/三宿主可达矩阵 | `local-agent/entries/host_transport.py` | docs/PLATFORM_ADAPTERS.md 三.9 | Issue #105 · module platform-adapter v0.6.0 |
| **需求** | 架构·产品（需求澄清）| 需求/澄清/用户故事/边界 | `.cnb/settings.yml` + roles/product.py | docs/ISSUE_MANAGEMENT.md | agent_version |
| **架构** | 架构·总师（架构八步）| 架构/设计/技术方案/架构八步 | `.codebuddy/skills/architect/SKILL.md` | docs/ARCHITECTURE.md | framework 版本线 |
| **架构** | 架构·总师助理（改错改框架专项）| 改错/改框架/框架修正 | `roles/chief_assistant.py` | docs/CHIEF_ASSISTANT.md | agent_version |
| **调度** | 架构·经理（分配调度核心）| 分配/调度/派活/派任务/经理 | `roles/manager.py` | docs/DISPATCHER.md | agent_version |
| **调度** | 分发深度模型 L1-L4 | 派发/派活深度/接单 | AGENTS.md·分发递进深度 | docs/DISPATCH_DEPTH.md | Issue #33 |
| **全员** | 对结果负责·真实唤醒闸门 | 假装分配/断链/待回执/不报L4 | `dispatch_engine.py`·真实唤醒闸门 | docs/DISPATCH_DEPTH.md | Issue #100 |
| **全员** | 派发能力（DispatchAbility）| 派发/接单/分发 | `local-agent/dispatch/` | docs/DISPATCH_ABILITY.md | Issue #33 |
| **全员** | 深度能力（DepthAbility L1-L7）| 唤醒/协作深度/到结果 | `local-agent/depth/` | docs/DEPTH_MODEL.md | Issue #47 |
| **全员** | 真实唤醒校验（dispatch_verify）| 假装分配/未唤醒/待回执 | `dispatch_engine.py` + `dispatch/` | docs/DISPATCH_DEPTH.md §八 | Issue #100 |
| **全员** | @ 定位能力（HandleAbility）| 跨仓库/@ 格式/权限 | `local-agent/handle/` | docs/HANDLE_ABILITY.md | 通用 |
| **全员** | 标签能力（LabelAbility）| 打标/进度/优先级/标签 | `local-agent/label/` | docs/LABEL_AUTOMATION.md | Issue #51 |
| **全员** | 开发规范能力（StandardAbility）| 合规/规范/检查/标准 | `local-agent/dev-standard/` | docs/DEV_STANDARD.md | Issue #83 |
| **协作** | 同岗协作（PeerCollab）| 会诊/编队/补位/同岗 | `local-agent/collab/` | docs/PEER_COLLAB.md | Issue #47 |
| **协作** | 同岗收尾闭环 | 会诊未收敛/收尾 | `local-agent/collab/closure.py` | docs/PEER_COLLAB_CLOSURE.md | Issue #47 |
| **质量** | 统一审查处置标签 | merge/proceed/fix_bug/human/consult/vote | `local-agent/collab/disposition.py` | docs/REVIEW_DISPOSITION.md | Issue #47 |
| **质量** | 有效性度量模型 | 度量/有效性/解决度/缺陷/稳定性/通用性/一致性 | `local-agent/review_metrics/` | docs/REVIEW_METRICS.md | Issue #100 决策⑤ |
| **质量** | 评审双轴必走（do_review 主流程强制）| 双轴/Standards/Spec/do_review/缺轴不完整 | `roles/reviewer.py` | docs/REVIEW_DUAL_AXIS.md | Issue #98 |
| **质量** | 功能级校验（feature-verify）| 功能校验/功能做完/feature-verify/feature-regress/坏功能定位 | `scripts/feature-verify/` + `scripts/feature-verify.sh` | docs/FEATURE_VERIFY.md | Issue #109 |
| **效率** | 评审增量上下文（review-context）| 评审复述/增量上下文/冻结骨架/免复述/上下文复用 | `local-agent/review_context/` | docs/REVIEW_EFFICIENCY.md | Issue #150 · module review-context v0.2.0 |
| **效率** | 评审段调度器（review-cycle）| 评审段/攒批/异步收集/同指纹不重复构建/减CPU损耗 | `local-agent/review_cycle/` | docs/REVIEW_EFFICIENCY.md | Issue #150 · module review-cycle v0.2.0 |
| **效率** | 攒批去重门（bus diff_fp）| 攒批去重/同指纹不重复发车/一次构建摊全批 | `local-agent/hybrid/bus.py` | docs/REVIEW_EFFICIENCY.md | Issue #150（hybrid bus 增强）|
| **质量** | 审核前置助手（决策补全）| 二选一/拿不准/解决不掉/换方案 | `roles/manager.py`(审核前置) | docs/REVIEWER_PRECURSOR.md | Issue #47 |
| **防无效** | 监控哨兵 | 监控/哨兵/停滞/横跳/无效努力 | `local-agent/sentinel/` | docs/SENTINEL.md | Issue #33 |
| **裁决** | 主链路裁决规则 ②③④ | 暂停点分级/AI优先/沿原意图/以测试为准 | AGENTS.md·主链路裁决规则 | docs/MAINLINE_RULES.md | Issue #100 |
| **规模** | 规模预设 + 3 阶段渐进 | prescale/规模/档位/阶段 | `local-agent/scale/prescale.py` | docs/ENTRY_PRESCALE.md | Issue #41 |
| **规模** | 秘书层动态扩展机制 | 秘书层/动态扩展/识别/注册/路由/秘书护栏 | `local-agent/scale/secretary_scale.py` | docs/SECRETARY_SCALE.md | Issue #100 决策① |
| **拓扑** | 融合路由（规模→拓扑）| 拓扑/路由/agile/dag | `local-agent/topology/` | docs/ROUTER.md + FUSION_TOPOLOGY.md | Issue #41 |
| **流水线** | 小组闭环（DevTeam）| 小组/开发小组/整合 | `local-agent/dev_team.py` | docs/DEV_TEAM.md | Issue #74 |
| **流水线** | 接线驱动层（dev-team-driver）| 驱动/接线/开发小组 | `local-agent/dev_team_driver.py` | docs/DEV_TEAM.md | Issue #74 |
| **流水线** | 开发增强拓扑 dev_enhanced | dev_enhanced/8节点 | `topology/topologies.py` | docs/DEV_ENHANCED.md | Issue #74 |
| **数据** | 数据底座（DataAdmin）| 数据/存档/进度/消息/任务 | `local-agent/data/` | docs/DATA_ARCHITECTURE.md | Issue #18 |
| **数据** | 标签自动化+进度推手 | 进度标签/自动化打标/推手 | `roles.d/progress_pusher.py` | docs/LABEL_AUTOMATION.md | Issue #51 |
| **并行** | hybrid（云端-本地并行）| hybrid/并行/缓存/批量 | `local-agent/hybrid/` | docs/HYBRID_*.md | Issue #90/#65 |
| **工具** | 找工具 / 对齐 | 找工具/对齐/现成方案 | `roles/tool_finder.py` | docs/EXTERNAL_SOURCE.md | 市场层 |
| **文档** | 领域术语表 CONTEXT.md | CONTEXT/术语表/共享语言 | `CONTEXT.md`(root) | 本仓库根 + CONTEXT-MAP 约定 | Issue #98 |
| **文档** | 决策记录 ADR | ADR/决策记录 | `docs/adr/` | docs/adr/0001-*.md | Issue #98 |
| **索引** | 能力索引（本表）| 功能索引/能力索引/该用哪个机制 | `docs/CAPABILITY_INDEX.md` | 本文件 | Issue #98 |
| **追踪** | 追踪问题（agent-ready brief）| triage/brief/被否需求/wontfix | AGENTS.md + roles/secretary.py | Issue #98(在建) | Issue #98 |

## 二、角色总索引

> 每个角色 = 一段触发能力，@ 输入「架构」自动补全。本表是角色唯一事实源（settings.yml）+ 语义触发词速查。

| 角色 | 语义触发词 | 唯一事实源 | 定位一句话 |
|---|---|---|---|
| 架构·秘书 | 默认入口/接待/先看看 | settings.yml | 接住诉求→翻译→路由留痕 |
| 架构·产品 | 需求/澄清/用户故事 | settings.yml | 需求澄清与拆分 |
| 架构·总师 | 架构/设计/方案/八步 | settings.yml+skill | 设计核心 |
| 架构·总师助理 | 改错/改框架 | settings.yml | 框架修正专项 |
| 架构·经理 | 分配/调度/派活 | settings.yml | 分配调度核心 |
| 架构·小组长 | 子任务/整合/加派 | settings.yml | 子任务细化与整合 |
| 架构·开发 | 写码/实现/自测/PR | settings.yml | 实现 |
| 架构·评审 | 评审/走查/质量 | settings.yml | 质量守门 |
| 架构·测试 | 联调/测试/验收/信号灯 | settings.yml | 质量验收 |
| 架构·交付 | 交付/收尾/汇总/呈现 | settings.yml+DELIVERER | 呈现+收尾 |
| 架构·数据管理员 | 数据/存档/进度 | settings.yml | 数据底座唯一负责人 |
| 架构·监控哨兵 | 监控/哨兵/停滞 | settings.yml+sentinel | 防无效努力 |
| 架构·进度推手 | 打标/进度/推手 | settings.yml+label | 进度标签自动化 |
| 架构·审核前置助手 | 二选一/拿不准 | settings.yml | 决策补全 |
| 架构·找需求/价值确认/竞品分析 | 找单/价值/竞品 | settings.yml | 市场情报线 |
| 架构·找工具 | 找工具/现成 | settings.yml | 工具检索 |
| 架构·对齐 | 对齐/待办对齐 | settings.yml | 待办对齐 |
| 市场·销售/客服/数据/渠道/工具 | 获客/客服/数据/渠道/工具 | settings.yml | 市场获客五层 |

## 三、ask-matt 式路由速查（"我这种情况该用哪个"）

> 类比 mattpocock 的 `ask-matt`：不知道自己该用哪个机制时，按「我的处境」定位到机制。

| 我的处境 | 去哪个机制/能力 |
|---|---|
| 我不清楚需求要做什么 | 架构·产品 / 架构·秘书（澄清+用户故事） |
| 我要设计一个系统/模块 | 架构·总师（架构八步）→ 架构·经理（调度） |
| 我要把一个需求拆给多个 agent 干活 | 架构·经理 dispatch + DispatchAbility（L1-L4）|
| 我要跨仓库召唤角色 | HandleAbility（不写死角色名）|
| 我要"真唤醒"对端而非只描述 | DepthAbility awake（L3 校验回执）|
| 我怕一个功能只"列个表/断言/通畅"就算做完 | feature-verify（功能级校验：一 PR 一脚本，跑不过=没做完）|
| 崩了/升级后想定位是哪个功能坏 | scripts/feature-regress.sh（全量回归逐个定位坏功能）|
| 我怕秘书/经理/产品"列个表假装完成" | dispatch_verify 真实唤醒校验（无回执暴露 awaiting_receipt）|
| 我在裁决暂停/放行，哪些卡人哪些 AI 自动 | 主链路裁决规则②（暂停点分级：低中 AI 自动+错改，高风险卡人）|
| 我想给一个失败实现补好（不主导方向） | 主链路裁决规则③（修复=沿原意图：先复述原意图再补）|
| 评审/测试到底怎么判有效 | 主链路裁决规则④（以测试为准，不靠看法）→ 既有客观闸门（dev_standard 检查器 + do_review 双轴 + 统一处置标签）|
| 我在做开发，想知道合规项 | StandardAbility（dev-standard 强制清单）|
| 我在评审，该如何处置 | disposition（merge/proceed/fix_bug/...）+ 双轴 |
| 我感觉一个 agent 在无效空转/停滞 | 监控哨兵（停滞/横跳/重复错误）|
| 我面对"二选一都不够好" | 架构·审核前置助手（决策补全）|
| 我不知道某个机制的最新规则 | 回本表找「唯一事实源」，改正文再刷本表 |
| 我想知道"某次评审/交付到底有没有效解决" | 有效性度量模型（review-metrics：维度化+分档+留痕；评审走 do_review 自动留处置观测）|
| 我想判断"某个场景要不要设个秘书/加个秘书层" | 秘书层动态扩展机制（识别/注册/路由+权限护栏）|
| 我想了解统一术语别叫混 | CONTEXT.md（共享语言）|
| 我想知道某个架构取舍为什么这么做 | docs/adr/（决策记录）|
| 我想推进度/打标/调优先级 | LabelAbility / 进度推手 |
| 我要改模型/想知道某角色用哪个模型/想知道配置有没有真生效 | model-routing（改 `local-agent/model_routing/models.yml` 一处：default.chain 通用链 + roles 按角色覆盖；角色名已接进调用链，改配置即长期生效；`PYTHONPATH=local-agent python3 -m model_routing.cli chain [角色]`）|
| 评审每轮都要我复述整个大项目 | 评审增量上下文（review-context：冻结骨架摘要 + 本轮变化）|
| 评审/开发反复触发、CPU 构建损耗大 | 评审段调度器（review-cycle：攒批 + 同指纹不重复触发 + 一次构建摊全批）|

## 四、维护纪律

1. 新增机制/能力/角色 → 在本表加一行 + 建/更新「唯一事实源」正文；
2. 正文变更 → **先改正文，再回来刷本表对应行**（防索引漂移，配 test_doc_consistency 防漂移护栏）；
3. 演进版本线 = 模块/能力自己的 module_version / agent_version（详见 docs/ISSUE_MANAGEMENT.md）；
4. 术语统一走 CONTEXT.md，决策取舍走 docs/adr/。
