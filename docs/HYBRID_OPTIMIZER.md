
## IncrementalSelector（T2）

基于 git diff 的变更感知增量选择器。

### 核心接口

```python
from hybrid.selector import IncrementalSelector
s = IncrementalSelector(root_dir=".")

# git diff 获取变更文件
files = s.changed_files("HEAD~1", "HEAD")

# 变更文件 → 受影响测试（含依赖传播）
selected = s.select(["collab/engine.py"])
# -> ['local-agent/tests/test_collab.sh',
#     'local-agent/tests/test_peer_collab.sh',
#     'local-agent/tests/test_peer_closure.sh']

# 一键增量选择
selected = s.incremental()  # 默认比较 HEAD~1..HEAD

# 工作区未提交变更
selected = s.incremental_workdir()

# 全量兜底
suite = s.full_suite()
```

### 依赖传播防漏测

```
test_collab  covers collab/engine.py
test_peer_collab depends_on test_collab
test_peer_closure depends_on test_peer_collab

变更 collab/engine.py → 运行 [test_collab, test_peer_collab, test_peer_closure]
```

---

## FingerprintCache（T3）

源码指纹缓存，把「某模块代码自上次跑通后没有变化，结果却重新算一遍」的重复劳动消除。

### 核心接口

```python
from hybrid.cache import FingerprintCache, default_cache
c = default_cache

# 计算某测试覆盖源码的指纹（git blob hash 摘要）
fp = c.fingerprint('local-agent/tests/test_engine.sh')   # 'sha1:8503e63'

# 判定是否可命中缓存（源码未变 + 上次 PASS）
hit, fp = c.is_hit('local-agent/tests/test_engine.sh')    # (True, 'sha1:...')

# 写入缓存（执行通过后标记 pass）
c.mark('local-agent/tests/test_engine.sh', {'exit_code':0}, 'pass')

# 批量过滤：返回 (可命中跳过的 hits, 需执行的 misses)
hits, misses = c.filter_hits(['test_engine.sh', 'test_collab.sh'])
```

### 指纹口径（保守可靠）
- 取该测试在 TestRegistry 中 `covers` 的源码文件，用 `git hash-object` 逐文件算 blob hash，
  再 SHA1 摘要这些 hash。
- 源码一变 → 指纹必变 → 缓存失效；指纹不变 → 复用上次 PASS 结果，零 CPU。

### 持久化
- 走 data 层新增 `test_cache` 表（可追溯可回溯）。
- 环境变量 `HYBRID_CACHE=off` 可关闭缓存（强制全量）。

---

## ParallelExecutor（T4）

把 LocalWorker 的顺序执行升级为线程池并行，`-P` 并行度、超时聚合、失败隔离。

### 核心接口

```python
from hybrid.parallel import ParallelExecutor, default_executor
ex = ParallelExecutor(root_dir='.', parallel=4)

# 并行执行（parallel=1 退化为串行）
res = ex.run_parallel(['t1.sh', 't2.sh', ...], parallel=4)
# summary 含 wall_seconds（并行墙钟）/ parallel（实际并行度）
```

### 能力
- **并行度**：`-P` 并行，默认 4，可配置；
- **超时聚合**：单脚本超时不阻塞其他并行脚本；
- **失败隔离**：单脚本失败不影响其他脚本执行；
- **向后兼容**：结构与 LocalWorker.run() 一致，调用方无需改。

---

## PolicyEngine（T5）

把 incremental/cache/parallel/full 各开关的决策规则配置化，根据 CI 上下文决定「跑哪些 + 怎么跑」。

### 核心接口

```python
from hybrid.policy import PolicyEngine, default_policy
p = PolicyEngine()   # 默认每 7 天一次全量回归

d = p.decide(
    changed_files=['collab/engine.py'],   # 增量输入
    selector=selector,                    # T2 选择器
    cache=cache,                          # T3 缓存
    full_suite=lambda: sel.full_suite(),  # 全量清单
    last_full_ts=ts,                      # 上次全量回归时间
)
# d: {mode, tests, cache_hits, parallel, switches, reason}
```

### 决策规则
- **全量回归周期**：默认每 7 天强制一次全量回归（防增量/缓存漏测累积），优先级最高；
- **增量**：`incremental` 开关开 + 有变更 + 选择器 → 只跑受影响测试；
- **缓存**：`cache` 开关开 → 命中跳过的测试剔除出待跑清单；
- **并行**：`parallel` 开关决定并行度（4/1）；
- 各开关可配：环境变量 `HYBRID_INCREMENTAL/CACHE/PARALLEL/FULL` 或 overrides。

---

## CostReporter（T6）

成本报表三合一扩展，量化「增量 + 缓存 + 并行」三路优化收益。

### 核心接口

```python
from hybrid.cost import CostReporter, default_cost_reporter
cr = CostReporter()
rep = cr.report_optimizer(policy, exec_result, baseline_serial_seconds=20.0)
# rep: {incremental, cache, parallel, total}
```

### 报表维度
- **incremental**：本应全量跑 vs 实际只跑受影响，跳过的测试数 + 节省 CPU 核·分钟；
- **cache**：缓存命中跳过的测试数 + 节省 CPU；
- **parallel**：串行 sum → 并行 wall 的加速比（speedup_ratio）；
- **total**：三合一总节省。

---

## CLI `smart` 一键

```bash
# 智能优化一键：增量选择 → 缓存剔除 → 并行执行 → 三合一成本报表
python -m hybrid.cli smart --dry          # 只决策不执行
python -m hybrid.cli smart --root .       # 执行（工作区未提交变更）
python -m hybrid.cli smart --base HEAD~1  # 指定 git 区间
python -m hybrid.cli smart --full         # 强制全量回归
```

---

## 验收对照

| 验收标准 | 实现 |
|---------|------|
| ① 增量感知：改 hybrid/router.py 只跑 hybrid 相关测试 | IncrementalSelector（T2）+ PolicyEngine（T5） |
| ② 缓存命中：同 commit 再跑，未变更模块复用结果零 CPU | FingerprintCache（T3） |
| ③ 并行加速：-P 4 生效，耗时降到 max/4 | ParallelExecutor（T4） |
| ④ 策略可配：incremental/cache/parallel/full 开关 | PolicyEngine（T5） |
| ⑤ 全量回归：默认每 7 天一次强制 | PolicyEngine.full_regression_due |
| ⑥ 成本报表：三合一节省 | CostReporter（T6） |
| ⑦ 向后兼容：hybrid/v1.0 接口可用 | 新增子模块不覆盖旧接口 |
