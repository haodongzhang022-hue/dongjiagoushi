/**
 * dsh 适配 · 构建脚本（src/*.ts → lib/*.js）
 * =========================================
 * 新版 dsh 的 Cordis loader **只 import 包的 `main`（lib/index.js）**，不读 TS 源码
 * （实测：直接 add TS 源包会在启动时 ERR_MODULE_NOT_FOUND lib/index.js）。因此本包
 * 必须像 dsh 官方包一样产出 `lib/` 构建产物。
 *
 * 本脚本用 Node 24 内置的 `module.stripTypeScriptTypes`（真实 TS 转换器，非正则）
 * 把 `src/*.ts` 转成 `lib/*.js`，并把 `./x.ts` 的 import 改写成 `./x.js`——
 * 零第三方依赖、离线可跑、与 dsh 自身的 ESM 产物形态一致。
 *
 * 用法：node dsh-adapter/scripts/build.mjs
 */
import { stripTypeScriptTypes } from 'node:module'
import { mkdirSync, readFileSync, writeFileSync, readdirSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgDir = resolve(here, '..')
const srcDir = join(pkgDir, 'src')
const outDir = join(pkgDir, 'lib')

rmSync(outDir, { recursive: true, force: true })
mkdirSync(outDir, { recursive: true })

const files = readdirSync(srcDir).filter((f) => f.endsWith('.ts'))
let count = 0
for (const f of files) {
  const code = readFileSync(join(srcDir, f), 'utf8')
  const stripped = stripTypeScriptTypes(code, { mode: 'strip', sourceUrl: f })
  // ESM 相对导入需带扩展名：./x.ts → ./x.js
  const out = stripped.replace(/(from\s+['"]\.\/[^'"]+?)\.ts(['"])/g, '$1.js$2')
  writeFileSync(join(outDir, f.replace(/\.ts$/, '.js')), out, 'utf8')
  count += 1
}
console.log(`[dsh-adapter/build] 产出 ${count} 个文件 → lib/`)
