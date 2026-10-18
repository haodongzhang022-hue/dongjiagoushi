# dsh 适配模块（DSH_ADAPTER · dsh-adapter v0.1.0）

> 面向 DSH（**DeepSeek Harness**）新版（`0.1.6-alpha.2`）的适配模块：把架构师体系
> `local-agent/` 的能力暴露为 DSH 工具，并把"版本兼容"做成**前置闸门**。
> 触发：Issue #145「dsh 已经有新版的了，适配一下最新版本……完成适配新版」。
> 决策记录见 `docs/adr/0014-dsh-adapter-new-version.md`。

---

## 一、为什么需要"适配新版"

DSH 处于 **0.x 技术预览期**，minor/rc 间存在 schema/行为变化。更关键的是**主推形态变了**：

| 维度 | 旧（0.1.2 ~ Python SDK 主推期） | 新版（0.1.5+ · all-plugin Cordis） |
|------|-------------------------------|-----------------------------------|
| 插件模型 | Python SDK 内嵌 SEA runtime 挂载 | **一切皆插件（Cordis）**：服务/事件/副作用皆插件 |
| 工具注册 | 各宿主自定 | **`ctx.tools.register(defineTool({...}))`** 唯一入口 |
| 分发格式 | profile 内联树 | **组合包（bundle）**：`package.json` 声明 `dsh.bundle.patch` |
| 覆盖方式 | — | **有序 patch overlay**（`cordis.patch.yml` / `--patch`）按 id 定位替换 |
| 加载产物 | 源码/内联 | **只 import 包的 `main`（`lib/index.js`）**，不读 TS 源码 |

旧适配插件（`@dsh-dongjiagoushi/adapter`）是**旧形态**且从未进版本库，装不上新版——
故本轮把适配重做为独立模块 `dsh-adapter/`。

**版本判据（可核验）**：npm `@deepseek-ai/dsh` 的 `latest = 0.1.5-rc.2`，
`alpha = 0.1.6-alpha.2`（最新）。本模块适配目标 = `0.1.6-alpha.2`，兼容 `>= 0.1.5-rc.1`。

---

## 二、模块结构

```
dsh-adapter/
├── package.json                  # 声明 dsh.bundle.patch（新版组合包契约）+ dshCompat 矩阵
├── cordis.patch.yml              # 组合包 patch：insert 适配插件行
├── dsh-collaboration-rules.yaml  # Agent Directory：注册 6 个架构角色（@ 触发）
├── src/
│   ├── compat.ts                 # ★ 版本矩阵 / API 面表（TS 侧唯一事实源）
│   ├── bridge.ts                 # ★ 薄桥：DSH 工具 → local-agent Python 引擎
│   └── index.ts                  # ★ Cordis 函数插件：apply(ctx) + defineTool 注册 7 工具
├── scripts/build.mjs             # 构建：src/*.ts → lib/*.js（Node 内置 TS 转换，零依赖）
└── tests/
    ├── compat.test.mjs           # 兼容层 15 项
    ├── bundle.test.mjs           # 组合包契约 15 项
    ├── plugin.test.mjs           # 插件加载/注册 9 项
    ├── bridge.live.test.mjs      # 桥接实跑（真实 Python 引擎）
    └── real-load.probe.mjs       # 真实/桩 defineTool 装载探针
local-agent/dsh_adapter/compat.py # ★ Python 侧版本矩阵（与 TS 侧同源）
local-agent/tests/test_dsh_adapter.sh   # 18 组信号灯（统一入口）
```

---

## 三、版本闸门（核心机制）

**API 面表**（唯一事实源，TS/Python 双端一致）：

| API 面 | 引入版本 | 含义 |
|--------|---------|------|
| `python-sdk` | 0.1.0-rc.2 | Python SDK 主推，内嵌 SEA runtime |
| `cli-headless` | 0.1.1-rc.1 | 官方 CLI headless（`dsh --profile headless`） |
| `profile-bundle` | 0.1.2-rc.1 | profile + 组合包分发格式 |
| `cordis-all-plugin` | 0.1.5-rc.1 | 一切皆插件（Cordis） |
| `defineTool` | 0.1.5-rc.1 | `ctx.tools.register(defineTool(...))` |
| `patch-overlay` | 0.1.6-alpha.1 | 有序 patch overlay |

**判定（确定性）**：

