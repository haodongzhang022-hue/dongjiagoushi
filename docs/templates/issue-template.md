# Issue 结构化声明模板

> 用法：在 `dongjiagoushi` 仓库（架构师体系）提交 Issue 时，**先填下方声明头**，再写正文。
> 声明头让 Issue 带上「所属模块 / 类型 / 目标 / **模块版本** / **agent 版本** / 更新内容 / 依赖」，使多个 Issue 之间形成**可版本管理的模块能力演进线**，而不是互不相关的平铺项。
> 由架构师 / 各协作角色按本模板产出入库。

---

## ① 声明头（必填 front-matter）

> ⚠️ **版本强制写明**：版本不是"整体版本"，而是**两个独立维度**，各自以**较小的迭代单位**独立推进——
> - **模块版本 `module_version`**：本次改动所属**模块**（`arch-skill` / `multirole` / `knowledge` / `dashboard` / `testing` / `pipeline` / `issue-mgmt`…）达到的语义化版本；
> - **agent 版本 `agent_version`**：本次改动涉及**某个 agent 角色**（`架构·总师` / `架构·产品` / `架构·开发` / `架构·评审` / `架构·测试`…）达到的语义化版本。
>
> 一个 Issue 可能**同时影响模块与 agent**，两维度都要按实际改动写明、各升各的、可只升其一。这样做是为了避免"局部迭代却强推整体版本"导致的并发合并冲突、合并失效——每个 Issue 只在一个**最小迭代单位**（单一模块 / 单一 agent）上前进，合并面收敛、冲突可控。

```yaml
module:         <模块ID>                       # 必填：声明所属模块，如 arch-skill / multirole / knowledge
module_version: <目标模块版本>                  # 必填：本 issue 落地后【模块】达到的版本（init 为 v0.1.0）
agent:          <角色ID>                       # 选填：本次改动涉及的 agent 角色（如 架构·总师）；不涉及 agent 能力可省
agent_version:  <目标 agent 角色版本>           # 若填了 agent 则必填：本 issue 落地后【该 agent 角色】达到的版本
type:           <init|update|fix|standalone>   # 必填：issue 类型（见下方类型表）
target:         <本 issue 要达成的目标>          # 必填：一句话说清做成了什么
update:         <相对上一版本的更新内容>         # 必填：本次相对上一版本改了什么 / 增强了什么
depends_on:     <父模块 issue 或前置 issue 编号>  # 选填：建立 Issue 层级关系的链接（同模块父/子）
```

**版本强制校验（提交前自查必勾）**：
- [ ] 凡是 `update` / `fix` / `init` 类型，**必须写明 `module_version`**（模块维度）；
- [ ] 凡是改动**某个 agent 角色能力/人设/输出契约**，**必须写明 `agent` + `agent_version`**（agent 维度）；
- [ ] 两个维度**各自独立升版**：只动模块就只升 `module_version`；只动 agent 就只升 `agent_version`；两者都动就两个都升。
- [ ] 版本用语义化版本 `vMAJOR.MINOR.PATCH`，与所属维度已有版本线一致，不跳版、不抢号。

---

## ② Issue 类型表（type）

| type | 含义 | 版本动作 | 是否需版本管理 | 示例 |
|------|------|----------|----------------|------|
| `init` | 模块建立 / 首个版本 | 创建模块/agent 版本线根节点，`v0.1.0` | ✅ 是（建立版本线） | 新建「测试体系」模块 |
| `update` | 能力增强 / 阶段性迭代 | `MINOR` 升级（`v0.2.0`） | ✅ 是（继承所属模块/agent 版本线） | 给某模块补能力、迭代 |
| `fix` | 缺陷修复 / 小改 | `PATCH` 升级（`v0.2.1`） | ✅ 是（继承所属模块/agent 版本线） | 修 bug、微调 |
| `standalone` | 一次性任务 | 不改变能力，无需版本 | ❌ 否 | 临时调研、纯文档整理 |

---

## ③ Issue 关系层级示例（双版本演进线）

```
模块「arch-skill」版本演进线             agent「架构·总师」版本演进线
    ├── #4  type=update mv0.2.0             ├── #5  type=update av0.3.0  (架构·总师人设补强)
    ├── #9  type=fix    mv0.2.1             └── #11 type=fix    av0.3.1  (总师输出契约微调)
    └── #12 type=update mv0.3.0

说明：#4 只升 module_version（mv0.2.0），不涉及 agent 能力 → 不写 agent/agent_version；
     #5 只升 agent_version（架构·总师 av0.3.0），不涉及模块代码 → 不写 module_version。
     两者可并行开发、各自合并，互不抢同一个"整体版本号"，局部迭代不会互相冲突。
```

---

## ④ 正文（接在声明头之后）

- **背景 / 动机**：为什么做这一版
- **需求点（用户故事）**：作为 <角色>，我希望 <目标>，以便 <价值>
- **验收标准**：可核验的通过条件
- **边界**：做 / 不做
- **风险与依赖**：阻塞点、依赖的 issue / 版本

---

## 提交前自查（版本强制）

- [ ] 声明头字段齐全：`module` + `module_version` + `type` + `target` + `update` 必填；涉及 agent 能力时 `agent` + `agent_version` 必填
- [ ] `type` 正确；`update`/`fix` 已写 `depends_on` 指向父模块 issue
- [ ] `module_version` 与所属模块版本线一致；`agent_version` 与所属 agent 角色版本线一致
- [ ] **双版本各自独立升版**，未强推"整体版本号"，改动局限在最小迭代单位（单一模块 / 单一 agent）
- [ ] 正文含验收标准与边界，可被下游（架构师/开发）稳定读取
