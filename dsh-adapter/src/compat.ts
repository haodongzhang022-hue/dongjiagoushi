/**
 * DSH 版本兼容层（dsh-adapter · compat.ts）
 * ==========================================
 * DeepSeek Harness 处于 0.x 技术预览期，minor/rc 间存在 schema / 行为变化
 * （0.1.2 预设置 code→ptc、0.1.5→0.1.6 由 Python SDK 主推转向 **all-plugin
 * Cordis**：profile + bundle + patch + defineTool）。适配插件必须**声明并校验**
 * 目标版本面，避免"装上去了但 API 面不匹配"的静默失效。
 *
 * 本模块是**唯一版本事实源**（被 src/index.ts / 兼容报告 / 测试共同读取）：
 *   - SEMVER_RE     语义化版本解析（兼容 0.1.6-alpha.2 / 0.1.5-rc.2 形态）
 *   - DSH_COMPAT    各 API 面引入版本 + 本插件的最低要求
 *   - checkVersion()给定 dsh 版本 → 兼容结论（ok / degrade / incompatible）
 *   - apiFaceOf()   版本 → API 面标识（用于报告"适配到哪一代"）
 */

/** 解析出的语义化版本三元组 + 预发布标识。 */
export interface ParsedVersion {
  major: number
  minor: number
  patch: number
  /** 预发布标识：rc / alpha / beta / ''（正式版）。 */
  channel: string
  /** 预发布序号，无预发布为 0。 */
  rank: number
  raw: string
}

const SEMVER_RE = /^v?(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)\.?(\d+))?/i

/** 解析语义化版本串；无法解析返回 null（不抛，调用方显式处理）。 */
export function parseVersion(raw: string): ParsedVersion | null {
  if (typeof raw !== 'string') return null
  const m = SEMVER_RE.exec(raw.trim())
  if (!m) return null
  return {
    major: Number(m[1]),
    minor: Number(m[2]),
    patch: Number(m[3]),
    channel: (m[4] ?? '').toLowerCase(),
    rank: m[5] ? Number(m[5]) : 0,
    raw: raw.trim(),
  }
}

/** 通道权重：正式版 > rc > beta > alpha（同版本号下正式版更"新"）。 */
const CHANNEL_WEIGHT: Record<string, number> = {
  '': 100,
  rc: 90,
  beta: 60,
  alpha: 40,
}

/** 比较两个版本：a > b 返回 1，a < b 返回 -1，相等 0。无法解析者排最前。 */
export function compareVersion(a: ParsedVersion | null, b: ParsedVersion | null): number {
  if (!a && !b) return 0
  if (!a) return -1
  if (!b) return 1
  for (const k of ['major', 'minor', 'patch'] as const) {
    if (a[k] !== b[k]) return a[k] > b[k] ? 1 : -1
  }
  const wa = CHANNEL_WEIGHT[a.channel] ?? 0
  const wb = CHANNEL_WEIGHT[b.channel] ?? 0
  if (wa !== wb) return wa > wb ? 1 : -1
  if (a.rank !== b.rank) return a.rank > b.rank ? 1 : -1
  return 0
}

/** 一个 API 面的元信息。 */
export interface ApiFace {
  /** 面标识（如 cordis-all-plugin）。 */
  id: string
  /** 该面"引入版本"（>= 该版本才有）。 */
  since: string
  /** 说明。 */
  note: string
}

/**
 * DSH 历代 API 面（按 since 升序）。
 * 这张表是"适配到哪一代"的判据，也是兼容报告的内容源。
 */
export const API_FACES: ApiFace[] = [
  {
    id: 'python-sdk',
    since: '0.1.0-rc.2',
    note: 'Python SDK 主推：内嵌 SEA runtime，插件以 Python 侧挂载为主',
  },
  {
    id: 'cli-headless',
    since: '0.1.1-rc.1',
    note: '官方 CLI headless 模式（dsh --profile headless），可脚本化驱动 agent',
  },
  {
    id: 'profile-bundle',
    since: '0.1.2-rc.1',
    note: 'profile + 组合包（bundle）分发格式：package.json 的 dsh.profile / dsh.bundle',
  },
  {
    id: 'cordis-all-plugin',
    since: '0.1.5-rc.1',
    note: '一切皆插件（Cordis）：服务/事件/副作用皆插件，无特权内核',
  },
  {
    id: 'defineTool',
    since: '0.1.5-rc.1',
    note: 'ctx.tools.register(defineTool({...})) 为工具注册唯一入口',
  },
  {
    id: 'patch-overlay',
    since: '0.1.6-alpha.1',
    note: '有序 patch overlay（--patch / cordis.patch.yml）按 id 定位并替换条目 config',
  },
]