```
无法解析 / 低于 min(0.1.5-rc.1) / 缺必需面(profile-bundle,cordis-all-plugin,defineTool)
   → incompatible（显式失败，不静默）
在测试矩阵内 → ok
高于要求但未实测 → degrade（可用，提示回归）
```

**用法**：

```bash
# Python 侧
python3 -m dsh_adapter.compat check 0.1.6-alpha.2   # → ok
python3 -m dsh_adapter.compat matrix                # → 完整矩阵
# 插件内：apply() 加载即自检；DSH_VERSION 可显式指定，缺省用 targetVersion 兜底
```

---

## 四、安装与使用（新版流程）

```bash
# 1) 构建产物（loader 只 import lib/index.js，必须构建）
node dsh-adapter/scripts/build.mjs

# 2) 装配进 profile（组合包机制）
dsh plugin --profile headless add /path/to/dongjiagoushi/dsh-adapter

# 3) 核验已装（bundle patch 生效）
dsh --profile headless --dump-config | grep dongjiagoushi-dsh-adapter
```

装好后，DSH 会话中模型可用以下工具（经桥转发到 `local-agent/`）：

| 工具 | 桥接模块 | 用途 |
|------|---------|------|
| `dsh.compat` | 纯 TS | 兼容自检（版本/API 面/缺失面） |
| `standard.summary` / `standard.enforced` | `dev_standard.host` | 开发规范概览 / 阶段强制清单 |
| `label.progress` / `label.apply` | `label.cli` | 程序化查进度 / 一线打标 |
| `relay.check` / `relay.gen` | `relay_card` | 接力卡合规校验 / 生成 |

**配置项**（`cordis.patch.yml` 的 `config`）：
`failFastOnIncompatible`（不兼容是否阻断，默认 true）、`root`（仓库根，缺省自动探测）、
`timeoutMs`（桥超时）、`dryRun`（工具照常注册、桥只回显，无 Python 环境冒烟用）。

---

## 五、Agent Directory（@ 触发）

`dsh-collaboration-rules.yaml` 把架构师团队注册给 DSH（默认入口锁「架构·秘书」），
协作范式映射：

| CNB 原生 | DSH |
|---------|-----|
| `@org/repo(角色)` | `@角色全称`（目录 name） |
| Issue 评论接力卡 + `[触发:X]` | `relay.*` 工具 + 角色目录 |
| 跨文件夹 = 仓库 | 绝对根（`DONGJIAGOUSHI_ROOT`）下 repo/issues/state 三区 |

---

## 六、在 CNB DSH 生态上做测试

CNB 平台已有 DSH 生态（`cnpc/dsh` = 官方 CLI 的 NPC、`fuliai/deepseek-harness` = 官方镜像等）。
本模块在 **CI 的真实 DSH 新版**上做验证（`.cnb.yml` 的 `dsh adapter compat test` 任务）：

1. 离线信号灯：版本矩阵 + 组合包契约 + API 面 + Agent Directory（18 组）；
2. 真实装载：`npm i @deepseek-ai/dsh@0.1.6-alpha.2` → 构建 `lib/` → `dsh plugin add`
   → `--dump-config` 确认 bundle patch 生效 → 真实 loader import 成功。

> 本地复现：`npm i @deepseek-ai/dsh@0.1.6-alpha.2` 后按「四」的步骤操作即可。
> 网络受限时真实装载步骤自动跳过（离线信号灯仍阻断不合规变更）。

---

## 七、与其它模块的关系（解耦）

- **依赖既有能力，不重写**：桥只转发 `dev-standard` / `label` / `relay_card`，逻辑仍在各模块。
- **不侵入核心编排**：`dsh-adapter/` 不 import `orchestrator`/`fractal`，与 `local-agent/` 通过
  显式子进程契约交互（接口显式化，可跨项目复用）。
- **与三入口归一化（ADR-0006）一致**：DSH 是「本地 harness」入口的宿主，适配层同构。

---

## 八、索引

| 产物 | 位置 |
|------|------|
| 本模块说明 | `docs/DSH_ADAPTER.md`（本文件） |
| 决策记录 | `docs/adr/0014-dsh-adapter-new-version.md` |
| 适配插件 | `dsh-adapter/` |
| 版本矩阵（TS） | `dsh-adapter/src/compat.ts` |
| 版本矩阵（Python） | `local-agent/dsh_adapter/compat.py` |
| 信号灯 | `local-agent/tests/test_dsh_adapter.sh` |
| 多宿主适配总览 | `docs/PLATFORM_ADAPTERS.md` 四.2 |
