// Everything between the mod and the installer CLI: user settings, repo
// resolution, argv building, running a command without a shell, and turning
// its JSON into the small shapes the pane keeps. Nothing here throws.
import type { EngineInterface, PluginOptions } from 'claude-code'
import type {
  AiSuiteCatalogRow,
  AiSuiteCheckState,
  AiSuiteDoctor,
  AiSuiteIssues,
  AiSuiteProblem,
  AiSuiteSkillRow,
  AiSuiteUpdates,
  AiSuiteWorkflow,
} from '../types'

export type Settings = { repoPath: string; python: string; checkOnStart: boolean }
export type Cfg = { repo: string; python: string; home: string }

export function readSettings(options: PluginOptions): Settings {
  const repoPath = typeof options.repoPath === 'string' ? options.repoPath.trim() : ''
  const python = typeof options.python === 'string' ? options.python.trim() : ''
  return {
    repoPath,
    python: python === '' ? 'python3' : python,
    checkOnStart: options.checkOnStart !== false,
  }
}

// ---------------------------------------------------------------- text helpers

export function errText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function truncate(text: string, max: number): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length <= max ? flat : `${flat.slice(0, Math.max(1, max - 1))}…`
}

function lines(text: string): string[] {
  return text.split('\n').map(line => line.trim()).filter(line => line !== '')
}

// ---------------------------------------------------------------------- paths

export function dirname(path: string): string {
  const trimmed = path.length > 1 ? path.replace(/\/+$/, '') : path
  const cut = trimmed.lastIndexOf('/')
  if (cut < 0) return '.'
  return cut === 0 ? '/' : trimmed.slice(0, cut)
}

export function grandparent(path: string): string {
  return dirname(dirname(path))
}

function joinPath(base: string, rest: string): string {
  return `${base.replace(/\/+$/, '')}/${rest}`
}

export function shortenHome(path: string, home: string): string {
  if (home === '' || home === '/') return path
  if (path === home) return '~'
  return path.startsWith(`${home}/`) ? `~${path.slice(home.length)}` : path
}

async function absolute($: EngineInterface, path: string, home: string): Promise<string> {
  if (path === '~' || path.startsWith('~/')) return home === '' ? path : `${home}${path.slice(1)}`
  if (path.startsWith('/')) return path
  try {
    return joinPath(await $.session.cwd(), path)
  } catch {
    return path
  }
}

async function missingMarkers($: EngineInterface, repo: string): Promise<string[]> {
  const missing: string[] = []
  for (const marker of ['install.sh', 'installer']) {
    let isThere = false
    try {
      isThere = await $.fs.exists(joinPath(repo, marker))
    } catch {
      isThere = false
    }
    if (!isThere) missing.push(marker === 'installer' ? 'installer/' : marker)
  }
  return missing
}

export type RepoResolution =
  | { ok: true; repo: string; shown: string; home: string }
  | { ok: false; error: string }

type Probe = { repo: string; shown: string; missing: string[] }

async function probeRepo($: EngineInterface, repo: string, home: string): Promise<Probe> {
  return { repo, shown: shortenHome(repo, home), missing: await missingMarkers($, repo) }
}

function describeMissing(probe: Probe): string {
  return `${probe.shown} (missing ${probe.missing.join(' and ')})`
}

/**
 * Where Claude Code keeps its plugin files: CLAUDE_CODE_PLUGIN_CACHE_DIR when set, else
 * <CLAUDE_CONFIG_DIR>/plugins when that is set, else ~/.claude/plugins.
 */
async function pluginsRoot($: EngineInterface, home: string): Promise<string> {
  const cacheDir = ((await $.env.get('CLAUDE_CODE_PLUGIN_CACHE_DIR')) ?? '').trim()
  if (cacheDir !== '') return absolute($, cacheDir, home)
  const configDir = ((await $.env.get('CLAUDE_CONFIG_DIR')) ?? '').trim()
  if (configDir !== '') return joinPath(await absolute($, configDir, home), 'plugins')
  return joinPath(home === '' ? '~' : home, '.claude/plugins')
}

/** The clone of the whole marketplace repo that Claude Code keeps: <plugins root>/marketplaces/ai-suite. */
async function marketplaceClone($: EngineInterface, home: string): Promise<string> {
  return joinPath(joinPath(await pluginsRoot($, home), 'marketplaces'), 'ai-suite')
}

/**
 * In order: repoPath when set (used as given, never skipped), else this plugin's grandparent
 * (a checkout run with --plugin-dir), else the marketplace clone (after /plugin install).
 * Each must hold install.sh and installer/.
 */
