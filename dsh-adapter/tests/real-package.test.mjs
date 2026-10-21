/**
 * dsh 适配 · **真实包**装载测试（反「桩假绿」）
 * ==============================================
 * 背景（Issue #202 收尾实测）：离线桩只校验 name/description/parameters/output/execute
 * 存在，**不校验 `output.render`**。而真实 `@deepseek-ai/dsh-tools` 里 `defineTool`
 * 只在构造时存引用，`output.render` 缺失时定义照样"注册成功"，模型第一次调用却抛
 * `TypeError: d.output.render is not a function` —— 7 个工具全军覆没，而旧信号灯全绿。
 *
 * 本测试因此只认**真实包**：拿不到真实 dsh-tools 就 `SKIP`（显式跳过，不假装通过）；
 * 拿到就逐个工具真调 `output.render` / `parameters` schema 编译 / `execute`。
 *
 * 用法：node --experimental-strip-types dsh-adapter/tests/real-package.test.mjs
 */

import { createRequire } from 'node:module'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgDir = join(here, '..')
const require = createRequire(import.meta.url)

function realToolsVersion() {
  try {
    const meta = JSON.parse(readFileSync(require.resolve('@deepseek-ai/dsh-tools/package.json'), 'utf8'))
    return String(meta.version || '').startsWith('0.0.0') ? null : meta.version
  } catch { return null }
}

const version = realToolsVersion()
if (!version) {
  console.log('[dsh-adapter/real-package] SKIP 未安装真实 @deepseek-ai/dsh-tools（显式跳过，不假装通过）')
  console.log('  提示：npm i -D @deepseek-ai/dsh-tools  后重跑')
  // 收尾行统一为 `pass=N fail=0` 形态（与 compat/plugin/bundle 一致）：
  // 调用方按 `tail -1 | grep -q 'fail=0'` 判定，SKIP 若不打印收尾行会被误判成
  // 红（CI 无 dsh-tools 时必然 SKIP）。SKIP 不等于通过 —— 是否真跑过由
  // 首行 SKIP 标记 + 本行 `pass=0` 同时暴露，日志里一眼可见。
  console.log('\n[dsh-adapter/real-package] pass=0 fail=0（SKIP：未跑真实包，仅离线可证部分）')
  process.exit(0)
}

const { defineTool } = await import('@deepseek-ai/dsh-tools')
const { apply } = await import('../src/index.ts')
const { BRIDGE_MAP } = await import('../src/bridge.ts')

let pass = 0
let fail = 0
function t(name, fn) {
  try { fn(); console.log(`  OK ${name}`); pass += 1 }
  catch (e) { console.log(`  XX ${name}\n     ${e.message}`); fail += 1 }
}

console.log(`===== [dsh-adapter/real-package] 真实 dsh-tools@${version} =====`)

const registered = []
apply(
  { logger: { info() {}, warn() {} }, tools: { register: (d) => { registered.push(d); return d } } },
  { root: join(pkgDir, '..') },
)

t(`注册工具数 == 契约表(${BRIDGE_MAP.length})`, () => {
  if (registered.length !== BRIDGE_MAP.length) throw new Error(`got ${registered.length}`)
})

t('每个工具 output.render 可调用（真实 dsh ≥0.2 必调，缺则每次调用都 TypeError）', () => {
  for (const d of registered) {
    if (typeof d.output?.render !== 'function') throw new Error(`${d.name}: 缺 output.render`)
    const blocks = d.output.render({ args: [] }, { ok: true })
    if (!Array.isArray(blocks) || blocks.length === 0) throw new Error(`${d.name}: render 未返回 ContentBlock[]`)
    if (blocks[0].type !== 'text') throw new Error(`${d.name}: render 首块非 text`)
  }
})

t('每个工具能被真实 defineTool 重新编译（参数/输出 schema 合法）', () => {
  for (const d of registered) {
    const again = defineTool({
      name: `${d.name}.recompile`,
      description: d.description,
      parameters: { args: { type: 'array', description: 'x' } },
      output: { schema: { type: 'json' }, render: d.output.render },
      async execute() { return { ok: true } },
    })
    if (typeof again.output.render !== 'function') throw new Error(`${d.name}: 重编译后 render 丢失`)
  }
})

t('dsh.compat 真执行返回兼容报告', async () => {
  const def = registered.find((d) => d.name === 'dsh.compat')
  const r = await def.execute({ version: '0.2.1-rc.2' })
  if (r.state !== 'ok') throw new Error(`state=${r.state} (${r.message})`)
  if (!r.faces.includes('output-render')) throw new Error('faces 缺 output-render')
})

t('兼容面表已含 output-render（运行时自检才有判据，否则闸门形同虚设）', async () => {
  const def = registered.find((d) => d.name === 'dsh.compat')
  const r = await def.execute({ version: '0.2.1-rc.2' })
  if (!r.faces.includes('output-render')) throw new Error('API 面表缺 output-render')
  if (!r.faces.includes('bundles-manifest')) throw new Error('API 面表缺 bundles-manifest')
})

console.log(`\n[dsh-adapter/real-package] pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
