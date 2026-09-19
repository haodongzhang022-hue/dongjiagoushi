# 模型路由（model-routing · 一选主通道 + 二选备用）

> **唯一事实源**：`local-agent/model_routing/spec.py`
> **演进线**：Issue #147 · module model-routing v0.1.0-init
> **触发词**：模型/主模型/备用模型/降级/渠道不通/v4.1 flash/glm/v4flash

## 一、用户诉求（Issue #147）

- **一选（主通道）= `deepseek-v4.1-flash`**
- **二选（备用通道）= `glm-5.3-flash`**，**主渠道不通时备用**
- 全角色统一走这套策略，**不做 per-role 散点写死**

## 二、为什么需要独立模块

此前模型只在 `.cnb.yml` 一处写死 `deepseek-v4-flash`（注释称"用户指定 v4 flash"，实为
**未指定到 4.1**），且**没有主/备降级机制**——主渠道不通即整体失败。本模块统一收敛：

| 层 | 职责 |
|---|---|
| `spec.py` | 渠道优先级 + 模型 ID（**唯一事实源**，禁止别处取名）|
| `engine.py` | 主→备降级路由 + 留痕（确定性逻辑，非 LLM 判断）|
| `ability.py` | `ModelRoutingAbility`（全员可调用）|
| `cli.py` | MCP 管线（`models`/`overview`/`dryrun`）|

## 三、降级规则（确定性）

1. 按 `spec` 优先级取**主通道** `deepseek-v4.1-flash` 调用；
2. 主渠道返回 **不可用 / 超时 / 限流 / 5xx**（`UNAVAILABLE_SIGNALS`）→ **自动降级** `glm-5.3-flash`；
3. 两渠道全挂 → **显式失败** `all_channels_unavailable`，**不静默、不假装成功**；
4. 每次路由决策写 `model_routing_trace.jsonl`，供监控俯瞰。

## 四、接线点

- **`.cnb.yml` `npc:go`**：`model:` 改为主通道 `deepseek-v4.1-flash`（npc:go 只接受单 model 字段，
  主/备降级由后端运行时接管）。
- **`local-agent/llm/openai_compat.py`**：默认模型从 `spec.PRIMARY` 读取（原为 `gpt-4o-mini`）。

## 五、验证

```bash
bash local-agent/tests/test_model_routing.sh   # 5 组信号灯
python3 -m model_routing.cli dryrun            # 本地演练：主通道挂→降级
```

## 六、边界说明

- 平台侧（NPC 选择器 / 云端 Agent 设置）的模型选择**仓库管不到**；本模块覆盖
  ① 仓库内一切模型默认值 ② `npc:go` 兜底路径 ③ 本地 harness 后端。
- 模型 ID 是否被平台识别的最终解释权在平台；若平台不接受 `deepseek-v4.1-flash`，
  改 `spec.py` 一行即可全仓生效（单点收敛，不散改）。
