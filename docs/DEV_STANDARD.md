# 开发规范体系设计文档（dev-standard · Issue #83）

## 一、背景与目标

用户在「分支和合并机制优化」探究（#83）基础上，提出构建**一套 Agent 开发规范体系**：

> "独立模块，各处引用使用；深度与开发过程绑定；开发体系可快速遵循的机制；
> 本身应该是一个体系，不应该是孤立的点；以使用结果为准，先搭建后测试，
> 怎么让 agent 学会用。"

**目标**：建立一套**开发规范体系**，让开发 agent 在开发过程中**强制遵循统一规范**，
提升开发质量与一致性，杜绝"半成品、污染残留、各自为政"。

**边界**：① 独立模块可各处引用；② 与开发过程深度绑定（非孤立文档）；
③ 开发体系可快速遵循（MCP/rules/CLI 三机制）；④ 本身是一套完整体系。

**验收标准**：① 规范可被任何开发 agent 程序化查询/检查；② 开发过程中规范被强制触发
（非自觉遵守）；③ agent 能稳定遵循规范并给出合规报告；④ 整套体系有测试验证。

## 二、整体架构（分层）

```
┌─────────────────────────────────────────────────────────────┐
│ 规范定义层（内容）                                           │
│   specs.py 规范条目注册表（唯一事实源）                       │
│   checker.py 确定性规范检查器（非 LLM 判断）                 │
├─────────────────────────────────────────────────────────────┤
│ 能力层（Agent 可遵循）                                       │
│   ability.py StandardAbility（BaseRole 全员挂载）            │
│   mcp.py MCP 工具（standard.*）   cli.py CLI（MCP 管线）     │
├─────────────────────────────────────────────────────────────┤
│ 机制层（绑定开发过程）                                       │
│   AGENTS.md 固定规则 + rules.md   enforce_at 强制时机        │
│   开发/评审/测试阶段检查点                                   │
├─────────────────────────────────────────────────────────────┤
│ 保障层（以使用效果为边界）                                   │
│   tests/test_dev_standard.sh 信号灯                          │
│   合规报告 + archives 留痕                                   │
└─────────────────────────────────────────────────────────────┘
```

## 三、核心设计决策

| 决策 | 理由 |
|------|------|
| **规范检查器是确定性代码而非 LLM 判断** | 避免"AI 自判合规"不可靠；可被 CI/测试重复验证 |
| **三层分级（L1必做/L2推荐/L3可选）** | 控制规范粒度，避免 agent 无法全遵循 |
| **StandardAbility 挂在 BaseRole（全员可用）** | 与 Dispatch/Handle/Depth/Label/DevTeam 挂载模式一致 |
| **三机制并行（rules + MCP/CLI + CI）** | rules 硬约束行为，MCP 程序化调用，CLI 供脚本/CI——互补覆盖 |
| **独立模块 + 唯一事实源（specs.py）** | 可各处引用，不各自取名、不产生版本差异 |
| **先核心后扩展（M1-M2→M3-M5）** | 先搭建可用核心 → 测试稳定性 → 再绑定扩展，符合"以使用效果为边界" |

## 四、规范条目（v0.1，5 类 14 条）

| 编号 | 类别 | 规范 | 级别 | 检查时机 |
|------|------|------|------|---------|
| S01 | 结构 | 模块独立成 PR，base 为 main | L1 | pre_pr/review |
| S02 | 结构 | 按功能域解耦 | L1 | pre_pr/review |
| S03 | 结构 | 接口显式化 | L1 | pre_pr/review |
| S04 | 结构 | 冲突前置规避（merge-tree） | L1 | pre_pr |
| S05 | 结构 | 每 PR 自含测试+文档 | L1 | pre_pr/review |
| C01 | 代码 | 错误处理显式（不吞异常） | L1 | commit/review |
| C02 | 代码 | 敏感信息不落代码 | L1 | commit/review/deliver |
| C03 | 代码 | 不留未引用 import/死代码 | L2 | commit/review |
| D01 | 文档 | 变更必留痕 | L1 | all |
| P01 | 流程 | Issue 声明头 + 双版本管理 | L1 | pre_pr/review |
| P02 | 流程 | 进度尺标注（goal_meters） | L1 | all |
| Q01 | 质量 | 自测结果上报 | L1 | deliver/review |
| Q02 | 质量 | 变更范围声明 | L2 | deliver |

## 五、开发过程绑定矩阵

| 开发阶段 | 强制时机 | 触发机制 |
|---------|---------|---------|
| 需求接收 | 规范注册表预检 | 开发角色回显时自动执行 |
| 开发中 | 代码规范检查 | StandardAbility 自动调用 |
| 提 PR | PR 规范检查 | CLI/CI 自动触发 + 评审复核 |
| 交付前 | 合规报告 + 自测上报 | StandardAbility.report_compliance |
| 评审时 | 评审核验规范符合度 | 评审调用 StandardChecker |
| 测试时 | 规范遵循追踪 | 测试信号灯 |

## 六、接力与传消息规则

- **开发接手** → 回显"我将遵循 dev-standard" → 查询阶段强制规范 → 开始开发；
- **开发中** → 每次提交前跑检查器 → 不通过标记 `blocked_on: standard_violation`；
- **交付时** → 附合规报告，评审可核验；
- **评审时** → 评审调用 `check_standard` 验证合规报告真实性，发现不合规打回 `[回转]`。

## 七、里程碑与测试验证

| 里程碑 | 内容 | 状态 |
|--------|------|------|
| M1 | dev-standard 模块（specs + checker + ability） | ✅ 已实施 |
| M2 | CLI + MCP 接口 + 文档 + 测试信号灯 | ✅ 已实施 |
| M3 | BaseRole 挂载 StandardAbility + AGENTS.md 规则绑定 | ✅ 已实施 |
| M4 | 测试信号灯运行验证 + PR | 本次交付 |
| M5 | MCP 宿主接入（第二阶段扩展） | 预留 |

**测试验证**：`tests/test_dev_standard.sh` 信号灯覆盖——规范注册表完整性、确定性检查
（含 hard/soft 判定）、CLI 可用性、BaseRole 挂载、各 check_* 逻辑（base main / 解耦 /
接口 / 冲突 / 测试文档 / 裸 except / 敏感信息 / 留痕 / 声明 / 进度尺 / 自测 / 范围）。

## 八、与现有体系关系

- **不重复**：规范只覆盖**开发质量**维度，与协作（AGENTS.md）/标签（LABEL_SPECS）/
  评审（REVIEW_DISPOSITION）规则正交；
- **同源沉淀**：S01-S05 是「解耦式功能模块开发」五条规则的程序化沉淀；
- **全员挂载一致**：BaseRole 挂载 StandardAbility，与 Dispatch/Handle/Depth/Label/DevTeam 同一模式。

## 九、索引

| 产物 | 位置 |
|------|------|
| 规范定义 | `local-agent/dev_standard/specs.py` |
| 规范检查器 | `local-agent/dev_standard/checker.py` |
| 全员能力 | `local-agent/dev_standard/ability.py` |
| MCP 工具 | `local-agent/dev_standard/mcp.py` |
| CLI 接口 | `local-agent/dev_standard/cli.py` |
| 规则绑定 | `local-agent/dev_standard/rules.md` + `AGENTS.md` |
| 模块说明 | `local-agent/dev_standard/README.md` |
| 测试信号灯 | `tests/test_dev_standard.sh` |
| 合规报告模板 | `docs/templates/standard-report.md` |
