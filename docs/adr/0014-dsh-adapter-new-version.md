# ADR-0014：dsh 适配作为独立模块（dsh-adapter）随 DSH 新版演进，版本闸门前置、不静默放行

- 状态：Accepted
- 决策日期：2026-09
- 相关：Issue #145（`dsh-adapter` v0.1.0）、`docs/DSH_ADAPTER.md`、`docs/PLATFORM_ADAPTERS.md` 四.2

## 背景
用户在 Issue #145 提出：
> 「dsh 已经有新版的了，适配一下最新版本，我看 cnb 平台也有新的 dsh 的生态了，可以从上面做测试，
> 完成适配新版。」

调研结论（可核验）：
- **DSH = DeepSeek Harness**（`deepseek-ai/deepseek-harness`）；npm `@deepseek-ai/dsh` 的
  `latest` 为 `0.1.5-rc.2`，**最新为 `0.1.6-alpha.2`（alpha tag）**——"新版"即指此。
- **CNB 平台 DSH 生态**已成型：`cnpc/dsh`（官方 CLI 的 CNB NPC，pin `0.1.5-rc.1`）、
  `O.o/deepseek-harness`、`fuliai/deepseek-harness`（官方镜像）等，可在其上做测试。
- **旧适配插件 `dsh-dongjiagoushi-adapter` 从未进版本库**（`docs/PLATFORM_ADAPTERS.md` 记
  "workspace 内"），且是 **Python SDK 主推期**的形态；新版 DSH 已转向 **all-plugin Cordis**
  （profile + bundle + patch + `defineTool`），旧形态装不上。

## 决策
把 dsh 适配**作为独立模块 `dsh-adapter/`** 落在本仓库，**随 DSH 新版演进**，并把"版本兼容"做成
**前置闸门**而非事后发现：

1. **独立模块 + 唯一事实源**：`dsh-adapter/` 自带 `package.json`（声明 `dsh.bundle.patch` 新版组合包
   契约）、`cordis.patch.yml`（bundle patch）、`src/*.ts`（Cordis 函数插件 + `defineTool` 注册）、
   测试与文档；与仓库其它模块解耦、可独立演进（对齐 AGENTS.md 解耦式开发 + ADR-0005）。
2. **版本矩阵唯一事实源（双端同源）**：`dsh-adapter/src/compat.ts`（TS 侧）与
   `local-agent/dsh_adapter/compat.py`（Python 侧）共享同一 **API 面表 + 测试矩阵**，
   任意端都能独立判定"适配到哪一代"。
3. **版本闸门前置、不静默放行**：插件 `apply()` 加载即 `checkVersion()`；**缺必需 API 面
   （cordis-all-plugin / defineTool / profile-bundle）即显式抛错**（`failFastOnIncompatible`），
   杜绝"装上了但工具不生效"的静默状态。
4. **能力只桥不重写**：DSH 工具经子进程桥转发到 `local-agent/` 既有 Python 引擎
   （dev-standard / label / relay），薄适配、不重复实现、失败不吞异常。
5. **只 import 构建产物**：实测新版 loader **只 import 包的 `main`（`lib/index.js`）**，不读 TS 源码；
   故本包附零依赖构建脚本 `scripts/build.mjs`（Node 内置 `stripTypeScriptTypes`）产出 `lib/`。
6. **CNB 生态上做验证**：CI 在新版 DSH（`0.1.6-alpha.2`）上做**真实装载验证**
   （装 CLI → 挂适配插件 → `--dump-config` 确认 bundle patch 生效 → 真实 loader import `lib/`）。

## 后果（权衡）
- 好处：适配新版可核验（双端版本矩阵 + 18 组信号灯 + 真实装载探针）；版本失配**前置暴露**；
  独立模块不污染核心编排；CNB DSH 生态上可回归。
- 代价：本包**需要构建步骤**（`lib/` 产物）——这是新版 loader 的硬约束，不可省；已用零第三方
  依赖的 Node 内置转换器实现，CI/离线均可跑。DSH 处 0.x 预览期，minor/rc 间仍可能有面变化——
  故保留 `degrade` 档位（未实测的新版不阻断但提示回归），并在 `dshCompat.testAgainst` 随验证更新。
  难反转（结构性路径选择），记 ADR。
