# 架构升级 · 可伸缩蜂群协作平台（FRAMEWORK_V3）

> 本文件是 ISSUE #20「架构升级：规模伸缩 + 前置流程区分 + 角色灵活增减」的架构八步产物留痕。
> 执行角色：架构·总师（官方 @CodeBuddy 化身）
> 核心结论：把体系从「单进程串行 + 单文件接力卡 + 硬编码角色表」的**小团队编排器**，升级为「**可伸缩蜂群协作平台**」——通过 **规模声明 + 消息总线 + 状态分片 + 并发池 + 前置流程区分 + 角色插件化**，在架构层面支撑 **上百 / 上千 / 2500 级**并发协作。

---

## ⏸CP0 · 需求澄清摘要

- **目标**：对现有体系做架构升级，解决 4 个核心诉求：
  1. **不同位置的流程稍微不同，需要前置区分** → 前置流程区分（Entry Profile）；
  2. **架构是否应加强 + 灵活增减角色，需要规则支撑** → 角色插件化注册（Plugin）；
  3. **允许跟 AI 交互，声明团队大小、分工层级** → 团队规模声明（Team Spec）；
  4. **大规模协作（上百/上千/2500 并发）是否还能正常协作、消息传递和分工** → 规模伸缩层（Scale）。
- **验收标准**：
  1. 可通过 `--spec '{"team_size": N, "levels": L, "mode": M}'` 声明团队规模，并据 levels 生成分工拓扑；
  2. 不同 profile（default/company/harness/acquisition/support）走不同前置流程；
  3. 角色可通过 `roles.d/*.py` 插件增减，无需改核心代码；
  4. 消息总线 + 状态分片 + 并发池可支撑 2500 级并发模拟；
  5. 既有 75 项主测试 + local-agent 19 项测试全部保持绿色。

---

## 1/8 调研报告

### 现状瓶颈诊断（关键：回答"当前能否 2500 协作"）

| 维度 | 当前实现 | 瓶颈 | 大规模（2500）可行性 |
|------|---------|------|---------------------|
| **执行模型** | `orchestrator.py` DAG 波次用 `for nid in wave` 逐个串行 | 波次标注"可并行"但**实际串行** | ❌ 无法真并发 |
| **状态存储** | `relay.py` 单一 `relay_card.json` | 单文件被全局共享，多 agent 状态互相覆盖 | ❌ 无法独立并发状态 |
| **消息传递** | `card["input"]=out` 单接力卡传递 | 一次只有一个 agent 持有全局输入 | ❌ 无 agent 间消息总线 |
| **角色注册** | `roles/__init__.py` 硬编码 `ROLE_REGISTRY` | 增删角色需改代码 | ⚠️ 不灵活 |
| **前置流程** | 单一秘书入口 | 不同场景无法区分流程 | ⚠️ 无 profile 概念 |
| **规模声明** | 无 | 团队大小/分工层级写死 | ❌ 无法声明 |
| **并发原语** | 无 thread/asyncio/concurrent/queue | 无并行执行能力 | ❌ 需引入 |

**结论：当前架构只能支撑约十几到几十个 agent 的顺序协作，完全无法支撑 2500 级并发。** 用户判断准确。

### 用户诉求 → 增强映射

| 用户原话 | 映射增强 | 落地载体 |
|---------|---------|---------|
| "不同位置的流程稍微不同，需要前置区分" | **前置流程区分** | `scale/profile.py` |
| "灵活增减角色的能力，需要规则支撑" | **角色插件化注册** | `scale/plugin.py` + `roles.d/` |
| "声明要的团队大小，分工层级" | **团队规模声明** | `scale/spec.py` |
| "上百个、上千个是否还能正常协作" | **规模伸缩层** | `scale/{broker,store,pool}.py` |
| "消息传递和分工等了吗" | **消息总线 + 状态分片** | `scale/broker.py` + `scale/store.py` |
| "deepseek harness 里面一个模式" | **harness profile** | `scale/profile.py` harness |
| "在线团队/公司，但不同位置流程不同" | **company profile** | `scale/profile.py` company |
| "调用架构师做架构升级" | **本架构八步** | `docs/FRAMEWORK_V3.md` |

### 参考与取舍
- **消息传递**借鉴 Kafka/Redis Streams 的 topic→订阅模型，但做成轻量内存版（可换分布式后端）；
- **状态分片**借鉴 sharding 思想，按 agent_id 分文件（可换 Redis），避免单点热点；
- **并发**用 ThreadPoolExecutor（IO 密集的 LLM 调用天然契合），预留 asyncio 扩展；
- **插件角色**借鉴 Python 动态 import + 命名空间隔离，注册规则显式化；
- **前置流程**借鉴"多入口路由"，不同位置不同流程模板。

