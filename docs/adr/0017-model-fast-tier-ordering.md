# ADR-0017：快档档序由人类拍板落定，兜底归 glm-5.3-flash

- 状态：Accepted
- 决策日期：2026-10-20
- 相关：Issue #199（自 #182 转出的待拍板项）、ADR-0016、`docs/MODEL_ROUTING.md`

## 背景

ADR-0016 把渠道链解读成三档语义，但两个值一直悬着、且**不是人类定的**：

1. 快档的真实档序（`deepseek-v4.1-flash-1017` / `minimax-3.1-flash` 谁先谁后）；
2. `last_resort_model` 写什么——`claude-3-5-sonnet` 是 PR #191 里 AI 替用户选的。

这两条悬着的原因是同一个：**平台可选列表里的精确 ID 没核到就登记，整链会静默
stage error**（#177 事故：`deepseek-v4-flash` 不在列表 → 整个 stage error）。所以
`alias: {}` 故意留空，宁可报红也不写伪配置。

它难反转也易困惑：档序一改，所有角色的降级路径都跟着变；后人看到「档2 是
minimax、档3 是 codebuddy」会以为是随手排的，其实是有出处的。

## 决策

1. **档序**（人类原话：「第一优先是 deepseek v4.1 flash，第二 minimax 3.1 flash，
   第三 glm 5.3 flash」）落为：`deepseek-v4.1-flash` → `minimax-3.1-flash` →
   `codebuddy` → `glm-5.3-flash`。`codebuddy` 保留在第三站：它是平台自带通道，
   可在模型网关不可达时接管，不占「快档」名额。
2. **兜底档 `last_resort_model` 由 `claude-3-5-sonnet` 改为 `glm-5.3-flash`** ——
   人类给的第三优先就是 glm，兜底与之一致，不再保留 AI 代选值。
3. **`alias` 仍为空**：人类这次给的是**优先级**，不是带 `-1017` 后缀的平台 ID 原文；
   云端无 key，`probe` 显式 `skipped`。**未验真不登记**这条纪律不因催进度而松。
   拿到 ID 原文后补一行 `alias` 即全角色生效，无需改链。

## 后果（权衡）

- 好处：档序、兜底都有出处（指向本 ADR + Issue #199），后人不会当它是随手排的；
  三档语义（ADR-0016）结构不变，只换了成员与顺序，`no_degrade_target` 等审计照旧有效。
- 代价：`codebuddy` 从「二选」退到「三选」，主档不通时会先试 minimax 再试它——
  多一跳。这是刻意的：快档优先于通道兜底。
- 未解耦的风险：`minimax-3.1-flash` 与 `glm-5.3-flash` 目前只在配置层声明，
  **平台可选列表里是否真存在未经 probe 验证**。一旦平台侧不存在，会在真调时暴露为
  `not in the optional models list`（显式失败，非静默）；届时按 #177 的事故处理流程
  回滚该档并留痕，不擅自改档序。
