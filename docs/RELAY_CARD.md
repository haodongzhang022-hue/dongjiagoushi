# relay_card · 接力卡触发校验（防断链工具）

## 背景与问题

协作链路出现"断裂"故障：交付方（如架构·开发）在交付时用 `@CodeBuddy` 而非完整
`@org/repo(角色)` 召唤下游协作角色，且**缺 `[触发:<角色全称>]` 标记**，导致下游
（架构·评审等）未被正确唤醒、链条断裂，需人类手动 `@` 补链（Issue #55 实例）。

**根因**：AGENTS.md「触发强制化·①显式声明触发最高优先」是固定 rules，但此前
**只靠自觉、无机器拦截**。接力卡生成时不校验 @ 格式，@CodeBuddy 断链无人拦。

## 本工具定位

把"接力卡必须带完整 @ + [触发] 标记"从**自觉规则**沉淀为**可执行校验工具**，
供交付/接力动作前置调用。任何角色 / 脚本 / CI 均可直接使用，从根上杜绝断链。

## 能力

| 接口 | 说明 |
|------|------|
| `check(text, role=None)` | 校验文本是否含完整 `@org/repo(角色)` + `[触发:<角色全称>]`；返回 `(ok, reasons)` |
| `check_required(text, role)` | 强制版：缺任意标记抛 `ValueError`（CI 红灯拦截） |
| `gen(to_role, repo=None)` | 基于当前仓库动态生成合规接力卡 @ 模板（复用 HandleAbility 不写死） |
| `capability()` | 能力声明（工具注册表登记） |

## CLI 用法

```bash
# 校验交付文本是否合规（缺标记 exit 1）
bash scripts/relay-card.sh check "<交付文本>" --role 架构·评审

# 从文件读取并强制校验（CI 拦截用）
bash scripts/relay-card.sh check --file payload.txt --role 架构·评审 --required

# 生成合规接力卡 @ 模板
bash scripts/relay-card.sh gen --to 架构·评审
# 输出: @dongdongxiaozu/dongjiagoushi(架构·评审) `[触发:架构·评审]`
```

Python 直接调用：

```python
import sys; sys.path.insert(0, "local-agent")
from relay_card import check, gen

ok, reasons = check("@dongdongxiaozu/dongjiagoushi(架构·评审) [触发:架构·评审]")
print(gen("架构·评审"))   # @dongdongxiaozu/dongjiagoushi(架构·评审) `[触发:架构·评审]`
```

## 校验规则

1. **完整 `@org/repo(角色)`**：协作角色须显式 @ 其完整仓库角色，`@CodeBuddy` 不保证命中评审/开发等角色，单独使用判无效。
2. **`[触发:<角色全称>]` 标记**：AGENTS.md 触发强制化·①最高优先，缺标记判无效、不猜测接手角色。
3. **角色归一化**：支持别名/缺「架构·」前缀自动补全（评审→架构·评审、总师→架构·总师…）。
4. **目标角色命中**：指定 `--role` 时，@ 与 [触发] 均须命中目标角色，否则判无效。

## 接入建议

- **交付/接力前置**：交付方在投接力卡前先 `relay_card.check`，缺标记即拦截补全，再投递。
- **CI 接线**：在 `.cnb.yml` 的交接事件中调用 `check --required`，红灯即拦，从机器层杜绝断链。
- **工具注册表**：本工具登记为 `relay-card`（模块 `module_version` 独立升版），全团队复用。

## 信号灯

```bash
bash tests/test_relay_card.sh   # 8/8 全绿
```

## 文件

- `local-agent/relay_card/__init__.py` — 核心校验 + 生成器
- `local-agent/relay_card/__main__.py` — CLI 入口
- `scripts/relay-card.sh` — CLI 封装
- `tests/test_relay_card.sh` — 信号灯
- `docs/RELAY_CARD.md` — 本文档
