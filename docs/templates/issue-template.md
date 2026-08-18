# Issue 结构化声明模板

> 用法：在 `dongjiagoushi` 仓库（架构师体系）提交 Issue 时，**先填下方声明头**，再写正文。
> 声明头让 Issue 带上「所属模块 / 类型 / 目标 / 版本 / 更新内容 / 依赖」，使多个 Issue 之间形成**可版本管理的模块能力演进线**，而不是互不相关的平铺项。
> 由架构师 / 各协作角色按本模板产出入库。

---

## ① 声明头（必填 front-matter）

```yaml
module:     <模块ID>                     # 必填：声明所属模块，如 arch-skill / issue-mgmt / pipeline / knowledge
type:       <init|update|fix|standalone> # 必填：issue 类型（见下方类型表）
target:     <本 issue 要达成的目标>        # 必填：一句话说清做成了什么
version:    <目标版本号>                  # 模块版本：本 issue 落地后模块达到的版本（init 为 v0.1.0）
update:     <相对上一版本的更新内容>       # 必填：本次相对上一版本改了什么 / 增强了什么
depends_on: <父模块 issue 或前置 issue 编号> # 选填：建立 Issue 层级关系的链接（同模块父/子）
```

## ② Issue 类型表（type）

| type | 含义 | 版本动作 | 是否需版本管理 | 示例 |
|------|------|----------|----------------|------|
| `init` | 模块建立 / 首个版本 | 创建模块根节点，`v0.1.0` | ✅ 是（建立模块版本线） | 新建「Issue 版本管理」模块 |
| `update` | 能力增强 / 阶段性迭代 | `MINOR` 升级（`v0.2.0`） | ✅ 是（继承模块根 issue） | 给某模块补能力、迭代 |
| `fix` | 缺陷修复 / 小改 | `PATCH` 升级（`v0.2.1`） | ✅ 是（继承所属模块） | 修 bug、微调 |
| `standalone` | 一次性任务 | 不改变模块能力，无需版本 | ❌ 否 | 临时调研、纯文档整理 |

## ③ Issue 关系层级示例

```
模块「issue-mgmt」的版本演进线
    ├── issue#10  module=issue-mgmt type=init   version=v0.1.0   ← 模块根节点
    ├── issue#15  module=issue-mgmt type=update version=v0.2.0   depends_on:#10
    ├── issue#18  module=issue-mgmt type=fix    version=v0.2.1   depends_on:#15
    └── issue#22  module=issue-mgmt type=update version=v0.3.0   depends_on:#10
```

## ④ 正文（接在声明头之后）

- **背景 / 动机**：为什么做这一版
- **需求点（用户故事）**：作为 <角色>，我希望 <目标>，以便 <价值>
- **验收标准**：可核验的通过条件
- **边界**：做 / 不做
- **风险与依赖**：阻塞点、依赖的 issue / 版本

---

## 提交前自查

- [ ] 声明头五字段（module/type/target/version/update）齐全
- [ ] `type` 正确；`update`/`fix` 已写 `depends_on` 指向父模块 issue
- [ ] `version` 符合语义化版本，与所属模块版本线一致
- [ ] 正文含验收标准与边界，可被下游（架构师/开发）稳定读取
