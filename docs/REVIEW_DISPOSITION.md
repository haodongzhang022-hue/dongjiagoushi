# 统一审查处置标签机制（Review Disposition）

> 文档控制本机制：`docs/REVIEW_DISPOSITION.md`（说明文档）+ `local-agent/collab/disposition.py`
> （唯一规范来源引擎）+ `AGENTS.md`（固定规则）+ `local-agent/tests/test_disposition.sh`（测试护栏）。
> 四者对齐，禁止漂移（见 doc-consistency 断言）。

## 一、要解决的问题（为什么需要统一标签）

审查机制里，结论该怎么处理（合并 / 推进 / 改bug / 调研 / 移交人类 / 会诊 / 投票等）
过去是**零散的、各写各的**——有的评审带了处置结论、有的没带，有的叫 `merge`、
有的叫 `adopt`、有的叫 `escalate`，触发不稳定、口径不统一。

这导致：同一件事在不同场景被不同称呼处理，下游自动化流程无法稳定读取，人类也无法
一致理解。

**本机制把"审查/决策点怎么处置"收敛为一套规范、稳定、强制的标签体系。**

## 二、处置标签全集（唯一规范来源）

| 标签 label | 名称 | 引擎 action | 自动化流程 route | 触发语义（when） |
|---|---|---|---|---|
| `merge` | 适合合并 | merge | merge_release | 方案成熟、评审通过、无🔴必修，可进入合并/发布放行 |
| `proceed` | 适合推进 | proceed | proceed_develop | 方案可行、风险可控，继续执行/继续开发，回小组长整合 |
| `fix_bug` | 适合改bug | fix | revert_to_develop | 评审发现 🔴必修 缺陷，需打回开发修复（[回转]） |
| `research` | 适合调研 | research | external_explore | 信息不足、方案未定，需调研/外部探索（L2 开放探索型） |
| `human` | 适合移交人类判断 | human | human_gate | 需担责/必要成本决策，结果前置叫人类拍板 |
| `consult` | 适合专家会诊 | consult | expert_consult | 疑难/对错难辨/多项方案都解决不掉，走专家会诊 |
| `vote` | 适合投票 | vote | consensus_vote | 意见多重、需集体决策/共识表决 |
| `blocked` | 链式未推进·待上游收口 | block | resume_chain | 阶段链门控驳回（抢跑/重复/乱序），等上游按链收口后再推进（**非放行**，不转交测试） |

> 规范集合定义在 `local-agent/collab/disposition.py` 的 `DISPOSITION_LABELS` /
> `DISPOSITION_ORDER`，是唯一来源；本表由引擎 spec 校验保持一致。

## 三、稳定触发（统一全加、缺一即评审未完成）

### 3.1 强制必有标签

任何**审查结论 / 决策点**都必须输出一个规范处置标签：

- **「架构·评审」输出契约强制绑定**：评审结论必须带 `disposition` 字段（八选一），
  **缺标签即评审未完成**，不视为有效评审；
- `dispose()` 是**确定性分类器**：给定严重级 + 触发信号 + 场景，**必然返回**一个
  规范标签——即使无任何输入也落到 `proceed` 兜底，保证"恒有标签、稳定触发"；
- 显式指定标签时**严格校验**（`require_label`）：非规范标签直接报错，防止"加错标签"。

### 3.2 触发来源（归一化到统一标签）

把过去零散的 action / 信号 / 分级统一映射到规范标签（`resolve_label`）：

| 来源 | 值 | → 处置标签 |
|---|---|---|
| 评审严重级 | 🔴 必修 / red | `fix_bug` |
| 评审严重级 | 🟡 建议 / yellow | `proceed` |
| 评审严重级 | 🟢 优化 / green | `merge` |
| 触发信号 | hard / high_risk | `consult` |
| 触发信号 | dispute | `vote` |
| 触发信号 | skill_gap / stall / undecided | `research` |
| 触发信号 | needs_human / requires_human | `human` |
| 触发信号 | defect | `fix_bug` |
| 既有 action | adopt / merge / release | `merge` |
| 既有 action | reroute | `research` |
| 既有 action | escalate | `human` |
| 场景语义 | 含"合并/发布/会诊/调研/投票/改bug/移交"等 | 对应标签 |

