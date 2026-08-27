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

---

## 8. 混合调度拓扑（Issue #41 优化 · 中央调控 + 一窝蜂抢单）

> 承接用户补充诉求：*"event 不一定非得提前开工然后返工，可以是前面架构和设计还是之前方式，架构然后分工，预先分工之后，余下的被这样快速瓜分，相当于中央调控，企业内部先吃好的，下面丢外部抢单一样一窝蜂解决和补全……或者如果没有架构，就是常规的零散任务，直接架构师确认没什么复杂架构，适合一窝蜂解决，就直接往下丢。"*

据此新增 **2 条拓扑线路**，按**任务性质差分**：

| 拓扑 | 适用任务性质 | 核心语义 | 阶段 |
|------|------------|---------|------|
| `hybrid` 混合调度·中央调控 | 架构化任务 | **前段中央调控**（架构→分工，企业内部先吃核心）+ **后段一窝蜂抢单**（预先分工后，余下子任务像"外部抢单"一样同时丢出、全部并行解决补全） | central → scramble → quality |
| `scatter` 零散·一窝蜂 | 零散任务 | 架构师快速确认"无复杂架构"→ **直接往下丢**，所有子任务一窝蜂并行解决补全 | confirm → swarm → quality |

### 设计要点
- **不依赖"提前开工+返工"**：hybrid 前段保持既有架构→分工方式（企业内先吃核心/高价值），不靠返工来体现差异；
- **余下一窝蜂抢单**：架构确定 + 预先分工后，余下子任务同时丢出，全部并行、各自补全——这是"中央调控"与"外部抢单"的结合；
- **差分处理**：架构化任务走 `hybrid`，无架构的零散任务走 `scatter`，两种模型结合但按任务性质**实际差分**分开。

### 使用（规模可调，让差异显现）

```bash
# 列出全部拓扑及适用任务性质
python3 local-agent/topology/benchmark.py --list-topos

# 架构化任务：对比 linear/dag/hybrid（scale 放大抢单节点，并发/token/文件差异清晰）
python3 local-agent/topology/benchmark.py --task suit:architected --suit architected --topologies linear,dag,hybrid --scale 3

# 零散任务：对比 linear/scatter
python3 local-agent/topology/benchmark.py --task suit:scattered --suit scattered --topologies linear,scatter --scale 3
```

### `--scale` 规模放大
- 早期对比差异被忽略的根因是**任务节点固定（11 节点）、token/文件/agent 恒定**，差异维度全为 0 或不稳定；
- `--scale N` 会把 hybrid 的抢单节点 / scatter 的一窝蜂节点按 N 倍复制放大，让**一窝蜂瓜分的并行优势（高并发/少波次/多文件/token 累积）与缺陷暴露（抢单子任务越多 bug 越多）在更大规模上清晰显现**；
- 对比结果（scale=5）示例：

| 维度 | linear | dag | hybrid |
|------|--------|-----|--------|
| 最大并发 | 1 | 3 | **40** |
| 总步骤 | 11 | 11 | **49** |
| 并行波次 | 11 | 9 | **3** |
| token | 468 | 498 | **10717** |
| bug数 | 1 | 1 | **7** |
| 文件数 | 22 | 22 | **66** |

> `linear`/`dag` 不放大节点，规模不变；`hybrid`/`scatter` 放大抢单/一窝蜂节点，规模越大差异越明显。

---

## 9. 前缀缓存·水龙头蔓延（prefix · Issue #41 优化补强）

> 承接用户补充诉求：*"框架方向对，但 bug 比较多、token 消耗也多，所以其实还可以尝试优化——近似区域下的，适合把有共享提示词头的聚合一下，以缓存命中为索引，把一盘散沙争抢，变成有序快领。相当于不是一次扔出都去抢，而是以缓存前缀形成水龙头，持续往下蔓延。"*

### 9.1 痛点定位（用户指出的真问题）

现有 `hybrid`/`scatter` 的抢单/一窝蜂阶段是**全并行**：每个抢单节点**独立携带完整共享上下文**。

