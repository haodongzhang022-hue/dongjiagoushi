/**
 * 本地能力桥（dsh-adapter · bridge.ts）
 * ======================================
 * DSH 是 JS/TS 世界，架构师体系的核心引擎在 `local-agent/`（Python）。本模块是
 * 两者之间的**薄适配器**，不重复实现任何逻辑：
 *   - 所有能力调用统一收敛为 `python3 -m <module> ...` 子进程（MCP 管线风格）；
 *   - 与既有 `dev_standard.host` / `label.cli` 的"宿主导入"模式一致；
 *   - 失败**不吞异常**（返回 ok=false + stderr），对齐仓库"错误处理不吞异常"C01。
 *
 * 设计对齐 AGENTS.md「解耦式功能模块开发」：本层只做进程桥与 JSON 归一化，
 * 引擎逻辑仍在各自 Python 模块，接口显式（调用契约 = 子命令 + JSON 输出）。
 */

import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

/** 单次桥调用结果（统一契约）。 */
export interface BridgeResult<T = unknown> {
  ok: boolean
  /** 归一化后的数据（成功时）。 */
  data?: T
  /** 失败原因（失败时）。 */
  error?: string
  /** 实际执行的命令（可核验留痕）。 */
  cmd: string
}

/** 桥配置。 */
export interface BridgeOptions {
  /** 仓库根（含 local-agent/）。缺省由调用处传入或向上探测。 */
  root?: string
  /** Python 可执行名。 */
  python?: string
  /** 单次调用超时（毫秒）。 */
  timeoutMs?: number
  /** dryRun：只回显将执行的命令，不真正跑（供测试/预览）。 */
  dryRun?: boolean
}

const DEFAULT_TIMEOUT_MS = 60_000

/**
 * 从起点向上探测含 `local-agent/` 的仓库根。
 * 不写死路径——对齐 HandleAbility「不写死」原则。
 */
export function findRoot(start: string): string | null {
  let cur = resolve(start)
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(join(cur, 'local-agent'))) return cur
    const parent = dirname(cur)
    if (parent === cur) break
    cur = parent
  }
  return null
}

/** 解析本次桥用的仓库根（显式 > 环境变量 > 向上探测 > cwd）。 */
export function resolveRoot(opts: BridgeOptions = {}): string {
  if (opts.root) return resolve(opts.root)
  const envRoot = typeof process !== 'undefined' ? process.env?.DONGJIAGOUSHI_ROOT : ''
  if (envRoot && existsSync(join(envRoot, 'local-agent'))) return resolve(envRoot)
  return findRoot(process.cwd()) ?? process.cwd()
}

/**
 * 执行一次 local-agent 能力调用。
 *
 * @param moduleArgs 形如 ['-m', 'label.cli', 'progress', '--task', 'tk-1']
 * @param opts       桥配置
 */
export function callLocalAgent<T = unknown>(
  moduleArgs: string[],
  opts: BridgeOptions = {},
): Promise<BridgeResult<T>> {
  const root = resolveRoot(opts)
  const python = opts.python ?? process.env?.DONGJIAGOUSHI_PYTHON ?? 'python3'
  const laDir = join(root, 'local-agent')
  const cmd = `${python} ${moduleArgs.join(' ')}`

  if (opts.dryRun) {
    return Promise.resolve({ ok: true, data: { dryRun: true, cwd: laDir } as unknown as T, cmd })
  }

  return new Promise((resolvePromise) => {
    execFile(
      python,
      moduleArgs,
      {
        cwd: laDir,
        timeout: opts.timeoutMs ?? DEFAULT_TIMEOUT_MS,
        maxBuffer: 8 * 1024 * 1024,
        env: { ...process.env, PYTHONPATH: laDir },
      },
      (err, stdout, stderr) => {
        if (err) {
          resolvePromise({ ok: false, error: (stderr || err.message || '').trim(), cmd })
          return
        }
        const text = (stdout || '').trim()
        try {
          resolvePromise({ ok: true, data: JSON.parse(text) as T, cmd })
        } catch {
          // 非 JSON 输出按纯文本返回，不吞异常（保留原文）
          resolvePromise({ ok: true, data: text as unknown as T, cmd })
        }
      },
    )
  })
}

/** local-agent 能力清单（DSH 工具 → Python 模块的映射契约）。 */
export interface AgentCapability {
  /** DSH 工具名（面向模型）。 */
  tool: string
  /** local-agent 模块（python -m <module>）。 */
  module: string
  /** 用途。 */
  description: string
}

/** 桥接契约表（唯一事实源，测试与文档都读这里）。 */
export const BRIDGE_MAP: AgentCapability[] = [
  { tool: 'dsh.compat', module: 'dsh_adapter.compat', description: 'DSH 版本/API 面兼容自检' },
  { tool: 'standard.summary', module: 'dev_standard.host', description: '开发规范概览' },
  { tool: 'standard.enforced', module: 'dev_standard.host', description: '某阶段强制规范清单' },
  { tool: 'label.progress', module: 'label.cli', description: '程序化查进度/状态/标签' },
  { tool: 'label.apply', module: 'label.cli', description: '一线直接打标' },
  { tool: 'relay.check', module: 'relay_card', description: '接力卡合规校验（防断链）' },
  { tool: 'relay.gen', module: 'relay_card', description: '生成合规接力卡 @' },
]
