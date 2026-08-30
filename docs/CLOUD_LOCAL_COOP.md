# 云端 ⇄ 本地协同机制（CLOUD_LOCAL_COOP）

> 版本：v1.0 · 2026-08-30 · 对应云端 Issue #90「云端和本地协同时候的分工问题」
> 定位：本文件是「地铁站点模型」（云端@架构·总师 M1-M6 方案）的本地落地 + 分工边界文档。
> 原则：**云端 CPU 构建贵（160 核时/月免费 + 已超额付费），token 够用，本地 CPU 便宜** —— 一切按此分工。

---

## 一、分工边界（谁能做什么）

| 工作类型 | 执行方 | 依据/工具 | 说明 |
| --- | --- | --- | --- |
| CPU 密集测试（37+ 脚本） | **本地** | `scripts/local-exec.sh`（route→run→sync→cost） | 云端已移除，本地跑 51.5s 全绿 |
| 增量/缓存/并行测试 | **本地** | hybrid selector/cache/parallel/policy | 变更感知，只跑受影响 |
| 测试结果留痕 | **本地→同步** | hybrid sync（data_layer / 降级日志） | 可审计回放 |
| 云端核时成本记账 | **本地** | hybrid quota（M6 护栏） | 160 核时免费额度账本 + 三态哨兵 |
| LLM 强相关（知识库/CodeWiki/推理） | **云端** | .cnb.yml knowledge:update 等 | 能力保留 |
| 评审（PR/Issue） | **云端** | review-gate（M5，≤5 轮熔断） | 减少唤醒与全量测试 |
| 任务声明/成果回传 | **本地→云端** | CloudBatch 批量打包 + yunduanjiaohu 协议 | 攒批一次唤醒 |
| 版本锚定/迁移重放 | **云端/本地** | station 模型（M1-M3） | 时点锚定不漂移 |

---

## 二、协同机制（触发时机与通道）

### 2.1 一键链路（本地主动）
```bash
# 本地全部活：测试 + 留痕 + 成本 + 攒批检查 + 配额记账
bash scripts/local-exec.sh --real
```
触发时机：每个本地开发轮次结束、或定时（推荐接入任务树/哨兵）。

### 2.2 云端任务声明（本地→云端）
```bash
python3 -m hybrid.cli batch enqueue "任务" --project xxx   # 本地零成本入批
python3 -m hybrid.cli batch status                          # 攒批进度
python3 -m hybrid.cli batch flush                           # 攒够一次唤醒（1 Issue 打包 N 任务）
```
触发时机：有云端任务时入批；攒够 min_tasks（默认 3）或时间窗（1h）即 flush；
**绝不单个任务单独唤醒来回**（防频繁唤醒是核心成本纪律）。

### 2.3 配额护栏（成本哨兵，M6）
```bash
python3 -m hybrid.cli quota status         # ok / warning / over 三态
python3 -m hybrid.cli quota meter --task build-ci --amount 20   # 云端消耗记账
python3 -m hybrid.cli quota credit --amount 696                 # 本地化节省抵扣
python3 -m hybrid.cli quota audit          # 完整账本
```
触发时机：每次云端构建/测试后记账；本地执行后自动抵扣 net_save；
状态 over → 哨兵告警，立即排查异常消耗（用户痛点：单日超月配额）。

### 2.4 结果同步（本地→云端留痕）
- `hybrid sync`：本地测试结果写数据层 archives/messages（source=local）；
- 数据层不可用时降级本地日志（.hybrid_sync.log），不阻断主流程；
- 云端视角：`.cnb.yml` main.push 只保留轻量自检 + LLM 强相关，全量结果以本地 sync 为准。

---

## 三、与「地铁站点模型」（Issue #90 M1-M6）的衔接

| 云端模块 | 状态 | 本地对应/落地 |
| --- | --- | --- |
| M1 station / M2 anchor / M3 replay | 云端设计中 | 本地 git 分支即站点锚（tag/分支时间点）；重放=合并序列；待云端落地后接 |
| M4 build-cache | 云端设计中 | 本地已有 FingerprintCache（hybrid/cache.py）+ PolicyEngine |
| M5 review-gate（≤5 轮） | 云端设计中 | 本地 disposition 协议已限轮次；等云端 PR 侧落地 |
| M6 quota-guard | **本地已落地** | `hybrid/quota.py` + CLI + 账本（160 核时护栏/抵扣/三态） |

---

## 四、异常处理

| 异常 | 处置 |
| --- | --- |
| 云端配额 over | quota 哨兵告警 → 立即排查昨日消耗（用户实测单日可用光一个月）→ 砍全量/频繁唤醒 |
| 本地测试失败 | worker 超时保护（300s）+ 退出码记录；成本报表 local_fail_rollback 回滚口径 |
| 数据层不可用 | sync 降级本地日志，不硬依赖 |
| WSL/Windows 环境差异 | worker `_pick_bash` + `_wsl_popen_cmd` 路径转换 + `_host_env` 读宿主变量 |
| 云端 API 不可达 | batch flush 失败保留队列，下次重试（不丢任务） |
| 跨月账本 | quota 自动滚动（保留上月摘要） |

---

## 五、验收口径

- [x] 37 CPU 测试本地全绿（51.5s），云端 0 负担
- [x] CloudBatch 攒批→一次唤醒（实测云端 Issue #30-#33）
- [x] QuotaGuard 160 核时护栏 + 本地化抵扣 + 三态
- [x] sync 留痕 + 降级路径
- [x] 本文件＝分工边界/触发时机/异常处理文档（对应云端 AC5）
- [ ] 等云端 M1-M5 落地后，接站点锚定与 build-cache 联动（联合验收）