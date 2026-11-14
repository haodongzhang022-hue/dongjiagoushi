# 模型路由（model-routing · 统一配置文件 + 多级降级链 + 真实接线）

> **唯一配置文件**：`local-agent/model_routing/models.yml`（改模型只改这一处）
> **读配置代码层**：`local-agent/model_routing/spec.py`
> **演进线**：Issue #147 · module model-routing **v0.3.0-update** → **v0.3.0-fix（Issue #182 · 角色逐个指定）** → **v0.3.1-tier（Issue #199 · 快档档序落定 + 兜底归 glm）**
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
| ① 快档第一优先 | `deepseek-v4.1-flash` | 主通道（人类 2026-10-20 Issue #199 定档序） |
| ② 快档第二优先 | `minimax-3.1-flash` | 一档不通时启用 |
| ③ @CodeBuddy 通道 | `codebuddy` | 前两档均不通时启用 |
| ④ 快档第三优先 / 兜底 | `glm-5.3-flash` | 前三档均不通时启用；同时是 `last_resort_model` |

> **档序来源**：Issue #199 人类拍板 ——「第一优先 deepseek v4.1 flash，第二 minimax 3.1 flash，
> 第三 glm 5.3 flash」。兜底档随之由 `claude-3-5-sonnet`（AI 代选）改为 `glm-5.3-flash`。

## 二、唯一配置文件（models.yml）

