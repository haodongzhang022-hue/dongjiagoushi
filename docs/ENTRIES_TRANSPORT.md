# entries.transport · 真实传输层与本地执行器（Issue #105 三.6 欠债补齐）

> 一句话：`entries.bridge` 原本四步闭环全走 **mock**（`_mock_send` 只返回构造值
> `{"issue_id": "sim-issue"}`，`_mock_local_run` 只回计划），所以「本地⇄云端协同」
> **文档完整、代码是骨架**。本模块把传输与执行两个口子补成真实现。

## 一、为什么需要它（三个实跑出来的事实）

| 事实 | 证据 |
|---|---|
| `request_cloud_dev()` 默认不发任何请求 | `bridge.py` 原第 124 行 `tr = transport or {"name":"mock","send":_mock_send}`；实跑返回 `sent_via: local` + `sim-issue` |
| Windows 上 `subprocess(["cnb",...])` 直接 `WinError 2` | 本机实测 `FileNotFoundError`；而 `dispatch_engine._create_issue` 把它和 `TimeoutExpired` 一起 `return None` → **真实发卡静默失败** |
| 仓内 `which("bash")` 命中 WSL bash，吃掉反斜杠 | 路径被转成 `E:CNBcool_test...` → `rc=127 No such file or directory` |

## 二、两个契约

```python
transport: {"name": str, "send": fn(handle)->dict, "ack": fn(handle)->dict}
executor:  {"name": str, "run": fn(scripts)->dict}
```

`send` 返回的 `cloud_ref.issue_id` 必须是**平台真实编号**。
拿不到就抛错，由 bridge 记成 `pending` + `send_error` —— **绝不构造值冒充已投递**
（这正是 mock 的问题：`sim-issue` 看起来像成功）。

> 兼容性：bridge 侧已用 `_transport_send/_transport_attr` 收口，
> **dict 与对象两种形态都认**（真实实现 `CnbTransport` 是对象，
> 早期只按 dict 下标访问会抛 `object is not subscriptable`，实测踩过）。

## 三、开关（默认不联网）

| 环境变量 | 取值 | 行为 |
|---|---|---|
| `BRIDGE_TRANSPORT` | `cnb` / 缺省 | `cnb`=真建 Issue；缺省=mock |
| `BRIDGE_LOCAL_EXEC` | `shell` / 缺省 | `shell`=真跑 `tests/*.sh`；缺省=mock |
| `CNB_CLI_JS` | 路径 | 显式指定 `cnb-cli/bin/cnb.js`（找不到时按已知落点推导） |
| `BRIDGE_BASH` | 路径 | 显式指定 bash；缺省优先 Git Bash |

## 四、实跑证据（2026-10-23）

```
1) request（BRIDGE_TRANSPORT=cnb）
   real_send: True
   cloud_ref: {"issue_id": 227, "sent_via": "cnb",
               "url": "https://cnb.cool/dongdongxiaozu/dongjiagoushi/-/issues/227"}
2) collect  → status=collected, state=need_fix
3) align    → relay_aligned=True, data_archived=True
4) local_test_first（BRIDGE_LOCAL_EXEC=shell）
   mode=shell, passed=1, failed=0
   test_bridge_loop.sh rc=0 → 9 通过 / 0 失败
```

回归：`test_bridge_loop.sh` 9/0、`test_platform_adapter.sh` 13/0、
新增 `test_entries_transport.sh` 7/0、`test_entries_cloud_state.sh` 6/0。

## 4.5 云端完成态自动判定（entries.cloud_state）

原 `collect_cloud_result` 是 `state = cloud_state or ... or "done"` —— **不传就默认完成**。
现在不传会**自动去读**（`auto_read=True` 默认开）：

| 正本 | 读什么 | 命令 |
|---|---|---|
| 评论回执 | 是否真有目标角色的 `[接单]` | `comment_stream.read_comments` |
| 标签 | `merge_ready` / `merged` / `need_fix` / `blocked` | `cnb issues get-issue --verbose` |

**三态，不许二值化**：

- `confirmed` → 映射为 `merged` / `done` / `need_fix`，可推进；
- `pending` → 继续等，**不产生状态**；
- `unknown` → 读不全/读不到/锚点非真实编号 → **不折叠成 pending**，`collect` 返回
  `ok=False` 且句柄停在 `in_cloud_dev`。

### 为什么不用现成的 `has_receipt()`（实测假绿）

`comment_stream.has_receipt()` 只要正文含 `[接单]` 就判 `received=True`，而**派发卡正文里
就写着「请回执 [接单]」**——于是「只有自己发的卡」也被判成已回执，且 `degraded=False`，
看起来完全正常。实测：

```
仅自己发的卡 → {'received': True, 'suspects': 1, 'degraded': False}   ← 假绿
```

所以本模块自建三道窄判据：① 不含 `[触发:`；② 作者 ≠ 派发方；③ 命中 `[接单]`。

### 另一个坑：别把角色名当必要条件

真实回执常写「`[接单]` 已接单，但 need_fix」，**不会再重复一遍角色名**。
把角色名当硬门槛会漏判真回执（实测踩过），故角色名只作 `role_match` 标注。

## 五、边界（不假装有）

- **云端角色回执**仍靠事件（`issue.comment@npc`）驱动，本层负责「建锚点 + 读回执」；
  端到端闭环还需在锚点 Issue 上再发一张 `[触发:角色]` 接力卡；
- `collect_cloud_result` 现在**能自动读**，但只在 `auto_read=True` 且句柄带真实 Issue 锚点时生效；
  `BRIDGE_TRANSPORT` 非 `cnb` 时锚点是 `sim-issue`，会显式 `unknown`（这是对的，不是故障）；
- 配额护栏（`CLOUD_LOCAL_COOP` 2.3）未在本层接线，仍按原文档执行。
