# Hybrid 测试智能优化层（Issue #65）

> 在现有 `hybrid/` 模块基础上扩展的**测试智能优化层**：增量感知 + 结果缓存 + 并行执行 + 策略引擎。
> 本 PR 交付 **T1 TestRegistry** 与 **T2 IncrementalSelector**。

## 背景

现有 CI 每次 push 都全量跑 32 个 CPU 密集测试脚本。无论改动哪个模块，全部重跑一遍，造成大量重复劳动。

**核心问题**：
- 无增量感知：只改了 `hybrid/` 模块，`test_collab.sh` 等无关模块也重跑
- 无结果复用：某模块代码无变化，结果却重新算一遍
- 无依赖传播：改公共模块（如 `data/schema.py`），所有依赖它的测试可能被漏测

## 架构

```
┌─────────────────────────────────────────────────────┐
│ ① TestRegistry（hybrid/registry.py）                │
│    集中 JSON 声明 32 测试 → 覆盖源码模块 + 依赖关系   │
│    数据驱动，可程序化查询，无散落注释头               │
├─────────────────────────────────────────────────────┤
│ ② IncrementalSelector（hybrid/selector.py）        │
│    git diff → 变更文件 → 映射到受影响测试            │
│    依赖传播：改公共模块 → 相关测试全部纳入            │
└─────────────────────────────────────────────────────┘
```

## 模块一：TestRegistry

### 数据文件

`local-agent/hybrid/data/test_registry.json` 为**唯一事实来源**。

每个测试脚本声明：
- `covers`：该测试覆盖的源码模块/文件（触发条件）
- `depends_on`：该测试依赖的源码路径（依赖传播用）

```json
{
  "version": "1.0",
  "scripts": {
    "test_hybrid_router.sh": {
      "covers": ["local-agent/hybrid/router.py"],
      "depends_on": ["local-agent/hybrid"]
    }
  }
}
```

### 查询接口

```python
from hybrid.registry import TestRegistry, default_registry

reg = TestRegistry()

# 按文件路径 → 找到需要跑的测试
reg.tests_for_file("local-agent/hybrid/router.py")
# → ['test_hybrid_pipeline.sh', 'test_hybrid_router.sh']

# 按模块名 → 找到覆盖该模块的测试
reg.tests_for_module("hybrid")
# → ['test_hybrid_pipeline.sh', 'test_hybrid_router.sh']

# 按变更文件 → 含依赖传播的完整测试清单（防漏测）
reg.affected(["local-agent/data/schema.py"])
# → 19 个测试（data 是公共基础设施）

# 注册表摘要
reg.summary()
# → {'total_scripts': 32, 'total_covers': 35, ...}
```

### 匹配规则

`tests_for_file()` 支持三种匹配模式：
1. **精确匹配**：`covers` 项与文件路径完全相同
2. **目录匹配**：文件路径在 `covers` 目录下（如 covers="local-agent/hybrid" 匹配 router.py）
3. **模块匹配**：文件属于 covers 模块目录

## 模块二：IncrementalSelector

### 选择逻辑

```python
from hybrid.selector import IncrementalSelector
from hybrid.registry import TestRegistry

sel = IncrementalSelector(registry=TestRegistry())

# 自动解析 git diff
result = sel.select(base="main", head="HEAD")
# → {'tests': [...], 'changed_files': [...], 'propagated': True}

# 或显式传入变更文件
result = sel.select(changed_files=["local-agent/hybrid/router.py"])
```

### 依赖传播（防漏测）

```
改 data/schema.py → 直接匹配 test_data_layer.sh
                  ↘ 依赖传播：test_collab.sh / test_dispatch_ability.sh / ...
                     （所有 depends_on 含 data 的测试全部纳入）
```

**关键设计**：
- **保守安全**：依赖传播确保改公共模块不漏测
- **文档/配置不触发**：`.md`、`.gitignore`、`.cnb.yml` 等非源码文件不触发测试
- **增量精准**：只跑受影响测试，不跑全量

## 预期收益

| 场景 | 优化前 | 优化后 |
|------|--------|--------|
| 改 `hybrid/router.py` | 全量 32 个测试 | 只跑 2 个（增量） |
| 改 `data/schema.py` | 全量 32 个测试 | 跑 19 个（依赖传播） |
| 改文档 `README.md` | 全量 32 个测试 | 0 个（非源码不触发） |

## 后续工作

- **T3 FingerprintCache**（`hybrid/cache.py`）：源码指纹 + 缓存命中跳过
- **T4 ParallelExecutor**（`hybrid/parallel.py`）：并行执行器（`-P` 参数）
- **T5 PolicyEngine**（`hybrid/policy.py`）：策略引擎（增量/缓存/并行/全量开关）
- **T6 CostReporter**（`hybrid/cost.py` 扩展）：成本报表扩展

## 兼容性

- `hybrid/v2.0` 升版，v1.0 接口完全保留（向后兼容）
- 与现有 `hybrid/` 模块解耦，通过显式公开接口交互
- 新增文件不修改现有模块内部实现
