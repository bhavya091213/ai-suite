// Turning the installer's JSON into the small shapes the pane keeps. Every parser
// answers null for a shape it does not know and skips rows it cannot read; none throws.
import type {
  AiSuiteCaps,
  AiSuiteCheckState,
  AiSuiteConfig,
  AiSuiteDoctor,
  AiSuiteLink,
  AiSuiteSkillRow,
  AiSuiteUpdates,
  AiSuiteWorkflow,
} from '../types'
import { OTHER_CATEGORY } from './presets'

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
const records = (value: unknown): Record<string, unknown>[] =>
  arr(value).filter((item): item is Record<string, unknown> => rec(item) !== null)
/** The use-case tags of a row: trimmed, each once; a missing field or anything but a list of texts is no tag. */
const tagsOf = (value: unknown): string[] => [...new Set(arr(value).map(item => str(item).trim()).filter(tag => tag !== ''))]

function linksOf(row: Record<string, unknown>): AiSuiteLink[] {
  return records(row.links).map(link => ({ consumer: str(link.consumer), state: str(link.state) }))
}

/** Links that are really wrong (a missing link is just not made yet). */
const badLinks = (links: readonly AiSuiteLink[]): AiSuiteLink[] =>
  links.filter(link => link.state !== 'ok' && link.state !== 'missing')

function describe(row: Record<string, unknown>, hasBadLink: boolean): string {
  const notes = [...texts(row.issues), ...texts(row.duplicates)]
  if (notes.length === 0) return hasBadLink ? 'link problem' : ''
  return `${notes[0] ?? ''}${notes.length > 1 ? ` (+${notes.length - 1} more)` : ''}`
}

function descriptionOf(row: Record<string, unknown>): string {
  for (const place of [rec(row.source), rec(row.installed)]) {
    const text = str(rec(place?.meta)?.description)
    if (text !== '') return text
  }
  return ''
}

export function parseStatus(raw: unknown): AiSuiteSkillRow[] | null {
  if (!Array.isArray(raw)) return null
  const rows: AiSuiteSkillRow[] = []
  for (const item of raw) {
    const row = rec(item)
    if (row === null || str(row.scope) === '' || str(row.name) === '') continue
    const links = linksOf(row)
    const bad = badLinks(links)
    const state = str(row.state)
    const hasProblem = texts(row.issues).length > 0 || arr(row.duplicates).length > 0 || bad.length > 0
    rows.push({
      scope: str(row.scope),
      name: str(row.name),
      state,
      description: descriptionOf(row),
      category: str(row.category).trim() || OTHER_CATEGORY,
      tags: tagsOf(row.tags),
      note: hasProblem ? describe(row, bad.length > 0) : '',
      hasSource: rec(row.source) !== null,
      hasProblem,
      hasRemote: row.remote !== null && row.remote !== undefined,
      canRelink: str(row.scope) === 'shared' && bad.length > 0,
      canRetire: rec(row.installed) !== null && ['installed', 'modified', 'foreign'].includes(state),
      links,
    })
  }
  return rows
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
    changed: records(root.changed)
      .filter(row => str(row.name) !== '')
      .map(row => ({ scope: str(row.scope), name: str(row.name), files: arr(row.files).length })),
  }
}

export function parseWorkflows(raw: unknown): AiSuiteWorkflow[] | null {
  if (!Array.isArray(raw)) return null
  return records(raw)
    .filter(row => str(row.name) !== '')
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
  const checks = records(root.checks).map(row => ({
    name: str(row.name),
    state: checkState(row.state),
    text: str(row.text),
  }))
  const counted = checks.filter(check => check.state === 'blocker').length
  return { checks, blockers: typeof root.blockers === 'number' ? root.blockers : counted }
}

/** `caps --json`: the tools probed (in the order given) and the Obsidian vaults Obsidian knows. */
export function parseCaps(raw: unknown): AiSuiteCaps | null {
  const root = rec(raw)
  if (root === null) return null
  const items = rec(root.items) ?? {}
  return {
    tools: Object.entries(items).flatMap(([key, item]) => {
      const tool = rec(item)
      if (tool === null) return []
      return [{ name: str(tool.name) || key, present: tool.present === true, version: str(tool.version) }]
    }),
    vaults: texts(root.vaults),
  }
}

/** How a config value reads as text: booleans on / off, lists comma-joined, null empty. */
function configText(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(configText).join(',')
  return ''
}

function flatten(node: Record<string, unknown>, prefix: string, out: AiSuiteConfig): AiSuiteConfig {
  return Object.entries(node).reduce<AiSuiteConfig>((all, [key, value]) => {
    const path = prefix === '' ? key : `${prefix}.${key}`
    const child = rec(value)
    return child === null ? { ...all, [path]: configText(value) } : flatten(child, path, all)
  }, out)
}

/** `config list --json`: the nested data flattened to dotted keys (tools.claude, subagents.codex.model, ...). */
export function parseConfig(raw: unknown): AiSuiteConfig | null {
  const root = rec(raw)
  return root === null ? null : flatten(root, '', {})
}
