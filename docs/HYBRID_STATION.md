# 站点锚定模型（StationAnchor · Issue #90 M1-M3）

> 版本：v1.0 · 2026-08-31 · 对应 Issue #90「云端和本地协同时候的分工问题」
> 定位：云端 @架构·总师 的「地铁站点模型」M1-M3 的**本地可运行落地**——
> 让云端/本地各执一份**可重放的版本基准（站点）**，锚定版本防漂移，
> 漂移后产**迁移重放计划**，保证两端一致。
> 载体：`local-agent/hybrid/station.py`（含 M4 缓存联动 + M5 评审闸门）。

---

## 一、为什么需要站点锚定

云端与本地各自演进（本地改代码、云端改架构），**不锚定就会漂移**——
两端 commit 对不上，合并冲突、验收失焦、上下文错位。地铁站点模型提出：

- **M1 station（站点）**：把「某个 git 分支/tag 时间点」登记为一个**站点**，
  站点 = 一份可重放的版本基准，天然锚定不漂移。
- **M2 anchor（锚定）**：把某时点的 commit 锚定为**协同基准**，写锚点记录；
  之后所有变更都相对该锚点计算。
- **M3 replay（重放）**：两端锚点之间若有漂移，产出**迁移重放计划**
  （rebase/merge 顺序），在一侧重放另一侧变更，保证一致。

---

## 二、CLI 用法

```bash
python3 -m hybrid.cli station list                          # 站点登记总览
python3 -m hybrid.cli station anchor --role local           # 锚定当前 git HEAD
python3 -m hybrid.cli station anchor --role cloud --commit abc123 --tag v2
python3 -m hybrid.cli station plan --from-role cloud --to-role local   # 漂移→重放计划
python3 -m hybrid.cli station replay --from-role cloud --to-role local # 演练（默认 dry）
python3 -m hybrid.cli station cache --role local            # 站点级构建缓存键
python3 -m hybrid.cli station review --role local --verdict fix_bug   # 评审轮次记账
python3 -m hybrid.cli station review --role local --reset   # 通过后复位
```

---

## 三、模块设计

### 3.1 M1 station（站点登记）

`register_station(role, branch, commit, tag, note)` / `get_station(role)` /
`list_stations()`。role ∈ `cloud` / `local`（可扩展 phone/vm/sandbox）。
每站点存：branch / commit / tag / ts / seq / note。

### 3.2 M2 anchor（版本锚定）

`anchor(role, branch?, commit?, tag, note)`：
- 不传 branch/commit 时**自动探测当前 git HEAD**（分支 + commit）；
- 写锚点记录（含单调 `seq`，同一秒内也确定先后）；
- 锚点即协同基准，防两端漂移。

### 3.3 M3 replay（迁移重放）

`replay_plan(from_role, to_role)` 返回：
`{base, target, status, steps, drift}`：
- `status`：`in_sync`（两端一致）/ `behind`（目标落后需重放）/ `ahead`（目标领先）
- `steps`：git diff 出的变更提交序列（`git log base..target`）
- 漂移方向判定：git diff 优先；离线/伪造 commit 时用锚点 `seq` 先后判序

`replay_apply(from_role, to_role, dry=True)`：
- 默认 **dry 演练**，只打印计划不真改 git；
- `dry=False` 对目标站点所在 git 做 rebase 到源（⚠️ 会改历史，慎用）。

### 3.4 M4 build-cache 联动

`build_cache_key(role, suffix="tests")`：`role/commit[:12]/tree[:8]/suffix`。
缓存键随锚点 commit/tree **变化而变化** → 锚点更新即缓存失效，
天然联动 `hybrid/cache.FingerprintCache`（站点级构建缓存）。

### 3.5 M5 review-gate（评审闸门）

`review_round(role, verdict)` / `review_status(role)` / `review_reset(role)`：
- 每轮评审记账（rounds + verdicts）；
- 达 `max_review_rounds`（默认 **5 轮**）即**熔断** → `fused=True`、
  `gate=human_cp3`（强制人类 ⏸CP3 拍板，不再无限循环）；
- 评审通过后 `review_reset` 复位轮次。

---

## 四、数据口径（统一）

| 字段 | 含义 |
| --- | --- |
| `role` | 站点角色（cloud/local/...） |
| `branch` | 站点 git 分支 |
| `commit` | 站点锚定 commit（全量 hash） |
| `seq` | 锚定单调序号（漂移方向判定） |
| `ts` | 锚定时间戳（ISO） |
| `gate` | 评审闸门状态（open / human_cp3） |

---

## 五、测试

```bash
bash local-agent/tests/test_hybrid_station.sh
```

预期 `PASS=12 FAIL=0`，覆盖 M1-M5 全部语义（站点登记 / 锚定 / 漂移判定 /
重放演练 / 缓存键联动 / 评审熔断复位）。

## 六、与 CLOUD_LOCAL_COOP.md 衔接

| CLOUD_LOCAL_COOP 模块 | 状态 | 本地落地 |
| --- | --- | --- |
| M1 station | 云端设计中 | **本模块落地**（站点登记） |
| M2 anchor | 云端设计中 | **本模块落地**（版本锚定 anti-drift） |
| M3 replay | 云端设计中 | **本模块落地**（迁移重放 plan/dry） |
| M4 build-cache | 云端设计中 | **本模块联动**（站点级缓存键） |
| M5 review-gate | 云端设计中 | **本模块落地**（≤5 轮熔断） |
| M6 quota-guard | 已落地 | hybrid/quota.py（上次已交付） |