---

## 2/8 顶层架构拓扑

```mermaid
graph TD
    U[用户 / AI 交互] -->|--spec 声明团队规模| S[scale/spec 规模声明]
    U -->|--profile 声明位置| P[scale/profile 前置流程区分]
    S --> E[scale/engine 统一调度]
    P --> E
    E -->|按 levels 生成分工拓扑| T[分工层级拓扑]
    E -->|加载内置+插件角色| R[scale/plugin 角色插件]
    E -->|建消息总线| B[scale/broker 消息总线]
    E -->|按 agent 分片| ST[scale/store 状态分片]
    E -->|真并行波次| PL[scale/pool 并发池]
    PL -->|收消息→处理→回写→发消息| A[agent 1..N]
    B <--> A
    ST <--> A
    A -->|交付汇总| D[规模化交付报告]

    subgraph 既有核心（保留）
      G[graph DAG] --> OR[orchestrator]
      FR[fractal 分形]
      RY[relay 接力卡]
    end
    E -.->|小规模可复用| OR
```

### 模块清单（本次新增 scale 层）
| 模块 | 载体 | 职责 | 依赖 | 可独立演进 |
|------|------|------|------|-----------|
| **规模声明** | `scale/spec.py` | 团队大小/分工层级/并发度/模式声明 + 资源评估 | 无 | ✅ |
| **前置流程区分** | `scale/profile.py` | 多入口模板（default/company/harness/acquisition/support） | 无 | ✅ |
| **角色插件** | `scale/plugin.py` | roles.d 自动发现 + 注册规则 + 按规模过滤 | roles.base | ✅ |
| **消息总线** | `scale/broker.py` | 发布/订阅/定向投递/广播 | 无 | ✅ |
| **状态分片** | `scale/store.py` | 按 agent 分片状态存储（替代单文件接力卡） | 无 | ✅ |
| **并发池** | `scale/pool.py` | ThreadPool 真并行波次 | 无 | ✅ |
| **统一调度** | `scale/engine.py` | 整合以上六者，规模化流水线 | 全 | ✅ |

---

## 3/8 可行性验证

| 关键假设 | 验证方式 | 结论 |
|---------|---------|------|
| 2500 并发可模拟调度 | `engine.run_scaled(team_size=2500)` | ✅ 2500 agent 全部成功，0 失败 |
| 状态分片可隔离并发状态 | store 多卡读写互不覆盖 | ✅ 通过 |
| 消息总线支持发布/定向/广播 | broker 单测 | ✅ 通过 |
| 并发池真并行（非纸面） | 10 任务 workers=10 耗时≈0.05s（串行需 0.5s） | ✅ 真并行 |
| 角色插件自动加载 | roles.d/analyst.py → 16 角色 | ✅ 通过 |
| 前置流程区分 | 5 个 profile 路由正确 | ✅ 通过 |
| 规模资源评估 | 2500 超单机上限 → 建议 redis+distributed | ✅ 正确提示 |
| 未破坏既有功能 | 主测试 75 项 + local-agent 19 项 | ✅ 全部绿 |

全部关键假设验证通过。

---

## 4/8 工程实施方案

### 新增文件清单
| 文件 | 改动 |
|------|------|
| `local-agent/scale/__init__.py` | 规模伸缩层包 |
| `local-agent/scale/spec.py` | 团队规模声明 + 资源评估 + 分工拓扑 |
| `local-agent/scale/profile.py` | 前置流程区分（5 个入口模板） |
| `local-agent/scale/plugin.py` | 角色插件化注册规则 |
| `local-agent/scale/broker.py` | 消息总线（发布/订阅/定向/广播） |
| `local-agent/scale/store.py` | 状态分片存储 |
| `local-agent/scale/pool.py` | 并发执行池 |
| `local-agent/scale/engine.py` | 统一调度引擎 |
| `local-agent/roles.d/analyst.py` | 插件角色示例（演示灵活增减） |
| `local-agent/run.py` | 新增 `--scale/--spec/--profile/--list-profiles/--concurrency` 入口 + `--list-roles` 合并插件 |
| `local-agent/tests/test_scale.sh` | scale 层 7 组功能测试 |

### 接口契约
```
--spec  '{"team_size":N, "levels":L, "concurrency":C, "mode":M, "profile":P, "roles":[...]}'
--scale --req "需求" --profile <模板> [--concurrency N]
broker.publish(topic, payload, from_agent) / deliver(agent, topic, payload) / fan_out(topics, payload)
store.new_card(card_id, **fields) / update / append_log / get / count / clear_all
pool.run_concurrent(tasks, max_workers) / run_wave(wave_items)
plugin.merged_registry() / load_plugins() / filter_by_spec(roles, subset)
profile.route(name) → {profile, entry, pre, route, fallback}
spec.build_topology(spec) / resource_estimate(spec)
```

