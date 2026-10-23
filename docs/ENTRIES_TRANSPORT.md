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
新增 `test_entries_transport.sh` 7/0。

## 五、边界（不假装有）

- **云端角色回执**仍靠事件（`issue.comment@npc`）驱动，本层只负责「把锚点建出来」；
  要端到端闭环（本地发卡 → 云端角色 `[接单]` → 本地 collect）需在 Issue 上再发一张接力卡；
- `collect_cloud_result` 的 `cloud_state` 目前由调用方给（或由上游打标驱动），
  **本层不去猜云端状态**；
- 配额护栏（`CLOUD_LOCAL_COOP` 2.3）未在本层接线，仍按原文档执行。
