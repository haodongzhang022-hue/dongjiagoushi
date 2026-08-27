# 融合路由接线层（Router · 把融合引擎接入真实执行链路）

> 本文档是 Issue #41「打通架构意图→真实执行断点」的落地留痕。
> 目的：`orchestrator.run_pipeline` 不再硬编码走 team.yaml 的 dag，
> 而是按 `fusion.route()` 选出的拓扑（agile/dag/prefix/scatter/hybrid）动态执行。

---

## 背景 · 要解决的断点

现有能力已经齐备，但**脱节**：

| 已建产物 | 状态 | 是否接入执行 |
|----------|------|-------------|
| `fusion.py` 融合路由规则引擎（按任务规模选拓扑 + 四套方案） | ✅ 完善 | ❌ 未接入 |
| `slim.py` 复杂度递进式精简体系（角色子集/占比） | ✅ 完善 | ❌ 未接入 |
| `topologies.py` agile/dag/prefix/scatter/hybrid 节点定义 | ✅ 完善 | ⚠️ 仅 benchmark 可跑 |
| `prescale.py` 规模预设 | ✅ 完善 | ✅ 已接入 run_pipeline |

**断点**：`orchestrator.run_pipeline()` 里硬编码只走 `team.yaml` 的 `dag` 节点，
从不 consult `fusion.route()`。也就是说——「小任务该走敏捷(3角色)、大任务该走完整体系」
的架构意图，只停留在演示，实际跑起来全走 dag。

**本模块就是打通这个断点的接线层**：把「需求 → 规模评估 → 拓扑选择 → 可执行节点集」
串成一条 API，供 `run_pipeline` 在启动时按规模选择并执行对应拓扑，形成
「规模→拓扑→执行」闭环。

---

## 核心机制（一层薄的接线，不重造引擎）

```
用户诉求
   │  run.py --pipeline（默认走融合路由）
   ▼
┌─────────────────────────────────────────────┐
│ router.route_pipeline(req)                   │  ★ 新增接线层
│   ① 规模信号：显式 > preset > 文本估算        │
│   ② fusion.route() → 选拓扑                  │
│   ③ topologies.get_topology() → 可执行节点集   │
└────────────────────┬────────────────────────┘
                     ▼
   run_pipeline 用所选拓扑节点构建 DagEngine 执行
   （agile 4 节点 / dag 11 节点 / prefix 17 节点 / scatter 15 节点 …）
```

**关键点**：
- **薄**：不重造引擎，复用 `fusion` 的选路规则 + `topologies` 的节点定义；
- **闭环**：规模信号（复杂度/子任务/并发）→ 选拓扑 → 拿到可执行节点 → 真实跑起来；
- **留痕**：`report["fusion"]` 记录 selected/tier/system/reason/node_count/estimated；
- **回退**：`--no-fusion` 或路由异常时回退 team.yaml 老 dag，行为不变。

---

## 接口

```python
from topology import router

# 主入口：需求 → 可执行拓扑节点集
r = router.route_pipeline(
    req="帮我改一下登录接口的 bug",
    preset=None,            # prescale 产物（可含 complexity_hint/subtasks）
    complexity=None,        # 显式复杂度分（0~10）
    subtasks=None,          # 显式子任务数
    concurrency=None,       # 显式并发量
    is_scattered=None,      # 是否零散
    force=None,             # 显式指定拓扑 id（绕过规模评估）
    available=None,         # 可用拓扑子集
)
# r.selected / r.tier / r.system / r.reason / r.nodes / r.plan / r.slim / r.signals

# 按档位直接路由（不依赖文本估算，供测试/单测）
router.route_for_tier("micro")     # → agile / 4 节点
router.route_for_tier("huge")      # → prefix / 17 节点

# 二级信息：各档位路由到的拓扑 + 节点数
router.overview()
```

### 规模信号估算（显式未给出时）

| 信号 | 方法 | 说明 |
|------|------|------|
| `complexity` | `estimate_complexity(req)` | 强架构词提高 / 弱词降低 / 文本长度 |
| `subtasks` | `estimate_subtasks(req)` | 显式编号条目 → 分隔条目 → 长度 |
| `concurrency` | `estimate_concurrency(req)` | 含"2500/并发/并行"→ 15，否则 1 |

---

## CLI 用法

```bash
# 默认走融合路由（按需求规模自动选拓扑执行）
python3 local-agent/run.py --pipeline full --req "帮我改一下登录接口的 bug"

# 回退老行为：硬编码 team.yaml dag（不 consult 融合路由）
python3 local-agent/run.py --pipeline full --req "..." --no-fusion

# 显式指定拓扑（绕过规模评估）
python3 local-agent/run.py --pipeline full --req "..." --topo prefix

# 显式给规模信号（覆盖文本估算）
python3 local-agent/run.py --pipeline full --req "..." --complexity 8 --subtasks 30

# 直接看路由结果（不执行）
python3 local-agent/topology/router.py --route --req "大型系统" [--force prefix]
python3 local-agent/topology/router.py --overview
```

---

## 实测效果（沙盒 · cli_fallback 后端）

| 需求 | 规模 | 承接体系 | 拓扑 | 节点数 |
|------|------|----------|------|--------|
| "帮我改一下登录接口的 bug" | micro | agile | `agile` | 4 |
| 低复杂度小需求 | small | agile | `agile` | 4 |
| 中等系统 | medium | architected | `dag` | 11 |
| 高复杂度/零散并发 | large | company | `scatter` | 15 |
| "2500并发大型分布式系统" | huge | full | `prefix` | 17 |

> 注意：`large` 档若 `concurrency>10` 且 `subtasks>5` 会触发散沙信号 → 走 `scatter`（既有 fusion 设计）。

---

## 验收标准

1. `--pipeline --req "单点修改X"` 实际跑 **agile（4 节点）**，不再硬编码 11 节点 dag；
2. `--pipeline --req "大型系统"` 实际跑 **prefix（17 节点）**；
3. `--no-fusion` 与老行为一致（team.yaml 11 节点 dag）；
4. `--topo scatter` 显式指定 scatter（绕过规模评估）；
5. `report["fusion"]` 含 selected/tier/system/reason/node_count/estimated 留痕。

---

## 索引

| 产物 | 位置 |
|------|------|
| 接线层 | `local-agent/topology/router.py` |
| 融合规则引擎 | `local-agent/topology/fusion.py` |
| 拓扑节点定义 | `local-agent/topology/topologies.py` |
| 精简体系 | `local-agent/topology/slim.py` |
| 执行链路接入 | `local-agent/orchestrator.py`（`run_pipeline` 增 `use_fusion`） |
| CLI 入口 | `local-agent/run.py`（`--no-fusion` / `--topo` / `--subtasks`） |
| 单测 | `local-agent/tests/test_router_integration.sh` |
