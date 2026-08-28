# Hybrid 资源路由模块

> 版本：hybrid v0.1 (init)  
> 模块类型：资源调度 / 成本优化  
> 关联 Issue：#57

---

## 一、问题背景

云端 CI（`.cnb.yml`）每次 push 到 `main` 会执行 **37 个 CPU 密集测试脚本**（全部是 bash/python 测试），
这些脚本每个都要加载 Python 环境、初始化数据库、全量跑测试。这导致**云原生构建-CPU 消耗过高**，
远超 token 消耗。

**根因**：纯 CPU 逻辑（测试/脚本/管线）应在本地执行，云端只保留 LLM 强相关操作。

---

## 二、架构设计

```
┌─────────────────────────────────────────────┐
│  本地执行层（零/低成本）                      │
│  HybridResourceRouter                       │
│  ├─ router.py  任务路由决策（local/cloud）   │
│  ├─ worker.py  批量跑测试/脚本/管线          │
│  ├─ sync.py    结果同步回云端留痕            │
│  └─ cost.py    成本监测与报表                │
└─────────────────────────────────────────────┘
                    │
                    ▼ 结果 commit+push
┌─────────────────────────────────────────────┐
│  云端执行层（仅保留 LLM 强相关）              │
│  ├─ knowledge:update  (embedding 向量化)     │
│  ├─ npc:go            (LLM 对话)             │
│  └─ codewiki          (Wiki 生成)            │
└─────────────────────────────────────────────┘
```

### 路由规则

| 类别 | 关键字 | 去向 |
|------|--------|------|
| LLM 强相关 | `knowledge:update` / `npc:go` / `codewiki` / `embedding` | **云端** |
| 纯 CPU | `test` / `bash` / `python` / `script` / `dashboard` | **本地** |
| 未知 | 未命中任何规则 | AUTO（默认本地） |

---

## 三、模块清单

| 文件 | 功能 | 依赖 |
|------|------|------|
| `router.py` | 路由决策器 `HybridResourceRouter` | 无 |
| `worker.py` | 本地执行器 `LocalWorker` | router |
| `sync.py` | 结果同步器 `ResultSyncer` | 无 |
| `cost.py` | 成本监测 `CostMonitor` | router |
| `cli.py` | 统一 CLI 入口 | router/worker/sync/cost |
| `__init__.py` | 模块导出 | 全部 |

---

## 四、使用方法

```bash
# 全量本地执行（测试 + 同步 + 成本）
bash scripts/local-exec.sh

# 只跑测试不推送
bash scripts/local-exec.sh --no-sync

# 快速模式（只跑关键测试）
bash scripts/local-exec.sh --quick

# CLI 方式
python3 local-agent/hybrid/cli.py route "bash tests/test_architect_system.sh"
python3 local-agent/hybrid/cli.py route "knowledge:update"
python3 local-agent/hybrid/cli.py route-ci
python3 local-agent/hybrid/cli.py run-all-tests
python3 local-agent/hybrid/cli.py run-test tests/test_galton.sh
python3 local-agent/hybrid/cli.py cost-report
python3 local-agent/hybrid/cli.py full
```

---

## 五、成本估算

| 指标 | 改造前 | 改造后 | 节省 |
|------|--------|--------|------|
| 云端构建时长 | ~15-30 分钟/次 | ~1-3 分钟/次 | **80-90%** |
| 云端构建-CPU 费用 | 高 | 极低 | **显著降低** |
| 本地执行 | 无 | ~5 分钟/次 | 本地免费 |

---

## 六、云端 CI 最小化

改造后的 `.cnb.yml` 云端流水线：

1. **移除** 37 个 CPU 密集测试脚本执行命令
2. **保留** 3 个 LLM 强相关操作（knowledge:update / npc:go / codewiki）
3. **新增** 结果校验（检查 `.cnb-results/results.json` 存在且 passed >= threshold）

---

## 七、测试

配套测试脚本：`local-agent/tests/test_hybrid_router.sh`

验证点：
- 路由决策正确性（local/cloud/auto 分类）
- 本地执行器批量测试
- 成本估算合理性
- CLI 入口可用性
