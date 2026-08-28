# Hybrid 测试智能优化层（Issue #65）

> 在现有 `hybrid/` 模块基础上扩展的**测试智能优化层**：增量感知 + 结果缓存 + 并行执行 + 策略引擎。
> 本 PR 交付 **T3 FingerprintCache**。

## 背景

现有 CI 每次 push 都全量跑 32 个 CPU 密集测试脚本。无论改动哪个模块，全部重跑一遍，造成大量重复劳动。

**核心问题**：
- 无增量感知：只改了 `hybrid/` 模块，`test_collab.sh` 等无关模块也重跑
- 无结果复用：某模块代码无变化，结果却重新算一遍
- 无依赖传播：改公共模块（如 `data/schema.py`），所有依赖它的测试可能被漏测

## T3 模块：FingerprintCache（`hybrid/cache.py`）

### 功能

对「测试脚本 → 覆盖源码文件」计算**内容指纹**，存到 data 层 `test_cache` 表。
当源码文件未变化时（指纹一致），对应测试结果可直接复用（**缓存命中跳过**）。

### 能力

| 方法 | 说明 |
|------|------|
| `fingerprint(path)` | 计算单个文件/目录的 SHA-256 内容指纹 |
| `compute_fingerprint(script)` | 计算某测试覆盖全部源码的**组合指纹** |
| `is_hit(script)` | 判断某测试是否命中缓存（指纹与上次一致） |
| `hit_tests(scripts)` | 批量判定一组测试的缓存命中 |
| `need_run(scripts)` | 返回需要运行的测试列表（未命中缓存） |
| `record(script, result)` | 记录一次测试执行（指纹 + 结果快照） |
| `clear(script)` | 清空缓存（全量回归前置） |
| `stats()` | 缓存统计（总记录/命中率） |

### 数据层

新增 `test_cache` 表（`local-agent/data/schema.py` #33）：

```sql
CREATE TABLE IF NOT EXISTS test_cache (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    test_script   TEXT NOT NULL UNIQUE,    -- 测试脚本名（唯一）
    fingerprint   TEXT DEFAULT '',          -- 覆盖源码组合指纹（SHA-256）
    result        TEXT DEFAULT '{}',        -- 最近一次运行结果快照（JSON）
    ts            TEXT                      -- 记录时间戳
)
```

### 使用方式

```python
from hybrid.cache import FingerprintCache, default_cache

cache = FingerprintCache()

# 判定某测试是否命中缓存
result = cache.is_hit("test_hybrid_router.sh")
# → {'hit': True, 'fingerprint': 'abc...', 'last_fingerprint': 'abc...'}

# 批量筛选需要运行的测试
need = cache.need_run(["test_hybrid_router.sh", "test_collab.sh"])

# 记录一次测试执行结果
cache.record("test_hybrid_router.sh", {"exit_code": 0, "duration": 2.5})

# 全量回归前置清空
cache.clear()
```

### 设计要点

- **纯逻辑 + 数据层**：指纹计算纯 Python，缓存落 `data` 层 `test_cache` 表；
- **数据层不可用时降级**：走内存 dict 兜底，不吞异常也不阻断流程；
- **解耦**：不 import registry/selector 等运行时模块，通过 `set_covers_provider()`
  注入 TestRegistry 接口（T1 就绪后自动升级）；
- **组合指纹**：把每个覆盖文件/目录的指纹排序拼接后再哈希，单一指纹代表整个
  测试的源码依赖状态。

## 兼容性

- `hybrid/v2.0` 升版，v1.0 接口完全保留（向后兼容）
- 与现有 `hybrid/` 模块解耦，通过显式公开接口交互
- 新增文件不修改现有模块内部实现

## 后续工作

- **T4 ParallelExecutor**（`hybrid/parallel.py`）：并行执行器（`-P` 参数）
- **T5 PolicyEngine**（`hybrid/policy.py`）：策略引擎（增量/缓存/并行/全量开关）
- **T6 CostReporter**（`hybrid/cost.py` 扩展）：成本报表扩展
