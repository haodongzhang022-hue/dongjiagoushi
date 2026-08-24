# 调度中枢 · 事件驱动自动化调度层（dispatcher）

> 本文件描述本仓库的「**调度中枢（dispatcher）**」—— 把团队协作从**对话/人工触发**
> 升级为**机制自动触发**：持续扫描事件源（本仓库 Issue/PR/评论/驳回/哨兵告警 +
> 外部适配器插槽），识别触发条件，经 Action 队列 + 防无效护栏，按 **gid 精准路由**
> 到对应 agent，并在 Web 面板上实时俯瞰。
>
> 对应 ISSUE #26；可执行载体 `local-agent/dispatcher/` + `local-agent/tests/test_dispatcher.sh`。

---

## 一、问题诊断：为什么需要调度中枢

| 用户原话要点 | 现状缺陷 | 缺什么 |
|--------------|----------|--------|
| 「需要一个面板 + 持续监控，识别到触发条件后路由到对应 agent」 | 触发**依赖对话入口**（`@`/评论/npc:go），无后台事件监听 | **持续扫描事件源** |
| 「不依赖对话触发，团队出现岗位需求自动派发」 | 路由被 `@`/接力卡驱动，无「条件→动作」自动派发 | **触发规则引擎 + 自动路由** |
| 「出现 issue 需审核遗漏未处理要安排」 | 无「未处理扫描 + 自动派发」调度器 | **遗漏扫描 → 安排** |
| 「有驳回的，得路由到负责他的直接处理，而不是等待命令」 | `[回转]` 打回靠人肉发现、人工召唤 | **驳回自动回派原负责 agent（按 gid）** |
| 「防止无效触发，得有足够有效的机制管理」 | 无 throttle/去重/幂等/进度上限，同一事件会反复触发 | **防无效护栏** |

**结论**：现有引擎都是**被动模块**（能力齐全但等人把事丢过来）。调度中枢补上
「事件源 → 规则 → 队列 → 防无效 → 路由 → Web 俯瞰」这一主动闭环，让团队自己动起来。

---

## 二、总体设计（调度中枢拓扑）

```
            ┌────────────────── 📡 调度中枢 dispatcher（新增）──────────────────┐
  事件源 ──▶ │ ① source   事件源监听   （本仓库+外部适配器插槽，复用 timer 巡检） │
  Issue/PR/ │ ② rules    触发规则引擎   （条件→路由目标，自动优先/规则优先）      │
  驳回/评论 │ ③ queue    Action队列     （自动放行+规则拦截+人工审核闸门，不卡进程）│
  哨兵告警 │ ④ router   路由派发器     （按 gid 精准定位负责 agent，投 pool/接力卡）│
            │ ⑤ guard    防无效护栏     （去重/去抖/幂等/频限 + sentinel 进度上限）│
            └──────────────────────────┬───────────────────────────────────────┘
                                       │
        数据层：rejections 表（驳回迭代闭环，按 gid 路由 + 监控）+ dispatch 路由日志表
        复用：broker 派发 / pool 队列 / gid 唯一寻址 / sentinel 量化监控
                                       │
                              ┌────────▼────────┐
                              │ ⑥ webui Web面板  │ ← 人类俯瞰实时事件流/路由/拦截
                              └─────────────────┘
```

