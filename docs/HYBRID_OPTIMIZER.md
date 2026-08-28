# 测试智能优化层（Hybrid Optimizer · v2.0）

## 北极星

把「每次全量跑 43 个 CPU 密集测试」优化为「变更感知增量 + 结果缓存 + 集中并行」，
云端/本地 CPU 消耗再降 **80%**。核心决策点：**CPU 负载优先于 token**。

## 模块拆解

| 模块 | 文件 | 说明 |
|------|------|------|
| TestRegistry | `hybrid/registry.json` + `hybrid/registry.py` | 集中测试注册表，声明测试脚本→覆盖源码模块+依赖 |
| IncrementalSelector | `hybrid/selector.py`（T2） | `git diff` → 受影响测试选择器，含依赖传播 |
| FingerprintCache | `hybrid/cache.py`（T3） | 指纹缓存 + `test_cache` 表，证据链可追溯 |
| ParallelExecutor | `hybrid/parallel.py`（T4） | 并行执行器，`-P` 并行度/超时/失败隔离 |
| PolicyEngine | `hybrid/policy.py`（T5） | 策略引擎，增量/缓存/并行/全量开关 + 7天全量回归 |
| CostReporter | `hybrid/cost.py` 扩展（T6） | 成本报表三合一节省统计 |

## TestRegistry（T1）

集中 JSON 注册表，声明每个测试脚本的：

- **covers**：该测试覆盖的源码模块路径（支持精确匹配和目录前缀匹配）
- **depends_on**：前置依赖测试（用于依赖传播防漏测）
- **cpu_cost_est / time_est**：预估成本（供策略引擎决策）
- **kind**：测试类型（当前为 `cpu-dense`）

### 查询接口

```python
from hybrid import registry

# 全部已注册测试
registry.all_tests()          # -> [script_path, ...]

# 单测试查询
registry.get("local-agent/tests/test_engine.sh")
registry.covers("local-agent/tests/test_engine.sh")     # -> [source_modules]
registry.dependencies("local-agent/tests/test_engine.sh")  # -> [dependent_tests]

# 反向查询：源码 → 受影响测试
registry.find_by_source("engine/state_machine.py")      # -> [test_paths]
registry.find_by_source("topology/")                    # 目录前缀匹配

# 依赖传播（防漏测）
registry.impact_closure("local-agent/tests/test_collab.sh")
# 综合入口：变更文件 → 需跑测试（含依赖传播）
registry.affected_tests(["engine/state_machine.py"])

# 概览
registry.summary()
```

### 依赖传播规则

- `test_a depends_on test_b`：表示 `test_a` 在逻辑上依赖 `test_b` 的模块。
- 当 `test_b` 覆盖的模块变更时，`test_b` 和 `test_a` 都需运行。
- `impact_closure()` 用 DFS 传递闭包，覆盖直接+间接依赖，防漏测。

## IncrementalSelector（T2）

`git diff` 获取变更文件 → `registry.affected_tests()` 得到受影响测试清单。

## 策略引擎（T5）

| 开关 | 默认 | 说明 |
|------|------|------|
| `--incremental` | on | 变更感知增量（git diff → 受影响测试） |
| `--cache` | on | 结果缓存命中跳过 |
| `--parallel` | auto | 并行执行（`-P` 并行度） |
| `--full` | off | 强制全量（7天自动触发回归） |

## 测试与验证

每个模块独立测试脚本（`local-agent/tests/test_hybrid_*.sh`），独立通过信号灯。
