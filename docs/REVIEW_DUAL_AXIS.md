# 双轴评审（Review Dual-Axis · Issue #98）

> **定位**：把「架构·评审」从单轴混评升级为**双轴并行独立评审**，防一轴结论带偏另一轴。
> 借鉴 mattpocock/skills 的 `code-review` 双轴（Standards ∥ Spec）——并行子轴各评各的、互不污染。
>
> **修复 Issue #98 遗留（评审机制不全）**：双轴不再是"就绪可调能力方法"，而是
> **评审必走闸门**——评审一律走主流程入口 `do_review()`，强制先产出双轴，
> 机器可核验 `axes_complete`，缺任一轴即评审**不完整、禁止放行**（杜绝走单轴混评漏双轴）。

## 两轴定义

| 轴 | 评什么 | 依据基线 |
|---|---|---|
| **Standards 轴** | 是否符合仓库规范 + 代码坏味道基线 | 语法 / 异味 / 最佳实践 / 性能 / 重复（Fowler 坏味道）|
| **Spec 轴** | 是否忠实实现源 issue/spec | 目标（target）/ 做·不做边界 / 验收标准是否覆盖（agent-ready brief）|

## 双轴必走（强制 · 机器可核验）

评审不再"散调各方法"，而是**必走评审主流程统一入口 `do_review()`**：
**双轴 → 处置 → 路由** 一站式闭环。其中双轴是**第一道必走闸门**：

- 评审必须先产出 **Standards ∥ Spec 两轴**（各评各的、互不污染）；
- `dual_axis_review()` 返回 `axes_complete`（机器核验两轴是否都有实质产出）；
- **缺任一轴 → `axes_complete=False` → 评审不完整** → `disposition=fix_bug`、
  `review_complete=False`、**禁止放行**（不能给 merge/proceed 假装评审过双轴）；
- 只有两轴都评全，才进入「必改优先」合并与处置/路由。

> 参照同仓库 `dispose()` 强制机制（统一审查处置标签）：双轴与处置标签并列为
> **评审输出契约双闸门**——缺双轴、缺处置标签任一即评审不完整、不视为有效评审。

## 合并规则（必改优先）

- Standards 🔴必修 **或** Spec 不达标 → `fix_bug`（[回转]退回开发），不复评不放行；
- 两轴均达标 → `merge` / `proceed`（放行转测试）。

## 为什么不混评

单轴混评时，"这代码风格丑/这处有异味"容易把"其实忠实实现了 spec"的结论一并带偏
（或反之）。并行双轴让「做没做对」与「做得好不好」分开判定，互不污染，落点更准。

## 承载

- 评审主流程入口：`local-agent/roles/reviewer.py` 的 `ReviewerRole.do_review()`
  （双轴强制 → 处置 → 路由 一站式闭环）；
- 引擎实现：`ReviewerRole.dual_axis_review()`
  （返回结构化双轴报告 + `axes_complete` + `blocked` + `recommended_disposition`）；
- 规范处置标签出口仍走 `dispose()`（统一审查处置标签，见 `docs/REVIEW_DISPOSITION.md`）；
- AGENTS.md 登记「双轴必走」固定 rules；
- 测试护栏：`tests/test_doc_consistency.sh` 第六节校验评审角色含双轴 + `do_review` 主流程 +
  运行时核验缺轴判不完整禁止放行。

## 使用

```python
from local_agent_roles import ReviewerRole  # 或角色实例
r = ReviewerRole()

# ① 评审主流程统一入口（推荐·必走）：双轴强制 → 处置 → 路由
rep = r.do_review(
    "任务A", source="PR #xx", spec_ref="Issue #xx agent-ready brief",
    standards_axis={"🔴": [], "note": "无必修"},      # Standards 轴
    spec_axis={"faithful": True},                     # Spec 轴
    issue_ref="xx", auto_route=True,
)
# rep["axes_complete"] / rep["review_complete"] / rep["disposition"] / rep["route"]

# ② 单独调用双轴核验（若需纯双轴结论）：缺任一轴 → axes_complete=False
rep2 = r.dual_axis_review(
    source="PR #xx", spec_ref="Issue #xx agent-ready brief",
    standards_axis={"🔴": ["风格/异味项"]},
    spec_axis={"faithful": True},
)
# rep2["axes_complete"] / rep2["blocked"] / rep2["recommended_disposition"]
```
