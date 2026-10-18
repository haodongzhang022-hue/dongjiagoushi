// 桥接实际调用：真实拉起 local-agent Python 引擎（非 dryRun），验证端到端可用。
import { callLocalAgent, resolveRoot, BRIDGE_MAP } from '../src/bridge.ts'

const root = '/workspace'
console.log('root =', resolveRoot({ root }))

let pass = 0, fail = 0
async function t(name, fn) {
  try { await fn(); console.log('  OK ' + name); pass++ }
  catch (e) { console.log('  XX ' + name + '\n     ' + e.message); fail++ }
}

await t('dsh_adapter.compat matrix 可跑', async () => {
  const r = await callLocalAgent(['-m', 'dsh_adapter.compat', 'matrix'], { root })
  if (!r.ok) throw new Error(r.error)
  if (r.data.target_version !== '0.1.6-alpha.2') throw new Error('bad target: ' + r.data.target_version)
})
await t('dev_standard.host summary 可跑（standard.summary）', async () => {
  const r = await callLocalAgent(['-m', 'dev_standard.host', 'call', 'standard.summary', '{}'], { root })
  if (!r.ok) throw new Error(r.error)
  const total = r.data?.data?.total ?? r.data?.total
  if (!(total >= 1)) throw new Error('bad summary: ' + JSON.stringify(r.data).slice(0, 160))
})
await t('relay_card gen 可跑（relay.gen）', async () => {
  const r = await callLocalAgent(['-m', 'relay_card', 'gen', '--to', '架构·评审'], { root })
  if (!r.ok) throw new Error(r.error)
})
await t('契约表每条 module 都能被 python 解析（--help 级冒烟）', async () => {
  for (const cap of BRIDGE_MAP) {
    if (cap.tool === 'dsh.compat') continue
    const r = await callLocalAgent(['-m', cap.module, '--help'], { root })
    if (!r.ok) throw new Error(`${cap.module} 不可用: ${r.error}`)
  }
})

console.log(`\n[dsh-adapter/bridge-live] pass=${pass} fail=${fail}`)
process.exit(fail === 0 ? 0 : 1)
