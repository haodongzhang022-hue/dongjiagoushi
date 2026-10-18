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
11. **远程后端事务内 `db.execute` fail-loud（复评 🔴 返工·择「显式收口」而非「实现完整 PG」）**：
    `db.execute()` 在 PG/MySQL 下每次都在新连接上 `eng.begin()` 另开事务，**无法复用当前
    `db.transaction()` 的连接**——真 PG 17.11 实测：`with db.transaction(): db.execute(INSERT); raise`
    **残留 1 行**（静默失去原子性），而 `tx.execute()` 路径回滚干净。本轮**不实现完整 PG 写路径**
    （非默认后端、CI 全走 sqlite、基线更差），而是**显式收口**：远程后端在事务内调用
    `db.execute()` / 嵌套 `db.transaction()` **直接抛 `RuntimeError`**（fail-loud，拒绝静默半工作），
    事务内一律走 `tx.execute()`；同时修正 `db.py` 模块 docstring 与 `DATA_ARCHITECTURE.md`
    的「无缝切换」表述为「接口层已抽象，**写路径闭环为跟踪项**」。
12. **组 10 假绿收口（复评 🔴 返工）**：`test_data_layer.sh` 第 10 组名为「pg 分支」却用
    `DB_URL=sqlite://`（真实方言 = sqlite），从未验证 PG 语义。收口为
    「**sqlalchemy 适配层冒烟（sqlite 方言 · PG 语义未验证）**」+ 组内**显式断言
    `eng.dialect.name == 'sqlite'`**（把假绿暴露在测试里），并补事务内 `db.execute`/嵌套的
    fail-loud 断言。
13. **`needs_m1()` 合并判据（复评 🟡2 一行硬化）**：唯一键缺 branch **或** 缺 `branch`/`status`
    列，任一成立即需重建。否则「唯一键已含 branch、但缺 status 列」的库（手工改库/第三方库形态）
    会被判「无需迁移」跳过，`idx_versions_status` 照样撞 `no such column` 崩在入口。

备选方案（未选）：
- 只加唯一约束兜底、不改事务 → 把竞态变成**报错**而非**判冲突**，调用方拿不到 conflict 语义，不做；
- 用 git worktree 式隔离工作区 → 把冲突推迟到 merge 时解决，恢复成本高（且违反 ADR-0005 的解耦意图）；
- 迁移只在 `admin.init()` 里跑 → 正是本次要修的「9 处入口绕过」缺陷，不采用。

## 后果（权衡）
- 好处：并发写从「撞键 / 锁死」变为确定性判冲突；冲突不再污染主线、不再静默丢失；
  旧库经任意入口自动升级；事务 API 自洽（`tx_depth` 无泄漏）。
  已由 `test_collab.sh` 第 7 组、`test_data_layer.sh` 第 8/9/10 组、
  feature-verify `collab/写时状态中介`（Then-1~11）锁死。第 9 组 / Then-5 专门锁
  「健康库读热路径不取写锁」：另一连接持写锁时纯读 gid / `init_schema()` 必须成功，
  去掉快路径即转红。
- 代价：写路径串行化（`BEGIN IMMEDIATE`），高并发下冲突方要重试/rebase——
  这是「一致性优先」的自觉取舍；迁移需要一次建表/拷数据（大库有成本，先 `data-cli migrate --dry-run` 看代价）。
- 难反转：一旦依赖负数编号语义与 branch 维度唯一键，回退会让既有冲突提案与分支版本错位。

## CI 依赖接线（CI 失败修复）
- `feature-verify` 的 Then-6（远程写路径 fail-loud）依赖 `sqlalchemy`。原先该作业
  不装依赖，只在本地开发机（已装 sqlalchemy）为绿 → **CI 与本地不一致**：CI 上
  `db.transaction()` 因缺 sqlalchemy 抛「需安装 sqlalchemy」的 `RuntimeError`，
  语义不符 → 闸门红（本 PR 修复）。
- 修法：① `local-agent/requirements.txt` 显式声明 `sqlalchemy>=2.0`；
  ② `.cnb.yml` feature-verify 作业 `pip install -r local-agent/requirements.txt`
  并 `import sqlalchemy` 校验，**装不上即作业失败，不静默跳过**（避免信号灯在云端
  空转变假绿）；③ 脚本内加环境守卫（无 sqlalchemy 优雅跳过，对齐 README 约定，
  保本地可跑）；④ `test_doc_consistency.sh` 加三条断言锁死「依赖声明 + CI 安装 +
  脚本守卫」三者，防再次静默退化。

## 跟踪项（本 PR 不实现 · 另开 Issue）
- **真 PG 写路径端到端闭环**：① `db.execute` 在远程后端复用当前事务连接（真闭环）；
  ② PG 方言 DDL（`SERIAL`/`BIGINT`，替换 `AUTOINCREMENT`）；③ 参数风格（`?` → `%(name)s`/`:name`）。
  现状：`init_schema()` 在真 PG 17.11 上直接 `SyntaxError: AUTOINCREMENT`，`db.query("... ?", ...)`
  抛 `ArgumentError`——**PG 端到端不可用**（非静默损坏，是直接失败）。本 PR 只保证
  **不再让假象留白**（fail-loud + 文档显式暴露），不承诺 PG 可用。
