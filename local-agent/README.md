# 本地 Agent 团队（local-agent）

> 在**无 `@` 能力**的本地环境，用**命令行**承载云端 `@CodeBuddy` 的触发语义，
> 让同一套「架构师 + 多角色团队」可在本地运行：用户提交请求 → 团队自动编排到交付。
> 架构设计见 [docs/LOCAL_AGENT.md](../docs/LOCAL_AGENT.md)。

## 为什么需要它

云端通过 CNB 平台 `@CodeBuddy` 触发（自动加载 `.codebuddy/skills/architect/SKILL.md` 化身架构师）。
但本地环境**没有 `@` 能力**，本模块用 `--role` / `--pipeline` 子命令补齐这一触发能力。

## 快速开始

```bash
cd local-agent
pip install -r requirements.txt      # 占位模式可跳过

# 1) 一键跑完整团队流水线（产品→架构→分工→协同→测试→交付）
python3 run.py --pipeline full --req "做一个订单系统"

# 2) 触发单个角色（等价云端 @角色）
python3 run.py --role 架构·总师 --req "对XX做架构设计"

# 3) 列出团队角色
python3 run.py --list-roles

# 4) 中断后续跑（等价云端 [打断] 续跑）
python3 run.py --resume
```

## 模型后端

| 后端 | 启用方式 | 说明 |
|------|----------|------|
| `openai_compat` | 设 `OPENAI_API_KEY` / `LOCAL_AGENT_API_KEY` | OpenAI 兼容 API 真实推理（默认优先） |
| `cli_fallback` | 设 `LLM_CLI`（如 `ollama run llama3`） | 调用命令行工具推理 |
| `cli_fallback`(占位) | 无 key 时自动 | **不伪造推理**，只生成角色输出契约骨架，保证流水线可跑通、可测试 |

```bash
# 指定后端
python3 run.py --pipeline full --req "XX" --backend cli_fallback
# 用本地 ollama
LLM_CLI="ollama run llama3" python3 run.py --pipeline full --req "XX"
```

## 团队角色（8 个）

| 角色 | 流水线环节 | 输出契约 |
|------|-----------|----------|
| 架构·产品 | 需求澄清/翻译意图/拆需求/分工排班 | 用户故事+验收标准+边界+反问 |
| 架构·总师 | 架构设计/确认版本/校验正确性/合理性/成本/周期 | 架构方案+双版本+校验+风险 |
| 架构·小组长 | 子任务拆解/协调 | 子任务+依赖+排期+协调 |
| 架构·开发 | 实现/自测 | 实现说明+文件+自测+PR |
| 架构·评审 | 五维评审/复评 | 五维+分级(🔴/🟡/🟢) |
| 架构·对齐 | 版本对齐/一致性校验 | 版本校验+依赖对齐+冲突预警 |
| 架构·找工具 | 工具/依赖检索 | 工具清单+评估+推荐 |
| 架构·测试 | 测试矩阵/信号灯 | 测试矩阵+缺陷分级+信号灯 |

## 协作协议（与云端对齐）

- **接力卡**：`state/relay_card.json` 持久化当前进度/下一步，支持续跑。
- **回转**：下游发现 🔴必修/🔴阻塞 → 接力卡写 `revert_to`，编排引擎回退重跑。
- **打断**：中断在 `current_progress` 留续跑点，`--resume` 续跑。

## 测试

```bash
bash local-agent/tests/test_local_agent.sh
```

验证：CLI 入口 / 单角色触发 / 团队流水线编排 / 接力卡 / 续跑 / 角色清单齐全。