export async function resolveRepo($: EngineInterface, settings: Settings): Promise<RepoResolution> {
  const home = (await $.env.get('HOME')) ?? ''
  if (settings.repoPath !== '') {
    const explicit = await probeRepo($, await absolute($, settings.repoPath, home), home)
    if (explicit.missing.length === 0) return { ok: true, repo: explicit.repo, shown: explicit.shown, home }
    return {
      ok: false,
      error:
        `repoPath ${explicit.shown} does not look like the ai-suite repo ` +
        `(missing ${explicit.missing.join(' and ')}). Fix it in /config.`,
    }
  }
  const nearby = await probeRepo($, grandparent($.plugin.root), home)
  if (nearby.missing.length === 0) return { ok: true, repo: nearby.repo, shown: nearby.shown, home }
  const clone = await probeRepo($, await marketplaceClone($, home), home)
  if (clone.missing.length === 0) return { ok: true, repo: clone.repo, shown: clone.shown, home }
  return {
    ok: false,
    error:
      'Could not find the ai-suite repo (a folder holding install.sh and installer/). Looked at: ' +
      `repoPath (not set); this plugin's grandparent ${describeMissing(nearby)}; ` +
      `the marketplace clone ${describeMissing(clone)}. ` +
      'Clone bhavya091213/ai-suite and set repoPath in /config, or start Claude from the clone ' +
      'with: claude --plugin-dir mods/ai-suite',
  }
}

// ------------------------------------------------------------------- running

export function buildArgv(python: string, repo: string, args: readonly string[]): string[] {
  return [python, '-m', 'installer', '--repo', repo, ...args]
}

export type RunOptions = { timeoutMs?: number; accept?: readonly number[] }
export type RunOutcome = { ok: true; stdout: string } | { ok: false; error: string }

/** Runs one installer command as an argv list in the repo; a failure is a value, never a throw. */
export async function runCli(
  $: EngineInterface,
  cfg: Cfg,
  args: readonly string[],
  options: RunOptions = {},
): Promise<RunOutcome> {
  const argv = buildArgv(cfg.python, cfg.repo, args)
  const init = options.timeoutMs === undefined
    ? { cwd: cfg.repo }
    : { cwd: cfg.repo, timeoutMs: options.timeoutMs }
  try {
    const result = await $.process.run(argv, init)
    const accepted = options.accept ?? [0]
    const isAccepted = accepted.includes(result.exitCode)
    const isEmptyFailure = result.exitCode !== 0 && result.stdout.trim() === ''
    if (isAccepted && !isEmptyFailure) return { ok: true, stdout: result.stdout }
    const detail = lines(result.stderr)[0] ?? lines(result.stdout).slice(-1)[0] ?? `exit ${result.exitCode}`
    return { ok: false, error: truncate(detail, 300) }
  } catch (error) {
    return { ok: false, error: truncate(`could not run ${argv[0] ?? 'python'}: ${errText(error)}`, 300) }
  }
}

export type JsonOutcome<T> = { ok: true; data: T } | { ok: false; error: string }

/** Runs a command and parses its stdout as JSON through `parse` (null means "wrong shape"). */
export async function runJson<T>(
  $: EngineInterface,
  cfg: Cfg,
  args: readonly string[],
  parse: (raw: unknown) => T | null,
  options: RunOptions = {},
): Promise<JsonOutcome<T>> {
  const out = await runCli($, cfg, args, options)
  if (!out.ok) return out
  let raw: unknown
  try {
    raw = JSON.parse(out.stdout)
  } catch {
    return { ok: false, error: `${args.join(' ')}: the output was not JSON` }
  }
  const data = parse(raw)
  return data === null
    ? { ok: false, error: `${args.join(' ')}: the JSON had an unexpected shape` }
    : { ok: true, data }
}

/** Top-level lines of a mutating command's output worth showing (not the plan or its ok rows). */
export function notableLines(stdout: string, home: string): string[] {
  return stdout
    .split('\n')
    .filter(line => line.trim() !== '' && !/^\s/.test(line))
    .filter(line => !/^(Plan \(|Done\.|Dry run|Nothing to do\.)/.test(line))
    .map(line => (home === '' ? line : line.split(home).join('~')))
    .map(line => truncate(line, 160))
    .slice(0, 3)
}

// -------------------------------------------------------------------- parsing

function rec(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}
const str = (value: unknown): string => (typeof value === 'string' ? value : '')
const num = (value: unknown): number =>
  typeof value === 'number' && Number.isFinite(value) ? value : 0
const arr = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])
const texts = (value: unknown): string[] => arr(value).map(str).filter(text => text !== '')

