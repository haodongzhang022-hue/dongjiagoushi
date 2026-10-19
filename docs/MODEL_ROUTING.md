# 模型路由（model-routing · 统一配置文件 + 多级降级链 + 真实接线）

> **唯一配置文件**：`local-agent/model_routing/models.yml`（改模型只改这一处）
> **读配置代码层**：`local-agent/model_routing/spec.py`
> **演进线**：Issue #147 · module model-routing **v0.3.0-update**
> **触发词**：模型/主模型/备用模型/降级/渠道不通/统一配置/角色指定/v4.1 flash/codebuddy/glm/接线/按角色

## 一、用户诉求（Issue #147）

1. **模型指定收敛到一个配置文件统一管理**——以后不用去检查哪里定义，改模型只改一处，不跨多个文件；
2. **不指定就默认通用**——未单独列出的角色一律走通用默认；
3. **允许对某个角色单独指定**——按角色名覆盖（**默认不启用定制，全部走默认**）；
4. **配置必须真正生效、且非单次有效**——配了就要在执行链路生效；后来改配置也要生效，
   不能"改了没实现"，否则对齐反而制造分歧；
5. **多级备选**——一级不完就往下走；
6. **加入索引介绍**——登记进 `docs/CAPABILITY_INDEX.md`。

配套的模型策略（渠道链，按优先级 1→N）：

| 档位 | 模型 | 说明 |
|---|---|---|
| ① 一选主通道 | `deepseek-v4.1-flash` | 首选 |
| ② 二选备用 | `codebuddy` | 主渠道不通时启用 |
| ③ 三选备用 | `glm-5.3-flash` | 前两档均不通时启用 |

## 二、唯一配置文件（models.yml）

```yaml
# ① 通用默认（不指定角色时用这个）
default:
  chain:                       # 渠道链，按优先级 1→N；主通道不通自动降级下一档
    - deepseek-v4.1-flash
    - codebuddy
    - glm-5.3-flash
  # 兼容字段（由 chain 派生；改模型建议只改上面的 chain）
  primary: deepseek-v4.1-flash
  fallback: glm-5.3-flash

# ② 按角色单独指定（可选；默认不启用，未列出的角色自动继承 default）
roles: {}
#    示例（取消注释即生效，无需改代码）：
#      "架构·评审": { chain: [glm-5.3-flash, deepseek-v4.1-flash] }

# ③ 渠道不通判定信号（触发降级）
unavailable_signals: [unavailable, timeout, connection_error, rate_limit, "429", "503", ...]
```

**解析顺序（确定性）**：`roles[角色]` → `default` → 内置兜底常量（配置缺失时不崩）。

- 角色**未在 roles 中列出** → 继承 `default`（「不指定就默认通用」）；
- 角色**在 roles 中列出** → 覆盖：写 `chain` 整链覆盖；写 `primary/fallback` 子链则**头部覆盖、default 补全尾部**（不缩短降级链）；
- 支持 `MODEL_ROUTING_CONFIG` 环境变量指向自定义配置文件（多环境部署用）。

## 三、为什么需要独立模块 + 统一配置

此前模型只在 `.cnb.yml` 一处写死 `deepseek-v4-flash`（注释称"用户指定 v4 flash"，实为
**未指定到 4.1**），且**没有主/备降级机制**——主渠道不通即整体失败。本模块统一收敛：

| 层 | 职责 |
|---|---|
| `models.yml` | 渠道链 + 角色覆盖 + 降级信号（**唯一事实源/唯一配置文件**）|
| `spec.py` | 加载配置 + 解析（default / role 覆盖）+ 稳定接口（**不硬编码模型 ID**；**每次解析实时读文件**）|
| `engine.py` | 多级降级路由 + 留痕（确定性逻辑，非 LLM 判断），支持 `role=` 按角色解析 + `call_with_chain` 多后端分派 |
| `ability.py` | `ModelRoutingAbility`（全员可调用）|
| `cli.py` | MCP 管线（`config`/`models`/`chain`/`overview`/`dryrun`）|

## 四、降级规则（确定性）

