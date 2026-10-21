/**
 * dsh 适配 · 兼容层测试（无 dsh 依赖，纯 ESM 冒烟）
 * =================================================
 * 用 node 直接跑（不需要装 @deepseek-ai/*），靠 Node 24 原生 TS 类型剥离
 * （--experimental-strip-types）直接 import src/compat.ts，验证版本矩阵 /
 * API 面判定的确定性行为——这是"适配新版"的判据核心，必须可独立于 dsh
 * 环境验证（对齐仓库"执行-验证分离"）。
 *
 * 用法：node --experimental-strip-types dsh-adapter/tests/compat.test.mjs
 */
import { strict as assert } from 'node:assert'
import {
  parseVersion,
  compareVersion,
  apiFaceOf,
  API_FACES,
  checkVersion,
  DSH_COMPAT,
} from '../src/compat.ts'

let pass = 0
let fail = 0
function t(name, fn) {
  try {
    fn()
    console.log(`  OK ${name}`)
    pass += 1
  } catch (e) {
    console.log(`  XX ${name}\n     ${e.message}`)
    fail += 1
  }
}

console.log('===== [dsh-adapter] 1. 版本解析 =====')
t('解析 0.1.6-alpha.2', () => {
  const p = parseVersion('0.1.6-alpha.2')
  assert.equal(p.major, 0); assert.equal(p.minor, 1); assert.equal(p.patch, 6)
  assert.equal(p.channel, 'alpha'); assert.equal(p.rank, 2)
})
t('解析 0.1.5-rc.2 / 正式版 4.0.2', () => {
  assert.equal(parseVersion('0.1.5-rc.2').channel, 'rc')
  assert.equal(parseVersion('4.0.2').channel, '')
})
t('无法解析返回 null（不抛）', () => {
  assert.equal(parseVersion('not-a-version'), null)
  assert.equal(parseVersion(undefined), null)
})

console.log('===== [dsh-adapter] 2. 版本比较 =====')
t('0.1.6 > 0.1.5', () => {
  assert.equal(compareVersion(parseVersion('0.1.6-alpha.2'), parseVersion('0.1.5-rc.2')), 1)
})
t('同号正式版 > 预发布（1.0.0 > 1.0.0-alpha.9）', () => {
  assert.equal(compareVersion(parseVersion('1.0.0'), parseVersion('1.0.0-alpha.9')), 1)
})
t('rc 高于 alpha（同号）', () => {
  assert.equal(compareVersion(parseVersion('0.1.5-rc.1'), parseVersion('0.1.5-alpha.2')), 1)
})
t('相等 → 0', () => {
  assert.equal(compareVersion(parseVersion('0.1.6-alpha.2'), parseVersion('0.1.6-alpha.2')), 0)
})

console.log('===== [dsh-adapter] 3. API 面 =====')
t('新版具备 cordis-all-plugin + defineTool + patch-overlay', () => {
  const f = apiFaceOf('0.1.6-alpha.2')
  assert.ok(f.includes('cordis-all-plugin'))
  assert.ok(f.includes('defineTool'))
  assert.ok(f.includes('patch-overlay'))
})
t('旧版 0.1.2 无 cordis-all-plugin（只有 python-sdk/profile-bundle）', () => {
  const f = apiFaceOf('0.1.2-rc.1')
  assert.ok(f.includes('python-sdk'))
  assert.ok(!f.includes('cordis-all-plugin'))
})

console.log('===== [dsh-adapter] 4. 兼容判定 =====')
t('targetVersion → ok（测试矩阵内）', () => {
  assert.equal(checkVersion(DSH_COMPAT.targetVersion).state, 'ok')
})
t('0.1.5-rc.2 / 0.1.5-rc.1 → degrade（API 面齐但未用真实包实测，不谎报 ok）', () => {
  for (const v of ['0.1.5-rc.2', '0.1.5-rc.1']) {
    const r = checkVersion(v)
    assert.equal(r.state, 'degrade', `${v}: ${r.state}`)
    assert.equal(r.missingFaces.length, 0, `${v} 不该缺必需面`)
  }
})
t('0.1.3-alpha.2 → incompatible（缺 cordis/defineTool）', () => {
  const r = checkVersion('0.1.3-alpha.2')
  assert.equal(r.state, 'incompatible')
  assert.ok(r.missingFaces.includes('cordis-all-plugin'))
})
t('0.9.9 新版未实测 → degrade（不阻断，提示回归）', () => {
  assert.equal(checkVersion('0.9.9').state, 'degrade')
})
t('乱版 → incompatible（显式暴露，不静默）', () => {
  const r = checkVersion('garbage')
  assert.equal(r.state, 'incompatible')
  assert.ok(r.message.includes('无法解析'))
})
t('targetVersion 在 testedAgainst 内（唯一事实源自洽）', () => {
  assert.ok(DSH_COMPAT.testedAgainst.includes(DSH_COMPAT.targetVersion))
  // 真实 dsh-tools 0.0.1-rc.1 实测出的必调面必须在面表里
  assert.ok(API_FACES.some((f) => f.id === 'output-render'))
})

console.log(`\n[dsh-adapter/compat] pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
