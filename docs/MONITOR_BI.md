# 📊 工作过程监控 + 可视化 BI 大屏（monitor-bi 模块）

> 模块：`monitor-bi` · 版本：`v0.1.0` · 类型：`init` · Issue：#55
> 依赖：#46（需求澄清基线）

## 一、模块定位

**工作过程监控 + 可视化 BI 大屏**：以 **agent / 岗位 / 对话 / 项目** 四维口径
统计体系工作量、token 消耗、总产出、对话文字量、代码变化量，并做异常监控
（没工作 / 异常重复 / 分工失衡），形态为**可视化 BI 大屏**（人类俯瞰二级信息视图）。

本模块**复用**现有 data 层（agents/messages/tasks/progress/archives/stats +
token_usage/code_changes）+ sentinel 引擎（停滞/横跳/重复错误），**不重造**核心能力。

## 二、能力清单

| # | 能力 | 模块文件 | 说明 |
|---|------|---------|------|
| M1 | 四维统计引擎 | `stats.py` | agent/role/conversation/project 四维工作量聚合 |
| M2 | token 分析 | `token.py` | 估算+真实双模式，四维聚合+趋势 |
| M3 | 代码变化统计 | `code.py` | 按项目/agent 归集 +/- 行数 |
| M4 | 异常监控 | `anomaly.py` | 复用 sentinel + 新增分工失衡 |
| M5 | 可视化渲染 | `render.py` | 生成 Markdown BI 大屏 |
| M6 | CLI 入口 | `cli.py` | overview/render/token/code/anomaly/stats |

## 三、四维口径

| 维度 | 统计内容 |
|------|---------|
| **agent** | 每个 agent 的工作量/产出/token/状态 |
| **role**  | 每个角色（秘书/产品/开发/评审/测试/哨兵）汇总 |
| **conversation** | 每轮对话/会话的文字量/参与方（topic） |
| **project** | 每个项目(Issue/任务)产出/参与度 |

## 四、关键指标

- **总产出**：archives 存档数 + progress 事件数
- **对话文字总量**：messages 消息数
- **代码变化总量**：code_changes 表的 added/deleted 行数
- **token 消耗**：token_usage 表（估算兜底 + 真实回传，按 msg_id 去重）
- **异常检测**：停滞 / 横跳 / 重复错误（复用 sentinel）+ 分工失衡（新增）

## 五、数据扩展

在 `data/schema.py` 新增 2 张表：

```sql
-- token 消耗记录（M2）
CREATE TABLE token_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id      TEXT NOT NULL UNIQUE,   -- 按消息去重，防重复计算
    agent_id    TEXT, role TEXT, topic TEXT, project TEXT,
    token_count INTEGER, method TEXT,   -- estimate/real
    ts          TEXT
);

-- 代码变化统计（M3）
CREATE TABLE code_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id   TEXT NOT NULL UNIQUE,   -- 按 commit 去重
    agent_id    TEXT, project TEXT,
    added       INTEGER, deleted INTEGER,
    ts          TEXT
);
```

## 六、接口契约

```python
from monitor_bi import MonitorBI
bi = MonitorBI()

bi.workload_4d("agent")          # 四维统计 → list[{key, progress_count, message_count, archive_count, total}]
bi.status_summary()              # 状态汇总 → list[{key, todo, in_progress, done, blocked}]
bi.drill_down("agent", "ag-1")   # 下钻明细 → list[{kind, ...}]
bi.token_summary("project")      # token 聚合 → {total, breakdown}
bi.token_trend("hour")           # token 趋势 → [{bucket, tokens}]
bi.code_changes()                # 代码变化 → list[{key/k0/k1, added, deleted, net, commits}]
bi.code_total()                  # 总代码变化 → {added, deleted}
bi.anomaly_scan()                # 异常扫描 → list[{entity, type, reason, severity}]
bi.render()                      # BI 大屏 Markdown → str
bi.render_to_file()              # 写入 docs/BI_DASHBOARD.md → path
```

## 七、CLI 用法

```bash
# 实时查询（终端输出）
python -m monitor_bi.cli overview

# 生成 BI 大屏文档（docs/BI_DASHBOARD.md）
python -m monitor_bi.cli render

# 查看 token 消耗
python -m monitor_bi.cli token

# 查看代码变化
python -m monitor_bi.cli code

# 扫描异常
python -m monitor_bi.cli anomaly

# 查看四维统计
python -m monitor_bi.cli stats
```

## 八、异常检测（M4）

| 类型 | 来源 | 判定标准 |
|------|------|---------|
| 停滞 | 复用 sentinel | sentinel_actions（reason=stagnation） |
| 横跳 | 复用 sentinel | sentinel_actions（reason=oscillation） |
| 重复错误 | 复用 sentinel | sentinel_actions（reason=repeated_error） |
| **分工失衡** | 新增判定 | 单 agent 工作量占比 > 40% 或 岗位量差 > 3 倍（阈值可配置） |

## 九、测试信号灯

```bash
bash tests/test_monitor_bi.sh
```

覆盖：文件存在性 / schema 扩展 / 数据层 CRUD 去重 / 四维统计 / 接口显式导出 /
CLI 六命令可运行。**任一失败即流水线红灯**。

## 十、与现有模块关系

- **data 层**：复用（扩展 token_usage/code_changes 2 表 + repository CRUD）
- **sentinel**：复用（停滞/横跳/重复错误三类判定）
- **generate-dashboard.py**：并存（各管各的，不耦合）
- **cache_stats**：数据源之一（token 消耗统计参考）
