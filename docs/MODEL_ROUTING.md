# 模型路由（model-routing · 统一配置文件 + 主通道/备用降级）

> **唯一配置文件**：`local-agent/model_routing/models.yml`（改模型只改这一处）
> **读配置代码层**：`local-agent/model_routing/spec.py`
> **演进线**：Issue #147 · module model-routing v0.2.0-update
> **触发词**：模型/主模型/备用模型/降级/渠道不通/统一配置/角色指定/v4.1 flash/glm

## 一、用户诉求（Issue #147）

1. **模型指定收敛到一个配置文件统一管理**——以后不用去检查哪里定义，改模型只改一处，不跨多个文件；
2. **不指定就默认通用**——未单独列出的角色一律走通用默认；
3. **允许对某个角色单独指定**——按角色名覆盖；
4. **加入索引介绍**——登记进 `docs/CAPABILITY_INDEX.md`。

配套的模型策略：
- **一选（主通道）= `deepseek-v4.1-flash`**
- **二选（备用通道）= `glm-5.3-flash`**，**主渠道不通时启用**

## 二、唯一配置文件（models.yml）

```yaml
# ① 通用默认（不指定角色时用这个）
default:
  primary: deepseek-v4.1-flash
  fallback: glm-5.3-flash

# ② 按角色单独指定（可选；未列出的角色自动继承 default）
roles:
  "架构·评审": { primary: glm-5.3-flash }   # 示例：该角色 primary 被覆盖，fallback 继承 default

# ③ 渠道不通判定信号（触发降级）
unavailable_signals: [unavailable, timeout, connection_error, rate_limit, "429", "503", ...]
```

**解析顺序（确定性）**：`roles[角色]` → `default` → 内置兜底常量（配置缺失时不崩）。

- 角色**未在 roles 中列出** → 继承 `default`（「不指定就默认通用」）；
- 角色**在 roles 中列出** → **字段级覆盖**（只写 `primary` 时 `fallback` 仍继承 default）；
- 支持 `MODEL_ROUTING_CONFIG` 环境变量指向自定义配置文件（多环境部署用）。

## 三、为什么需要独立模块 + 统一配置

此前模型只在 `.cnb.yml` 一处写死 `deepseek-v4-flash`（注释称"用户指定 v4 flash"，实为
**未指定到 4.1**），且**没有主/备降级机制**——主渠道不通即整体失败。本模块统一收敛：

| 层 | 职责 |
|---|---|
| `models.yml` | 模型 ID + 角色覆盖 + 降级信号（**唯一事实源/唯一配置文件**）|
| `spec.py` | 加载配置 + 解析（default / role 字段级覆盖）+ 稳定接口（**不硬编码模型 ID**）|
| `engine.py` | 主→备降级路由 + 留痕（确定性逻辑，非 LLM 判断），支持 `role=` 按角色解析 |
| `ability.py` | `ModelRoutingAbility`（全员可调用）|
| `cli.py` | MCP 管线（`config`/`models`/`overview`/`dryrun`）|

## 四、降级规则（确定性）

1. 按解析出的策略取**主通道**调用；
2. 主渠道返回 **不可用 / 超时 / 限流 / 5xx**（`unavailable_signals`）→ **自动降级**备用通道；
3. 两渠道全挂 → **显式失败** `all_channels_unavailable`，**不静默、不假装成功**；
4. 每次路由决策写 `model_routing_trace.jsonl`，供监控俯瞰。

## 五、接线点

- **`.cnb.yml` `npc:go`**：`model:` 为通用默认主通道 `deepseek-v4.1-flash`（npc:go 只接受
  单 model 字段，主/备降级由后端运行时接管）。
- **`local-agent/llm/openai_compat.py`**：默认模型从 `spec.PRIMARY`（读配置）获取。

## 六、验证

```bash
bash local-agent/tests/test_model_routing.sh   # 8 组信号灯
python3 -m model_routing.cli config            # 查看唯一配置文件路径 + 生效内容
python3 -m model_routing.cli models 架构·开发  # 查看某角色渠道顺序（不传 → 通用默认）
python3 -m model_routing.cli dryrun            # 本地演练：主通道挂→降级
```

## 七、边界说明

- 平台侧（NPC 选择器 / 云端 Agent 设置）的模型选择**仓库管不到**；本模块覆盖
  ① 仓库内一切模型默认值 ② `npc:go` 兜底路径 ③ 本地 harness 后端。
- 模型 ID 是否被平台识别的最终解释权在平台；若平台不接受某个 ID，
  **改 `models.yml` 一处即可全仓生效**（单点收敛，不散改）。
