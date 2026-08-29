# 开发规范 · 固定规则（dev-standard / rules.md · Issue #83）

本文件被 `AGENTS.md` 引用，作为**仓库级固定规则**绑定开发过程。
任何开发/评审/测试 agent 在处理代码任务时**必须**遵循以下规范。

> 触发：本规则为仓库最高固定规则（rules 固定触发），对所有 agent 生效。
> 程序化来源：`local-agent/dev_standard/specs.py`（唯一事实源），本文件为人类可读版。

## 一、强制遵循（L1 必做 · hard 阻断）

| 编号 | 规范 | 检查时机 |
|------|------|---------|
| S01 | 模块独立成 PR，base 一律为 main | 提 PR / 评审 |
| S02 | 按功能域解耦，不挂到他人功能分支 | 提 PR / 评审 |
| S03 | 接口显式化（公开接口 + docstring + 单测） | 提 PR / 评审 |
| S04 | 冲突前置规避（merge-tree 校验） | 提 PR |
| S05 | 每个 PR 自含测试 + 文档 | 提 PR / 评审 |
| C01 | 错误处理显式（不吞异常） | 提交 / 评审 |
| C02 | 敏感信息不落代码（Token/密码/密钥） | 提交 / 评审 / 交付 |
| D01 | 变更必留痕（Issue/PR/提交） | 全程 |
| P01 | Issue 声明头 + 模块/Agent 双版本管理 | 提 PR / 评审 |
| P02 | 进度尺标注（goal_meters） | 全程 |
| Q01 | 自测结果上报（通过/失败） | 交付 / 评审 |

## 二、推荐遵循（L2 · soft 警告）

| 编号 | 规范 | 检查时机 |
|------|------|---------|
| C03 | 不留未引用 import / 死代码 | 提交 / 评审 |
| Q02 | 变更范围声明（改了哪些） | 交付 |

## 三、可选遵循（L3 · 提示）

| 编号 | 规范 | 检查时机 |
|------|------|---------|
| — | （预留，按需扩展） | — |

## 四、如何遵循（程序化 · 不靠自觉）

1. **接手任务** → 自动回显"我将遵循 dev-standard 规范" → 查询当前阶段强制规范：
   ```bash
   python -m dev_standard.cli enforced --stage pre_pr   # 提 PR 前强制规范
   python -m dev_standard.cli list --level L1           # 全部必做规范
   ```
2. **开发中** → 每次提交前跑代码规范检查：
   ```bash
   python -m dev_standard.cli check-code --file local-agent/your.py
   ```
3. **提 PR 前** → 跑 PR 规范检查，不通过禁止提交：
   ```bash
   python -m dev_standard.cli check-pr --target main --source auto/module-x \
       --test-files tests/test_x.sh --docs-files docs/X.md
   ```
4. **交付时** → 附合规报告（`report_compliance`），评审可核验：
   - 自测结果必须上报（Q01）；
   - 变更范围必须声明（Q02）。

## 五、合规判定（确定性 · 执行-验证分离）

- 规范检查器是**确定性代码**（`StandardChecker`），非 LLM 判断——杜绝"AI 自判合规"。
- 硬检查（hard）未过 = **阻断**（`blocked_on: standard_violation`），列出违反项；
- 软检查（soft）未过 = **警告**，不阻断但需说明。
- 开发只负责"做"不负责"判"：是否合规由检查器裁定，绝不自行裁定"我完成了"。

## 六、与现有机制的关系（体系 · 非孤点）

- 规范只覆盖**开发质量**维度，不与协作（AGENTS.md）/ 标签（LABEL_SPECS）/
  评审（REVIEW_DISPOSITION）规则重复；
- 与「解耦式功能模块开发」五条规则同源（S01-S05 即其程序化沉淀）；
- 通过 `BaseRole` 全员挂载 `StandardAbility`，与 Dispatch/Handle/Depth/Label/DevTeam 一致。
