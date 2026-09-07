# Hybrid 成本报表扩展（Issue #65 · T6）

## 背景

v1.0 的 CostMonitor 只量化「本地化路由」的节省（local/cloud 路由成本）。
T6 扩展为 **三合一节省报表**，把增量、缓存、并行三种优化的成本节省
统一量化为一个报告。

## 扩展方法：`report_optimizer()`

### 三合一节省维度

| 维度 | 节省来源 | 量化口径 |
|------|---------|---------|
| **增量节省** | 未受影响测试跳过（git diff 无关） | 该测试原本的云端 CPU 核·分钟 |
| **缓存节省** | 指纹未变化跳过（缓存命中） | 该测试原本的云端 CPU 核·分钟 |
| **并行节省** | 并行 vs 串行的墙钟时间差 | 节省时间 × 成本单价 |

### 使用方式

```python
from hybrid.cost import CostMonitor

monitor = CostMonitor()

# 1. 先获取 policy 的执行计划
# plan = engine.build_plan(all_scripts, changed_files)
# plan = {'mode': 'incremental+cache', 'run': [...], 'skip': [...], 'reason': {...}}

# 2. 执行测试
# result = engine.execute(plan['run'])

# 3. 生成三合一节省报表
report = monitor.report_optimizer(plan, run_result=result, costs=costs)
# → {
#     'incremental_saved': 20.0,       # 增量节省（核·分钟）
#     'cache_saved': 15.0,             # 缓存节省（核·分钟）
#     'parallel_time_saved': 8.0,      # 并行节省时间（分钟）
#     'parallel_cost_saved': 8.0,      # 并行节省折算成本
#     'total_saved': 43.0,             # 三合一合计节省
#     'hit_rate': 0.6667,              # 跳过率
#     'speedup': 2.5,                  # 并行加速比
#     'total_scripts': 3, 'run_scripts': 1, 'skip_scripts': 2,
#     'mode': 'incremental+cache',
# }
```

### 成本参数

`costs` 参数可选：`{test_script: cloud_cpu_est}` 为每个测试预估云端成本。
未提供时默认每脚本 10 核·分钟。

## 兼容性

- v1.0 `report()` 接口完全保留，`report_optimizer()` 为新增方法
- 与 policy.build_plan() 的返回值兼容
- `hybrid/v2.0` 升版，v1.0 接口向后兼容
