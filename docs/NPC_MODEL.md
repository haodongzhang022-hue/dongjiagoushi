# NPC 模型策略（npc-model · v0.1.0）

> **一句话**：不写死模型 ID，默认选**大参数**模型，选不到就**兜底走平台默认**，
> 平台有新模型就**改数据不改流水线**。
>
> 唯一事实源：`.cnb/npc-models.yml` · 解析入口：`scripts/npc-model.sh` ·
> 能力实现：`local-agent/npc_model/` · 信号灯：`local-agent/tests/test_npc_model.sh`

## 一、要解决的问题

`npc:go` 的 `model` 必须是「当前组织可选模型列表」里的 ID，而该列表由组织配置决定、
会随平台更新漂移。把它写死在 `.cnb.yml` 里，组织一调整就在 **stage 层**直接 error：

```
npc:go model "<id>" is not in the optional models list of your organization.
```

故障形态极其难查：`Prepare` 是 success，`npc go` 3~4 秒就 error，表现为
「评论 @架构·总师 → 流水线起来了 → 立刻挂」，**对端既不回执也不接单**，
从本地看像接力卡发出去了。历史上踩过两次（`deepseek-v4-flash`、`hy3`），都是同一个坑。

反方向的坑同样存在：完全**不写** `model` 确实永远能跑通，但落到平台默认的
`deepseek-v4.1-flash` 是小参数模型 —— 架构师要啃长文档、走架构八步、出结构化长产出，
撑不住。

## 二、策略：大参数优先 + 默认兜底

| 优先级 | 来源 | 行为 |
|---|---|---|
| 1 | **环境变量覆盖** | `NPC_MODEL_OVERRIDE=<模型ID>` 显式指定，不改仓库、不提 PR 就能换 |
| 2 | **prefer（大参数优先）** | 从上到下取第一个「不在 unavailable 里」的候选 |
| 3 | **fallback（平台默认）** | `platform_default` = **不写 `model`**，走平台默认模型 |

三条一起构成闭环：**首选大参数 → 不可用自动降级 → 无论如何都通**。

关键设计（都是踩过坑换来的）：

- **黑名单是缓存，不是墓碑**：`unavailable` 是「已实测不在可选列表」的 ID 缓存。
  平台上线某个模型后，把它从 `unavailable` 删掉，`prefer` 里同名候选**立刻生效**。
  换模型 = 改一行数据。
- **兜底只能是 `platform_default`**：写成具体模型 ID 等于把漂移风险原样搬回来，
  所以 `ModelSpec.from_dict()` 会**确定性拒绝**（不是 LLM 判断，是代码校验）。
- **绝不产出 `model: ''`**：走兜底时 `npc_options` 返回 `{}`（不含 `model` 键）。
  实测写空串会让 `npc:go` 报 `"model" must be a non-empty string`。
- **失败即闭环学习**：`npc-model.sh learn` 从失败日志认出被拒的模型 ID，
  直接给出「把它加进 unavailable、把下一个大参数模型放到 prefer 最前」的整改建议。

## 三、配置（`.cnb/npc-models.yml`）

```yaml
prefer:            # 大参数优先顺序（从上到下取第一个可用的）
  - hy4            # 混元 4：当前本组织最大参数可选模型（实测可用）
  - qwen4          # 千问 4：等平台放进可选列表后，从 unavailable 移除即自动生效

unavailable:       # 已知不可用（黑名单缓存）：命中即跳过、顺延下一个
  - hy3
  - qwen4
  # ...

fallback: platform_default   # 只允许这个值：不写 model，走平台默认
override_env: NPC_MODEL_OVERRIDE
history:                     # 变更留痕，换模型时写原因
  - "2026-11-14 v0.1.0 首次落地：hy4 为大参数首选，兜底走平台默认"
```

## 四、换模型的正确顺序

**先确认 ID 真在「当前组织可选模型列表」里**，任选一种核实：

1. 在评论里 @ 一个 NPC，看 `npc go` stage 是否报 `optional models list`；
2. 用 `cnb build start-build --config` 起一条探针流水线，stage 里跑 `npc:go`；
3. 平台「NPC 选择器 / 云原生开发 Agent 设置」看可选模型下拉。

然后：

- **可用** → 加到 `prefer` 最前；
- **不可用** → 加到 `unavailable`；
- 两者都只改 `.cnb/npc-models.yml`，`.cnb.yml` 一个字都不动。

临时试某个模型（不改仓库）：流水线 `env` 里设 `NPC_MODEL_OVERRIDE=<模型ID>`。

### 实测记录（2026-11-14 · dongdongxiaozu 组织）

用 16 + 24 条 `npc:go` 探针流水线逐条验证：

