// Pure helpers: counts per scope, the status line, the /skills-check summary
// and paging. No `$` in here, so the pane and the tests can share them.
import type {
  AiSuiteDoctor,
  AiSuiteFilters,
  AiSuiteInstalledFilter,
  AiSuiteSkillRow,
  AiSuiteSnapshot,
  AiSuiteUpdates,
} from '../types'
import { truncate } from './cli'

const SCOPE_ORDER = ['shared', 'claude', 'codex']

export type ScopeCount = {
  scope: string
  installed: number
  modified: number
  missing: number
  problems: number
}

function rank(scope: string): number {
  const at = SCOPE_ORDER.indexOf(scope)
  return at < 0 ? SCOPE_ORDER.length : at
}

export function countByScope(rows: readonly AiSuiteSkillRow[]): ScopeCount[] {
  const scopes = [...new Set(rows.map(row => row.scope))]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
  return scopes.map(scope => {
    const mine = rows.filter(row => row.scope === scope)
    return {
      scope,
      installed: mine.filter(row => row.state === 'installed').length,
      modified: mine.filter(row => row.state === 'modified').length,
      missing: mine.filter(row => row.state === 'not-installed').length,
      problems: mine.filter(row => row.hasProblem).length,
    }
  })
}

export type CountTone = 'success' | 'warning' | 'dim' | 'error'
export type CountPart = { value: number; word: string; tone: CountTone }

/** The four numbers under a scope's bar: installed, modified, missing and problems, each with its tone. */
export function scopeParts(count: ScopeCount): CountPart[] {
  return [
    { value: count.installed, word: 'installed', tone: 'success' },
    { value: count.modified, word: 'modified', tone: 'warning' },
    { value: count.missing, word: 'missing', tone: 'dim' },
    { value: count.problems, word: count.problems === 1 ? 'problem' : 'problems', tone: 'error' },
  ]
}

/** `57 installed · 6 modified · 26 missing · 0 problems`, the terminal's line under a scope's bar. */
export const scopeNumbers = (count: ScopeCount): string =>
  scopeParts(count).map(part => `${part.value} ${part.word}`).join(' · ')

export type BarSegments = { ok: number; mod: number; rest: number }

/**
 * How a bar of `cells` units divides: `ok` installed, `mod` modified (drawn after them), `rest`
 * missing. Installed and modified together fill `present / offered` of the bar; a skill that
 * is there at all gets a unit, and an empty offer is an empty bar.
 */
export function barSegments(installed: number, modified: number, offered: number, cells: number): BarSegments {
  const total = Math.max(1, cells)
  const present = installed + modified
  if (offered <= 0 || present <= 0) return { ok: 0, mod: 0, rest: total }
  const filled = Math.min(total, Math.max(1, Math.round((present / offered) * total)))
  const mod = modified === 0 ? 0 : Math.min(filled, Math.max(1, Math.round((modified / offered) * total)))
  return { ok: filled - mod, mod, rest: total - filled }
}

export const plural = (n: number, one: string, many: string): string =>
  `${n} ${n === 1 ? one : many}`

export type SkillCounts = { present: number; offered: number; changed: number; problems: number }

/** The numbers behind the status line and the band: installed of offered, upstream changes, problems. */
export function skillCounts(
  rows: readonly AiSuiteSkillRow[],
  updates: AiSuiteSnapshot<AiSuiteUpdates>,
): SkillCounts {
  const offered = rows.filter(row => row.hasSource)
  return {
    present: offered.filter(row => row.state === 'installed' || row.state === 'modified').length,
    offered: offered.length,
    changed: updates.data === null
      ? rows.filter(row => row.hasRemote).length
      : updates.data.changed.length,
    problems: rows.filter(row => row.hasProblem).length,
  }
}

/** `skills 57/90 · 3 updates · 2 issues`; undefined while nothing has been read yet. */
export function statusLineText(
  status: AiSuiteSnapshot<AiSuiteSkillRow[]>,
  updates: AiSuiteSnapshot<AiSuiteUpdates>,
): string | undefined {
  const rows = status.data
  if (rows === null) return status.error === null ? undefined : 'skills: check failed (see /skills)'
  const counts = skillCounts(rows, updates)
  const parts = [`skills ${counts.present}/${counts.offered}`]
  if (counts.changed > 0) parts.push(plural(counts.changed, 'update', 'updates'))
  if (counts.problems > 0) parts.push(plural(counts.problems, 'issue', 'issues'))
  return parts.join(' · ')
}

export type BandInput = {
  status: AiSuiteSnapshot<AiSuiteSkillRow[]>
  updates: AiSuiteSnapshot<AiSuiteUpdates>
  /** The repo resolution's error; empty when the repo was found or not looked for yet. */
  repoError: string
  /** True when a start check is expected to fill the snapshots without being asked. */
  isChecking: boolean
}

