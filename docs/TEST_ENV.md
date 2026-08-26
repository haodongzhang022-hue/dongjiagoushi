# 测试环境说明（TEST_ENV · T4）

> 本文档记录 dongjiagoushi 框架测试的**运行环境差异**，避免把「环境限制」误判为「代码缺陷」。归属 T4「测试环境依赖加固」（Issue #8）。

## 一、两套环境

| 环境 | 运行时 | cnb 云凭据 | 知识库(RAG) | 用途 |
|------|--------|-----------|-------------|------|
| **云 CI**（cnb.cool .cnb.yml） | 有 python3 | 有 | 有 | 官方信号灯，唯一验收口径 |
| **本地沙盒**（开发/演示） | 常缺 python3 | 无 | 无 | 静态检查/文档编辑，不能全量验证 |

## 二、本沙盒已确认的环境限制（非代码缺陷）

| 测试脚本 | 失败项 | 根因（环境） |
|----------|--------|-------------|
| `local-agent/tests/*.sh`（12 个） | 全部 | `python3: command not found` |
| `tests/test_doc_consistency.sh` | embedding dim 校验(2) | 缺 python3，无法计算真实维度 |
| `tests/test_functional_links.sh` | F1/F2(cnb API) + F3(RAG) | 无 cnb 凭据 + 云知识库未建（仅云可用） |

> 以上在云 CI（装 python3 + 有凭据 + 已建知识库）后应转绿。本地沙盒**不能**据此判定代码有缺陷。

## 三、验证指引

1. **云 CI 全绿 = 信号灯放行**：以 `.cnb.yml` test 阶段为准，勿用沙盒结果代替。
2. **T4 加固项**：
   - 云 CI 安装 python3 依赖（`pip install -r local-agent/requirements.txt` + `src/memory/requirements.txt`）；
   - functional-links 依赖云凭据 + 已入库知识库，由 T1 前置保障；
   - 本沙盒如需本地验证，需自行安装 python3 + LanceDB。
3. **沙盒可跑的**：`tests/test_architect_system.sh`、`tests/test_relay_workflow.sh`（纯 bash，本沙盒已验证 PASS）。
