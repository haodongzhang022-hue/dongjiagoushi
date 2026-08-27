# 缓存命中监控机制（Cache Monitor）

> Issue #41 用户明确要求：
> **"需要建立一个能监控缓存命中率的机制……监控每个 agent 的缓存命中，才能量化效果怎么样，
> 确定是否有浪费。只要没浪费，消耗多少 token 都是没问题的。"**

## 目标

把缓存命中做成**可观测、可量化、可判定**的机制，回答两个问题：
1. **缓存是否有效**？—— 每个 agent 的缓存命中率、节省 token 是多少。
2. **是否有浪费**？—— 命中率低 + 重复构造共享前缀 = 有浪费；命中率高 = 无浪费（token 多点也没问题）。

> 用户诉求「只要没浪费，消耗多少 token 都是没问题的」—— 本机制用**数据**判定「是否浪费」，
> 命中率高的 agent 即便 token 消耗大也被判定为无浪费，符合用户口径。

## 模块

`local-agent/topology/cache_monitor.py`

| 函数 | 作用 |
|------|------|
| `collect_from_memory()` | 从 `llm.cache` 内存级统计收集各 agent × 层缓存命中 |
| `waste_check(stats)` | 单个 agent 的浪费判定（数据说话） |
| `monitor()` | 一站式收集 + 判定 + 可选持久化 |
| `monitor_report()` | 人类可读报告（二级信息） |

## 浪费判定口径

```
命中率高(≥80%)         → ✅ 无浪费：前缀复用充分，token 属合理成本
命中率中等(<80%但≥阈值) → 🔶 可优化：可进一步提升复用（非硬性浪费）
命中率低(<30%) + misses>0 + prefix_chars>0
                       → ⚠️ 有浪费：共享前缀被重复构造而未复用，应聚合前缀做水龙头蔓延
总事件<3               → 样本不足：不做判定（避免误伤）
```

阈值默认 30%（`WASTE_HIT_RATE_THRESHOLD`），可按需调整。

## 数据流

```
LLM 调用层 / 角色壳 / 编排层 / 节点层
        │  record_cache_event(agent, layer, hit, prefix_chars, saved)
        ▼
   llm.cache 内存级统计（线程内）
        │  cache_monitor.collect_from_memory()
        ▼
   cache_monitor.monitor()  →  waste_check() 逐 agent 判定
        │  CacheStatsSink.persist()
        ▼
   data.cache_stats 表（数据管理员统一统计 · 人类俯瞰）
```

## 使用

```bash
# 查看缓存命中监控（按 agent × 层，量化效果 + 浪费判定）
python3 local-agent/topology/cache_monitor.py

# 限定 agent / 层
python3 local-agent/topology/cache_monitor.py --agent "架构·开发" --layer node

# 持久化到 cache_stats 表
python3 local-agent/topology/cache_monitor.py --persist

# 通过 benchmark CLI 查看（跑过 AB 对比后）
python3 local-agent/topology/benchmark.py --monitor-cache
```

## 示例输出

```
📊 缓存命中监控 · 按 agent × 层量化效果
总体命中率: 63.6% | 浪费信号: 1 个 | 持久化: 0 条

| agent | 层 | 命中 | 未命中 | 命中率% | 节省token | 判定 |
|-------|----|-----|--------|--------|----------|------|
| 架构·开发 | node | 6 | 0 | 100.0 | 600 | ✅ 无浪费 |
| 架构·评审 | node | 1 | 4 | 20.0 | 66 | ⚠️ 有浪费 |
```

**解读**：架构·开发命中率 100%，前缀复用充分 → 无浪费（token 消耗属合理成本）；
架构·评审命中率 20%，4 次未命中重复构造共享前缀 → 有浪费，应聚合前缀做水龙头蔓延。

## 指标表 `cache_stats`

数据层持久化各 agent × 层的缓存命中统计，供「架构·数据管理员」统一统计与长时间趋势分析。

## 测试

`local-agent/tests/test_cache_layer.sh` M6/M6b 覆盖：高命中=无浪费、低命中+重复构造=有浪费、持久化。
