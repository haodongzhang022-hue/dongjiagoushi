# Hybrid 资源路由模块（云原生构建-CPU 本地化）

> Issue #57 · 模块版本 `hybrid/v1.0` · agent `architect-develop/v1.0`

## 一、背景与问题

云端 CI 的 `main.push` 阶段串联执行 **37 个 CPU 密集测试脚本**（`bash tests/*.sh`
与 `bash local-agent/tests/*.sh`），这些脚本是**纯 CPU 逻辑**（跑断言、比对、模拟），
与 LLM 强相关操作无关，却在云原生构建机上计费消耗 CPU，导致**云原生构建-CPU 成本过高**。

## 二、方案：混合资源路由

把纯 CPU 逻辑**本地化执行**，云端只保留 **LLM 强相关操作**（知识库入库、CodeWiki、
AI 推理、NPC 兜底）。核心是 `HybridResourceRouter` 的路由判定：

```
云端 CI（main.push）
  ├─ 保留：knowledge:update / codewiki / npc 等 LLM 强相关操作
  └─ 移除：37 个 CPU 密集测试脚本（bash tests/*.sh + local-agent/tests/*.sh）
              ↓ 移交
本地执行（scripts/local-exec.sh → hybrid.cli）
  ├─ route   ：HybridResourceRouter 判定 local/cloud
  ├─ run     ：LocalWorker 批量本地执行
  ├─ sync    ：ResultSync 结果同步留痕（写数据层 archives/messages）
  └─ cost    ：CostMonitor 成本报表（量化节省）
```

## 三、路由判定规则

| 优先级 | 判定 | 落地 | 说明 |
|--------|------|------|------|
| 1 | 命中 `CLOUD_HINTS`（llm/knowledge/codewiki/embedding…） | **cloud** | LLM 强相关，能力保留 |
| 2 | 命中 `LOCAL_HINTS`（local/cpu/unit/test/benchmark…） | **local** | 纯 CPU 逻辑本地化 |
| 3 | 兜底 | 默认 cloud | fail-safe，不误伤 |

**成本收益**：`CostMonitor` 量化每个被判 local 的脚本原本占用的云端 CPU 核·分钟，
本地化后该笔成本归零 → `net_save`；本地失败需回滚的计入 `rollback`，保证报表口径诚实。

## 四、模块结构

```
local-agent/hybrid/
  ├─ __init__.py    显式公开接口（跨项目可复用）
  ├─ router.py      HybridResourceRouter 核心路由（local/cloud 判定）
  ├─ worker.py      LocalWorker 本地批量执行器（超时保护/dry-run）
  ├─ sync.py        ResultSync 结果同步留痕（数据层 archives/messages，降级本地日志）
  ├─ cost.py        CostMonitor 成本监测与报表（net_save/rollback/ratio）
  └─ cli.py         CLI 入口（classify/route/run/sync/cost/all）
scripts/local-exec.sh     本地执行统一入口
docs/HYBRID_RESOURCE.md   本文档
local-agent/tests/test_hybrid_*.sh   配套测试
```

**解耦设计**：各模块只通过稳定接口交互，不互相 import 实现；
数据层通过 `sync` 延迟导入，数据层不可用时降级本地日志，不硬依赖。

## 五、用法

```bash
# 本地执行完整链路（dry-run 演练）
bash scripts/local-exec.sh

# 真实执行（真跑测试）
bash scripts/local-exec.sh --real

# 只看成本报表
bash scripts/local-exec.sh --only cost

# CLI 直接调用
python3 -m hybrid.cli classify test_unit_cpu.sh llm_knowledge_update
python3 -m hybrid.cli route
python3 -m hybrid.cli all --dry
```

## 六、云端最小化改造（.cnb.yml）

云端 `main.push` 阶段**移除 37 个 CPU 密集测试命令**，仅保留 LLM 强相关操作。
被移除的测试改由 `scripts/local-exec.sh` 在本地执行，结果经 `sync` 同步留痕。

## 七、验收口径

- [x] 37 个 CPU 密集脚本可被 `HybridResourceRouter` 判定为 local
- [x] 本地执行器可批量跑通并汇总
- [x] 结果同步回数据层留痕（可回溯）
- [x] 成本报表量化节省
- [x] `.cnb.yml` 云端仅保留 LLM 强相关操作
---

## v1.1 跑通记录（2026-08-30 · Windows 本地实跑）

> 之前「没跑通测试」的根因与修复，以及新增强的云端批量打包（防频繁唤醒）。

### 修复的故障点

| 故障 | 根因 | 修复 |
| --- | --- | --- |
| F1 CRLF | 53/53 测试脚本 CRLF（core.autocrlf=true、无 .gitattributes）→ bash 报 python3\r not found | 新增 .gitattributes（*.sh text eol=lf 等），222 文件字节级转 LF |
| F2 cost 链崩溃 | route_many 对字符串入参不防御（len>2 把字符当字段），cost.report float += str 崩溃 | router 字符串→元组 + float 转换；cost 防御缺失/字符串/非 RouteDecision |
| F5/F6 Windows 执行 | bash 输出非 UTF-8 字节解码崩溃；bash.exe 是 WSL bash 不认 Windows 路径 | encoding='utf-8', errors='replace'；_pick_bash 探测 + _wsl_popen_cmd 路径转 /mnt/<盘>/... |

### 真实执行结果（2026-08-30）

```json
{ "route": {"total": 37, "local": 37, "cloud": 0},
  "run":   {"total": 37, "pass": 37, "fail": 0, "total_duration": 53.88},
  "sync":  {"synced": true, "target": "data_layer"},
  "cost":  {"total_cloud_cpu": 696.0, "localized_cpu": 696.0,
            "net_save": 696.0, "localization_ratio": 1.0} }
```

### 新增：CloudBatch 云端批量打包（batch.py）

**动机**：云端 CodeBuddy 每次唤醒有冷启动/上下文重建成本，频繁唤醒浪费云端 CPU。CPU 密集活已本地化，剩给云端的 LLM 强相关任务应**攒批**后一次唤醒处理多个。

- enqueue(title, ...)：任务入批（本地 0 成本）
- status()：攒批队列状态（ready = 攒够 min_tasks）
- flush(dry_run)：一次提交云端（默认 1 Issue 打包多任务，按任务声明协议内嵌 yaml 元数据）
- 秘钥：环境变量 cnbcooldong（实测 API 认证成功）；目标仓库 CNB_REPO 可覆盖
- CLI：python -m hybrid.cli batch enqueue|status|flush

**实测**：2 任务攒批 → 一次 flush → 云端 yunduanjiaohu#31 批量任务单创建成功。

### 一键使用

```bash
# 本地跑全部 CPU 测试 + 留痕 + 成本报表
bash scripts/local-exec.sh --real
# 或直接：
python -m hybrid.cli all --timeout 300 --batch <batch名>

# 云端任务攒批（本地零成本）→ 一次唤醒
python -m hybrid.cli batch enqueue "任务" --project xxx
python -m hybrid.cli batch status
python -m hybrid.cli batch flush     # 攒够后一次提交
```
