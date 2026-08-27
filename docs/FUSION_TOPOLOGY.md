# 融合拓扑规则引擎（Fusion Topology Router · 规模金字塔 → 承接体系 · 缓存命中为主线）

> 本文档是 Issue #41「装一个规则机制，根据任务规模选择拓扑 + 融合机制」的架构产物留痕。
> 执行角色：架构·总师

---

## 背景 · 用户诉求（含关键纠偏升级）

> **纠偏核心**："不行，小任务其实占比最高，这个才最适合体系承接，但需要简化的体系，
> 类似于只剩下产品和开发、审查了，复杂度低的基本就是敏捷开发。中等开始有架构师，
> 复杂度高的公司结构拉满，再高的就是完整体系了，公司规模最大，动态扩容，加下面的
> 水龙头蔓延，带蔓延关系的回传合并。核心是缓存命中为主线，分工协作的架构是以能完成
> 目标为准的。……越小的部分反而占比越高，越需要好好优化。"

原版本（"小任务 → 散沙一窝蜂"）**没有真正为最小任务建模**。本次升级对齐用户纠偏：

1. **规模金字塔 → 承接体系**：任务从最小（单开发即可）到最大（完整公司），协作复杂度递增；
2. **小任务最该优化**：micro/small 走**简化体系·敏捷**（产品→开发→审查），占比最高最该精雕细琢；
3. **缓存命中为主线（cache-first）**：横贯所有档位，只是聚合程度递增。

---

## 规模金字塔 → 承接体系（核心表）

| 规模档位 | 判定 | 承接体系 | 选用拓扑 | 说明 |
|----------|------|----------|----------|------|
| **micro** | 复杂度≤1 且 子任务≤1 | **agile 简化体系·敏捷** | `agile` | **单任务修改/单开发即可完成**，占比最高最该优化，只留产品→开发→审查 |
| **small** | 复杂度≤3 且 子任务≤5 | **agile 敏捷开发** | `agile` | 低复杂度，仍轻量（简化体系） |
| **medium** | 复杂度≤6 且 子任务≤20 | **architected 加架构师** | `dag` | 中等复杂度，加入架构师把关 |
| **large** | 复杂度>6 或 子任务>20 | **company 公司拉满** | `dag` | 高复杂度，DAG 全角色 + 分形多小组 + 找工具/对齐 |
| **huge** | 复杂度≥9 或 子任务>50 | **full 完整体系 + 蔓延** | `prefix` | 极高复杂度/大型，公司规模最大 + 动态扩容 + 水龙头蔓延 + 带蔓延关系回传合并 |

> 承接体系（`TIER_SYSTEM`）：agile → architected → company → full，随规模递增协作复杂度。

---

## 缓存命中为主线（cache-first · 横贯所有档位）

用户："**核心是缓存命中为主线**"。不是只有大规模才缓存，而是所有档位都复用共享上下文，
只是**聚合程度递增**：

| 档位 | 缓存命中策略 |
|------|-------------|
| micro/small | **最简共享需求前缀**：产品→开发→审查共享需求前缀，前缀只构造一次，后续节点命中缓存只付增量 token |
| medium/large | 按 role 聚合共享前缀，命中缓存增量蔓延（常规规模 token 复用充分） |
| huge | **水龙头蔓延聚合为集群**：前缀只构造一次，后续节点增量蔓延（动态扩容 + 带蔓延关系回传合并） |

> 分工协作架构以「能完成目标」为准，高复杂/大型才兼顾快速（提速）——缓存命中是主线，
> 不是唯一目的。

---

## 融合触发门控（不是必选）

| 触发信号 | 条件 | 动作 |
|----------|------|------|
| `scale_exceeded` | 档位 > large（即 huge） | 完整体系 + 水龙头蔓延（prefix 融合） |
| `scattered_high_concurrency` | 零散 或（子任务>5 且 并发>10） | 直接用新框架一窝蜂（scatter） |
| 默认 | 按规模档位走承接体系 | micro/small→agile，medium→architected，large→company |

**优先级**：`scale_exceeded` > `scattered` > 规模档位承接体系。
即：极高复杂度/大型触发完整体系+蔓延；散沙高并发一窝蜂；其余按规模档位走对应承接体系，
不轻易上融合（防止对小任务过度设计）。

---

## 四套配套方案（随选择产出）

| 方案 | 落地要点 |
|------|----------|
| **① 缓存命中（主线）** | 所有档位共享前缀复用；micro/small 最简共享需求前缀 → huge 水龙头蔓延聚合为集群 |
| **② 分工** | 规模分层映射子任务分配策略（micro/small 不做重分工单开发完成；large/huge 分形拆小组 / 中央调控+瓜分） |
| **③ 信息回传** | 各节点完成后回传收口到评审/测试节点；gid 稳定寻址；huge 带蔓延关系回传合并 |
| **④ 合并** | 分形/抢单结果按最小模块粒度统一向上整合交付（commits 以小组为单位） |

---

## 模块清单

| 模块 | 载体 | 职责 |
|------|------|------|
| **融合规则引擎** | `topology/fusion.py` | `evaluate_scale` 规模评估（含 micro 档 + 承接体系）+ `select_topology` 规则选择 + `build_plan` 四套方案 + `route` 一条 API |
| **敏捷承接拓扑** | `topology/topologies.py` `agile` | 简化体系（产品→开发→审查）极简线路，占最高频任务 |
| **注册** | `topology/__init__.py` | 导出 `fusion` / `topologies` |
| **测试** | `tests/test_topology_fusion.sh` | 12 项信号灯（规模金字塔 → 承接体系 + 缓存主线） |

