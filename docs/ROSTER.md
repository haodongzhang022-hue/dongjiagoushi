# 角色名册与派单接入（ROSTER）

> **定位**：给外部对端（管理-派单控制面 / 本地中控 / Agent 网关）一个**稳定接口面**——
> 「你这边有哪些角色、ID 是什么、能不能跑」，以及「按 ID 派单过来怎么入场」。
>
> **触发词**：角色列表 / 名册 / roster / 派单 / 对接 / 握手 / 跨仓派活 / role_id /
> 对端清单 / 能力清单 / 本地发请求过来开发
>
> **唯一事实源**：`local-agent/roster/`（`specs.py` 归并 + `payload.py` 接口 + `intake.py` 派单）

---

## 一、要解决的问题

角色信息在本仓散在**四个事实源**里，各自服务不同消费者：

| 事实源 | 消费者 | 内容 |
|---|---|---|
| `.cnb/settings.yml` | CNB 平台（云端 NPC） | 人设 prompt / `defaultRole` |
| `local-agent/team.yaml` | 本地编排 / 管理台 | `module` / `step` / `trigger_words` |
| `roles/__init__.py:ROLE_REGISTRY` | 本地执行 | 角色类（**能不能真跑**） |
| `relay_card/__init__.py:ROLES` | 交接校验 | 接力卡可用的角色名 |

四份之间天然漂移。对端只想要一件事：**有哪些角色、ID 是多少、怎么触发**。
所以 roster 做的是**归并 + 显式标注缺口**，不造第五份清单。

实测当前缺口（`python -m roster.cli drift` 可复现）：

- `架构·审核前置助手`：settings 有，team / registry **没有**
- `架构·小组长`、`架构·监控哨兵`：team / registry 有，**settings 没有**
- `架构·对齐`、`架构·找工具`：team / registry 有，settings / relay **没有**

这些缺口不修，而是**照样暴露**——对端在派单前就知道哪些角色「登记了但跑不起来」，
不用等派过去失败一次才发现。

---

## 二、三个接口（对端只需这三个）

```python
from roster import catalog, resolve, intake

catalog()                                   # ① 握手：角色清单 + 缺口
resolve("架构·开发")                         # ② 解析：中文名/别名/@串 → role_id
intake({"target": "arch.developer",         # ③ 派单：走标准调度链路
        "task": "补 token 刷新逻辑",
        "entity": "issue-42"})
```

### ① `catalog()` — 能力清单

```json
{
  "contract": "dongjiagoushi.roster/v1",
  "repo": "dongdongxiaozu/dongjiagoushi",
  "entry_role_id": "arch.secretary",
  "count": 28,
  "roles": [{"role_id": "arch.developer", "name": "架构·开发",
             "impl": true, "at": "@org/repo(架构·开发)",
             "relay": "[触发:架构·开发]", "trigger_words": [...], "pipeline": [...]}],
  "gaps": {"drift": [...], "missing_ids": [...]}
}
```

`contract` 是协议版本：**加角色/加字段不升版**（向后兼容），
**删角色、改 `role_id` 才升 v2**——对端据此判断要不要重拉。

### ② `resolve(target)` — 认脸

认五种形态：`role_id` / 中文全名 / 别名（`开发`、`reviewer`）/
`@org/repo(角色)` / `[触发:角色]`。

**认不出不猜**：返回 `ok=false` + 候选建议。猜一个"最像的"角色 = 把活派给错的人，
比失败更糟。

### ③ `intake(req)` — 派单入场

把请求翻译成 dispatcher 的标准事件，走**既有链路**
`normalize_event → rules → queue → guard → router.dispatch`：

- 留痕：返回 `event_id`，落 `dispatch` 表可回查；
- 去重：同 `实体 + 角色` 二次派单被 guard 拦截（不重复派活）；
- 护栏：`gate=auto` 自动放行，需要人判断的走闸门。

---

## 三、入口规则：为什么指定角色不算绕过秘书

本仓规则是「默认入口永远是架构·秘书」。但这和「派单指定目标」不冲突：

| 场景 | 落点 | 依据 |
|---|---|---|
| 对端**没给** target | `arch.secretary`（秘书路由） | 默认入口协议 |
| 对端**给了** target | 直接派给该角色 | 触发强制化·①显式声明触发优先 |

护栏 `guard_entry` 管的是**对话入口**（有人说"帮我做 X"），不是**派单目标**
（有人明确说"这活给评审"）。两者分开，才不会把正常派单判成违规。

---

## 四、CLI（脚本 / CI 直接调，不依赖对话）

```bash
python -m roster.cli catalog --json      # 能力清单
python -m roster.cli wire                # 一行一条（grep/awk 可切）
python -m roster.cli resolve 架构·开发    # 解析
python -m roster.cli drift               # 缺口明细
python -m roster.cli verify --file their.json   # 对端清单 ⇄ 本仓名册 双向核对
python -m roster.cli intake --target arch.developer --task "..." [--dry-run]
```

`verify` 是对接期的关键一步：把对方上报的角色列表丢进来，直接得到
`only_theirs`（对方有我们没有）/ `only_ours`（我们有对方没有）/ `unimplemented`
（对上了但本地跑不了）——差集**不隐藏**，可直接贴回对接评论。

---

## 五、接进来要做的三步（对端视角）

1. **拉清单**：`catalog()` 或 `GET` 对等接口，存下 `role_id` 列表 + `contract` 版本；
2. **对一次**：`verify(自己的清单)`，把差集确认清楚（谁多谁少、谁跑不了）；
3. **派单**：`intake({"target": role_id, "task": ...})`，用返回的 `event_id` 回查状态。

对端**不需要** import 本仓任何模块——`intake` 也可以经 dispatcher 的
webhook / 外部源适配器推进来（见 `docs/DISPATCHER.md`），协议面是同一套事件。

---

## 六、信号灯

`local-agent/tests/test_roster.sh`（15 组）：

握手契约齐备 / ID 不漂移 / @与[触发]解析 / 未知角色不猜 / 未指定落秘书 /
空 task 拒收 / 派单留痕 event_id / `dispatch` 表可回查 / 无实现角色显式告警 /
缺口如实暴露 / verify 双向差集 / verify 不误报 / dry-run 不落库 /
批量逐条记账 / 去重护栏生效。

红灯即说明「名册与事实源漂移」或「派单链路断了」，不是测试写错。