```yaml
# ① 通用默认（不指定角色时用这个）
default:
  chain: &default_chain        # 渠道链，按优先级 1→N；主通道不通自动降级下一档
    - deepseek-v4.1-flash
    - minimax-3.1-flash
    - codebuddy
    - glm-5.3-flash
last_resort_model: glm-5.3-flash
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

**解析顺序（确定性 · Issue #182 复评收紧 · PR #184）**：
`role_alias(全称↔短名双向归一)` → `roles[角色]` → **`fallback_chain`**（= `default.chain` 的 YAML 锚点引用）→ 内置兜底常量。

- 角色**真正需要不同链**才显式写进 `roles`；**未列出的角色走 `fallback_chain`**（= default.chain），
  不在配置里堆与 default 逐字相同的「空壳链」（Issue #182 复评：23/25 条空壳已撤销）；
- `role_policy()['specified']` 标该角色是否显式指定（`False` = 走 fallback，是预期行为，非异常）；
- `role_aliases` 让全称与短名**双向**可查（`架构·开发` ↔ `开发`），云端传全称也匹配得上；
- 支持 `MODEL_ROUTING_CONFIG` 环境变量指向自定义配置文件（多环境部署用）。

### 2.1 角色按需指定（Issue #182 复评 · PR #184 · 不造假差异化）

用户原话：「我记得有对哪个角色用哪个模型的那部分的配置的定义，你检查一下，所以不是默认，
其实有额外的文件指定了的」。**配置确实在**，但初版把 `.cnb/settings.yml` 声明的角色
**逐字复制**成 25 条与 default 相同的链——那是空壳声明，并非真差异化。
复评（PR #184）改为：

| 项 | 真相 / 修法 |
|---|---|
| 初版断点① | 25 条角色链 23 条与 `default.chain` 逐字相同，属空壳声明 |
| 复评修法① | **撤销空壳**：只在角色**真正需要不同链**时写进 `roles`（当前仅 进度推手/客服 主档换快档）；其余角色走 `fallback_chain` |
| 初版断点② | 全称/短名匹配不上 → 摘掉 `role_aliases` 后短名静默走 fallback，审计一条不报 |
| 复评修法② | `audit_roles()` **全称 + 短名双体检**（`short_names` 含去前缀自然短名）；摘掉别名立即报 `alias_broken`，断点不再换位置复发 |

写进代码的约束：

```bash
python3 -m model_routing.cli audit      # 体检：空壳链 / 别名断裂 / 缺链（有即退出码 2）
python3 -m model_routing.cli roles      # 逐角色实际生效主档 + specified
```

信号灯：`bash tests/test_model_role_assign.sh`（7 组，含「两链一致」「摘掉短名别名 → 审计立刻报红」反向验证）。

**快档锚定角色**（档序服从 Issue #199 拍板，不自排；不堆空壳）：

| 角色 | 主档 | 理由 |
|---|---|---|
| 架构·进度推手 / 市场·客服 | `deepseek-v4.1-flash`（快档锚定） | 打标/百分比/短答，不需长上下文，要回合快 |
| 架构·开发 | `deepseek-v4.1-flash`（快档锚定） | 主力读写码、回合最多，要的是「回合快」（PR #185） |
| 其余角色 | 走 `fallback_chain`（= default） | 未显式指定即走默认，specified=False，可审计 |

### 2.1.1 三档语义 + 显性降级（PR #185 · 用户定调）

用户原话：「**给他 3 个档**，一个是指定的，降级是和其他一样的，再降低再到现在的兜底。
只是注意**降级要显性，不要静默降级**」。落地为：

| 档 | 语义 | 配置写法 | 说明 |
|---|---|---|---|
| 档1 `fast` | **指定** | `roles[角色].chain[0]` | 该角色专属快档 = 快档第一优先 `deepseek-v4.1-flash`（Issue #199 拍板，快档角色不自排档序）。带版本后缀的真实平台 ID（如 `deepseek-v4.1-flash-1017`）待人类给出原文并 `probe` 验真后登记 `alias`（Issue #199：人类给的是档序优先级，不是 ID 原文） |
| 档2 `same` | **和其他角色一样** | chain 里与 `fallback_chain` 同名的档位 | 不另造名字、不重复字面量，直接是通用链那套模型 |
| 档3 `last_resort` | **现在的兜底** | `last_resort_model`（顶层单值，现为 `glm-5.3-flash`） | `npc:go` 只接受单 model，平台侧一定跑得起来的那一道 |

```bash
python3 -m model_routing.cli tiers 架构·开发   # 三档语义俯瞰（fast / same / last_resort）
```

**显性降级（本版核心纪律）**——降级不是「悄悄换了个模型」：

- `engine.route_call` 每一跳失败都写 `model.call.fail` 且带 `degraded=1 / fallback_from / next`；
  降级成功后再补一条 `model.call.degraded`（监控/巡检 grep 一条就够，不用回读整条链）；
- 结果里带 `degraded / from_model / used_tier`，调用方一眼看到「本轮不是主档答的」；
- `llm/openai_compat` 把它记进 `last_degraded` + 打 warning 日志；全挂时异常文案也带 `degraded=True`；
- 审计项 `no_degrade_target`：显式列出的角色链若**没有「和其他角色一样」的档位**就报红——
  单档链 = 主档一挂整条断，等于把静默失败写进配置。

**顺手修掉一个真 bug（PR #185 实测命中）**：`openai_compat.call()` 里构造每档 caller 时写的是
`{m: (lambda sp, ui, **k: self._call_model(m, ...)) for m in chain}`——闭包捕获的是**循环变量**，
循环结束后所有档都指向链尾模型：降级链形同虚设，还伪装成「每档都试过了」。现已改为
`model=ch` 逐个绑定，并由信号灯 ⑬ 断言 `calls == chain[:2]`（真换模型，不是重复打同一个）。

### 2.2 版本别名（用户说的 `deepseek v4.1 flash 1017` · 实名登记，不留伪配置）

```yaml
alias: {}   # 故意为空：1017 对应哪个平台真实 ID 尚未由人类确认，不留伪配置
```

- **未确认不登记**：`1017` 这类口语版本串只在人类确认平台真实 ID 后，才补一行
  `deepseek-v4.1-flash-1017: <真实ID>`（改 `alias` 右侧一处即全角色生效，不用逐角色改）；
- **未登记 alias 显式报红（不放行）**：`resolve_alias` 对带版本后缀（`-<数字>`）却未登记的
  模型名，在解析期直接抛 `未登记别名` 异常——不再静默透传给后端（否则
  `model ... is not in the optional models list` → 整个 stage error，#177 事故）。别名映射
  统一收口在 `engine.resolve_models`（含 `role_at`），不在 `openai_compat` 散落；
- 普通模型 ID（无版本后缀）原样返回，不影响正常链路。

## 三、为什么需要独立模块 + 统一配置

此前模型只在 `.cnb.yml` 一处写死 `deepseek-v4-flash`（注释称"用户指定 v4 flash"，实为
**未指定到 4.1**），且**没有主/备降级机制**——主渠道不通即整体失败。本模块统一收敛：

| 层 | 职责 |
|---|---|
| `models.yml` | 渠道链 + 角色覆盖 + 降级信号（**唯一事实源/唯一配置文件**）|
| `spec.py` | 加载配置 + 解析（default / role 覆盖）+ 稳定接口（**不硬编码模型 ID**；**每次解析实时读文件**）|
| `engine.py` | 多级降级路由 + 留痕（确定性逻辑，非 LLM 判断），支持 `role=` 按角色解析 + `call_with_chain` 多后端分派 |
| `ability.py` | `ModelRoutingAbility`（全员可调用）|
| `cli.py` | MCP 管线（`config`/`models`/`chain`/`tiers`/`params`/`probe`/`audit`/`overview`/`dryrun`）|

## 四、降级规则（确定性）

1. 按解析出的渠道链取**第一档**调用；
2. 该档返回 **不可用 / 超时 / 限流 / 5xx**（`unavailable_signals`）→ **自动降级下一档**；
3. 逐档降级直到成功；**全链耗尽** → **显式失败** `all_channels_unavailable`，**不静默、不假装成功**；
4. **降级必须显性**：每跳写 `degraded=1 / fallback_from / next`，成功降级补写
   `model.call.degraded`，结果带 `degraded/from_model/used_tier`，后端记 `last_degraded` + warning 日志
   ——绝不静默换模型（用户 PR #185 明确要求）；
5. 每次路由决策写 `model_routing_trace.jsonl`，供监控俯瞰。

## 五、接线点（★本版核心：配置真正生效）

> 用户明确：**配了就要生效，不生效等于白做**。本版把「配置文件的模型链」真正接进执行链路。

| 接线点 | 改动 |
|---|---|
| **`roles/base.py run()`** | 把 `role=self.name` 传进 `llm.call(...)`（用签名探测，不吞异常）——**角色名首次贯通调用链** |
| **`llm/base.py` `call()`** | 签名加 `role=None`（统一接口）|
| **`llm/openai_compat.py` `call()`** | 每次调用按 `role` 从唯一配置解析渠道链，取首档；失败**逐档降级**（`call_with_chain`）；全挂显式抛错；显式 `LOCAL_AGENT_MODEL` 时尊重单模型 |
| **`llm/cli_fallback.py` `call()`** | 兼容 `role`（占位输出带角色名）|
| **`.cnb.yml` `npc:go`** | 首档 `model:` = `npc_go.model_preference[0]`（大参数优先，现为 `hy4`）；**`failStages` 兜底档不写 model**（走平台默认）。npc:go 只接受单 model 字段，多档降级由后端运行时接管 |

**非单次有效**：`spec` 每次解析都**重新读取** `models.yml`（不缓存死值）——
改配置文件后无需重启/重装即生效；也可用 `MODEL_ROUTING_CONFIG` 指向别处。

## 六、验证

```bash
bash local-agent/tests/test_model_routing.sh          # 12 组信号灯（含接线核验）
bash tests/test_model_role_assign.sh                 # 14 组信号灯（角色按需指定 / 两链一致 / 别名双体检 / 三档语义 / 显性降级）
# 仓库根目录运行 CLI（加 PYTHONPATH，避免 ModuleNotFoundError）：
PYTHONPATH=local-agent python3 -m model_routing.cli config       # 唯一配置文件路径 + 生效内容
PYTHONPATH=local-agent python3 -m model_routing.cli chain        # 通用默认渠道链
PYTHONPATH=local-agent python3 -m model_routing.cli chain 架构·开发  # 某角色渠道链（未列出 → 默认）
PYTHONPATH=local-agent python3 -m model_routing.cli tiers 架构·开发  # 三档语义（指定 / 和其他角色一样 / 兜底）
PYTHONPATH=local-agent python3 -m model_routing.cli dryrun       # 本地演练：主通道挂→逐档降级
```

> 也可 `cd local-agent` 后直接 `python3 -m model_routing.cli ...`。

## 七、边界说明

- 平台侧（NPC 选择器 / 云端 Agent 设置）的模型选择**仓库管不到**；本模块覆盖
  ① 仓库内一切模型默认值 ② `npc:go` 兜底路径 ③ 本地 harness 后端（角色名已真实贯通）。
- 模型 ID 是否被平台识别的最终解释权在平台；若平台不接受某个 ID，
  **改 `models.yml` 一处即可全仓生效**（单点收敛，不散改）。
- `minimax-3.1-flash` / `codebuddy` / `glm-5.3-flash` 作为备用档，走同一 OpenAI 兼容端点（网关侧路由到对应模型）；
  若网关不支持某档模型名，该档调用失败即自动降级下一档，行为仍正确。

## 七'、npc:go 模型偏好链（Issue #346 · 大参数优先 + 兜底默认）

人类 2026-11-14 定调：「**默认选大参数的模型，兜底默认**，这样就会一直可以通；
比较大的模型也不是静态的，有更新就可以换」。

落地成两条互补的规则，配置在 `models.yml` 的 `npc_go.model_preference`（唯一事实源）：

| 位置 | 写法 | 作用 |
|---|---|---|
| `.npc_task.stages[0]` | `model: hy4`（= `model_preference[0]`） | **追求参数大、判断深**——架构师这类角色的取向 |
| `.npc_task.failStages[0]` | **不写 model** | **平台默认模型**——组织保证可用的那一道，随配置自动跟随 |

**为什么分成两条链**：`default.chain` 是「快档」（回合快、tps 优先），
`model_preference` 是「大参数」（判断深、能扛复杂推理）。取向不同，合并会让两者互相绑架
（为了快把架构师按到小模型，或为了大参数把开发拖慢）。

**为什么首档敢写死一个 ID**：单写死 ID 的风险（组织可选列表漂移 → stage 秒挂）
由 failStages 兜底消化。`#177`（`deepseek-v4-flash` 不在列表）和 `#346`（`hy3` 不在列表）
是同一根因的两次事故——现在「首档大参数 + 兜底平台默认」两头都不写死，链路不会再整条断掉。

