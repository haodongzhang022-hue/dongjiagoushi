# Hybrid 并行执行器（Issue #65 · T4）

## 背景

现有 `LocalWorker.run()` 顺序批量执行测试脚本，32 个测试串行跑耗时长。
`ParallelExecutor` 在保证结果兼容的前提下提供**并行执行**能力。

## 模块：ParallelExecutor（`hybrid/parallel.py`）

### 功能

| 能力 | 说明 |
|------|------|
| 并行执行 | 基于 `ProcessPoolExecutor`，多进程同时跑多个脚本 |
| 超时聚合 | 单个脚本超时统一记录 `exit_code=124` + `status=timeout` |
| 失败隔离 | 单个脚本失败/超时不阻塞其他脚本继续执行 |
| 结果聚合 | 汇总 `pass / fail / timeout / error` 计数 + 总耗时 |
| 结果兼容 | 与 `LocalWorker.run()` 返回结构一致 `{results, summary}` |

### 使用方式

```python
from hybrid.parallel import ParallelExecutor

# 4 进程并行，单脚本超时 120s
ex = ParallelExecutor(max_workers=4, timeout=120)

# 并行执行测试脚本
result = ex.run(["local-agent/tests/test_a.sh", "local-agent/tests/test_b.sh"])
# → {'results': [...], 'summary': {'total': 2, 'pass': 2, 'fail': 0, 'timeout': 0, ...}}

# 兼容 LocalWorker.run_many() 接口
result = ex.run_many(["test_a.sh"], per_script_timeout=60)

# dry_run 演练模式
ex = ParallelExecutor(dry_run=True)
```

### CLI 开关

在 `hybrid.cli` 中通过 `-P/--parallel N` 指定并行度：

```bash
python3 -m hybrid.cli run --parallel 4 --local scripts.txt
```

## 设计要点

- **失败隔离**：ProcessPoolExecutor 天然隔离异常，单个脚本崩溃不影响其他
- **超时聚合**：subprocess timeout 统一捕获，`exit_code=124` 表示超时
- **结果稳定**：按输入顺序排序输出，与 LocalWorker 兼容
- **零依赖**：纯标准库（concurrent.futures），无需额外安装

## 兼容性

- 与 `LocalWorker.run()` 返回结构完全一致，可无缝替换
- `hybrid/v2.0` 升版，v1.0 接口向后兼容
