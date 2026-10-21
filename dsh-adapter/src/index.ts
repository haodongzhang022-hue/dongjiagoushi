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
 * 纯值 → ContentBlock[] 渲染（dsh-tools ≥0.2 的 `output.render` **必调**钩子）。
 *
 * 为什么必须显式给：真实 `@deepseek-ai/dsh-tools` 的 `defineTool` 只在构造时
 * 存引用、不校验，`output.render` 缺失时定义照样"注册成功"，但**模型每次调用
 * 都会抛 `TypeError: d.output.render is not a function`**——一种典型的"装上了
 * 但一用就崩"的静默失效。仓库自带的离线桩不校验这一点，所以旧测试全绿也漏了它。
 *
 * @param _args 本次调用参数（当前不参与渲染，保持纯函数可重放）。
 * @param value 已按 output.schema 校验过的规范值。
 */
function renderValueContent(_args: unknown, value: unknown): Array<{ type: 'text'; text: string }> {
  const text = typeof value === 'string' ? value : JSON.stringify(value ?? null, null, 2)
  return [{ type: 'text', text }]
}

/** 桥接工具的统一参数面（单一事实源，工具注册与文档共用）。 */
const BRIDGE_PARAMETERS = {
  args: { type: 'array' as const, description: '透传给 local-agent 子命令的位置参数' },
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

  // ── 1' 输出渲染面自检（真实 dsh-tools ≥0.2 才有这个必调钩子）──
  // 缺该面时工具**能注册但一调用就崩**，属于最难发现的静默失效；
  // 这里主动喊出来（不阻断加载：老版本运行时确实没有这个面，工具仍可用）。
  if (!compat.faces.includes('output-render')) {
    ctx.logger?.warn?.(
      `[${name}] 当前运行时（${detected}）无 output-render 面：`
      + '工具仍按旧契约注册，若后续升级到 dsh ≥0.2 请回归本插件（output.render 必调）',
    )
  }

  const root = resolveRoot(bridgeOpts)

  // ── 2. 注册 compat 自检工具（无需 Python，纯 TS 判定）──
  ctx.tools.register(defineTool({
    name: 'dsh.compat',
    description: '报告架构师适配插件与当前 dsh 的兼容状态（版本 / API 面 / 缺失面）。',
    parameters: {
      version: { type: 'string', description: '待检查的 dsh 版本；缺省用检测值' },
    },
    output: { schema: { type: 'json' }, render: renderValueContent },
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
      parameters: BRIDGE_PARAMETERS,
      output: { schema: { type: 'json' }, render: renderValueContent },
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