1. 按解析出的渠道链取**第一档**调用；
2. 该档返回 **不可用 / 超时 / 限流 / 5xx**（`unavailable_signals`）→ **自动降级下一档**；
3. 逐档降级直到成功；**全链耗尽** → **显式失败** `all_channels_unavailable`，**不静默、不假装成功**；
4. 每次路由决策写 `model_routing_trace.jsonl`，供监控俯瞰。

## 五、接线点（★本版核心：配置真正生效）

> 用户明确：**配了就要生效，不生效等于白做**。本版把「配置文件的模型链」真正接进执行链路。

| 接线点 | 改动 |
|---|---|
| **`roles/base.py run()`** | 把 `role=self.name` 传进 `llm.call(...)`（用签名探测，不吞异常）——**角色名首次贯通调用链** |
| **`llm/base.py` `call()`** | 签名加 `role=None`（统一接口）|
| **`llm/openai_compat.py` `call()`** | 每次调用按 `role` 从唯一配置解析渠道链，取首档；失败**逐档降级**（`call_with_chain`）；全挂显式抛错；显式 `LOCAL_AGENT_MODEL` 时尊重单模型 |
| **`llm/cli_fallback.py` `call()`** | 兼容 `role`（占位输出带角色名）|
| **`.cnb.yml` `npc:go`** | `model:` 为渠道链首档 `deepseek-v4.1-flash`（npc:go 只接受单 model 字段；多档降级由后端运行时接管）|

**非单次有效**：`spec` 每次解析都**重新读取** `models.yml`（不缓存死值）——
改配置文件后无需重启/重装即生效；也可用 `MODEL_ROUTING_CONFIG` 指向别处。

## 六、验证

```bash
bash local-agent/tests/test_model_routing.sh          # 12 组信号灯（含接线核验）
# 仓库根目录运行 CLI（加 PYTHONPATH，避免 ModuleNotFoundError）：
PYTHONPATH=local-agent python3 -m model_routing.cli config       # 唯一配置文件路径 + 生效内容
PYTHONPATH=local-agent python3 -m model_routing.cli chain        # 通用默认渠道链
PYTHONPATH=local-agent python3 -m model_routing.cli chain 架构·开发  # 某角色渠道链（未列出 → 默认）
PYTHONPATH=local-agent python3 -m model_routing.cli dryrun       # 本地演练：主通道挂→逐档降级
```

> 也可 `cd local-agent` 后直接 `python3 -m model_routing.cli ...`。

## 七、边界说明

- 平台侧（NPC 选择器 / 云端 Agent 设置）的模型选择**仓库管不到**；本模块覆盖
  ① 仓库内一切模型默认值 ② `npc:go` 兜底路径 ③ 本地 harness 后端（角色名已真实贯通）。
- 模型 ID 是否被平台识别的最终解释权在平台；若平台不接受某个 ID，
  **改 `models.yml` 一处即可全仓生效**（单点收敛，不散改）。
- `codebuddy` / `glm-5.3-flash` 作为备用档，走同一 OpenAI 兼容端点（网关侧路由到对应模型）；
  若网关不支持某档模型名，该档调用失败即自动降级下一档，行为仍正确。

## 八、模型 ID 纪律（Issue #182）

- **不臆造版本后缀**：本仓规范里的模型 ID 只有 `deepseek-v4.1-flash` 这一个写法，
  没有 `1017` / 日期码之类的版本标识。`npc:go` 的 `model` 只认组织「可选模型列表」里的
  **精确 ID**，写错即整 stage `error`（#177 的静默失效正是 `deepseek-v4-flash` 不在列表）。
  平台若确实提供带版本号的 ID，以平台选择器显示为准，改 `models.yml` 一处 + `.cnb.yml` 一行同步。
- **模型 ≠ 速度**：`npc:go` 的 `model` 只决定「云端这条执行体用哪个模型」，
  **不决定 tps / 生成速度**，也不决定单次执行要写多少 token。以「某角色只有 65 tps」
  为由改模型，是按错的地方下药：速度感受主要由**单轮上下文规模**（AGENTS.md + skill +
  角色 prompt + Issue 全量评论）与**工具步数**决定——上下文越长、步数越多，单轮耗时越久，
  摊出来的 tps 越低。
- **按角色调优的正确姿势**：先量（`model_routing_trace.jsonl` / 执行日志的实际 token 与耗时），
  再决定是减上下文（读材料只读必要段、评论流显式分页）、减步数，还是真换模型。
