# dev-standard · 开发规范体系模块

把「开发规范」从零散人肉约定升级为**一套完整体系**（Issue #83）。

## 为什么需要

- 现有规范（AGENTS.md 协作规则 / LABEL_SPECS 标签 / REVIEW_DISPOSITION 评审）
  是**碎片化的点**——各自独立、无统一入口、无法被开发 agent 程序化遵循；
- 需要**独立模块**（可各处引用）+ **深度绑定开发过程** + 开发体系可快速遵循的机制；
- 规范检查必须是**确定性**的（非 LLM 判断），杜绝"AI 自判合规"；
- 本身应是一套**体系**，不是孤立点。

## 模块组成

| 文件 | 职责 |
|------|------|
| `specs.py` | 规范条目注册表（唯一事实源） |
| `checker.py` | 确定性规范检查器 |
| `ability.py` | StandardAbility 全员能力 |
| `mcp.py` | MCP 工具暴露层 |
| `cli.py` | CLI 接口（脚本/CI 调用） |
| `rules.md` | AGENTS.md 引用的规范规则 |

## 能力接口（BaseRole 已挂载）

```python
role.list_standards(level="L1")          # 列出规范
role.get_standard("S01")                 # 取单条规范
role.get_enforced_specs("pre_pr")        # 某阶段强制规范
role.check_standard(target)              # 合规检查（确定性）
role.check_pr(pr_info)                   # PR 规范检查
role.check_code(file, repo_path)         # 代码规范检查
role.check_deliver(deliver_info)         # 交付规范检查
role.report_compliance(entity, results)  # 合规报告并留痕
```

## CLI（MCP 管线）

```bash
python -m dev_standard.cli list --level L1
python -m dev_standard.cli enforced --stage pre_pr
python -m dev_standard.cli check-pr --target main --source auto/x --test-files tests/a.sh --docs-files docs/A.md
python -m dev_standard.cli check-code --file local-agent/x.py
python -m dev_standard.cli check-all --target '{"pr_info": {...}}'
```

## 规范分级

- **L1 必做**（hard · 阻断）：结构 S01-S05 / 代码 C01-C02 / 文档 D01 / 流程 P01-P02 / 质量 Q01
- **L2 推荐**（soft · 警告）：代码 C03 / 质量 Q02
- **L3 可选**（提示）：预留扩展

详见 `docs/DEV_STANDARD.md`（体系设计）与 `rules.md`（规则绑定）。

## MCP 宿主接入（M5 · Issue #83）

把 `standard.*` 工具接入可运行宿主，供外部宿主程序化调用：

```python
from dev_standard import get_host
host = get_host("开发")
host.register_tools()                 # 工具清单（供宿主注册）
host.call("standard.summary", {})     # 按名调用
host.call("standard.enforced", {"stage": "pre_pr"})
host.overview()                        # 宿主接入俯瞰
# host.serve(port=8701)               # 起 JSON host 服务（POST /rpc）
```

CLI / CI：

```bash
python -m dev_standard.host list                  # 宿主工具清单
python -m dev_standard.host call standard.summary '{}'
python -m dev_standard.host serve --port 8701     # 起 JSON host 服务
# CI 接线（hard 失败 → 阻断流水线）
bash scripts/standard-check.sh check-pr --target main --source auto/x-1 \
    --test-files "tests/a.sh" --docs-files "docs/A.md"
bash scripts/standard-check.sh check-code --file local-agent/x.py
```

调用契约与 MCP 管线一致：`standard.*` 工具名 + params JSON → `{ok, data/error}`。
