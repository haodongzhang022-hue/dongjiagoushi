# 开发增强配比（Dev-Ratio · Issue #74）

> 本文档记录「开发才是真正推进度的核心，辅助多则浪费」的深化结构升级方案落地留痕。

---

## 背景 · 用户诉求

用户（山东予路 张浩东）在 Issue #74 指出当前协作结构的关键失衡：

> "把一套4个的当一个开发小组……开发才是里面真正持续推进度的，不然进度没多少，
>  辅助很多就浪费了……研究是否调整比例，一套循环里面2个开发，继续研究深化结构的升级。"

**痛点**：一套协作循环中，辅助角色（秘书/产品/总师/经理/评审/测试/对齐/找工具）包围开发，
而**开发才是真正持续推进度的实干主力**——辅助过多则浪费、进度被拖慢。

---

## 方案 · 开发增强配比机制

### 核心机制（3 个落地件）

| 落地件 | 位置 | 说明 |
|--------|------|------|
| **`devs_per_team`（每小组开发数）** | `local-agent/fractal.py` | 每个分形小组配 N 个开发并行实现，**默认 2 = "一套循环 2 个开发"** |
| **`dev_ratio()`（开发密度量化）** | `local-agent/fractal.py` | 量化小组内开发占比，辅助过多时直观暴露浪费 |
| **`dev_enhanced`（开发增强拓扑）** | `local-agent/topology/topologies.py` | 产品→总师→小组长→2开发→评审→测试→交付，8 节点，供 router 显式选用 |

### 小组内结构深化（一套4个 → 一个开发小组）

```
一个开发小组（Dev-Enhanced Team）
  ┌─────────────────────────────────────┐
  │  架构·小组长  拆解子任务 + 整合交付     │   ← 只做拆解/整合，不占开发名额
  │  架构·开发 A  实现/自测（第 1 个）     │   ← 实干主力
  │  架构·开发 B  实现/自测（第 2 个）     │   ← 实干主力（一套循环 2 个开发）
  └─────────────────────────────────────┘
  辅助质量闸门（在小组外，不挤占开发名额）：
    架构·评审 → 五维评审/复评
    架构·测试 → 测试矩阵/信号灯
```

**关键点**：
- **开发是实干主力**：推进度靠开发，辅助只做必要质量兜底，不堆角色。
- **辅助精简**：前端只留产品（澄清）+ 总师（把关），去掉秘书/经理/对齐/找工具等冗余辅助。
- **开发密度可量化**：`dev_ratio()` = 开发数 / (开发数 + 小组长数)，默认 67%（过半），
  若辅助角色混进小组内会直接拉低该比例，暴露浪费。

---

## 落地改动

### 1. `local-agent/fractal.py`
- 新增 `DEFAULT_DEVS_PER_TEAM = 2`（一套循环 2 个开发）。
- `build_fractal_plan(..., devs_per_team=2)`：每个小组携带 `devs` 开发实例列表。
- 新增 `dev_ratio(plan)`：量化开发密度。
- `describe_plan` 输出体现"每小组 N 个开发 + 开发密度"。

### 2. `local-agent/topology/topologies.py`
- 新增 `DEV_ENHANCED_NODES`（8 节点开发增强拓扑）。
- 注册 `dev_enhanced` 到 `TOPOLOGIES`（`dev_ratio: 2`、`dev_enhanced: True`）。

### 3. `local-agent/team.yaml`
- develop 节点 fractal 配置增加 `devs_per_team: 2`。

### 4. `local-agent/orchestrator.py`
- `build_fractal_plan` 传入 `devs_per_team`。
- `_fractal_develop` 每个小组 cohort size 用 `devs_per_team`（恒定为 2，不按任务数膨胀）。

---

## 验证

```bash
bash local-agent/tests/test_dev_enhanced.sh   # Issue #74 专项测试（5 项全绿）
bash local-agent/tests/test_local_agent.sh    # 回归（分形兼容旧调用）
bash local-agent/tests/test_router_integration.sh
bash local-agent/tests/test_topology_fusion.sh
bash local-agent/tests/test_topology_slim.sh
```

实测：分形 10 任务 → 3 小组，每小组 2 开发，开发密度 67%。

---

## 使用方法

```bash
# 显式选用开发增强拓扑（一套循环 2 个开发）
python3 local-agent/run.py --pipeline full --req "..." --topo dev_enhanced

# 看分形计划（含每小组开发数与开发密度）
python3 local-agent/run.py --pipeline full --req "..."   # DAG 开发分形自动带 devs_per_team=2
```
