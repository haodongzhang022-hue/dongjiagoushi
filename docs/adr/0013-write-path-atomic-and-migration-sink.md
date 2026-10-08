# ADR-0013：写路径原子化用「事务包裹 + 冲突提案独立编号」，迁移下沉到建表入口

- 状态：Accepted
- 决策日期：2026-10-08
- 相关：Issue（多 Agent 协作核心层）、`docs/COLLAB_ENGINE.md` §六、`local-agent/collab/engine.py`、
  `local-agent/data/migrate.py`、feature-verify `collab/写时状态中介`

## 背景
`collab` 的版本整合（④）宣称「多 agent 改同一东西不冲突」，但写路径
`latest_version()` → `add_version()` 是**两步无事务**，冲突检测只是「事后比版本号」：

- 两个 agent 同基于 v3 提交 → 都读到 `latest=3` → 都写 `vno=4`
  → sqlite 下直接 `UNIQUE constraint failed` / `database is locked`（16 线程实测 15 个失败）；
- 冲突分支写的是 `latest + 1`（**正数**），而 `latest_version()` 是 `MAX(vno)` 不分 status
  → **一次冲突把该实体永久卡死**：后续基于真实主线的提交都被误判 conflict；
- `versions` 唯一键不含 `branch`，但 `latest_version(loc, branch)` 分 branch 取 max
  → 不同分支写同一 vno 直接撞键，branch 维度形同虚设；
- `conflicts()` 走 `versions_of` 的 `vno DESC LIMIT 50` 窗口，冲突提案排在最后
  → 主线版本 ≥50 后冲突**静默丢失**，受理闸门拿不到提案。

这三条都满足 ADR 三条铁律（难反转 / 无上下文会困惑 / 有真实取舍）：它决定了
「并发写是撞键报错还是确定性判冲突」，改法一旦铺开，回到「无事务 + 事后 merge」会
重新引入静默互踩。

## 决策
1. **写路径原子化**：`update_entity()` / `update_entity_with_base()` 的「读 latest → 写新版本」
   整体进 `db.transaction()`；sqlite 最外层用 `BEGIN IMMEDIATE` 立即取写锁。
   并发结果从「撞键报错」变为**确定性**：恰好 1 个成功 + N-1 个 conflict + 0 异常。
2. **冲突提案独立编号空间**：冲突版本写**负数 vno**（`add_conflict_version`），
   `latest_version()` 只认 `vno>0 AND status!='conflict'`；`conflicts()` 按
   `status='conflict'` 直查（`idx_versions_status`），不走排序窗口。
3. **唯一键补 branch 维度**：`UNIQUE(entity_loc, branch, vno)`——不同分支各自编号空间。
4. **迁移下沉到 `schema.init_schema()`**：旧库（旧唯一键 / 冲突占正数 vno）由
   `data/migrate.py` 幂等迁移（建新表→拷数据→换名→重建索引；冲突行搬负数编号），
   并把 `migrate()` 挂到建表函数末尾——全仓 11 处入口只要建表就会升级既有库，
   **不依赖各自记得先调 `admin.init()`**（此前 dispatcher 等 9 处入口绕过迁移，旧库仍写坏）。
5. **迁移与标记同事务**：`_mark()` 与迁移步骤同一事务，杜绝「已记 applied 但表不存在」半写。
5b. **健康库快路径（复评 🔴1 返工）**：`_run_migrations()` 先查已应用标记，**M1/M2 均已应用
   即直接返回、不开写事务、不跑任何 DDL**。原因：迁移下沉后 `init_schema()` 成了读热路径的
   必经点（gid / sentinel / dispatcher / webui），若无条件 `BEGIN IMMEDIATE`，一次纯读也要
   抢写锁，并发长写事务下被阻塞到 `busy_timeout` 抛 `database is locked`（读路径本不该受写锁
   影响）；同理已建表时 `CREATE TABLE IF NOT EXISTS` 也会取写锁，必须一并跳过。
   判据用 `schema_migrations` 标记（与迁移步骤同事务，标记在即表在），不用建表探测。
6. **事务收尾路径唯一**：`_SQLite_Tx.commit()/rollback()/__exit__` 共用 `_finish()`，
   `tx_depth` 只在最外层归零才真正提交——非 `with` 用法不再泄漏计数、
   不再让后续事务静默失去原子性。嵌套事务里的**显式** `commit()/rollback()` 直接抛错
   （sqlite 无真嵌套，静默吞掉会让人以为回滚了、其实落库）。
7. **热路径只读纪律**：`migrate()` 先**只读**探测 pending（`pending()`），
   **只在确有 pending 时才开事务**。`init_schema()` 在 webui（每请求）/ gid（每操作）
   等热路径高频调用，无条件 `BEGIN IMMEDIATE` 会把只读语义的操作串行化，
   他人持写锁时直接抛 `database is locked`（复评 🔴5）。
8. **旧表先升再建索引**：`init_schema()` 在建表 DDL 之前调 `migrate.ensure_versions_upgraded()`
   ——索引 DDL 引用 `branch`/`status` 列，旧库没这列时建索引会先崩、迁移根本没机会跑。
9. **迁移建表引用常量**：`migrate_m1_unique_branch()` 引用 `schema.VERSIONS_TABLE_DDL` /
   `VERSIONS_INDEX_DDL`，不再靠 DDL 字符串匹配（DDL 一改格式就静默失配）。
10. **`--dry-run`**：`data-cli migrate --dry-run` 只报告待迁移项、不落写（大库先看代价）。

备选方案（未选）：
- 只加唯一约束兜底、不改事务 → 把竞态变成**报错**而非**判冲突**，调用方拿不到 conflict 语义，不做；
- 用 git worktree 式隔离工作区 → 把冲突推迟到 merge 时解决，恢复成本高（且违反 ADR-0005 的解耦意图）；
- 迁移只在 `admin.init()` 里跑 → 正是本次要修的「9 处入口绕过」缺陷，不采用。

## 后果（权衡）
- 好处：并发写从「撞键 / 锁死」变为确定性判冲突；冲突不再污染主线、不再静默丢失；
  旧库经任意入口自动升级；事务 API 自洽（`tx_depth` 无泄漏）。
  已由 `test_collab.sh` 第 7 组、`test_data_layer.sh` 第 8/9/10 组、
  feature-verify `collab/写时状态中介`（Then-1~5）锁死。第 9 组 / Then-5 专门锁
  「健康库读热路径不取写锁」：另一连接持写锁时纯读 gid / `init_schema()` 必须成功，
  去掉快路径即转红。
- 代价：写路径串行化（`BEGIN IMMEDIATE`），高并发下冲突方要重试/rebase——
  这是「一致性优先」的自觉取舍；迁移需要一次建表/拷数据（大库有成本，先 `data-cli migrate --dry-run` 看代价）。
- 难反转：一旦依赖负数编号语义与 branch 维度唯一键，回退会让既有冲突提案与分支版本错位。
