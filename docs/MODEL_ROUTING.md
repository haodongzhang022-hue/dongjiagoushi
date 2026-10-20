# 模型路由（model-routing · 统一配置文件 + 多级降级链 + 真实接线）

> **唯一配置文件**：`local-agent/model_routing/models.yml`（改模型只改这一处）
> **读配置代码层**：`local-agent/model_routing/spec.py`
> **演进线**：Issue #147 · module model-routing v0.3.0-update → v0.3.0-fix（Issue #182）→ **v0.3.0-fix（PR #185 · 平台参数与别名键）**
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

**真正差异化的依据**（只列确实不同的，不堆空壳）：

| 角色 | 主档 | 理由 |
|---|---|---|
| 架构·进度推手 / 市场·客服 | `glm-5.3-flash`（快档优先） | 打标/百分比/短答，不需长上下文，要回合快 |
| 其余角色 | 走 `fallback_chain`（= default） | 未显式指定即走默认，specified=False，可审计 |

### 2.2 版本别名（用户说的 `deepseek v4.1 flash 1017` · 实名登记，不留伪配置）

```yaml
alias: {}   # 故意为空：1017 对应哪个平台真实 ID 尚未由人类确认，不留伪配置
```

- **未确认不登记**：`1017` / `minimax 3.1 flash` 这类口语版本串只在**探针（`cli probe`）实跑通过**
  后才补一行（改 `alias` 右侧一处即全角色生效，不用逐角色改）。当前待确认候选：
  `deepseek-v4.1-flash-1017`、`minimax-3.1-flash`；
- **别名键也受体检（`alias_unused`）**：登记了但没有任何角色链引用它 = 接线不到，
  右值写成错 ID 也没人测得出（#177 静默版）→ 审计报红，须写进角色链或删掉；
- **未登记 alias 显式报红（不放行）**：`resolve_alias` 对带版本后缀（`-<数字>`）却未登记的
  模型名，在解析期直接抛 `未登记别名` 异常——不再静默透传给后端（否则
  `model ... is not in the optional models list` → 整个 stage error，#177 事故）。别名映射
  统一收口在 `engine.resolve_models`（含 `role_at`），不在 `openai_compat` 散落；
- 普通模型 ID（无版本后缀）原样返回，不影响正常链路。

### 2.3 换模型 ≠ 提速：`npc:go` 还有一组和模型绑定的参数（PR #185）

用户问「minimax 3.1 flash / deepseek v4.1 flash 1017 能直接用吗，直接指定按说也会快」。
结论分两半，必须拆开说，否则又会把「模型选谁」和「跑多快」糊成一个数：

**① 能不能用 = 平台可选列表说了算，不由本配置决定。**
`npc:go` 的 `model` 只传一个模型 ID，认不认由平台判。写错的表现是
`model ... is not in the optional models list` → **整个 stage error**（#177 事故，
链路静默失效）。所以唯一可信的判定方式是**真调用探针**，不是"按说应该行"：

```bash
python3 -m model_routing.cli probe minimax-3.1-flash      # → ok:true 才能登记
python3 -m model_routing.cli probe deepseek-v4.1-flash-1017
```

探针没 key 时**明确返回 `skipped` + 退出码 2**，不假装成功（「会返回空但显示通过」是我们要绝掉的假象）。

**② 平台参数的默认值随 `model` 变，必须写死。**
文档（`zh/build/internal-steps/npc/go.md`）写明：显式指定自定义 `model` 时，平台**不再继承**
默认模型配置，回落到内置默认：

| 参数 | 显式指定 model 后的内置默认 | 说明 |
|---|---|---|
| `thinkingLevel` | `medium` | 推理深度，`off`~`max` 七档 |
| `contextWindow` | `1m` | 128k~1m；降它能减少溢出压缩触发 |
| `maxTokens` | `48k` | 单次输出上限 |
| `maxTurns` | `500` | 最大对话轮次 |

这几项**不派生于渠道链**（不是「换个模型就自动对」），所以在 `models.yml` 的 `npc_go:` 块
声明期望值，`.cnb.yml` 的 `.npc_task` 同步落地，两边一致性由
`tests/test_model_role_assign.sh` ⑧ **机器核验**（npc:go 只认流水线 options，不读 models.yml，
不核验就是"配置看着对、线上没生效"）。

**③ 「慢」的主因不在模型名。** 单轮上下文体积（AGENTS.md + skill 全文 + 全量评论流）和工具步数
才是量级主因；换模型只动「每秒吐字」。真要提速走 `contextWindow` 收敛 + 上下文瘦身，不是换 ID。

> 边界：`tps` 在本仓库**零痕迹**（模型链路、`models.yml`、`call()` 里没有吞吐限流或速率分档），
> 所以平台实测的 46 tps 与「配置里写哪个模型」之间没有因果，别把两个问题混成一个。

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
bash tests/test_model_role_assign.sh                 # 7 组信号灯（角色按需指定 / 两链一致 / 别名双体检）
# 仓库根目录运行 CLI（加 PYTHONPATH，避免 ModuleNotFoundError）：
PYTHONPATH=local-agent python3 -m model_routing.cli config       # 唯一配置文件路径 + 生效内容
PYTHONPATH=local-agent python3 -m model_routing.cli chain        # 通用默认渠道链
PYTHONPATH=local-agent python3 -m model_routing.cli chain 架构·开发  # 某角色渠道链（未列出 → 默认）
PYTHONPATH=local-agent python3 -m model_routing.cli dryrun       # 本地演练：主通道挂→逐档降级
PYTHONPATH=local-agent python3 -m model_routing.cli params       # 平台 npc:go 可控参数
PYTHONPATH=local-agent python3 -m model_routing.cli probe <ID>   # 真实探针：平台认不认这个模型 ID
```

> 也可 `cd local-agent` 后直接 `python3 -m model_routing.cli ...`。

## 七、边界说明

- 平台侧（NPC 选择器 / 云端 Agent 设置）的模型选择**仓库管不到**；本模块覆盖
  ① 仓库内一切模型默认值 ② `npc:go` 兜底路径 ③ 本地 harness 后端（角色名已真实贯通）。
- 模型 ID 是否被平台识别的最终解释权在平台；若平台不接受某个 ID，
  **改 `models.yml` 一处即可全仓生效**（单点收敛，不散改）。
- `codebuddy` / `glm-5.3-flash` 作为备用档，走同一 OpenAI 兼容端点（网关侧路由到对应模型）；
  若网关不支持某档模型名，该档调用失败即自动降级下一档，行为仍正确。
