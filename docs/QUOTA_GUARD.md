# M6 · 云端核时配额护栏（QuotaGuard）

> 模块：`local-agent/hybrid/quota.py` · 版本：v1.0 · 2026-08-31
> 归属：Issue #90「云端和本地协同时候的分工问题」M6 quota-guard

## 定位

云端 CPU 构建贵（160 核时/月免费 + 已超额付费），token 够用，本地 CPU 便宜。
QuotaGuard 是**云端核时配额护栏**：按任务计量云端核时消耗 + 月度免费额度护栏 + 三态哨兵，
在超支前预警、超支后告警，防止"单日超月配额"的异常消耗。

## 设计语义

- 免费额度：`FREE_MONTHLY_CORE_MINUTES = 160`（核·分钟/月，与云端统一口径）。
- 三态哨兵：`ok`（<80%）→ `warning`（≥80%）→ `over`（≥100% 触发告警）。
- **本地化节省自动抵扣**：`credit_localized` 把本地跑掉的 CPU 测试（原本会消耗云端核时）
  折算成抵扣，账本真实反映云端实付——本地化 696 核·分钟已自动抵扣。
- **跨月自动滚动**：账本随月份滚动，保留上月摘要，不混淆月度额度。

## 公开接口

| 方法 | 说明 |
| --- | --- |
| `meter_consume(task_id, amount, note="")` | 记录一次云端核时消耗，返回当前三态 |
| `credit_localized(amount, note="")` | 本地化节省抵扣云端账本 |
| `quota_status()` | 返回 `{state, monthly_used, free_minutes, ratio, localized_saved, net_used, month}` |
| `audit()` | 完整账本（任务粒度 + 月度 + 上月） |

模块导出：`hybrid.QuotaGuard` / `hybrid.default_guard`。

## CLI 用法

```bash
python3 -m hybrid.cli quota status         # ok / warning / over 三态
python3 -m hybrid.cli quota meter --task build-ci --amount 20   # 云端消耗记账
python3 -m hybrid.cli quota credit --amount 696                 # 本地化节省抵扣
python3 -m hybrid.cli quota audit          # 完整账本
```

`scripts/local-exec.sh` 已接线：每次本地一键执行后自动 `quota credit` 抵扣 + `status` 核验。

## 测试

```bash
bash local-agent/tests/test_quota_guard.sh
```
覆盖：模块存在 / 常量 / 三态 / 计耗+抵扣 / 跨月 / CLI 接线 / __init__ 导出 / local-exec 接线 / 真实功能（python 可用时）。
