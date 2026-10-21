/**
 * dsh 适配 · 真实装载探针（用真实/桩 defineTool + 真实插件 apply）
 * ================================================================
 * 模拟新版 dsh 运行时提供的 `ctx.tools` 契约，加载**真实插件源码** `src/index.ts`，
 * 核验：
 *   1. 插件 `apply(ctx)` 不抛（版本闸门通过）
 *   2. 7 个工具经 defineTool 注册进 `ctx.tools`，schema 面完整
 *   3. `dsh.compat` 工具执行返回兼容报告
 *
 * defineTool 来源：优先真实 `@deepseek-ai/dsh-tools`（CI 装入 dsh 后），
 * 否则回落到 node_modules 下的最小桩（离线跑，契约面一致）。
 *
 * 用法：node --experimental-strip-types dsh-adapter/tests/real-load.probe.mjs
 */
import { createRequire } from 'node:module'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgDir = join(here, '..')
const require = createRequire(import.meta.url)

// 判定 defineTool 的真实性：读到的包自报版本是否 0.0.0-*桩
let defineTool
let source = 'stub'
try {
  const pkgPath = require.resolve('@deepseek-ai/dsh-tools/package.json')
  const meta = JSON.parse(readFileSync(pkgPath, 'utf8'))
  if (!String(meta.version).startsWith('0.0.0')) source = `real@${meta.version}`
  ;({ defineTool } = await import('@deepseek-ai/dsh-tools'))
} catch {
  ({ defineTool } = await import(join(pkgDir, 'node_modules/@deepseek-ai/dsh-tools/index.js')))
}

const registered = []
const ctx = {
  logger: { info: (m) => console.log('[dsh]', m) },
  tools: { register: (d) => { registered.push(d); return d } },
}

const { apply, inject, name } = await import('../src/index.ts')
console.log(`plugin: ${name}  inject: [${inject}]  defineTool: ${source}`)
apply(ctx, { dryRun: true, root: pkgDir.replace(/\/dsh-adapter$/, '') })

console.log('registered tools:', registered.map((d) => d.name).join(', '))
if (registered.length !== 7) { console.error(`FAIL: expected 7 tools, got ${registered.length}`); process.exit(1) }
for (const d of registered) {
  if (!d.parameters || !d.output?.schema) { console.error('FAIL: incomplete tool', d.name); process.exit(1) }
}
const compat = registered.find((d) => d.name === 'dsh.compat')
const r = await compat.execute({ version: '0.2.1-rc.2' })
console.log('dsh.compat →', r.state, r.faces.join(','))
if (r.state !== 'ok') process.exit(1)
console.log(`REAL-LOAD-OK: ${registered.length} tools registered via ${source} defineTool`)
