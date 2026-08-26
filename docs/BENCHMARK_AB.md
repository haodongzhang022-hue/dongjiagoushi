# 真实任务 AB 隔离对比（Benchmark AB）

> 本文档承接 Issue #41「拓扑对比」，在已有 `topology` 框架之上补齐用户诉求的**全维度对比**与**真实任务 AB 隔离测试**。
> 用户原话：「对比一下不同拓扑下的效果……要对比的是**并发量、速度、任务完成度、bug量、token消耗、产生的文件数、使用的agent数、资源消耗量（cpu、网络等）**，帮我具体对比……拿现成未完成的任务做分工测试，做 AB 测试做隔离。」

---

## 1. 为什么需要增强版（对照用户诉求）

已有 `topology` 框架（b35666a）只采集了 6 个维度：步骤/波次/回转/阻塞/耗时/成功率，且输入是虚拟需求"做一个登录系统"。

用户本次明确要求**扩展 9 类对比维度** + **用真实未完成任务测试** + **AB 隔离**：

| 用户诉求维度 | 映射指标 | 增强实现 |
|------|------|------|
| **并发量** | `max_concurrency` | 新增：单波次内同时活跃节点数峰值 |
| **速度** | `elapsed_ms` | 已有：执行耗时 |
| **任务完成度** | `completion_pct` | 新增：成功执行节点数 / 总节点数（%） |
| **bug量** | `bug_count` | 新增：开发节点缺陷检出数 |
| **token消耗** | `token_usage` | 新增：输出 token 估算 × 并发上下文系数 |
| **产生文件数** | `files_created` | 新增：隔离目录节点产出文件 + 资源快照增量 |
| **使用agent数** | `agents_used` | 新增：实际被调度的角色数 |
| **资源消耗·CPU** | `cpu_avg_pct` | 新增：/proc/stat 两次采样差值 |
| **资源消耗·内存** | `mem_delta_kb` | 新增：VmRSS 峰值/增量 |
| **资源消耗·网络** | `net_sent/recv_bytes` | 新增：/proc/net/dev 收发字节 |
| **AB 隔离** | 独立工作目录 | 每条拓扑跑在 `_bench/<任务>/<拓扑>/` 独立目录，杜绝串扰 |
| **真实任务** | 任务源 | 从「架构完未分配」「经理分工未触发」的真实待办读取 |

---

## 2. 模块结构

```
local-agent/topology/
  ├── topologies.py        # 3 条拓扑线路（linear/dag/event）——已有
  ├── metrics.py           # 全维度指标收集/持久化/汇总 ——已扩展 17 维度
  ├── resource.py          # 🆕 资源监控（CPU/内存/网络/文件，零第三方依赖）
  ├── tasksource.py        # 🆕 真实任务源（架构完未分配 / 经理分工未触发）
  ├── runner.py            # 基础对比执行器——已有
  └── benchmark.py         # 🆕 增强 AB 隔离对比执行器（真实任务+全维度+资源监控）
```

## 3. 真实任务源（tasksource）

用户明确：「架构师架构完了但还没完成分配的、经理分工了但还没给到对应 issue 和触发工作，拿他们测试」。

`tasksource` 读取两类真实待办，标记阶段：

| stage | 含义 | 示例任务 |
|------|------|---------|
| `architected_unassigned` | 架构完·未分配（经理还没分） | 市场获客分层通用基建落地、2500 并发池弹性伸缩 |
| `assigned_untriggered` | 经理已分工·未触发（没给Issue/没开工） | 分形引擎递归细分、审核者前置助手接入 |

数据层有库时从 `tasks`/`dispatch` 表读；数据层为空时用内置样例真实任务兜底（同样来自项目已定义未派发的工作）。

## 4. AB 隔离设计

- **对照组**：同一真实任务在 `linear` / `dag` / `event` 三条拓扑上互为 A/B/C 组，采集同一套指标，直接横向对比。
- **隔离**：每条拓扑跑在独立工作目录 `_bench/<task_id>/<topology>/`，执行前清空，资源快照各自独立，杜绝文件串扰与指标污染。
- **版本兼容**：指标汇总只统计含该维度的记录，旧版本缺新字段的数据不当作 0 污染均值。

## 5. 资源监控（resource.py，零第三方依赖）

沙盒/云环境无 `psutil`，故全部用标准库实现：

| 资源 | 实现 |
|------|------|
| CPU | `/proc/stat` 两次采样差值（idle/total 换算百分比） |
| 内存 | `/proc/self/status` VmRSS；fallback `resource.getrusage` |
| 网络 | `/proc/net/dev` 收发累计字节差值 |
| 文件 | 隔离目录快照前后对比（文件数/字节数增量） |

模拟执行（`--no-llm`）网络 IO 为 0 属正常；真实 LLM 环境（云端调用 API）会采集到真实网络流量。

## 6. 快速使用

```bash
# 列出真实未完成任务
python3 local-agent/topology/benchmark.py --list-tasks

# 用全部真实任务做 AB 隔离对比（linear vs dag vs event）
python3 local-agent/topology/benchmark.py --task all --topologies linear,dag,event

# 只对比某阶段真实任务
python3 local-agent/topology/benchmark.py --task stage:architected_unassigned

# 跑 N 轮累积（长时间对比判断）
python3 local-agent/topology/benchmark.py --task all --rounds 5

# 全维度汇总（长时间累积）
python3 local-agent/topology/benchmark.py --summary

# 查看某需求对比
python3 local-agent/topology/benchmark.py --compare "<task_id>"
```

## 7. 判定口径（长时间判断）

- 并行波次越少 + 最大并发越高 → 并行度越好
- 耗时越短 → 速度越快
- 完成度越高 → 交付越完整
- bug/回转/阻塞越少 → 质量与稳定性越好
- token/文件/agent/CPU/内存/网络越少 → 成本与资源占用越低
- **结论由多次运行 + 长时间累积的数据说话，单次仅供参考**

> 框架验证在沙盒 `--no-llm` 模式跑通（调度逻辑 + 全维度采集正确）；
> 真实 LLM 效果对比在云 CI / 有凭据环境补跑，届时网络/内存/token 反映真实值。
