# Hybrid 并行执行器（Issue #65 · T4）

## 背景

现有 `LocalWorker.run()` 顺序批量执行测试脚本，串行跑耗时长。
`ParallelExecutor`（继承 `LocalWorker`）在保证结果兼容的前提下，把「顺序 for」升级为**线程池并行**。

## 模块：ParallelExecutor（`hybrid/parallel.py`）

### 功能

| 能力 | 说明 |
|------|------|
| 并行执行 | 基于 `concurrent.futures.ThreadPoolExecutor`，多脚本同时执行 |
| 串行退化 | `parallel=1` 或单脚本时退化为串行（复用 `LocalWorker.run`） |
| 超时聚合 | 单脚本超时统一记录 `exit_code=124`，不阻塞其他脚本 |
| 失败隔离 | 单脚本失败/超时不中断其他脚本（`as_completed` 谁先完成谁先收） |
| 结果聚合 | 汇总 `pass / fail` 计数 + `total_duration / wall_seconds / parallel` |
| 结果兼容 | 与 `LocalWorker.run()` 返回结构一致 `{results, summary}`，按输入顺序稳定输出 |

### 使用方式

```python
from hybrid.parallel import ParallelExecutor

# 4 路并行，单脚本超时 300s（默认）
ex = ParallelExecutor(timeout=300, parallel=4)

# 并行批量执行（返回结构与 LocalWorker.run 一致）
result = ex.run_parallel(["local-agent/tests/test_a.sh", "local-agent/tests/test_b.sh"], parallel=4)
# → {'results': [...], 'summary': {'total': 2, 'pass': 2, 'fail': 0, 'total_duration': ..., 'wall_seconds': ..., 'parallel': 4}}

# 兼容 LocalWorker 接口：run() 默认走实例并行度
result = ex.run(["local-agent/tests/test_a.sh"])   # parallel=self.parallel

# 串行退化
result = ex.run_parallel(scripts, parallel=1)

# dry_run 演练模式
ex = ParallelExecutor(dry_run=True)
```

便捷单例 `default_executor`（默认 4 路并行）：

```python
from hybrid import default_executor, ParallelExecutor
```

### CLI 开关

`hybrid.cli` 已接入并行：`smart` 决策输出 `parallel` 开关，`--parallel` 控制并行度：

```bash
python3 -m hybrid.cli smart --dry
python3 -m hybrid.cli smart --parallel 4
```

## 设计要点

- **复用 LocalWorker**：继承 `LocalWorker`，复用 `run_one()` 的单脚本执行能力（含超时/失败兜底），仅把「顺序 for」升级为「线程池并行」，产出结构一致
- **失败隔离**：`as_completed` 谁先完成先收谁，单脚本失败不互相阻塞
- **超时聚合**：`run_one` 中 subprocess timeout 统一捕获，`exit_code=124` 表示超时
- **结果稳定**：按输入顺序排序输出，与 LocalWorker 兼容
- **墙钟耗时**：`wall_seconds` 是并行关键指标（并行墙钟耗时），`parallel` 记录实际并行度
- **零额外依赖**：纯标准库（concurrent.futures），无需额外安装

## 兼容性

- 与 `LocalWorker.run()` 返回结构完全一致，可无缝替换 / 向后兼容
- `default_executor` 便捷单例，供 `hybrid.cli` 等调用方直接使用
- `hybrid/v2.1` 升版，v1.0 接口向后兼容
