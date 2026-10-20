# 变更范围感知机制 · 交接索引文档

> 仓库：dongdongxiaozu/dongjiagoushi（架构师体系）
> 用途：供 dongdongxiaozu/youxikaifaxilieagent#54 参考适配
> 作者：CodeBuddy · 2026-08-28

---

## 一、背景

`youxikaifaxilieagent#54` 暴露了云原生 CI 的 CPU 过度消耗问题：
- 每次 PR 推送全量跑 50 个测试脚本（含 `test_all_modules.sh` 重复跑 17 个模块）
- issue.open / PR 合并后无条件拉起全部部门 NPC stage
- 评审→修复闭环可能无限循环烧 CPU

我们仓库 `dongjiagoushi` 经过自查，CPU 消耗占比较低（对面占 88%），
但同源问题存在弱化版：`main.push` 全量串行跑 35 个测试脚本。
已通过 **Issue #57「云原生构建-CPU 本地化」** + **Issue #57 T2「变更感知增量选择器」**
解决。以下文件与机制可供参考适配。

---

## 二、核心机制：变更范围感知（Change-Aware Test Selection）

### 2.1 IncrementalSelector · 变更感知增量选择器

**文件**：`local-agent/hybrid/selector.py`
**作用**：根据 git diff 变更的文件，只选择受影响的测试脚本运行，
避免全量跑 43 个 CPU 密集测试。

**核心能力**：
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

# 一键增量选择（默认 HEAD~1..HEAD）
selected = s.incremental()

# 工作区未提交变更
selected = s.incremental_workdir()

# 全量兜底
suite = s.full_suite()
```

**依赖传播防漏测**：
```
test_collab  covers collab/engine.py
test_peer_collab depends_on test_collab
test_peer_closure depends_on test_peer_collab

变更 collab/engine.py → 运行 [test_collab, test_peer_collab, test_peer_closure]
```

### 2.2 TestRegistry · 集中测试注册表

**文件**：`local-agent/hybrid/registry.json` + `local-agent/hybrid/registry.py`
**作用**：集中维护「每个测试覆盖哪些源码文件」「测试间依赖关系」
「CPU 成本估算」「执行时长估算」。

**注册表条目示例**：
```json
{
  "name": "test_collab",
  "covers": ["collab/engine.py", "collab/peer.py", "data/admin.py"],
  "depends_on": [],
  "cpu_cost_est": 3.5,
  "time_est": 9.0,
  "kind": "cpu-dense"
}
```

**核心接口**：
```python
from hybrid.registry import (
    all_tests, get, covers, dependencies,
    find_by_source, find_many_by_source,
    impact_closure, affected_tests, summary,
)
```

### 2.2.1 覆盖漂移与"假绿"兜底（Issue #166）

`select()` 只认 registry 里登记过的 `covers`。一旦变更落在**没登记的模块**上（新增模块、
纯文档、新脚本），`select()` 返回空，CI 以前直接回落"只跑核心冒烟"——等于该模块
**一个测试都没跑却显示通过**。Issue #166 就踩到这个：`comment_stream` 是新增模块，
没登记 registry，CI 跳过了它的信号灯。

两道防线：

1. **登记齐全（首要）**：新增模块必须把对应测试登记进 `hybrid/registry.json`
   （含 `covers` / `kind`）。`kind=light` 的脚本（如 dsh 装载验证）按设计留云端，
   不进本地执行清单。当前 registry 已与磁盘上的 `test_*.sh` 对齐，缺失为 0。
2. **兜底不再假绿**：`IncrementalSelector.suggest_tests(changed)` 按命名约定反推候选
   （`local-agent/comment_stream/reader.py` → `local-agent/tests/test_comment_stream.sh`），
   只返回磁盘上真实存在的脚本；推断不出才回落核心冒烟。

```python
selected = s.select(changed) or s.suggest_tests(changed) or ['tests/test_architect_system.sh']
```

### 2.3 变更感知的接入方式（云原生 CI）

**在 `.cnb.yml` 中**，`pull_request` 触发时只跑受影响的测试：
```yaml
main:
  pull_request:
    - name: change aware test
      stages:
        - name: test
          script: |
            python3 - <<'PY'
            import sys; sys.path.insert(0, 'local-agent')
            from hybrid.selector import IncrementalSelector
            s = IncrementalSelector()
            selected = s.incremental()  # 变更感知增量选择
            ...
            PY