/** 本插件对 DSH 的最低要求与测试矩阵（唯一事实源）。 */
export const DSH_COMPAT = {
  /** 最低可用版本（低于此判 incompatible）。 */
  minVersion: '0.1.5-rc.1',
  /** 优先适配的最新版本（适配目标的"当前"值）。 */
  targetVersion: '0.1.6-alpha.2',
  /** 已实测/声明兼容的版本清单。 */
  testedAgainst: ['0.1.6-alpha.2', '0.1.5-rc.2', '0.1.5-rc.1'],
  /** 本插件要求的 API 面（缺任一即不完整）。 */
  requiredFaces: ['cordis-all-plugin', 'defineTool', 'profile-bundle'],
} as const

/** 兼容结论。 */
export type CompatState = 'ok' | 'degrade' | 'incompatible'

export interface CompatReport {
  state: CompatState
  /** 输入版本（原样）。 */
  version: string
  /** 解析结果，无法解析为 null。 */
  parsed: ParsedVersion | null
  /** 该版本具备的 API 面 id。 */
  faces: string[]
  /** 缺失的必需 API 面。 */
  missingFaces: string[]
  /** 人类可读结论。 */
  message: string
}

/** 给定 dsh 版本 → 列出其具备的 API 面。 */
export function apiFaceOf(version: string | ParsedVersion | null): string[] {
  const p = typeof version === 'string' ? parseVersion(version) : version
  if (!p) return []
  return API_FACES.filter((f) => compareVersion(p, parseVersion(f.since)) >= 0).map((f) => f.id)
}

/**
 * 兼容性判定（确定性，无 LLM）：
 *   - 版本无法解析 → incompatible（显式暴露，不静默放行）
 *   - 低于 minVersion → incompatible
 *   - 缺任一 requiredFaces → incompatible
 *   - 高于要求但未在 testedAgainst 中 → degrade（可用但未实测，提示回归）
 *   - 否则 → ok
 */
export function checkVersion(version: string): CompatReport {
  const parsed = parseVersion(version)
  const faces = apiFaceOf(parsed)
  const missingFaces = DSH_COMPAT.requiredFaces.filter((f) => !faces.includes(f))

  if (!parsed) {
    return {
      state: 'incompatible',
      version: String(version),
      parsed: null,
      faces,
      missingFaces: [...DSH_COMPAT.requiredFaces],
      message: `无法解析 dsh 版本 "${version}"，拒绝静默加载（请核对 dsh --version）`,
    }
  }
  if (compareVersion(parsed, parseVersion(DSH_COMPAT.minVersion)) < 0) {
    return {
      state: 'incompatible',
      version,
      parsed,
      faces,
      missingFaces,
      message: `dsh ${version} 低于最低要求 ${DSH_COMPAT.minVersion}，缺失 cordis/defineTool API 面，请升级`,
    }
  }
  if (missingFaces.length > 0) {
    return {
      state: 'incompatible',
      version,
      parsed,
      faces,
      missingFaces,
      message: `dsh ${version} 缺少必需 API 面：${missingFaces.join(', ')}`,
    }
  }
  if (!DSH_COMPAT.testedAgainst.includes(version)) {
    return {
      state: 'degrade',
      version,
      parsed,
      faces,
      missingFaces,
      message: `dsh ${version} 具备所需 API 面但未在测试矩阵内（已测：${DSH_COMPAT.testedAgainst.join(', ')}），按降级模式加载，请回归`,
    }
  }
  return {
    state: 'ok',
    version,
    parsed,
    faces,
    missingFaces,
    message: `dsh ${version} 兼容（API 面：${faces.join(', ')}）`,
  }
}

/** 从环境变量探测当前 dsh 版本（无则返回空串）。 */
export function detectVersionFromEnv(env: Record<string, string | undefined> = {}): string {
  return env.DSH_VERSION || env.DSH_CLI_VERSION || ''
}
