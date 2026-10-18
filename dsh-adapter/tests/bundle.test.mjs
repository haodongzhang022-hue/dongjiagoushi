/**
 * dsh 适配 · 组合包契约测试（新版 bundle + patch + agent directory）
 * =================================================================
 * 验证"适配新版"的装配面是否合规——不依赖 dsh 运行时，直接读文件断言契约：
 *   1. package.json 声明 dsh.bundle.patch（新版组合包唯一分发包契约）
 *   2. cordis.patch.yml 是合法 insert patch，id/name 正确
 *   3. src/index.ts 用新版 API 面（Cordis apply + inject + defineTool）
 *   4. agent directory 注册 6 个架构角色（@ 触发）
 *
 * 用法：node dsh-adapter/tests/bundle.test.mjs
 */
import { strict as assert } from 'node:assert'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const rootDir = join(here, '..')
const read = (p) => readFileSync(join(rootDir, p), 'utf8')

let pass = 0
let fail = 0
function t(name, fn) {
  try { fn(); console.log(`  OK ${name}`); pass += 1 }
  catch (e) { console.log(`  XX ${name}\n     ${e.message}`); fail += 1 }
}

console.log('===== [dsh-adapter] 1. 组合包契约（package.json） =====')
const pkg = JSON.parse(read('package.json'))
t('声明 dsh.bundle.patch（新版契约）', () => {
  assert.ok(pkg.dsh?.bundle?.patch, 'missing dsh.bundle.patch')
  assert.equal(pkg.dsh.bundle.patch, './cordis.patch.yml')
})
t('patch 文件存在', () => {
  assert.doesNotThrow(() => read(pkg.dsh.bundle.patch))
})
t('peer 依赖声明 dsh-tools + cordis（新版 API 面）', () => {
  assert.ok(pkg.peerDependencies['@deepseek-ai/dsh-tools'])
  assert.ok(pkg.peerDependencies['@deepseek-ai/cordis'])
})
t('dshCompat 声明测试矩阵且含 0.1.6-alpha.2', () => {
  assert.ok(pkg.dshCompat.testedAgainst.includes('0.1.6-alpha.2'))
  assert.equal(pkg.dshCompat.targetVersion ?? pkg.dshCompat.testedAgainst[0], '0.1.6-alpha.2')
})
t('engines.node 对齐 dsh 要求（^22.19 || >=24）', () => {
  assert.ok(pkg.engines.node.includes('22.19'))
  assert.ok(pkg.engines.node.includes('24'))
})

console.log('===== [dsh-adapter] 2. Cordis patch 结构 =====')
const patchText = read(pkg.dsh.bundle.patch)
t('是 insert 定向 patch', () => {
  assert.match(patchText, /-\s*insert:/)
})
t('insert 行 id/name 指向本插件', () => {
  assert.match(patchText, /id:\s*dongjiagoushi-dsh-adapter/)
  assert.match(patchText, /name:\s*'@dongjiagoushi\/dsh-adapter'/)
})
t('config 含 failFastOnIncompatible 闸门', () => {
  assert.match(patchText, /failFastOnIncompatible:\s*true/)
})

console.log('===== [dsh-adapter] 3. 新版 API 面（src/index.ts） =====')
const idx = read('src/index.ts')
t('Cordis 函数插件（export function apply(ctx)）', () => {
  assert.match(idx, /export function apply\(ctx/)
})
t('inject 声明 tools 依赖（新版依赖跟踪）', () => {
  assert.match(idx, /export const inject = \['tools'\]/)
})
t('用 defineTool 注册工具（新版唯一入口）', () => {
  assert.match(idx, /defineTool\(/)
  assert.match(idx, /ctx\.tools\.register\(/)
})
t('加载即做版本闸门（failFast 显式失败）', () => {
  assert.match(idx, /checkVersion\(/)
  assert.match(idx, /throw new Error/)
})

console.log('===== [dsh-adapter] 4. Agent Directory（@ 触发） =====')
const dirText = read('dsh-collaboration-rules.yaml')
t('注册 6 个架构角色', () => {
  const names = [...dirText.matchAll(/-\s*name:\s*(架构·\S+)/g)].map((m) => m[1])
  assert.equal(names.length, 6, `got ${names.length}: ${names}`)
})
t('角色名带「架构·」命名空间前缀', () => {
  assert.match(dirText, /name:\s*架构·秘书/)
  assert.match(dirText, /name:\s*架构·总师/)
  assert.match(dirText, /name:\s*架构·评审/)
})
t('默认入口锁「架构·秘书」', () => {
  assert.match(dirText, /defaultRole:\s*架构·秘书/)
})

console.log(`\n[dsh-adapter/bundle] pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
