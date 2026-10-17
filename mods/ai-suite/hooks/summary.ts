// Pure helpers: counts per scope, the status line, the /skills-check summary
// and paging. No `$` in here, so the pane and the tests can share them.
import type {
  AiSuiteDoctor,
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

export function scopeLine(count: ScopeCount): string {
  return `${count.scope}: ${count.installed} installed, ${count.modified} modified, ` +
    `${count.missing} missing, ${plural(count.problems, 'problem', 'problems')}`
}

export const plural = (n: number, one: string, many: string): string =>
  `${n} ${n === 1 ? one : many}`

/** `skills 57/90 · 3 updates · 2 issues`; undefined while nothing has been read yet. */
export function statusLineText(
  status: AiSuiteSnapshot<AiSuiteSkillRow[]>,
  updates: AiSuiteSnapshot<AiSuiteUpdates>,
): string | undefined {
  const rows = status.data
  if (rows === null) return status.error === null ? undefined : 'skills: check failed (see /skills)'
  const offered = rows.filter(row => row.hasSource)
  const present = offered.filter(row => row.state === 'installed' || row.state === 'modified')
  const parts = [`skills ${present.length}/${offered.length}`]
  const changed = updates.data === null
    ? rows.filter(row => row.hasRemote).length
    : updates.data.changed.length
  if (changed > 0) parts.push(plural(changed, 'update', 'updates'))
  const problems = rows.filter(row => row.hasProblem).length
  if (problems > 0) parts.push(plural(problems, 'issue', 'issues'))
  return parts.join(' · ')
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
