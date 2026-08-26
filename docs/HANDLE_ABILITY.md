# 自适应 @ 定位能力（HandleAbility · 全员通用能力）

> 把「@ 谁、@ 哪个仓库的谁」从写死的字符串，升级为**根据当前触发仓库自动解析**
> 的通用机制。每个 agent 都具备，跨仓库协作时自动用目标仓库的有权限角色。

## 解决什么问题（Issue #33 用户拍板）

此前身份声明 / 跨库召唤写死 `@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)`，
存在两个硬伤：

1. **角色名 / 承载仓库写死**
   - 触发本仓库 CodeBuddy 的**可能不是 `youkaifaxilieagent`**；
   - org 甚至可能不是 `dongdongxiaozu`；
   - 写死了，换一个触发角色就失效。
2. **跨库权限受限**
   - 到其他仓库协作时，若仍用本仓库的 @ 去召唤目标仓库角色，
     会因「角色不属于该仓库」而**无目标仓库权限**（角色权限通常只覆盖其所属仓库）。

## 两个仓库维度

本能力区分并同时识别**两个仓库维度**：

| 维度 | 含义 | 来源 |
|------|------|------|
| **角色承载仓库** | CodeBuddy NPC 由哪个仓库承载（用 `@org/承载仓库(CodeBuddy)` 触发） | 会话触发串 `@org/repo(角色)` |
| **当前操作仓库** | agent 正在为其工作的仓库 | git remote / 环境变量 / 默认约定 |

典型场景：`@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)` 触发一个 CodeBuddy
去操作 `dongdongxiaozu/dongjiagoushi`。此时**角色承载仓库**是 `youkaifaxilieagent`，
**当前操作仓库**是 `dongjiagoushi`，二者不同。

## 能力维度

| 方法 | 作用 |
|------|------|
| `self_handle()` | 返回本 agent **自身**完整 @ 格式（身份声明 / 汇报落款用，不写死） |
| `identity()` | 返回 {触发承载仓库, 当前操作仓库, target, role, handle} |
| `resolve(target_org, target_repo, role)` | **跨库定位**目标仓库有权限 @ 格式（权限更高） |
| `is_cross(target_org, target_repo)` | 判定目标仓库是否**跨仓库**（同仓可复用防冗余） |
| `codebuddy(target_org, target_repo)` | 目标仓库 CodeBuddy 兜底 @ 格式 |

## 核心规则

1. **不写死**：角色名 / 承载仓库 / org 一律动态解析（触发串 → 探测 → 默认兜底）。
2. **跨库用目标仓库**：跨仓库协作必须用目标仓库完整 `@org/repo(角色)`，保权限。
3. **同仓复用防冗余**：同仓库先检测能复用本仓库 @ 就不重造；跨仓库才走完整解析。
4. **权限优先**：要动哪个仓库，就用哪个仓库里有权限的角色；拿不准给权限建议并显式暴露。

## 解析优先级

目标仓库三要素优先级：**显式 target 参数 > 触发串承载仓库 > 当前操作仓库**。

## 用法（任意角色实例上）

```python
role = DeveloperRole(at_str="@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)",
                     current_org="dongdongxiaozu", current_repo="dongjiagoushi")

role.self_handle()                    # → "@dongdongxiaozu/youkaifaxilieagent(CodeBuddy)"
role.resolve("dongdongxiaozu", "someotherrepo")  # 跨库 → "@dongdongxiaozu/someotherrepo(CodeBuddy)"
role.is_cross("dongdongxiaozu", "dongjiagoushi")  # → False（同仓，可复用）
role.is_cross("dongdongxiaozu", "other")          # → True（跨库，须用完整 @）
```

## 模块结构

```
local-agent/handle/
  ├── __init__.py        # 导出 HandleAbility
  ├── resolver.py        # 核心解析器：触发串/探测/跨同仓判定/权限建议
  └── ability.py         # HandleAbility 能力类（self_handle/resolve/is_cross…）
```

挂载：`local-agent/roles/base.py` 的 `BaseRole.__init__` 懒加载 `HandleAbility`，
与 `DispatchAbility`（派发能力全员化）并列，**所有角色自动具备**。

## 测试

`tests/test_handle_ability.sh`（已在 `.cnb.yml` test 阶段挂载）锁死六条：
- T-H1 不写死角色名（从触发串动态识别自身承载仓库）
- T-H2 跨库用目标仓库完整 @（权限更高）
- T-H3 同仓复用防冗余
- T-H4 解析器各格式支持
- T-H5 BaseRole 全员挂载透传
- T-H6 权限建议

> 触发：显式 `[触发:架构·评审]` / 语义命中「@ 格式 / 跨仓库召唤 / 权限 / 写死角色名 /
> 自适应定位 / handle」/ rules 固定。
