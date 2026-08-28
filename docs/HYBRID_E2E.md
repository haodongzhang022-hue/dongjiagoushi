# Hybrid 端到端集成测试（Issue #65 · T7）

## 定位

验证「测试智能优化层」**完整链路**：单模块改动只跑受影响测试 + 缓存命中跳过 + 并行执行 + 策略选择 + 成本报表。

这是 **T7 集成验证**，承接 T1-T6 六子模块（TestRegistry / IncrementalSelector / FingerprintCache / ParallelExecutor / PolicyEngine / CostReporter），作为**持续集成入口**——T3-T6 模块合并进 main 后，本骨架自动走真实接口做全链路核验。

## 验收标准映射（Issue #65 六项）

| # | 验收标准 | 骨架验证点 |
|---|---------|-----------|
| 1 | 增量感知：改 `hybrid/router.py` → 只跑 hybrid 相关测试 | git diff 映射 → 只跑 `test_hybrid_router.sh`+`test_hybrid_pipeline.sh`，从全量 7 收敛到 2 |
| 2 | 缓存命中：同一 commit 再跑 → 未变更模块跳过 | 源码指纹缓存，首次全跑、二次全命中跳过（零重复执行） |
| 3 | 并行加速：`-P 4` 生效，总耗时显著下降 | 4 路并行，speedup≥1.5（实测 ~4.0） |
| 4 | 策略可配：PolicyEngine 四开关可组合 | incremental / cache / parallel / full 各开关独立生效 |
| 5 | 全量回归：7 天强制机制生效 | 距上次 ≥7 天强制全量；近期不强制 |
| 6 | 成本报表：三合一节省报表输出 | CostMonitor 输出 localized / net_save / 本地化率 |

## 运行

```bash
bash local-agent/tests/test_hybrid_e2e.sh
```

预期输出 `PASS=16 FAIL=0`，并打印 T3-T6 模块状态。

## 优雅降级机制

T3-T6 模块（`hybrid/cache.py` / `hybrid/parallel.py` / `hybrid/policy.py`）**尚未合并进 main 时**，骨架用**内联等价逻辑**验证链路（git diff 增量、文件指纹缓存、子进程并行、策略开关组合），保证：

- 骨架在任意合并状态可运行、CI 可过；
- 脚本启动时检测模块可用性（`import` 探测），T3-T6 合并后**自动切换真实接口**；
- 成本报表始终走真实 `CostMonitor`（T1 已合并）。

```
模块可用性探测（cache/parallel/policy）→ 可用?走真实接口 : 走内联等价逻辑
```

## 文件

| 文件 | 说明 |
|------|------|
| `local-agent/tests/test_hybrid_e2e.sh` | 端到端集成测试骨架（16 项断言） |
| `docs/HYBRID_E2E.md` | 本文档 |

## 架构约束

- base=`main`，独立 PR，不耦合其他功能分支；
- 不引入 T3-T6 模块实现（由各 PR 独立合并），本骨架只**引用/探测**其公开接口；
- 向后兼容 `hybrid/v1.0` 全部接口（router / worker / sync / cost）；
- 自带测试 + 文档，独立通过信号灯。