function badLinks(row: Record<string, unknown>): { consumer: string; state: string }[] {
  return arr(row.links)
    .map(rec)
    .filter((link): link is Record<string, unknown> => link !== null)
    .map(link => ({ consumer: str(link.consumer), state: str(link.state) }))
    .filter(link => link.state !== 'ok' && link.state !== 'missing')
}

export function parseStatus(raw: unknown): AiSuiteSkillRow[] | null {
  if (!Array.isArray(raw)) return null
  const rows: AiSuiteSkillRow[] = []
  for (const item of raw) {
    const row = rec(item)
    if (row === null || str(row.scope) === '' || str(row.name) === '') continue
    rows.push({
      scope: str(row.scope),
      name: str(row.name),
      state: str(row.state),
      hasSource: rec(row.source) !== null,
      hasProblem:
        texts(row.issues).length > 0 || arr(row.duplicates).length > 0 || badLinks(row).length > 0,
      hasRemote: row.remote !== null && row.remote !== undefined,
    })
  }
  return rows
}

export function parseCatalog(raw: unknown): AiSuiteCatalogRow[] | null {
  if (!Array.isArray(raw)) return null
  const rows: AiSuiteCatalogRow[] = []
  for (const item of raw) {
    const row = rec(item)
    if (row === null || str(row.scope) === '' || str(row.name) === '') continue
    rows.push({
      scope: str(row.scope),
      name: str(row.name),
      state: str(row.state),
      installed: str(row.installed),
      description: str(row.description),
    })
  }
  return rows
}

function toProblem(row: Record<string, unknown>): AiSuiteProblem {
  const notes = [...texts(row.issues), ...texts(row.duplicates)]
  const links = arr(row.links).map(rec).filter((link): link is Record<string, unknown> => link !== null)
  const state = str(row.state)
  const more = notes.length > 1 ? ` (+${notes.length - 1} more)` : ''
  return {
    scope: str(row.scope),
    name: str(row.name),
    state,
    text: `${notes[0] ?? 'link problem'}${more}`,
    canRelink: str(row.scope) === 'shared' && links.some(link => str(link.state) !== 'ok'),
    canRetire: rec(row.installed) !== null && ['installed', 'modified', 'foreign'].includes(state),
  }
}

export function parseIssues(raw: unknown): AiSuiteIssues | null {
  const root = rec(raw)
  if (root === null) return null
  return {
    problems: arr(root.problems)
      .map(rec)
      .filter((row): row is Record<string, unknown> => row !== null)
      .map(toProblem),
    repoIssues: arr(root.repo_issues)
      .map(rec)
      .filter((row): row is Record<string, unknown> => row !== null)
      .map(row => ({ scope: str(row.scope), name: str(row.name), message: str(row.message) })),
  }
}

function formatTime(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return ''
  const ms = value < 1e12 ? value * 1000 : value
  return `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')}Z`
}

export function parseUpdates(raw: unknown): AiSuiteUpdates | null {
  const root = rec(raw)
  if (root === null) return null
  const git = rec(root.git) ?? {}
  return {
    git: {
      message: str(git.message),
      hint: str(git.hint),
      branch: str(git.branch),
      upstream: str(git.upstream),
      ahead: num(git.ahead),
      behind: num(git.behind),
      lastFetch: formatTime(git.last_fetch),
    },
    commits: texts(root.commits),
    changed: arr(root.changed)
      .map(rec)
      .filter((row): row is Record<string, unknown> => row !== null && str(row.name) !== '')
      .map(row => ({ scope: str(row.scope), name: str(row.name), files: arr(row.files).length })),
  }
}

export function parseWorkflows(raw: unknown): AiSuiteWorkflow[] | null {
  if (!Array.isArray(raw)) return null
  return raw
    .map(rec)
    .filter((row): row is Record<string, unknown> => row !== null && str(row.name) !== '')
    .map(row => ({
      name: str(row.name),
      phases: num(row.phases),
      skills: num(row.skills),
      valid: row.valid !== false,
      note: texts(row.errors)[0] ?? texts(row.warnings)[0] ?? '',
    }))
}

function checkState(value: unknown): AiSuiteCheckState {
  return value === 'ok' || value === 'blocker' ? value : 'warn'
}

export function parseDoctor(raw: unknown): AiSuiteDoctor | null {
  const root = rec(raw)
  if (root === null || !Array.isArray(root.checks)) return null
  const checks = root.checks
    .map(rec)
    .filter((row): row is Record<string, unknown> => row !== null)
    .map(row => ({ name: str(row.name), state: checkState(row.state), text: str(row.text) }))
  const counted = checks.filter(check => check.state === 'blocker').length
  return { checks, blockers: typeof root.blockers === 'number' ? root.blockers : counted }
}
