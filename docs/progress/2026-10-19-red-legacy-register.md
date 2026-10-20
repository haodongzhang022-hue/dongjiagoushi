# 红色遗留登记（2026-10-19 · PR #178 收尾前）

> 起因：人类要求「记录好了红的部分遗留的情况，之后可能对接到本地时候再解决，记录一下，带着时间」。
> 本文只做一件事：把**所有已知红/债/边界**逐条钉在时间线上，标明**归属 Issue** 与**解除条件**。
> 不写"基本没问题"这种话——没验的就是没验。

## 一、口径（怎么算"红"）

- **绿灯**：本机真跑、退出码 0、断言有变异牙（回退即红）。
- **红灯**：本机真跑 → 非 0 退出 / 断言失败。
- **未验**：本机根本没跑（缺环境 / 缺依赖 / 缺权限）→ **一律记为遗留，不折算成绿**。

## 二、2026-10-19 本机真跑结果（PR #178 头 `78fcf51`）

| 套件 | 结果 | 备注 |
|---|---|---|
| `tests/test_feature_verify.sh` | 🟢 PASS=65 FAIL=0 SKIP=0 | T5a–T5f/T25a–T25d 全过 |
| `scripts/feature-verify.sh --all` | 🟢 PASS=10 FAIL=0 TDD=0 | pre-existing 红灯**本轮已清** |
| `scripts/feature-regress.sh` | 🟢 rc=0 | 逐功能明细正常 |
| `tests/test_doc_consistency.sh` | 🟢 PASS=101 FAIL=0 | ADR-0013 口径锁对象正确 |
| `local-agent/tests/test_data_layer.sh` | 🟢 全通过 | 含组8b/8c、组10 真 PG 对照（sqlalchemy 2.1.5） |
| `local-agent/tests/test_collab.sh` | 🟢 全通过 | 组7 `tx_depth` 归零 + 嵌套显式 rollback 抛错 |
| `local-agent/tests/test_dsh_adapter.sh` | 🟢 pass=18 fail=0 | |
| `local-agent/tests/test_dispatch_verify.sh` | 🟢 ALL PASS | |

**结论：PR #178 改动面内没有未决红灯。** 以下是**改动面外 / 已知边界 / 未验**的遗留。

## 三、红色遗留登记（按时间倒序）

### R-01 · 2026-10-19 · 遗弃兜底会静默丢掉外层那一轮写入（已知边界，不修 → 跟踪 ADR-0013）

- **现象**：正常嵌套事务 + 同时存在遗弃残骸的极端组合下，`_reclaim_abandoned_tx()` 把计数一次性归零，
  **外层那一轮写入被静默丢弃且不报错**（`commit()` 照走、数据没了），下一轮事务自然复位。
- **为何不修**：判据刻意不依赖 `conn.in_transaction`（CPython sqlite3 在 `isolation_level=''` 下
  `in_transaction` 常态为 True，拿它当判据会把正常状态误判成遗弃、反而丢掉最外层 commit）。
  改判据的代价 > 该极端组合的实际风险。
- **归属**：ADR-0013 跟踪项（写路径原子化）。
- **解除条件**：真 PG 写路径闭环时一并收口（届时事务态由驱动显式暴露，可用可靠判据替代）。

### R-02 · 2026-10-19 · 真 PG 写路径端到端未闭环（未验，非失败）

- **现象**：`db.execute` 在 PG/MySQL 下每次另开连接事务，事务内调 `db.execute()` / 嵌套 `db.transaction()`
  会 fail-loud 抛错（拒绝静默半工作）。即**接口层已抽象，写路径闭环未验**。
- **为何不修**：本机无 PG 实例，仓库当前无 PG CI 作业——**不能把"没跑"说成"通过"**。
- **归属**：ADR-0013「真 PG 写路径闭环为跟踪项」。
- **解除条件**：接入 PG 服务后真跑 `test_data_layer.sh`（组 10 之外的 PG 写路径用例需补），
  届时文档中「无缝切换」表述一并改准。

### R-03 · 2026-10-19 · `test_data_layer` 组 10 只验方言，PG 语义未验

- **现象**：组 10 是 sqlalchemy 适配层**冒烟**（sqlite 方言 + 真 PG URL 反向夹逼），
  **不代表 PG 语义已验证**。
- **归属**：同 R-02（ADR-0013）。
- **解除条件**：同 R-02。

### R-04 · 2026-10-19 · 测试直 import `data.db` 私有符号

- **现状**：上一轮已新增公开探针 `db.tx_depth()` / `db.alive_tx_frames()` /
  `db.reclaim_abandoned_tx()`，`test_data_layer` 不再抠 `_depth` / `_alive_frames`；
  但部分变异牙仍直接引用内部函数名（作牙齿测试可接受）。
- **归属**：PR #178 遗留 🟡（评审两轮点名，非阻断）。
- **解除条件**：内部实现重构前先跑 `test_data_layer`，红则同步改测试；不单独开单。

### R-05 · 2026-10-19 · registry `covers` 只归一化了一处

- **现象**：`local-agent/hybrid/registry.json` 5 条改全路径 + `embedding/` 目录 → `.py` 文件已修，
  **其余条目未全量扫裸名/错路径**。
- **归属**：PR #178 遗留 🟡2。
- **解除条件**：T25 已具备检测能力（T25a/T25b/T25c/T25d），排定期跑即可防再生；
  全量扫描为可选清理，不影响闸门正确性。

### R-06 · 2026-10-19 · `.tdd` / `.tdd.verified` 判据文件当前未启用

- **现状**：TDD 两阶段判据已接线（T5e/T5f 真跑主执行器），但仓库当前 `TDD=0`——
  没有任何模块被声明为 TDD 待实现，**该分支在生产数据上没有走过**。
- **归属**：Issue #165 P2 收口的**已知空跑面**。
- **解除条件**：真正采用测试先行的模块出现时把模块名写进 `.tdd`，观察 `--all` 是否记 TDD 账不阻断；
  首次真实使用前视为未验。

### R-07 · 2026-10-19 · Issue #166「统一读评论流入口」— **2026-10-20 已解除**

- **原状**：跨页读评论（`cnb ... --page`）需手动翻页，统一入口不存在。
- **解除证据**：PR #188 merged（`66a714a`）→ `local-agent/comment_stream/` 落在 `origin/main`；
  `bash local-agent/tests/test_comment_stream.sh` 真跑 **6/6 绿**（含「裸调只读到 10 条 → RED」
  防退化断言）；`dispatch_engine._cloud_receipt` 已接线（读全判回执 / 读不全判 degraded）。
- **状态**：✅ 已解除，不再是遗留。

### R-08 · 2026-10-19 · Issue #177 推送权限 403

- **现状**：`repo-code:rw` 缺失导致 `git push` 403，改动只能停在本地。
- **归属**：Issue #177。
- **解除条件**：人类授予推送权限，或改由有权限通道提交。

## 四、对接本地时要还的（给未来的自己）

上面 8 条里，**真会咬人的只有 R-01 / R-02 / R-03 三条**，且都挂在 ADR-0013 名下；
其余 R-04~R-08 是债与未开工项，不会让当前闸门变假绿。

对接本地环境（有 PG、有独立 python 环境）时按此顺序处理：R-02 → R-03 → R-01 → R-06。
