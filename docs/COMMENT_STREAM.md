# 评论流统一读取入口（comment_stream · Issue #166）

> 一句话：读 Issue/PR 评论流**只用** `comment_stream.read_comments()`——它默认读全量，
> 不让 CNB 接口的默认 `page_size=10` 把你的判据悄悄截断。

## 为什么有它

CNB 评论接口**默认 `page_size=10`**。不带分页读评论流 = **静默截断**：HTTP 200、内容合法、
条数看起来正常，但读到的"最新一条"其实是 10 条之前的一条。

它污染的是**派发前置判据**——「上游是否已回执」「评审链是否悬空」。真实案例（PR #161）：
架构·经理裸调读到末条 18:38Z，误判"之后零评论 → 链悬空 → merge_ready 失真"，于是补发 L3
派发卡、触发评审/测试重跑一轮；实况该 PR 已有 75 条评论、18:38Z 后 65 条，链早已闭环。
→ 无效派发 + 无谓构建损耗，与 #150「减 CPU 损耗」、#74「防无效努力」正面对冲。

**不靠自觉，靠机制**（AGENTS.md）：默认全量 + 元信息可核验 + 防退化断言。

## 用法

```python
from comment_stream import read_comments, comment_meta, has_receipt

r = read_comments(kind="pulls", number=161, repo="dongdongxiaozu/dongjiagoushi")
r["comments"], r["count"], r["pages"], r["complete"]   # 默认 page_size=100 + 翻页取尽
comment_meta(r)                                        # 紧凑元信息
has_receipt(r, role="架构·开发")                        # 读取侧回执判定
```

CLI：

```bash
python -m comment_stream --kind pulls --number 161            # 人可读摘要
python -m comment_stream --kind issues --number 166 --days 3  # 只看近 3 天
python -m comment_stream --kind pulls --number 161 --json     # 机器消费
python -m comment_stream --kind pulls --number 161 --check-receipt --role 架构·开发
```

`--check-receipt` 是「上游到底回执没有」的**确定性问法**：命中回执退出码 0；
读不全又没命中退出码 **2**（区分「确定未回执」与「没读全，不知道」），不谎报。

## 契约

| 字段 | 含义 |
|------|------|
| `count` | 实际取回条数 |
| `pages` | 实际翻了几页 |
| `page_size` | 显式发出的页大小（绝不依赖接口默认） |
| `has_more` | 是否还有下一页 |
| `complete` | **确定读全了**（未触末页且未撞翻页上限） |
| `truncated` | 未读全（显式暴露，不许当"读全了"用） |
| `source` | 固定 `comment_stream.read_comments`（标识走了统一入口） |

`has_receipt()` 在 `complete=False` 且未命中回执时返回 `degraded=True`——**读不全时
不谎报"未回执"**，上层须先修读取侧再判。

## 接线

- `dispatch_engine._cloud_receipt()`：云端语境按 Issue/PR 评论流核 `[接单]` 回执，
  走本入口读全量；读取失败/未读全进 `degraded`，不静默判"未回执"。
  与 `_has_receipt()`（本地 progress 事件）双轨互补，见 `docs/DISPATCH_DEPTH.md` §八。
- **`dispatch_engine.receipt_verify()`（实时核验·双轨合并）**：`dispatch_verify()` 是
  派发**瞬间**的闸门（只查本地 progress 台账）；真实唤醒多发生在云端，台账不会同步
  回本地。`receipt_verify()` 一次把两轨都看了再下结论：

  | 本地台账 | 云端评论流（读全） | 结论 |
  |---|---|---|
  | 已回执 | 任意 | `receipt=True`（channels=local） |
  | 无 | 已回执 | `receipt=True`（channels=cloud） |
  | 无 | 确定无回执 | `receipt=False`（确定性未回执） |
  | 无 | 读不全 | `receipt=False` + **`degraded`**（不得断言链悬空） |

  合并原则只有一条：**读不全就闭嘴**——显式 `degraded`，不当"未回执"用。
  已挂到 `DispatchAbility.receipt_verify` / `BaseRole.receipt_verify`，全员可用。
- 离线可测：传输层可注入（`transport=` 参数），夹具模拟"默认 10 条"的假 API。

## 防退化

`local-agent/tests/test_comment_stream.{sh,py}`（8 组信号灯）用「评论数 89 > 默认页大小
10」的夹具锁死：**裸调只读到 10 条 → 漏掉尾部回执（假阴性 RED）**，入口读到全量纠正。
绕过入口的写法一旦回潮，信号灯即红。

第 7/8 组把"不谎报"也锁死：读不全时 `receipt_verify` 必须 `degraded`、
`--check-receipt` 必须退出码 2——**允许"不知道"，禁止"不知道却说没有"**。