/**
 * The band's one line: `Skills · 57/90 installed · 3 updates · 2 issues`, or `Skills · checking…`,
 * or the check's error. null means the band has nothing to say (the repo cannot be found and
 * there is no summary), so it draws nothing.
 */
export function bandText(input: BandInput): string | null {
  const rows = input.status.data
  if (rows !== null) {
    const counts = skillCounts(rows, input.updates)
    const parts = [`Skills · ${counts.present}/${counts.offered} installed`]
    if (counts.changed > 0) parts.push(plural(counts.changed, 'update', 'updates'))
    if (counts.problems > 0) parts.push(plural(counts.problems, 'issue', 'issues'))
    return parts.join(' · ')
  }
  if (input.repoError !== '') return null
  if (input.status.error !== null) return `Skills · check failed: ${truncate(input.status.error, 120)}`
  return input.isChecking ? 'Skills · checking…' : 'Skills · not checked yet'
}

export type CheckInput = {
  doctor: AiSuiteDoctor | null
  doctorError: string | null
  updates: AiSuiteUpdates | null
  updatesError: string | null
}

export function checkSummary(input: CheckInput): string {
  const parts: string[] = []
  if (input.doctor !== null) {
    const warns = input.doctor.checks.filter(check => check.state === 'warn').length
    parts.push(
      input.doctor.blockers > 0
        ? `doctor: ${plural(input.doctor.blockers, 'blocker', 'blockers')}`
        : `doctor ok${warns > 0 ? `, ${plural(warns, 'warning', 'warnings')}` : ''}`,
    )
  } else {
    parts.push(`doctor failed (${truncate(input.doctorError ?? 'no answer', 90)})`)
  }
  if (input.updates !== null) {
    const git = input.updates.git
    parts.push(
      git.upstream === ''
        ? 'no upstream to compare with'
        : `${plural(git.behind, 'commit', 'commits')} behind`,
    )
    parts.push(`${plural(input.updates.changed.length, 'skill', 'skills')} changed upstream`)
  } else {
    parts.push(`updates failed (${truncate(input.updatesError ?? 'no answer', 90)})`)
  }
  return `skills check: ${parts.join(' · ')}`
}

export type Page<T> = { items: T[]; page: number; pages: number; hidden: number }

export function pageOf<T>(items: readonly T[], page: number, size: number): Page<T> {
  const per = Math.max(1, size)
  const pages = Math.max(1, Math.ceil(items.length / per))
  const at = Math.min(Math.max(0, page), pages - 1)
  const end = Math.min(items.length, (at + 1) * per)
  return { items: items.slice(at * per, end), page: at, pages, hidden: items.length - end }
}

// --------------------------------------------------------------------- filters

export const CARDS_PER_PAGE = 5

/** Skills the repo offers that are not on this machine yet. */
export const missingRows = (rows: readonly AiSuiteSkillRow[]): AiSuiteSkillRow[] =>
  rows.filter(row => row.state === 'not-installed')

/** The missing skills the Install view shows: one scope (or all) and names or descriptions holding the query. */
export function filterMissing(
  rows: readonly AiSuiteSkillRow[],
  filters: Pick<AiSuiteFilters, 'installScope' | 'installQuery'>,
): AiSuiteSkillRow[] {
  const query = filters.installQuery.trim().toLowerCase()
  return missingRows(rows).filter(
    row =>
      (filters.installScope === 'all' || row.scope === filters.installScope) &&
      (query === '' ||
        row.name.toLowerCase().includes(query) ||
        row.description.toLowerCase().includes(query)),
  )
}

const ON_DISK = ['installed', 'modified', 'foreign', 'ignored']

/** What the Installed view lists for a filter chip; `ignored` rows are the tool-managed ones. */
export function filterInstalled(
  rows: readonly AiSuiteSkillRow[],
  filter: AiSuiteInstalledFilter,
): AiSuiteSkillRow[] {
  const present = rows.filter(row => ON_DISK.includes(row.state))
  switch (filter) {
    case 'modified':
      return present.filter(row => row.state === 'modified')
    case 'problems':
      return present.filter(row => row.hasProblem)
    case 'foreign':
      return present.filter(row => row.state === 'foreign')
    case 'tool-managed':
      return present.filter(row => row.state === 'ignored')
    case 'all':
      return present
  }
}

/** Modified skills that also changed upstream: what `Update changed` replaces. */
export function updatable(
  rows: readonly AiSuiteSkillRow[],
  updates: AiSuiteUpdates | null,
): { scope: string; name: string }[] {
  const modified = new Set(rows.filter(row => row.state === 'modified').map(row => `${row.scope}/${row.name}`))
  return (updates?.changed ?? []).filter(change => modified.has(`${change.scope}/${change.name}`))
}