### 模块清单

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `dispatcher/source.py` | 事件源监听器 + **外部适配器插槽**（通用解决，不局限本仓库） | 原始事件源 | 规范化事件对象 |
| `dispatcher/rules.py` | 触发规则引擎（四大场景：岗位/审核/驳回/遗漏） | 事件 + 规则表 | 派发意图 |
| `dispatcher/queue.py` | Action 队列（自动优先 + 人工审核闸门，**不卡进程**） | 派发意图 | queued/hold/released/dispatched |
| `dispatcher/guard.py` | 防无效护栏（去重/频限/**进度上限**） | 派发意图 | 放行 or 拦截（留痕） |
| `dispatcher/router.py` | 路由派发器（按 **gid 精准定位**负责 agent） | 意图 | 投 pool / broker / 接力卡 |
| `dispatcher/reject.py` | 驳回迭代表（**驳回非终点**，按 gid 回派改进重提） | 驳回标记 | rejections 记录 + 迭代回派 |
| `dispatcher/engine.py` | 统一调度引擎（单次扫描 / --watch 持续守护 / drain） | 事件流 | 扫描/派发/驳回回派摘要 |
| `dispatcher/webui.py` | **Web 可视化面板**（零前端依赖） | dispatch/rejections/sentinel | 实时 HTML 俯瞰 |
| `dispatcher/cli.py` | 命令行入口（scan / watch / web / overview / reject） | 参数 | 报告/面板 |

---

## 三、核心机制（对齐用户 5 点拍板）

### 1. 事件源：本仓库 + 外部适配器插槽（#1）
`source.ExternalAdapter` 是扩展插槽：用户可注册任意外部事件源（GitHub/Gitee/工单系统/
webhook 轮询等），实现 `poll()` 返回一批原始事件，dispatcher 统一 normalize 并入流。
内置 `RepoPollAdapter`（本仓库 Issue/PR 状态扫描）。**通用解决，不局限本仓库。**

### 2. Action 队列：自动优先 + 人工审核闸门，不卡进程（#2）
- 派发意图先进队列（dispatch 表），消费方异步拉取，**不卡进程**；
- `gate=auto` 直接自动放行（常规不人力、规则优先）；
- 仅 `gate=hold`（规则拦截后**需人工判断**）才进人工审核闸门；
- 队列解耦：任务允许追加内容/重新分配（`requeue`），不会因单点阻塞卡死进程。

### 3. 驳回迭代表：驳回非终点，进入再次迭代（#3）
- `rejections` 表放**数据库**，每条带 **gid（唯一确定的负责实体）** + **agent_id**；
- **监控功能**路由到该 gid 的负责 agent，让其**改进问题重新提交**；
- **迭代闭环**：`iteration` 计数，驳回 → 回派原 agent 改进重提 → 复评 → 再驳回 +1 再回环，
  **直到通过或被哨兵判 2 级上报 blocked**——驳回不是终点，而是进入再次迭代流程。

### 4. 防无效护栏 + 进度上限判定（#4）
- **去重/幂等**：同 `dedup_key` 只派一次（复用 gid）；
- **频限**：单 gid 单位时间最大触发次数；
- **进度上限**（核心）：复用 sentinel 目标进度尺——若任务**最大完成度不再提升**
  （max(current) 封顶停滞），护栏拦截继续派发同一任务，并联动 sentinel 判定
  「最大完成度不能提升」→ 打断重规划，标记**未完成部分**，避免"开发陷入同样尝试走不出"。
- **sentinel 强化**：新增 `progress_cap_stall` 判定（最大完成度封顶 + 未完成部分占比），
  优先级最高，正常单调推进不误伤。

### 5. Web 可视化优先（#5）
`dispatcher/webui.py` 用 Python 标准库 `http.server` 起轻量 Web 服务（零前端依赖），
实时渲染：事件流全链路 / 待路由队列 / 人工审核闸门 / 已派发 / 守卫拦截 / 驳回迭代闭环 /
哨兵断点 / 目标进度尺。`POST /release/<event_id>` 支持人工放行 hold 项。

---

## 四、与既有机制的衔接

| 既有机制 | 与调度中枢的关系 |
|----------|------------------|
| timer/host 时序引擎 | 复用定时巡检做持续扫描；dispatcher 是"把事件串起来的主动大脑" |
| broker 消息总线 | 派发通道：`deliver(agent_gid, 'dispatch', ...)` 定向投递 |
| pool 功能域任务池 | 派发时按角色/功能域投池，弹性扩展 agent |
| gid 全局唯一寻址 | 驳回按 gid 精准回派唯一负责 agent，二次触发不漂移 |
| sentinel 量化监控 | 护栏进度上限复用 goal_meters；sentinel 新增 progress_cap_stall 判定 |
| collab 协作引擎 | rejections/dispatch 记录可作实体被寻址/授权/留痕 |
| generate-dashboard | Web 面板与静态版本看板并存（Web 优先实时，静态做历史） |

## 五、CLI 用法

```bash
cd local-agent
python3 -m dispatcher.cli scan           # 单次扫描事件源并派发
python3 -m dispatcher.cli watch --interval 5   # 持续守护循环
python3 -m dispatcher.cli web --port 8080      # 起 Web 可视化面板
python3 -m dispatcher.cli overview             # 队列/驳回/统计摘要
python3 -m dispatcher.cli reject --task tk-报表 --agent ag-报表开发 --reason "🔴必修 竞态"
                                           # 手工登记驳回并触发迭代回派
```

## 六、验收（AC，可量化）

| # | 验收标准 |
|---|----------|
| AC1 | 事件源（本仓库/外部适配器）可规范化并入流，`ExternalAdapter` 插槽可注册 |
| AC2 | 四大场景规则命中自动派发（岗位→产品 / issue→评审 / 驳回→按gid回派 / 遗漏→安排） |
| AC3 | `gate=auto` 自动放行不卡进程；`gate=hold` 进人工审核闸门，人工放行后派发 |
| AC4 | 同一驳回去重拦截（第二次 rejected）；任务最大完成度封顶则进度上限拦截并联动哨兵 |
| AC5 | 驳回迭代表记录迭代次数，按 gid 精准回派原负责 agent，驳回非终点、进入再次迭代 |
| AC6 | Web 面板实时展示事件流/待路由/已派发/守卫拦截/驳回闭环/哨兵断点/进度尺 |
| AC7 | `test_dispatcher.sh` 8 组测试全绿，纳入 `.cnb.yml` test 阶段 |