```

**`main.push`（合并后）保留全量回归兜底**，保证质量。

---

## 三、核心机制：云原生构建-CPU 本地化

### 3.1 HybridResourceRouter · 资源路由

**文件**：`local-agent/hybrid/router.py`
**作用**：把纯 CPU 逻辑（37 个测试脚本）与 LLM 强相关操作（knowledge/codewiki/npc）
区分开来，CPU 密集测试**本地执行**，云端 CI 只保留轻量校验。

**路由判定规则**：
| 优先级 | 判定 | 落地 |
|--------|------|------|
| 1 | 命中 `CLOUD_HINTS`（llm/knowledge/codewiki/embedding…） | **cloud** |
| 2 | 命中 `LOCAL_HINTS`（local/cpu/unit/test/benchmark…） | **local** |
| 3 | 兜底 | 默认 cloud |

### 3.2 LocalWorker / ResultSync / CostMonitor

- `local-agent/hybrid/worker.py` — 本地批量测试执行器（超时保护/dry-run）
- `local-agent/hybrid/sync.py` — 结果同步留痕（数据层 archives/messages）
- `local-agent/hybrid/cost.py` — 成本监测与报表（net_save/rollback/ratio）

### 3.3 本地执行入口

**文件**：`scripts/local-exec.sh`
```bash
bash scripts/local-exec.sh                # dry-run 演练
bash scripts/local-exec.sh --real         # 真实执行
bash scripts/local-exec.sh --only cost    # 只看成本报表
```

---

## 四、相关机制参考（防「无进度互传」「无关 agent 凑热闹」）

| 机制 | 文档 | 作用 |
|------|------|------|
| **监控哨兵** | `docs/SENTINEL.md` | 量化到北极星的收敛监控，判定停滞/横跳/重复错误 |
| **分发四层深度** | `docs/DISPATCH_DEPTH.md` | L1 声明→L4 开工交付，无接单回执即派发断裂 |
| **七层协作深度** | `docs/DEPTH_MODEL.md` | 路由真实唤醒，校验 [接单] 回执 |
| **标签+进度自动化** | `docs/LABEL_AUTOMATION.md` | 事件驱动自动打标，防没干活 |
| **路由决策** | `local-agent/hybrid/router.py` | 只路由到确有工作包的部门 |
| **解耦式模块开发** | `AGENTS.md` | 每模块独立 PR，base 为 main，防耦合 |

---

## 五、适配建议（针对 youxikaifaxilieagent#54）

1. **问题 1（测试信号灯全量 50 脚本）**：
   → 引入 `IncrementalSelector` + `TestRegistry`，PR 推送时只跑受影响的测试
2. **问题 2（评审闭环无限循环烧 CPU）**：
   → 用 `hybrid.router` 路由判定，把 CPU 密集测试本地化；
   → 加变更范围感知，修复循环只在受影响的模块上跑
3. **问题 3/4（issue.open / merged 全拉起部门）**：
   → 用 `routing.py`（你们已有）做规则匹配 + `ifModify` 流水线级拦截
4. **问题 5（NPC 重复/重叠检查）**：
   → 合并只读检查类 NPC，用 `ifModify` 只触发变更相关模块
5. **问题 6（crontab 每日空跑）**：
   → 用 `if` 条件判断「是否有待确认 Issue」再触发

---

## 六、文件索引（跨仓库直接拷贝参考）

| 文件 | 作用 |
|------|------|
| `local-agent/hybrid/selector.py` | ⭐ 变更感知增量选择器（核心） |
| `local-agent/hybrid/registry.json` | ⭐ 集中测试注册表（43 个测试的覆盖关系） |
| `local-agent/hybrid/registry.py` | 注册表程序化接口 |
| `local-agent/hybrid/router.py` | ⭐ 资源路由（local/cloud 判定） |
| `local-agent/hybrid/worker.py` | 本地批量测试执行器 |
| `local-agent/hybrid/sync.py` | 结果同步留痕 |
| `local-agent/hybrid/cost.py` | 成本监测报表 |
| `local-agent/hybrid/cli.py` | CLI 入口 |
| `scripts/local-exec.sh` | 本地执行统一入口 |
| `docs/HYBRID_OPTIMIZER.md` | ⭐ IncrementalSelector 使用文档 |
| `docs/HYBRID_RESOURCE.md` | Hybrid 资源路由设计文档 |

---

> 以上机制已在 `dongjiagoushi` 仓库 main 分支落地并通过测试，
> 可供 `youxikaifaxilieagent` 参考适配。欢迎架构师帮忙做架构升级适配。