- **token 大**：`benchmark` 中 `ctx_factor = 1 + (concurrency-1)*0.12`，并发 40 时每节点上下文放大到 5.7 倍。共享前缀被每个节点重复付费。
- **bug 多**：每节点独立重新构造上下文，出错面大、共享部分不一致，越大的抢单规模越易暴露缺陷。

这是典型的**散沙争抢**代价：一次扔出都去抢，各自重造前缀。

### 9.2 优化方案（水龙头蔓延）

新增 **`prefix`（前缀缓存·水龙头蔓延）** 拓扑 + **`prefix_cache`** 聚合模块：

| 维度 | scatter/hybrid（散沙·全并行） | prefix（水龙头·蔓延） |
|------|------------------------------|----------------------|
| 抢单/一窝蜂阶段 | 全部节点同时并行 | 同 role 共享前缀节点**串行蔓延** |
| 共享前缀 | 每节点独立携带完整前缀 | 前缀只构造一次（首节点付全量） |
| 后续节点 | 每节点重复付前缀 token | **命中缓存**只付增量差异 token |
| token | 按并发 N 线性放大 | 前缀 1 次 + 每节点增量 |
| bug | 各自独立构造上下文，出错面大 | 共享上下文一致，仅增量部分可能出错 |
| 本质 | 一盘散沙争抢 | 以缓存前缀形成水龙头，持续往下蔓延 |

### 9.3 核心机制（以缓存命中为索引）

```
散沙:  [节点1: 前缀+增量A] [节点2: 前缀+增量B] [节点3: 前缀+增量C]  ← 前缀×3
水龙头: [节点1: 前缀+增量A] →[缓存命中]→ [节点2: 增量B] →[缓存命中]→ [节点3: 增量C]  ← 前缀×1
```

- **聚合**：`prefix_cache.extract_prefixes` 把共享同一前缀（同 role + 同需求）的节点聚成集群。
- **缓存命中索引**：`_run_batch(cache_state=...)` 以「共享前缀 key」为索引——集群首节点付全量前缀，后续节点命中缓存只付增量。
- **水龙头蔓延**：同一集群内节点按顺序一个接一个在前缀缓存上增量推进；不同集群间无共享前缀，天然并行。

### 9.4 新增模块与指标

| 模块/指标 | 载体 | 说明 |
|----------|------|------|
| 前缀聚合模块 | `local-agent/topology/prefix_cache.py` | `extract_prefixes` 聚合 / `analyze` 静态对比 / `token_cost_of_cluster` 增量 token |
| prefix 拓扑 | `local-agent/topology/topologies.py` | central → faucet → quality 三阶段，faucet 串行蔓延 |
| 缓存指标 | `benchmark.py` / `metrics.py` | `cache_hits` / `cache_clusters` / `prefix_saved_chars` / `cache_hit_rate` |
| 测试 | `local-agent/tests/test_prefix_cache.sh` | T1~T4：注册/聚合/命中率/AB 降 token 降 bug |

### 9.5 使用

```bash
# 对比散沙(hybrid) vs 水龙头(prefix)，规模放大让优化差异清晰
python3 local-agent/topology/benchmark.py --task suit:architected --suit architected \
  --topologies hybrid,prefix --scale 5

# 查看前缀聚合静态分析
python3 -c "import sys;sys.path.insert(0,'local-agent');from topology import prefix_cache;print(prefix_cache.analyze(...))"

# 跑测试信号灯（云 CI 有 python3 环境）
bash local-agent/tests/test_prefix_cache.sh
```

### 9.6 判定口径

- `token_usage`：水龙头蔓延应**显著低于**散沙（前缀只付一次）；
- `bug_count`：水龙头蔓延应**不高于**散沙（共享上下文一致）；
- `cache_hit_rate`：越高说明前缀复用越充分（水龙头蔓延效率越高）；
- `prefix_saved_chars`：前缀节省字符量，量化 token 降幅。

> 框架验证在沙盒 `--no-llm` 模式（调度逻辑 + 缓存聚合逻辑正确）；真实 LLM 效果对比在云 CI / 有凭据环境补跑，届时 token/网络反映真实值。
