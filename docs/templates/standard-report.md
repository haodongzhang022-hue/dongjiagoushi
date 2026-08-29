# 开发规范合规报告

> 实体: `{entity}` · 操作方: `{operator}` · 生成时间: `{time}`

## 结论: **{overall}**

- 总检查: {total}  通过: {passed}  硬失败(hard): {hard_fail}  软失败(soft): {soft_fail}

## 🔴 硬失败（阻断 · 须整改后重新提交）

- `S01` [模块独立成 PR，base 为 main] {details}
- `C01` [错误处理显式（不吞异常）] {details}

## 🟡 软失败（警告）

- `C03` [不留未引用 import / 死代码] {details}

## ✅ 通过项

- `S02` [按功能域解耦] ✅
- `S05` [每个 PR 自含测试 + 文档] ✅

## 判定说明

- 检查器为**确定性代码**（`StandardChecker`），非 LLM 判断；
- 有 hard 失败即 **blocked**（`blocked_on: standard_violation`），须整改后重新走流程；
- 合规留痕写入 archives（kind=`standard_compliance`），可回溯。
