/**
 * dsh 适配 · 插件加载测试（真实 import + mock Cordis ctx）
 * ========================================================
 * 用 Node 24 原生 TS 类型剥离直接 import `src/index.ts`（真实代码路径），
 * 只 mock `ctx`（新版 dsh 的运行时面）。验证：
 *   1. 插件可加载（版本闸门通过）
 *   2. tools 注册数与契约表一致、工具定义含新版 defineTool 全部字段
 *   3. 工具执行：dsh.compat 走纯 TS 判定；桥工具 dryRun 只回显
 *   4. 不兼容版本 + failFast → apply 抛错（显式暴露，不静默）
 *
 * 依赖 `dsh-adapter/node_modules/@deepseek-ai/{dsh-tools,cordis}` 测试 stub
 * （仅校验用法面，不拉真实 dsh 大包）。
 *
 * 用法：node --experimental-strip-types dsh-adapter/tests/plugin.test.mjs
 */
import { strict as assert } from 'node:assert'
import { mkdirSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgDir = join(here, '..')

// 依赖解析策略：CI 装了真实 dsh 时用真实 @deepseek-ai/dsh-tools；
// 离线（无 dsh）时回落到本包内的最小 stub，保证信号灯可离线跑
// （对齐"执行-验证分离"：契约核验不依赖外部大包）。
/** 判断某包 path 是否为真实包（非本地桩）。 */
function isRealPackage(pkgJsonPath) {
  try {
    const meta = JSON.parse(readFileSync(pkgJsonPath, 'utf8'))
    return !String(meta.version || '').startsWith('0.0.0')
  } catch { return false }
}

function ensureDeps() {
  // 桩写入 node_modules/@deepseek-ai（Node 裸导入解析需要），但**只在真实包
  // 缺席时**写入——existsSync 守卫确保绝不遮蔽真实安装的 @deepseek-ai/*。
  const modDir = join(pkgDir, 'node_modules', '@deepseek-ai')
  const toolsDir = join(modDir, 'dsh-tools')
  const cordisDir = join(modDir, 'cordis')
  // 守卫：目录已存在（真实包或已建桩）即不写入——绝不覆盖真实安装
  if (existsSync(toolsDir) && existsSync(cordisDir)) return
  // 再守一道：真实包（版本非 0.0.0-桩）存在即完全不建桩
  if (isRealPackage(join(toolsDir, 'package.json'))) return
  const make = (dir, pkg, body) => {
    if (existsSync(join(dir, 'index.js'))) return
    mkdirSync(dir, { recursive: true })
    writeFileSync(join(dir, 'package.json'), JSON.stringify({
      name: pkg, version: '0.0.0-offline-stub', type: 'module',
      main: 'index.js', exports: { '.': './index.js' },
    }))
    writeFileSync(join(dir, 'index.js'), body)
  }
  make(toolsDir, '@deepseek-ai/dsh-tools',
    `export function defineTool(def){if(!def||!def.name)throw new Error('defineTool: name required');if(!def.description)throw new Error('defineTool: description required');if(!def.parameters)throw new Error('defineTool: parameters required');if(!def.output)throw new Error('defineTool: output required');if(typeof def.execute!=='function')throw new Error('defineTool: execute required');return Object.freeze({kind:'dsh-tool',...def})}\n`)
  make(cordisDir, '@deepseek-ai/cordis', 'export {}\n')
  // lib/ 若不存在则先构建（loader 只 import lib/index.js）
  if (!existsSync(join(pkgDir, 'lib', 'index.js'))) {
    try { require('node:child_process').execFileSync(process.execPath, [join(pkgDir, 'scripts', 'build.mjs')], { stdio: 'ignore' }) } catch {}
  }
}
ensureDeps()

const { apply, inject } = await import('../src/index.ts')
const { BRIDGE_MAP } = await import('../src/bridge.ts')

let pass = 0
let fail = 0
async function t(name, fn) {
  try { await fn(); console.log(`  OK ${name}`); pass += 1 }
  catch (e) { console.log(`  XX ${name}\n     ${e.message}`); fail += 1 }
}

function makeMockCtx() {
  const registered = []
  return {
    registered,
    logger: { info() {}, warn() {}, error() {} },
    tools: { register(def) { registered.push(def); return def } },
  }
}

console.log('===== [dsh-adapter] 1. 插件加载 =====')
await t('apply(ctx) 可加载不抛（版本闸门通过）', () => {
  const ctx = makeMockCtx()
  assert.doesNotThrow(() => apply(ctx, { dryRun: true }))
})
await t('声明 inject = [tools]', () => {
  assert.deepEqual(inject, ['tools'])
})

console.log('===== [dsh-adapter] 2. 工具注册（新版 defineTool 面） =====')
const ctx = makeMockCtx()
apply(ctx, { dryRun: true })
await t(`注册工具数 == 契约表(${BRIDGE_MAP.length})`, () => {
  assert.equal(ctx.registered.length, BRIDGE_MAP.length)
})
await t('工具名与契约表一致', () => {
  assert.deepEqual(
    ctx.registered.map((d) => d.name).sort(),
    BRIDGE_MAP.map((c) => c.tool).sort(),
  )
})
await t('每个工具定义含 name/description/parameters/output/execute', () => {
  for (const d of ctx.registered) {
    assert.ok(d.name && d.description && d.parameters && d.output, d.name)
    assert.equal(typeof d.execute, 'function', d.name)
  }
})

console.log('===== [dsh-adapter] 3. 工具执行 =====')
await t('dsh.compat 执行返回兼容报告', async () => {
  const def = ctx.registered.find((d) => d.name === 'dsh.compat')
  const r = await def.execute({ version: '0.1.6-alpha.2' })
  assert.equal(r.state, 'ok')
  assert.ok(r.faces.includes('defineTool'))
  assert.equal(r.targetVersion, '0.1.6-alpha.2')
})
await t('桥工具 dryRun 只回显不真跑 Python', async () => {
  const def = ctx.registered.find((d) => d.name === 'label.progress')
  const r = await def.execute({ args: ['progress', '--task', 'tk-1'] })
  assert.equal(r.ok, true)
  assert.equal(r.data.dryRun, true)
  assert.ok(r.cmd.includes('label.cli'))
})

console.log('===== [dsh-adapter] 4. 版本闸门（显式失败） =====')
await t('不兼容 + failFast → apply 抛错', () => {
  const badCtx = makeMockCtx()
  const orig = process.env.DSH_VERSION
  process.env.DSH_VERSION = '0.1.2-rc.1'
  try {
    assert.throws(() => apply(badCtx, { failFastOnIncompatible: true }))
  } finally {
    if (orig === undefined) delete process.env.DSH_VERSION; else process.env.DSH_VERSION = orig
  }
})
await t('不兼容 + failFast=false → 仍注册工具（降级可见）', () => {
  const softCtx = makeMockCtx()
  process.env.DSH_VERSION = '0.1.2-rc.1'
  try {
    apply(softCtx, { failFastOnIncompatible: false, dryRun: true })
    assert.equal(softCtx.registered.length, BRIDGE_MAP.length)
  } finally {
    delete process.env.DSH_VERSION
  }
})

console.log(`\n[dsh-adapter/plugin] pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