**实测（2026-11-14 真机 `npc:go` stage 逐一探针，不是猜、不是抄文档）**：

```
通过   → hy4 / glm-5.3 / glm-5.3-flash / deepseek-v4.1-flash
不认    → hy3 / qwen4 / qwen4-max / glm-4.6 / glm-5 / hunyuan-4 / hunyuan-2.0 /
          hunyuan-turbos / deepseek-v4.1 / deepseek-v4.1-pro / minimax-3.1 /
          minimax-3.1-flash / codebuddy / qwen3-max / qwen3-coder / kimi-k2 /
          doubao-1.5-pro / glm-5.3-plus 等
          （均报 `not in the optional models list of your organization`）
```

`allowFailure` **必须放在流水线层**：放 job 层会让首档失败被判 success →
**failStages 直接被跳过**（实测：首档 success 72ms / 兜底 skipped），
变成「首档没跑成、兜底也没跑」的假绿。放流水线层则是：首档 error → 兜底真跑 → 整体上报 success。

**换模型怎么做**：改 `models.yml` 的 `model_preference`（可排多个候选，按序优先），
同步 `.cnb.yml` 首档一行；`local-agent/tests/test_model_routing.sh ⑫` 与
`tests/test_model_role_assign.sh ⑦` 双端机器核验——两处不一致即红灯。
**兜底档永远留空**，这条由 ⑫ 断言锁死（写死模型就报红）。

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