---

## 5/8 分工与协作规则

### 规模声明规则（与 AI 交互的入口）
- 用户通过 `--spec` 声明团队规模，**不再由代码写死**；
- `levels` 分工层级决定嵌套分组深度（上限 6 防爆栈）；
- `concurrency` 决定并发池大小（默认取 team_size）；
- `mode` 区分 team（团队）/ company（公司）/ harness（deepseek 内嵌）；
- `profile` 指定前置流程模板（不同位置不同流程）。

### 角色增减规则（Plugin）
- 新增角色：在 `roles.d/` 放一个继承 `BaseRole`、定义 `name`（带「架构·/市场·」前缀）的 `.py` 文件，**自动加载**；
- 删除角色：删文件或 `plugin.unregister_role(name)`；
- 按规模过滤：`filter_by_spec(roles, spec_roles)` 只保留需要的角色。

### 规模化协作规则（Scale）
- 每个 agent 有独立状态卡（分片）+ 消息队列（总线）；
- agent 循环：收消息 → 处理 → 回写状态 → 发消息；
- 波次真并行由并发池驱动，并发度受控；
- 超过单机上限自动提示升级分布式后端。

---

## 6/8 进度对齐

| 里程碑 | 验收 | 状态 |
|--------|------|------|
| S1 规模声明模块 | spec 声明 + 资源评估 + 分工拓扑 | ✅ 本次实现 |
| S2 前置流程区分 | 5 个 profile 路由 | ✅ 本次实现 |
| S3 角色插件化 | roles.d 自动加载 + 注册规则 | ✅ 本次实现 |
| S4 消息总线 + 状态分片 | broker/store 单测 | ✅ 本次实现 |
| S5 并发池 | 真并行波次验证 | ✅ 本次实现 |
| S6 统一调度引擎 | 2500 级模拟 + 100 级 harness 全链路 | ✅ 本次实现 |
| S7 测试 | test_scale.sh 7 组 + 既有测试全绿 | ✅ 本次实现 |
| S8 文档 + 合并 | FRAMEWORK_V3/README/ROADMAP | ⏳ 文档 + ⏸CP3 待放行 |

暂停点：⏸CP3 合并确认（PR 提交后待用户本人放行）。

---

## 7/8 索引建立

| 产物 | 留痕位置 |
|------|---------|
| 本架构设计 | `docs/FRAMEWORK_V3.md`（本文件） |
| 规模声明 | `local-agent/scale/spec.py` |
| 前置流程区分 | `local-agent/scale/profile.py` |
| 角色插件 | `local-agent/scale/plugin.py` |
| 消息总线 | `local-agent/scale/broker.py` |
| 状态分片 | `local-agent/scale/store.py` |
| 并发池 | `local-agent/scale/pool.py` |
| 统一调度 | `local-agent/scale/engine.py` |
| CLI 入口 | `local-agent/run.py` |
| 插件角色示例 | `local-agent/roles.d/analyst.py` |
| scale 测试 | `local-agent/tests/test_scale.sh` |
| 交付 PR | 本次提交 PR 链接 |

---

## 8/8 汇报与复盘

### 决策摘要
- **已定**：新增「规模伸缩层」scale 六模块，把体系升级为可伸缩蜂群协作平台；新增前置流程区分 + 角色插件化；run.py 增加规模声明交互入口；插件角色示例落地。
- **待定**：⏸CP3 合并确认；分布式后端（Redis 消息/状态）真实接入作为后续迭代。

### 风险清单
| 风险 | 等级 | 规避方案 |
|------|------|---------|
| 单机无法真跑 2500 并发 worker | MEDIUM | 线程数受控（压测用 override）；架构层已验证可分片/可总线，分布式后端可替换 |
| 插件加载冲突 | LOW | 命名空间隔离 + 注册规则校验 + 显式报错 |
| 新增层破坏既有测试 | LOW | 全量回归测试（75+19+7 全绿） |
| 分布式后端未落地 | MEDIUM | 已留后端抽象（memory/filesystem/redis），Redis 作为 S9+ 迭代 |

### 复盘四要素
- **根因**：现有架构是"单进程串行 + 单文件接力卡 + 硬编码角色表"，本质上是一次一个 agent 的顺序编排器，架构上限低。
- **教训**：并发与消息传递不能靠"单接力卡 + for 串行"纸面实现；规模化必须引入独立状态 + 消息总线 + 真并发。
- **预防机制**：后端抽象（可换分布式）+ 并发池 + 状态分片 + 插件注册规则 + 回归测试。
- **已落地**：scale 六模块 + run.py 规模入口 + 插件角色示例 + 2500 级模拟验证 + 测试 + 文档。