---

## 用法

```bash
# 一条 API：规模评估 + 承接体系选择 + 拓扑 + 四套方案
python3 -c "import sys;sys.path.insert(0,'local-agent');from topology import fusion;r=fusion.route(complexity=0,subtasks=1,concurrency=1);print(r['tier'],r['system'],r['selected'])"
# → micro agile agile   （单任务修改 → 简化体系·敏捷）

python3 -c "import sys;sys.path.insert(0,'local-agent');from topology import fusion;print(fusion.route(complexity=9,subtasks=60,concurrency=3)['selected'])"
# → prefix             （极高复杂度/大型 → 完整体系 + 水龙头蔓延）

# CLI 路由 / 二级信息快照
python3 local-agent/topology/fusion.py --route --complexity 0 --subtasks 1 --concurrency 1
python3 local-agent/topology/fusion.py --overview

# 信号灯测试
bash local-agent/tests/test_topology_fusion.sh
```

---

## 验证结果（信号灯 12/12 通过）

```
✅ micro 档=简化体系·敏捷 agile          ✅ small 档=敏捷开发 agile
✅ medium 档=加架构师 dag               ✅ large 档=公司拉满 dag
✅ huge 档=完整体系 prefix              ✅ 散沙高并发选一窝蜂 scatter
✅ huge 档 scale_exceeded=True          ✅ 四套配套方案齐全
✅ agile 缓存命中为主线（cache-first）   ✅ 融合场景缓存方案含水龙头蔓延
✅ overview 二级信息可用（含 micro）     ✅ CLI overview 运行
```

---

## 补充 · 复杂度递进式精简体系（Complexity-Slim · 角色子集 + 占比量化）

> 上层「规模金字塔→承接体系」负责**选体系/选拓扑**，本层 `topology/slim.py` 与其互补（非重复），
> 为每个金字塔档位给出**最小角色子集**（以能完成目标为准）+ **占比量化**（越小占比越高、越精简）。
> 二者协同：金字塔选承接体系，slim 定该体系的精确角色清单与占比，缓存命中为主线贯穿。

### 角色子集精简（金字塔档位 → 最小角色清单）

| 档位 | 承接体系 | 角色子集（最小可用） | 协作形态 | 占比 |
|------|----------|---------------------|----------|------|
| **micro** | agile | `[架构·开发]` | 单名开发直做，改完即交付 | 40% |
| **small** | agile | `[产品, 开发]` | 敏捷开发，无架构/评审冗余 | 30% |
| **medium** | architected | `[产品, 总师, 开发, 评审]` | 架构接力 | 15% |
| **large** | company | `[秘书, 经理, 产品, 总师, 小组长, 开发, 评审, 测试]` | 公司式分工，结构拉满 | 10% |
| **huge** | full | 完整体系 + `[监控哨兵, 数据管理员]` | 完整体系+动态扩容+水龙头蔓延 | 5% |

> **以能完成目标为准**：只建到能完成目标的角色，绝不为小任务拉满团队。
> **越小占比越高越精简**：micro 40% 占比最高、最该优化精简（单名开发省去全部协作开销）。

### 缓存命中为主线（贯穿所有档位，聚合程度递增）

| 档位 | 缓存主线 |
|------|----------|
| micro | 单 agent 连续改同一处 → 复用同一上下文缓存，仅付增量差异 token（占比最高，省得最多） |
| small | 产品+开发共享需求前缀，开发接手复用澄清前缀，命中增量蔓延 |
| medium | 按 role 聚共享前缀（架构结论→开发复用），评审复用开发产出前缀 |
| large | 按功能域/小组聚合共享前缀为集群，同 role 只构造一次，多部门天然并行 |
| huge | 共享前缀聚合为集群（缓存命中为索引）→ 水龙头蔓延，带蔓延关系回传合并，动态扩容复用集群前缀 |

### 新增模块与接入

| 模块 | 载体 | 职责 |
|------|------|------|
| **精简体系引擎** | `topology/slim.py` | `slim_route(tier)` 返回角色子集/协作/缓存主线/占比 + `overview` 全档俯视图 |
| **融合接入** | `topology/fusion.py` | 惰性加载 slim；`select_topology` 各分支结果带 `slim` 角色子集；新增 `fusion.slim_route` 便捷 API + CLI `--slim` |
| **导出** | `topology/__init__.py` | 导出 `slim` |
| **测试** | `local-agent/tests/test_topology_slim.sh` | 13 项信号灯 |

### 用法

```bash
# 精简体系路由（角色子集 + 占比 + 缓存主线）
python3 local-agent/topology/fusion.py --slim --tier micro

# 全档俯视图（人类俯瞰）
python3 local-agent/topology/slim.py --overview

# 融合路由结果直接带 slim 角色子集
python3 -c "import sys;sys.path.insert(0,'local-agent');from topology import fusion;r=fusion.route(complexity=0,subtasks=1,concurrency=1);print(r['slim']['roles'], r['slim']['ratio'])"
# → ['架构·开发'] 0.4
```
