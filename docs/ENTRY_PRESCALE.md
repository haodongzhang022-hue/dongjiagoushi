# 强制秘书入口 + 规模预设引擎（ENTRY & PRESCALE）

> 本文档记录对 Issue #31 测试环节暴露的**两处机制缺口**的修复，是对既有
> `AGENTS.md`（默认入口协议 / 规模预设规则）的可执行落地与留痕载体。

---

## 背景：测试暴露的两处 🔴 缺口

以本项目 Issue #31 作为真实测试场景（评估本项目即有意义），「架构·测试」核验后发现两处
**机制已落地但没被做成可执行 / 没被真实触发**的短板：

| # | 测试发现 | 机制设计 | 真实执行结果 |
|---|---|---|---|
| 1 | **需求移交跳过了秘书** | 默认从「架构·秘书」进入 | 用户直接 @架构·产品，跳过秘书，未留路由理由 |
| 2 | **规模预设未做成引擎** | 澄清阶段预设 team_size+collab_plan+risk_level | 无独立引擎/测试，Issue#31 全流程无任何预设记录 |

这两处正是"一开始谁移交需求、初始团队规模是否适配"——**流程最前端、最该先被机制锁住的两个点**。

---

## 修复 1：强制秘书入口（不可跳过）

**问题**：`harness` 模板之外，秘书只是"默认建议"，被显式 `@` 即可绕过，未留路由留痕。

**修复**：把「架构·秘书」设为 **rules 固定的强制入口**，并落地引擎护栏：

- `local-agent/scale/profile.py`
  - `SECRETARY_MANDATORY_PROFILES = {default, company, acquisition, support}`：强制秘书入口
  - `SECRETARY_OPTIONAL_PROFILES = {harness}`：harness 内嵌模板因调用方已定角色，允许直入研发
  - `guard_entry(spec_profile, direct_role)`：强制入口护栏，直接 `@` 非秘书角色即返回 `ok=False`（红灯）
- `local-agent/scale/engine.py`
  - `preflight()` / `run_scaled()` 已接入 `guard_entry`，报告含 `entry_guard`
- `local-agent/roles/secretary.py`
  - `SecretaryRole.route_guard(target_role)` → 输出路由留痕卡（`已接管自秘书路由的 X`）
- `local-agent/run.py`
  - `--guard-entry` + `--direct-role`：CLI 可校验是否跳过秘书
- `AGENTS.md`「默认入口协议」已升级为强制入口（不可跳过）

**语义**：默认/公司/获客/客服等模板必须先经秘书接收→翻译→路由留痕；即使显式 `@` 某角色，
被召角色仍须回显『已接管自秘书路由的 X』，不可因显式 `@` 而绕过秘书。

---

## 修复 2：规模预设可执行引擎（prescale）

**问题**：只有 `spec.team_size`（用户/上层 CLI 声明，用户自己喊 2500），不是"秘书/产品澄清
阶段的体量预设"。两者不是一回事，且无独立引擎/测试。

**修复**：新增 `local-agent/scale/prescale.py`，补齐"澄清阶段规模预设"：

| 能力 | 函数 | 说明 |
|---|---|---|
| 规模预设 | `prescale(req, kind, complexity_hint)` | → `{team_size, collab_plan, risk_level, source}` 基准锚点 |
| 复杂度判定 | `_estimate_complexity` | 文本关键词加权 → simple/medium/complex |
| 经验方案库 | `search_pattern(kind, band)` | 命中同体量/同类型历史成功/修正方案即复用；未命中全新规划 |
| 经理增量修正 | `adjust_by_architect(preset, factors)` | 基于预设按架构 scale_factor 增量修正，**不做从零规划** |
| 强制留痕 | `record_prescale` / `prescale_records` / `has_prescale` | "需求进入前必须有预设记录"可被机器核验（红灯判据） |
| 稳定寻址 | `req_key(req, kind)` | 同需求二次预设取回同一结果，不做漂移变更 |

**设计原则**（对齐用户纠偏）：
- **默认单兵**：简单需求默认 1 人 + 低风险，不为了预设而预设（防无效堆砌）；
- 只有复杂度/风险/多视角需求才抬升体量；
- 预设值是**基准锚点**，不是终局——经理按架构做增量修正。

**接入**：`scale/__init__.py` 导出 prescale；`engine.preflight/run_scaled` 集成；`run.py`
新增 `--prescale` / `--complexity` / `--prescale-records`。

---

## 测试

新增 `local-agent/tests/test_prescale_entry.sh`（15 条断言，全绿）：

- 规模预设：复杂度自动判定 / 显式复杂度带 / 基准锚点
- 经验方案库：命中复用 / 未命中全新规划 / 稳定寻址不漂移
- 强制入口：默认必须经秘书（绿灯）/ 显式@产品跳过（红灯）/ harness 放行 / 秘书路由留痕卡
- 引擎集成：preflight / run_scaled 报告含 entry_guard + prescale
- CLI：`--prescale` / `--prescale-records` / `--guard-entry`

已在 `.cnb.yml` 的 test 阶段接入（`bash local-agent/tests/test_prescale_entry.sh`）。

---

## 相关文件

| 文件 | 变更 |
|---|---|
| `local-agent/scale/prescale.py` | **新增**：规模预设引擎 + 经验方案库 + 强制留痕 |
| `local-agent/scale/profile.py` | 新增 `guard_entry` / `is_secretary_mandatory` 强制入口护栏 |
| `local-agent/scale/engine.py` | preflight / run_scaled 集成 entry_guard + prescale |
| `local-agent/scale/__init__.py` | 导出 prescale |
| `local-agent/roles/secretary.py` | 新增 `route_guard` 路由留痕卡 |
| `local-agent/run.py` | 新增 `--prescale` / `--guard-entry` / `--prescale-records` / `--complexity` / `--direct-role` |
| `local-agent/tests/test_prescale_entry.sh` | **新增**：15 条断言 |
| `AGENTS.md` | 默认入口协议升级为强制入口；规模预设标注可执行引擎 |
| `.cnb.yml` | test 阶段接入 prescale-entry 测试 |
