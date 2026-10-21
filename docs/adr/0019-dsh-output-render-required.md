# 0019 · dsh 适配面以「真实包实测」为准，output.render 必调

- 状态：Accepted
- 日期：2026-10-21
- 关联：Issue #202（收尾）、Issue #145（dsh 适配模块）、ADR-0014

## 背景

`dsh-adapter/` 自 v0.1.0 起以「离线桩」跑信号灯：`tests/plugin.test.mjs` 在
`node_modules/@deepseek-ai/dsh-tools` 缺席时写入一个最小 stub，只要
`name/description/parameters/output/execute` 存在就算通过。这套 18 组信号灯长期全绿。

2026-10-21（Issue #202 收尾）拿真实 `@deepseek-ai/dsh-tools` 装载构建产物，发现 7 个
工具**全部一调用就崩**：

```
TypeError: d.output.render is not a function
```

真实 `defineTool` 的实现是 `output.render` **只在构造时存引用、不做任何校验**：

```js
output: { schema: outputSchema, render(args, value) { return userRender(args, value) } }
```

缺 `render` 时定义照样构造成功、照样注册进 `ctx.tools`、`tools/change` 照常触发——模型
第一次真正调用才抛 `TypeError`。这是比"装不上"更坏的失效：**装上了、注册了、一用全崩**。

## 决策

1. **适配面以真实包实测为准，不以离线桩为准。** 新增 `tests/real-package.test.mjs`：
   只认真实 `@deepseek-ai/dsh-tools`，拿不到就 `SKIP`（显式跳过），拿到就逐个工具真调
   `output.render` / 用真实 `defineTool` 复核 schema 合法。
2. **每个工具显式提供 `output.render`**，且必须是**纯函数**（同输入同输出，可重放）——
   与 `defineTool` 的 UI 重放契约一致。
3. **把 `output-render` 登记为 API 面**（自 `0.2.0-alpha.1`），`apply()` 时若运行时缺该面
   则 `logger.warn` 显式喊出来，不做静默。
4. **测试矩阵只列真实包实测过的版本。** `0.1.x` 一代没拿真实包跑过，从 `testedAgainst`
   移除 → 走 `degrade`（API 面齐、不阻断、提示回归），**不谎报 `ok`**。

## 理由

- 仓库既有纪律是**执行-验证分离 + 以测试为准**。但"桩测试"是自我指涉的验证：桩里没写的
  约束永远验不出来。真实包才是唯一事实源。
- 离线可跑的价值仍在（无网环境阻断不合规变更），所以**不删桩**，而是**加一道真实包的闸**，
  且桩模式下打印显式告警："本条绿≠真实包装得上"。
- `degrade` 而非 `ok` 是对"未实测"的诚实表达：既不阻断旧运行时，也不给假保证。

## 后果

- 信号灯从 18 组增到 20 组；`real-package` 拿不到真实包时 SKIP，不制造假绿。
- CI 需要 `npm i -D @deepseek-ai/dsh-tools` 才能跑满；未装时该条显示 SKIP 及原因。
- 真实包装载测试**红灯可查**：故意删掉 `render` → `real-package` 立刻 `fail=1`（已验证）。

## 被推翻会怎样

若未来 dsh 把 `output.render` 改为可选（或换名），改 `compat.ts` 的 `API_FACES` 与
`DSH_COMPAT.requiredFaces` 即可，`real-package.test.mjs` 会同步给出新契约的判据。
本 ADR 不删除，如被推翻改状态 `Superseded by ADR-00NN`。