## 四、按标签的自动化流程（route）

每个标签路由到一个确定的自动化流程，与既有 peer collab 收尾闭环无缝衔接：

```
审查/决策点 → dispose() → 规范标签
   ├─ merge      → 评审🔴清零 → 验收通过 → 合并确认(CP3) → 放行/发布
   ├─ proceed    → 继续开发 → 回小组长整合 → 推进到下一检查点
   ├─ fix_bug    → 标🔴必修缺陷 → [回转]退回开发 → 复评清零后放行
   ├─ research   → 明确调研问题 → 外部探索(开源/插件/skill/论文)
   │               → 命中且零负面→自决采用；否则→结果前置交人
   ├─ human      → 结果前置打开人类拍板闸门(human_gate) → 列清风险点/因果对齐
   │               → 人类拍板后放行/否决
   ├─ consult    → 触发专家会诊(peer.expert_consult) → 各专长结论+留理由
   │               → 收敛→放行；未收敛→审核者前置助手→人类
   └─ vote       → 触发共识表决(peer.consensus_judge)
                   → 按收敛判定(2~3人无否决 / 4+人≥2/3)
                   → 未共识→显式上报小组长→总师→人类
```

### 与既有机制的衔接

- **`human`** → 复用 `collab/human_gate.py`：结果前置、CP 留痕、禁止代替用户确认；
- **`consult` / `vote`** → 复用 `collab/peer.py` 的 `expert_consult` / `consensus_judge`；
- **`research`** → 复用 `collab/precursor.py` 的 L2 开放探索型（外部搜索）；
- **`fix_bug`** → 复用既有 `[回转]` 打回协议（revert_to develop）；
- **`merge`** → 复用安全护栏 ⏸CP3 合并确认；
- **`proceed`** → 默认单兵/差异化补位推进，回小组长整合。

## 五、留痕与俯瞰

- **留痕**：每次审查处置调用 `record_disposition()` 写入 `archives`（kind=`disposition`），
  含 `problem / disposition / label_name / route / reviewer / detail`，可回溯审计；
- **俯瞰**：`disposition_overview()` 统计各标签出现次数，供人类/经理/哨兵监控
  "审查结论是否覆盖所有处置路径、有无失衡"。

## 六、规则文件控制（如何保证稳定可靠、可被读取理解、相同协作）

1. **唯一规范来源**：`disposition.py` 的 `DISPOSITION_LABELS` / `DISPOSITION_ORDER` /
   `spec()` 是规范源头，文档与规则、测试都从这里对齐；
2. **强制必有**：`require_label` / `dispose()` 保证任何审查点恒有规范标签，缺/错即报错；
3. **可机器校验**：`spec()` 输出机器可读规范，doc-consistency 测试断言文档与本表一致；
4. **测试护栏**：`test_disposition.sh` 覆盖全部标签、稳定触发、自动化路由；
5. **固定规则**：`AGENTS.md` 把"统一全加 + 稳定触发"写成仓库级最高规则，任何 agent
   遵守，不因角色人设缺漏而失效。

## 七、落点

| 产物 | 位置 |
|---|---|
| 唯一规范来源引擎 | `local-agent/collab/disposition.py` |
| 评审输出契约强制绑定 | `local-agent/roles/reviewer.py` |
| 说明文档 | `docs/REVIEW_DISPOSITION.md`（本文件） |
| 固定规则 | `AGENTS.md`「统一审查处置标签」 |
| 测试护栏 | `local-agent/tests/test_disposition.sh` |
| 一致性断言 | `tests/test_doc_consistency.sh` |
| CI | `.cnb.yml` |