| 结果 | 模型 ID |
|---|---|
| ✅ 可选 | `hy4`（大参数，首选）、`deepseek-v4.1-flash`（= 平台默认，小参数） |
| ❌ 不在可选列表 | `hy3`、`qwen4`、`qwen3-max`、`qwen-max`、`hunyuan-4`、`hunyuan-large`、`glm-5`、`glm-4.6`、`deepseek-v4.1`、`deepseek-v4.1-pro`、`claude-sonnet-4.5`、`claude-opus-4`、`gpt-5`、`doubao-pro`、`kimi-k2` |
| ✅ 不写 model | 平台默认 → 实际落到 `deepseek-v4.1-flash` |

> **注意**：不出现在报错里的模型 ID 也可能"跑通"，但那是**平台按默认模型兜掉了**，
> 不代表该 ID 生效。所以核实要看 `Master[agent] model=<id>` 这行日志，
> 而不是只看 stage 是否 success。

## 五、流水线接线（`.cnb.yml`）

```yaml
.npc_task: &npc_task
  name: architect npc
  stages:
    - name: resolve npc model
      script: bash scripts/npc-model.sh resolve
      exports:
        npc_model: NPC_MODEL
        npc_use_default: NPC_USE_DEFAULT
    - name: npc go                     # 首选：命中大参数模型
      if: |
        [ "${NPC_USE_DEFAULT:-0}" != "1" ]
      type: npc:go
      options:
        role: "架构·秘书"
        model: $NPC_MODEL
    - name: npc go (platform default)  # 兜底：prefer 全不可用
      if: |
        [ "${NPC_USE_DEFAULT:-0}" = "1" ]
      type: npc:go
      options:
        role: "架构·秘书"
  failStages:
    - name: npc model diagnose         # 闭环学习：认出被拒模型 + 给整改建议
      script: bash scripts/npc-model.sh learn --log-text "${CNB_BUILD_FAILED_MSG:-}"
    - name: npc go (fallback)          # 首选被组织拒 → 就地降级兜底
      if: |
        printf '%s' "${CNB_BUILD_FAILED_MSG:-}" | grep -q "optional models list"
      type: npc:go
      options:
        role: "架构·秘书"              # 不写 model，走平台默认
```

**为什么要有 `failStages` 一层**：`prefer` 命中的模型可能"配置里看着可用、组织那边已经撤了"。
实测确认 `failStages` 里再跑一跳不写 `model` 的 `npc:go`，卡片照常打出去 ——
这就是"一直可以通"的硬保证。（实测日志：首选 `npc go` error → `npc model diagnose`
打出被拒模型 + 整改建议 → `npc go (fallback)` 跑在 `deepseek-v4.1-flash` 上成功。）

**为什么不给 `.npc_task` 设 `allowFailure: true`**：实测发现它会连「首选和兜底**都**失败」
一起显示成 success，等于把真故障藏掉。保留红色是有意的：红 = 环境漂移了、卡由兜底发出去了、
但 `.cnb/npc-models.yml` 该更新了。这是显式提醒，不是误报。

### 端到端实测（2026-11-14）

| 场景 | 首选 stage | fallback stage | 实际生效模型 |
|---|---|---|---|
| 正常（prefer 命中 hy4） | success | 未触发 | `model=hy4`（不是 flash ✅） |
| 首选被组织拒（override 成假模型） | error | success | `model=deepseek-v4.1-flash`（兜底）|

两条都用真流水线跑过，`Master[agent] model=<id>` 日志逐条核实。

## 六、CLI

```bash
bash scripts/npc-model.sh info       # 人可读策略快照（当前会选谁、为什么）
bash scripts/npc-model.sh resolve    # 流水线用：导出 NPC_MODEL / NPC_USE_DEFAULT
bash scripts/npc-model.sh resolve --json
bash scripts/npc-model.sh learn --log-file /path/to/log   # 从失败日志认模型
NPC_MODEL_OVERRIDE=hy4 bash scripts/npc-model.sh resolve  # 临时覆盖
```

## 七、风险与边界

| 风险 | 应对 |
|---|---|
| `unavailable` 慢慢过期（模型重新上线） | 它是缓存不是墓碑，删掉即生效；`info` 会打印完整黑名单供人工巡检 |
| `prefer` 第一个总是命中，后面候选成摆设 | 候选顺序即优先级，平台更新时把新大模型提到最前；黑名单保证不会反复撞墙 |
| 兜底永远命中当默认小模型，没人发现首选坏了 | 首选 error 会进 `failStages` 的 `npc model diagnose` 日志，`learn` 直接给整改建议；pipeline 状态仍 success 但日志有据可查 |
| 写死模型 ID 的诱惑 | 信号灯第 8 组断言 `.cnb.yml` 里没有任何生效的 `model: <具体ID>` |
