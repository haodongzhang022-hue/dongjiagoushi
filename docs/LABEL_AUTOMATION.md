# 标签管理 + 进度自动化（LabelAbility · Issue #51）

本模块把「标签管理 + 程序化进度获取 + 事件驱动自动打标」做成**自动化程度较高的
流水线**，满足用户在 Issue #51 的诉求：

> 让标签形成任务进度的数值（0% 5% 10% ... 100%），作为进度推手的专项角色；
> 在进度下给额外的自动化触发机制，利于规模协作；自动化程度要高。

## 核心设计：能力层 vs 自动化触发层

| 层 | 触发方式 | 说明 |
|----|---------|------|
| **能力层** LabelAbility | 响应式（等人调） | 只是"有能力"，**不会自动去做** |
| **自动化触发层** AutoLabelEngine | 主动式（事件驱动） | **事件到达即自动打标**，无需任何人记得去调 ★核心 |

用户强调"自动化程度较高"——这轮把标签从"能力层"补成"事件驱动自动打标闭环"。

## 一、规范标签集（LABEL_SPECS · 唯一规范来源）

| 分类 | 标签 |
|------|------|
| progress | blocked / in_progress / review / done / merged |
| type | feature / bug / refactor / docs / infra / research |
| priority | p0_critical / p1_high / p2_normal / p3_low |
| status | open / stale / verified / invalid |
| disposition | merge_ready / need_fix / need_review / need_human |
| progress_pct | 0% / 5% / 10% / ... / 100%（人可读进度百分比） |

**权限分层**：
- **查询**：全员开放（走数据库，程序化 MCP 管线，不靠 AI 对话）
- **直接打标**：架构·开发 / 评审 / 测试 / 经理 / 总师 / 产品 / 秘书 / 数据管理员 / 小组长 / 进度推手（白名单）
- **提议审批**：全员可 propose_label → 数据管理员（标签管理员）审批 → approved 自动落标

**工作流**：
```
一线直接打标（最常见）：apply_label → 写 labels 表 → 任何人可查
全员提议：propose_label → label_requests 表(pending) → 管理员审批 → 自动打标
事件自动：AutoLabelEngine 命中规则 → 自动打标（无需 agent 记得去调）
```

## 二、事件驱动自动打标（AutoLabelEngine · 8 类规则）

| 事件 | 自动打标 |
|------|---------|
| issue.open | open |
| issue.update | 刷进度百分比 |
| requirement | open |
| progress.advance | in_progress + 进度百分比 |
| task.done | done |
| pr.merged | merged + done |
| review.need_fix | need_fix + blocked |
| sentinel.alert | stale（停滞） |

**进度百分比（人可读层）**：读 `goal_meters` 的 current/goal_total 折算
`round(current/goal*100)`；无量化时按状态估算（todo→5% / 进行→40% / 评审→90% / 完成→100%）。
机器收敛判定仍用哨兵内部 `distance`（不丢"还剩多少"），百分比是给人俯瞰，**两者互补**。

## 三、程序化 MCP 管线

CLI 命令（任何脚本/CI 可调，不依赖 AI 对话）：
```bash
python -m label.cli progress --task tk-xxx        # 查进度
python -m label.cli status --entity issue-12       # 查状态标签
python -m label.cli labels --entity issue-12       # 查全部标签
python -m label.cli apply --entity issue-12 --label in_progress --operator 架构·开发  # 一线打标
python -m label.cli propose --entity issue-12 --label p0_critical --operator 市场·销售 --reason 阻塞上线
python -m label.cli review --request lq-xxx --operator 架构·数据管理员 --decision approved
python -m label.cli auto --event progress.advance --entity issue-12 --goal-total 10 --current 4  # 事件自动
```

任意角色实例（全员挂载）：
```python
role.query_progress("tk-xxx")            # 程序化查进度
role.query_status("issue-12")            # 程序化查状态
role.apply_label("issue-12", "in_progress")  # 一线直接打标
role.propose_label("issue-12", "p0_critical", "阻塞上线")  # 全员提议
role.auto_trigger("progress.advance", "issue-12", 10, 4)   # 事件自动打标
```

## 四、数据层增强

新增两张表：
- `labels`：标签记录（entity + label_key + value + operator + action + source + note）
- `label_requests`：标签提议（proposer + label_key + reason + status: pending/approved/rejected）

`query_progress()` 同时查询 `goal_meters` + `progress` 表，统一走 MCP 管线暴露，
任何角色可程序化获取，不依赖 AI 对话告知（MCP 管线效果）。

## 五、架构·进度推手（专项角色）

- **定位**：进度标签 + 优先级 + 自动化喂料专项角色，把内部距离翻译成人可读百分比。
- **能力**：`push_progress`（刷进度百分比+状态）/ `push_priority`（P0-P3 正交维度）/
  `check_auto`（进度停滞喂哨兵打断 / 高优先级阻塞升级上报）。
- **角色注册**：`.cnb/settings.yml`（人设 + 触发词）+ `local-agent/team.yaml`（团队清单）。

## 六、CI 事件接线（真·自动化落地）

`.cnb.yml` 在 **issue.open / issue.update 事件钩子** 自动调用 `scripts/auto-label.sh` →
程序化打标。Issue 一开/一改，标签自动上，不依赖任何 agent 记得去调。

## 七、文件清单

| 文件 | 变更 |
|------|------|
| `local-agent/label/ability.py` | 新增：LabelAbility 标签能力（查询/打标/提议/审批/自动触发） |
| `local-agent/label/auto.py` | 新增：AutoLabelEngine 事件驱动自动打标引擎（8 类规则） |
| `local-agent/label/cli.py` | 新增：CLI 入口（MCP 管线） |
| `local-agent/label/progress_pusher.py` | 新增：架构·进度推手专项角色 |
| `local-agent/label/__init__.py` | 新增：模块入口 |
| `local-agent/data/schema.py` | 修改：新增 labels / label_requests 表 |
| `local-agent/data/repository.py` | 修改：标签 CRUD + MCP 进度/状态查询 |
| `local-agent/roles/base.py` | 修改：BaseRole 挂载 LabelAbility（全员能力） |
| `.cnb/settings.yml` | 修改：注册 架构·进度推手 角色 |
| `local-agent/team.yaml` | 修改：团队清单加 进度推手 |
| `.cnb.yml` | 修改：issue 事件钩子自动打标 + 测试入 CI |
| `scripts/auto-label.sh` | 新增：事件自动打标脚本 |
| `docs/LABEL_AUTOMATION.md` | 新增：本设计文档 |
| `AGENTS.md` | 修改：标签机制固定规则 |
| `local-agent/tests/test_label_automation.sh` | 新增：可复现测试 |

## 八、风险与规避

| 风险 | 等级 | 规避 |
|------|------|------|
| 标签乱标 | MEDIUM | 规范标签集 + INVALID_LABEL 拦截 |
| 一线越权 | LOW | DIRECT_OPERATORS 白名单控制 |
| 与 disposition 标签混淆 | LOW | disposition 是评审结论标签，LabelAbility 是通用 Issue 标签 |
| 数据量增长 | LOW | 走 SQLite/PG 统一后端，索引覆盖 |
