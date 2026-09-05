# 双轴评审（Review Dual-Axis · Issue #98）

> **定位**：把「架构·评审」从单轴混评升级为**双轴并行独立评审**，防一轴结论带偏另一轴。
> 借鉴 mattpocock/skills 的 `code-review` 双轴（Standards ∥ Spec）——并行子轴各评各的、互不污染。

## 两轴定义

| 轴 | 评什么 | 依据基线 |
|---|---|---|
| **Standards 轴** | 是否符合仓库规范 + 代码坏味道基线 | 语法 / 异味 / 最佳实践 / 性能 / 重复（Fowler 坏味道）|
| **Spec 轴** | 是否忠实实现源 issue/spec | 目标（target）/ 做·不做边界 / 验收标准是否覆盖（agent-ready brief）|

## 合并规则（必改优先）

- Standards 🔴必修 **或** Spec 不达标 → `fix_bug`（[回转]退回开发），不复评不放行；
- 两轴均达标 → `merge` / `proceed`（放行转测试）。

## 为什么不混评

单轴混评时，"这代码风格丑/这处有异味"容易把"其实忠实实现了 spec"的结论一并带偏
（或反之）。并行双轴让「做没做对」与「做得好不好」分开判定，互不污染，落点更准。

## 承载

- 引擎实现：`local-agent/roles/reviewer.py` 的 `ReviewerRole.dual_axis_review()`
  （返回结构化双轴报告 + `blocked` + `recommended_disposition`）；
- 规范处置标签出口仍走 `dispose()`（统一审查处置标签，见 `docs/REVIEW_DISPOSITION.md`）；
- 测试护栏：`tests/test_doc_consistency.sh` 第六节校验评审角色含 Standards/Spec 双轴。

## 使用

```python
from local_agent_roles import ReviewerRole  # 或角色实例
r = ReviewerRole()
rep = r.dual_axis_review(
    source="PR #xx",
    spec_ref="Issue #xx agent-ready brief",
    standards_axis={"🔴": ["风格/异味项"]},
    spec_axis={"faithful": True},
)
# rep["blocked"] / rep["recommended_disposition"] → 接 dispose() 落规范处置标签
```
