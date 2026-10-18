/**
 * 架构师体系 ⇄ DeepSeek Harness (dsh) 适配插件入口
 * ==================================================
 * 适配目标：dsh **新版**（0.1.6-alpha.2 / all-plugin Cordis）。
 *
 * 与旧版（0.1.5-rc.1 前后、Python SDK 主推期）的差异，本插件已对齐：
 *   1. **一切皆插件（Cordis）**：本模块是标准 Cordis 函数插件（`apply(ctx)`），
 *      通过 `ctx.tools` 注册工具，注册即副作用、卸载即撤销。
 *   2. **defineTool 注册**：工具用 `defineTool({ name, description, parameters,
 *      output, execute })` 声明，schema 自动进入系统提示词组装（旧版无此统一入口）。
 *   3. **组合包（bundle）分发**：`package.json` 的 `dsh.bundle.patch` 指向
 *      `cordis.patch.yml`，由 `dsh plugin --profile <p> add` 装配（旧版无 bundle 契约）。
 *   4. **版本闸门**：加载时先做 `checkVersion()` 兼容自检，缺 API 面**显式失败**，
 *      不像旧版那样"装上了但工具不生效"的静默状态。
 *
 * 设计对齐 AGENTS.md：解耦式模块（本插件独立成模块、独立演进）、接口显式化、
 * 错误不吞异常、变更留痕。
 */

import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'

import {
  DSH_COMPAT,
  checkVersion,
  detectVersionFromEnv,
  apiFaceOf,
} from './compat.ts'
import { BRIDGE_MAP, callLocalAgent, resolveRoot } from './bridge.ts'

export const name = 'dsh-dongjiagoushi-adapter'

/**
 * 声明的服务依赖：`inject` 列出后，Cordis 会保持本插件 PENDING 直到服务就绪，
 * 卸载服务时本插件随之卸载（依赖跟踪，非一次性启动检查）。
 * `tools` 由 @deepseek-ai/dsh-tools 提供。
 */
export const inject = ['tools']

/** 本插件可配置项（Schemastery 风格，字段可全空用默认值）。 */
export interface AdapterConfig {
  /** 兼容自检失败时是否阻断加载（默认 true：不静默放行）。 */
  failFastOnIncompatible?: boolean
  /** 覆盖仓库根（含 local-agent/）；缺省自动探测。 */
  root?: string
  /** 桥调用超时（毫秒）。 */
  timeoutMs?: number
  /** dryRun：注册工具但桥调用只回显命令（冒烟/无 Python 环境用）。 */
  dryRun?: boolean
}

/**
 * Cordis 函数插件入口。
 * @param ctx 上下文；`ctx.tools` 已由 inject 保证就绪。
 * @param config 插件配置。
 */
export function apply(ctx: Context, config: AdapterConfig = {}): void {
  const failFast = config.failFastOnIncompatible !== false
  const bridgeOpts = {
    root: config.root,
    timeoutMs: config.timeoutMs,
    dryRun: config.dryRun,
  }

  // ── 1. 版本闸门：加载即自检，缺 API 面显式暴露（不静默）──
  const detected = detectVersionFromEnv(process.env as Record<string, string | undefined>)
    || DSH_COMPAT.targetVersion
  const compat = checkVersion(detected)
  ctx.logger?.info?.(
    `[${name}] ${compat.message}`,
  )
  if (compat.state === 'incompatible' && failFast) {
    throw new Error(`[${name}] dsh 版本不兼容：${compat.message}`)
  }

  const root = resolveRoot(bridgeOpts)

  // ── 2. 注册 compat 自检工具（无需 Python，纯 TS 判定）──
  ctx.tools.register(defineTool({
    name: 'dsh.compat',
    description: '报告架构师适配插件与当前 dsh 的兼容状态（版本 / API 面 / 缺失面）。',
    parameters: {
      version: { type: 'string', description: '待检查的 dsh 版本；缺省用检测值' },
    },
    output: { schema: { type: 'json' } },
    async execute(args: { version?: string }) {
      const v = args.version || detected
      const r = checkVersion(v)
      return {
        state: r.state,
        version: r.version,
        faces: r.faces,
        missingFaces: r.missingFaces,
        requiredFaces: [...DSH_COMPAT.requiredFaces],
        testedAgainst: [...DSH_COMPAT.testedAgainst],
        targetVersion: DSH_COMPAT.targetVersion,
        message: r.message,
      }
    },
  }))

  // ── 3. 注册桥接工具（转发 local-agent Python 能力）──
  for (const cap of BRIDGE_MAP) {
    if (cap.tool === 'dsh.compat') continue
    ctx.tools.register(defineTool({
      name: cap.tool,
      description: `${cap.description}（桥接 local-agent · ${cap.module}）`,
      parameters: {
        args: { type: 'array', description: '透传给 local-agent 子命令的位置参数' },
      },
      output: { schema: { type: 'json' } },
      async execute(args: { args?: string[] }) {
        const argv = ['-m', cap.module, ...(args.args ?? [])]
        const res = await callLocalAgent<unknown>(argv, { ...bridgeOpts, root })
        return {
          tool: cap.tool,
          module: cap.module,
          apiFaces: apiFaceOf(detected),
          ...res,
        }
      },
    }))
  }

  ctx.logger?.info?.(
    `[${name}] 已注册 ${BRIDGE_MAP.length} 个工具（root=${root}${config.dryRun ? ', dryRun' : ''}）`,
  )
}
